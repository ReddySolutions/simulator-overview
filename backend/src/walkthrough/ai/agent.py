from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import anthropic

from walkthrough.config import Settings
from walkthrough.models.project import Project

logger = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 8192
MAX_AGENT_TURNS = 50

SYSTEM_PROMPT = """\
You are the Walkthrough Agent — an AI orchestrator that transforms call-center \
training videos and SOP PDFs into interactive, branching web simulations.

You have access to tools for perceiving, analyzing, and synthesizing training content. \
Use these tools systematically to process uploaded files and produce a structured \
walkthrough.

## Pipeline Phases

Execute these phases in order:
1. **Ingestion**: Process each uploaded video with analyze_video and each PDF with \
extract_pdf. For PDF images, follow up with analyze_screenshot.
2. **Path Merge**: Call merge_paths to align multiple video analyses into unified \
decision trees, identifying shared screens and branch points.
3. **Contradiction Detection**: Call detect_contradictions to cross-reference video, \
audio, and PDF sources for inconsistencies.
4. **Clarification**: Call ask_user_question to generate batched questions for the user \
about detected gaps. Wait for user responses.
5. **Generation**: Call generate_walkthrough to produce the final structured output.

## Mandatory Invariants (M1-M9)

M1: Cross-reference ALL three source types independently — video-observed UI, audio \
narration, and PDF documentation. Never rely on a single source.
M2: Every gap or contradiction MUST include evidence from at least two sources with \
SourceRef citations (source_type, reference, excerpt).
M3: Classify every gap by severity — critical (blocks generation: ambiguous routing, \
conflicting procedures), medium (unclear labels, wording differences), low (cosmetic).
M4: Batch clarification questions by severity — critical gaps first.
M5: Wireframe/screen data MUST come from video keyframe UI descriptions. Do NOT \
generate UI elements from general knowledge.
M6: Preserve full decision tree structure — no lossy compression. Narrative text may \
be compressed after synthesis, but workflow structures (screens, branches, elements) \
must remain complete.
M7: Every narrative field (what/why/when) MUST cite sources via SourceRef — video \
timestamp, audio transcript segment, or PDF section.
M8: All agent state (messages, intermediate results) must be serializable for \
persistence. Pipeline must be resumable from any phase.
M9: Every screen carries an evidence_tier: 'observed' (seen in video) or 'mentioned' \
(referenced in audio/PDF only).

## Negative Invariants (N1-N7)

N1: Do NOT infer screens or branches. Only include what was observed in video or \
mentioned in audio/PDF.
N2: Do NOT adjudicate contradictions. Present both versions with their sources. The \
user decides which is authoritative.
N3: Unanswerable critical gaps MUST produce warning metadata on affected screens. \
Never silently drop unresolved critical issues.
N4: No source is inherently authoritative. Video, audio, and PDF carry equal weight. \
Disagreements are escalated, not resolved by the agent.
N5: Do NOT hallucinate UI elements, screen flows, or procedures not present in the \
source materials.
N6: Do NOT skip phases or tools. Execute the full pipeline even when sources appear \
consistent — silent issues may exist.
N7: The clarification phase ALWAYS runs, even with zero contradictions detected. \
Confirm the clean state with the user.

## Tool Usage Guidelines

- Call analyze_video once per uploaded MP4 file.
- Call extract_pdf once per uploaded PDF file.
- Call analyze_screenshot for each image extracted from PDFs.
- After all files are processed, call merge_paths to build decision trees.
- After merge, call detect_contradictions for three-way cross-reference.
- Call ask_user_question to surface gaps to the user.
- Only call generate_walkthrough after all critical gaps are resolved or acknowledged.\
"""

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "analyze_video",
        "description": (
            "Analyze a training video using Gemini. Extracts keyframes with UI "
            "element inventories, transition events between screens, timestamped "
            "audio transcripts with intent annotations, and temporal flow. Returns "
            "a VideoAnalysis object."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "video_path": {
                    "type": "string",
                    "description": "GCS URI (gs://...) to the MP4 video file.",
                },
                "video_id": {
                    "type": "string",
                    "description": "Unique identifier for this video.",
                },
            },
            "required": ["video_path", "video_id"],
        },
    },
    {
        "name": "extract_pdf",
        "description": (
            "Extract structured data from a PDF using Document AI. Extracts text "
            "sections with headings and confidence scores, tables with headers and "
            "rows, and page images for screenshot analysis. Returns a PDFExtraction "
            "object."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {
                    "type": "string",
                    "description": (
                        "GCS URI (gs://...) or local path to the PDF file."
                    ),
                },
                "pdf_id": {
                    "type": "string",
                    "description": "Unique identifier for this PDF.",
                },
            },
            "required": ["pdf_path", "pdf_id"],
        },
    },
    {
        "name": "analyze_screenshot",
        "description": (
            "Analyze a PDF-extracted screenshot image using Gemini. Classifies UI "
            "elements (buttons, fields, dropdowns, tabs, labels) with their text "
            "labels. For non-UI images, returns description only. Call this for "
            "each image extracted during PDF processing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "image_id": {
                    "type": "string",
                    "description": (
                        "Image identifier from PDFExtraction "
                        "(format: {pdf_id}_page_{N})."
                    ),
                },
            },
            "required": ["image_id"],
        },
    },
    {
        "name": "merge_paths",
        "description": (
            "Merge multiple video analyses into unified decision trees. Identifies "
            "shared screens across videos, detects branch points where paths "
            "diverge, and collapses shared prefixes. Each screen gets a stable "
            "screen_id and source references. Call after all videos are analyzed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "detect_contradictions",
        "description": (
            "Perform three-way cross-reference across video, audio, and PDF "
            "sources. Detects label mismatches, step count disagreements, control "
            "type conflicts, policy gaps, and cross-video behavioral conflicts. "
            "Returns gaps classified by severity with evidence from at least two "
            "sources. Call after merge_paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "ask_user_question",
        "description": (
            "Generate batched clarification questions from detected gaps. Questions "
            "are ordered by severity (critical first) and include evidence from "
            "relevant sources. Contradictions are presented with both versions for "
            "the user to adjudicate. Call after detect_contradictions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "generate_walkthrough",
        "description": (
            "Generate the final structured walkthrough JSON. Produces decision "
            "trees, wireframe screen data from video keyframes (M5), evidence tier "
            "markings (M9), warnings for unresolved critical gaps (N3), and open "
            "questions section. Only call after all critical gaps are resolved or "
            "acknowledged unanswerable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]

_ToolHandler = Callable[
    [dict[str, Any], Project],
    Coroutine[Any, Any, tuple[str, Project]],
]


class WalkthroughAgent:
    """Claude-powered agent that orchestrates the SOP-to-Simulation pipeline.

    Uses the Anthropic SDK to run an agent loop with tool calling, dispatching
    tool calls to Gemini perception tools and analysis functions.

    Message history is serializable for Firestore persistence (M8).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = CLAUDE_MODEL,
    ) -> None:
        settings = Settings()
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or settings.ANTHROPIC_API_KEY
        )
        self._model = model
        self._messages: list[dict[str, Any]] = []

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Current message history for inspection or persistence (M8)."""
        return self._messages

    def serialize_messages(self) -> str:
        """Serialize message history to JSON string for Firestore persistence."""
        return json.dumps(self._messages)

    def load_messages(self, messages_json: str) -> None:
        """Load message history from JSON string for session resumption."""
        self._messages = json.loads(messages_json)

    async def run(self, project: Project) -> Project:
        """Run the agent loop through all pipeline phases.

        The agent calls tools to analyze files, merge paths, detect
        contradictions, generate clarification questions, and produce
        the final walkthrough.

        Args:
            project: Project with uploaded files to process.

        Returns:
            Updated project with analysis results.
        """
        user_message = _build_project_context(project)
        self._messages.append({"role": "user", "content": user_message})

        for turn in range(MAX_AGENT_TURNS):
            logger.info("Agent turn %d/%d", turn + 1, MAX_AGENT_TURNS)

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,  # type: ignore[arg-type]
                messages=self._messages,  # type: ignore[arg-type]
            )

            assistant_msg = _response_to_message(response)
            self._messages.append(assistant_msg)

            if response.stop_reason == "end_turn":
                logger.info("Agent completed after %d turns", turn + 1)
                break

            if response.stop_reason == "tool_use":
                tool_results: list[dict[str, Any]] = []
                for block in response.content:
                    if block.type == "tool_use":
                        input_data = block.input
                        if not isinstance(input_data, dict):
                            input_data = {}
                        result_str, project = await _dispatch_tool(
                            block.name, input_data, project
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_str,
                        })

                self._messages.append(
                    {"role": "user", "content": tool_results}
                )
        else:
            logger.warning(
                "Agent reached maximum turns (%d)", MAX_AGENT_TURNS
            )

        return project


# --- Helper functions ---


def _build_project_context(project: Project) -> str:
    """Build initial user message describing project state for the agent."""
    parts = [
        f"Project: {project.name} (ID: {project.project_id})",
        f"Status: {project.status}",
    ]

    video_lines = [
        f"  - {v.filename} (video_id: {v.video_id})" for v in project.videos
    ]
    if video_lines:
        parts.append("Analyzed videos:\n" + "\n".join(video_lines))

    pdf_lines = [
        f"  - {p.filename} (pdf_id: {p.pdf_id})" for p in project.pdfs
    ]
    if pdf_lines:
        parts.append("Extracted PDFs:\n" + "\n".join(pdf_lines))

    if project.decision_trees:
        parts.append(f"Decision trees: {len(project.decision_trees)} built")

    if project.gaps:
        unresolved = sum(1 for g in project.gaps if not g.resolved)
        parts.append(
            f"Gaps: {len(project.gaps)} total, {unresolved} unresolved"
        )

    parts.append(
        "\nProcess all uploaded files through the pipeline phases. "
        "Use the available tools in sequence as described in your instructions."
    )

    return "\n\n".join(parts)


def _response_to_message(
    response: anthropic.types.Message,
) -> dict[str, Any]:
    """Convert Anthropic API response to a serializable message dict."""
    content: list[dict[str, Any]] = []
    for block in response.content:
        if block.type == "text":
            content.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            content.append({
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            })
    return {"role": "assistant", "content": content}


async def _dispatch_tool(
    name: str, tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    """Dispatch a tool call to its handler implementation."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        error = f"Unknown tool: {name}"
        logger.error(error)
        return json.dumps({"error": error}), project

    try:
        return await handler(tool_input, project)
    except Exception as e:
        msg = f"Tool '{name}' failed: {e}"
        logger.error(msg, exc_info=True)
        return json.dumps({"error": msg}), project


# --- Tool handler implementations ---


async def _handle_analyze_video(
    tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.gemini_video import analyze_video

    result = await analyze_video(
        video_path=tool_input["video_path"],
        video_id=tool_input["video_id"],
    )
    project.videos.append(result)
    return result.model_dump_json(), project


async def _handle_extract_pdf(
    tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.document_ai import extract_pdf

    result = await extract_pdf(
        pdf_path=tool_input["pdf_path"],
        pdf_id=tool_input["pdf_id"],
    )
    project.pdfs.append(result)
    return result.model_dump_json(), project


async def _handle_analyze_screenshot(
    tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.document_ai import get_extracted_image
    from walkthrough.ai.gemini_screenshot import analyze_screenshot

    image_id: str = tool_input["image_id"]
    image_bytes = get_extracted_image(image_id)
    if image_bytes is None:
        return json.dumps({"error": f"Image not found: {image_id}"}), project

    result = await analyze_screenshot(image_bytes, image_id)

    # Update corresponding PDFImage in the project
    for pdf in project.pdfs:
        for i, img in enumerate(pdf.images):
            if img.image_id == image_id:
                pdf.images[i] = result
                break

    return result.model_dump_json(), project


async def _handle_merge_paths(
    _tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.tools.merge_paths import merge_paths

    result = await merge_paths(project.videos)
    project.decision_trees = result
    return json.dumps([t.model_dump() for t in result]), project


async def _handle_detect_contradictions(
    _tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.tools.detect_contradictions import (  # type: ignore[import-not-found]
        detect_contradictions,
    )

    result = await detect_contradictions(
        project.videos, project.pdfs, project.decision_trees
    )
    project.gaps = result
    return json.dumps([g.model_dump() for g in result]), project


async def _handle_ask_user_question(
    _tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.tools.clarification import generate_questions  # type: ignore[import-not-found]

    result = await generate_questions(project.gaps)
    project.questions = result
    return json.dumps([q.model_dump() for q in result]), project


async def _handle_generate_walkthrough(
    _tool_input: dict[str, Any], project: Project
) -> tuple[str, Project]:
    from walkthrough.ai.tools.generate import generate_walkthrough  # type: ignore[import-not-found]

    result = await generate_walkthrough(project)
    return json.dumps(result), project


_TOOL_HANDLERS: dict[str, _ToolHandler] = {
    "analyze_video": _handle_analyze_video,
    "extract_pdf": _handle_extract_pdf,
    "analyze_screenshot": _handle_analyze_screenshot,
    "merge_paths": _handle_merge_paths,
    "detect_contradictions": _handle_detect_contradictions,
    "ask_user_question": _handle_ask_user_question,
    "generate_walkthrough": _handle_generate_walkthrough,
}
