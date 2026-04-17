"""Agent phase orchestrator — drives the SOP-to-Simulation pipeline.

Coordinates video analysis, PDF extraction, path merging, narrative synthesis,
contradiction detection, clarification, and walkthrough generation. Persists
state to Firestore after each phase (M8) and yields progress events for SSE
streaming. Supports resumption from any phase by inferring progress from
project state.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone

from walkthrough.config import Settings
from walkthrough.deps import get_firestore_client, get_storage_client
from walkthrough.models.project import Project
from walkthrough.storage.phase_artifacts import (
    PHASE_ORDER,
    completed_phases,
    write_phase_artifact,
)

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvent:
    """Progress event for SSE streaming to the frontend."""

    phase: str
    percentage: int
    message: str


class PhaseOrchestrator:
    """Orchestrates the SOP-to-Simulation pipeline through 8 phases.

    Drives file ingestion, analysis, merging, synthesis, contradiction
    detection, clarification, and generation in sequence. Persists project
    state to Firestore after each phase (M8) and yields progress events
    for real-time SSE streaming. Can resume from any phase by loading
    persisted state and skipping completed phases.
    """

    def __init__(self) -> None:
        self._settings = Settings()
        self._firestore = get_firestore_client()

    async def run_pipeline(
        self, project_id: str
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Drive Phase 1 through Phase 8 in order.

        Loads project from Firestore, determines resume point, and executes
        remaining phases. Yields ProgressEvent at each phase transition.
        Pauses after Phase 6 (clarification) to wait for user input.

        Args:
            project_id: Firestore project document ID.

        Yields:
            ProgressEvent with phase name, percentage, and descriptive message.

        Raises:
            ValueError: If project_id is not found in Firestore.
        """
        project = await self._firestore.load_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        resume = _infer_resume_phase(project)
        logger.info("Pipeline %s resuming from phase: %s", project_id, resume)

        if resume == "done":
            yield ProgressEvent("generation", 100, "Walkthrough already complete")
            return

        # Phase 1-2: Ingestion — video analysis + PDF extraction + screenshots
        if _phase_index(resume) <= _phase_index("ingestion"):
            project.status = "analyzing"
            project.updated_at = _now()
            await self._firestore.save_project(project)

            async for event in self._run_ingestion(project):
                yield event
            await self._save(project)

        # Phase 3: Path merge — align multiple video analyses into decision trees
        if _phase_index(resume) <= _phase_index("path_merge"):
            yield ProgressEvent(
                "path_merge", 0, "Merging video paths into decision trees..."
            )
            await self._run_path_merge(project)
            yield ProgressEvent("path_merge", 100, "Path merge complete")
            await self._save(project)

        # Phase 4: Narrative synthesis (M6 — structures preserved in full)
        if _phase_index(resume) <= _phase_index("narrative"):
            yield ProgressEvent(
                "narrative", 0, "Synthesizing step narratives..."
            )
            await self._run_narrative(project)
            yield ProgressEvent("narrative", 100, "Narrative synthesis complete")
            await self._save(project)

        # Phase 5: Contradiction detection — three-way cross-reference
        if _phase_index(resume) <= _phase_index("contradictions"):
            yield ProgressEvent(
                "contradictions", 0,
                "Cross-referencing sources for contradictions...",
            )
            await self._run_contradictions(project)
            yield ProgressEvent(
                "contradictions", 100, "Contradiction detection complete"
            )
            await self._save(project)

        # Phase 6: Clarification — generate questions, then pause for user input
        if _phase_index(resume) <= _phase_index("clarification"):
            yield ProgressEvent(
                "clarification", 0, "Generating clarification questions..."
            )
            await self._run_clarification(project)
            yield ProgressEvent(
                "clarification", 100, "Waiting for user responses"
            )
            await self._save(project)
            return  # Pipeline pauses — user answers via API endpoints

        # Phase 7-8: Generation — produce final walkthrough JSON
        if _phase_index(resume) <= _phase_index("generation"):
            async for event in self._run_generation(project):
                yield event
            await self._save(project)

        # Phase 9: QA — run validators in parallel and stash report on output
        if _phase_index(resume) <= _phase_index("qa"):
            async for event in self._run_qa(project):
                yield event
            await self._save(project)

    async def run_generation_phase(
        self, project_id: str,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Run Phase 7-8 generation + Phase 9 QA after clarification completes.

        Called when the user triggers generation after answering questions.
        The QA phase must run on this code path too — most real projects
        pause for clarification and never re-enter `run_pipeline`.
        """
        project = await self._firestore.load_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        async for event in self._run_generation(project):
            yield event
        async for event in self._run_qa(project):
            yield event
        await self._save(project)

    # --- Phase implementations ---

    async def _run_ingestion(
        self, project: Project,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Phase 1-2: Analyze videos and extract PDFs with screenshot analysis."""
        if self._settings.LOCAL_DEV:
            from walkthrough.ai.local_gemini_screenshot import analyze_screenshot
            from walkthrough.ai.local_gemini_video import analyze_video
            from walkthrough.ai.local_pdf import (
                extract_pdf,
                get_extracted_image,
            )
        else:
            from walkthrough.ai.document_ai import (  # type: ignore[no-redef]
                extract_pdf,
                get_extracted_image,
            )
            from walkthrough.ai.gemini_screenshot import (  # type: ignore[no-redef]
                analyze_screenshot,
            )
            from walkthrough.ai.gemini_video import (  # type: ignore[no-redef]
                analyze_video,
            )

        storage = get_storage_client()

        prefix = f"projects/{project.project_id}/uploads/"
        blobs = await storage.list_blobs(prefix)

        mp4_blobs = [b for b in blobs if b.lower().endswith(".mp4")]
        pdf_blobs = [b for b in blobs if b.lower().endswith(".pdf")]
        total = len(mp4_blobs) + len(pdf_blobs)

        analyzed_video_ids = {v.video_id for v in project.videos}
        analyzed_pdf_ids = {p.pdf_id for p in project.pdfs}
        processed = 0

        # Video analysis
        total_videos = max(len(mp4_blobs), 1)
        for blob_path in mp4_blobs:
            filename = blob_path.rsplit("/", 1)[-1]
            video_id = filename.rsplit(".", 1)[0]

            if video_id in analyzed_video_ids:
                processed += 1
                continue

            video_idx = processed
            base_pct = int(video_idx / total_videos * 100)
            yield ProgressEvent(
                "video_analysis", base_pct, f"Analyzing {filename}…"
            )

            if self._settings.LOCAL_DEV:
                file_uri = f"local://{blob_path}"
            else:
                file_uri = f"gs://{self._settings.GCS_BUCKET}/{blob_path}"

            q: asyncio.Queue[tuple[str, int]] = asyncio.Queue()

            async def _cb(
                msg: str, sub_pct: int, _q: asyncio.Queue[tuple[str, int]] = q,
            ) -> None:
                await _q.put((msg, sub_pct))

            task = asyncio.create_task(
                asyncio.wait_for(analyze_video(file_uri, video_id, _cb), timeout=600)
            )
            start = time.monotonic()
            last_msg = f"Analyzing {filename}"
            last_sub_pct = 0
            while not task.done():
                try:
                    last_msg, last_sub_pct = await asyncio.wait_for(
                        asyncio.shield(q.get()), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    pass
                elapsed = int(time.monotonic() - start)
                overall = base_pct + last_sub_pct // total_videos
                yield ProgressEvent(
                    "video_analysis",
                    min(overall, 99),
                    f"{filename}: {last_msg} ({elapsed}s)",
                )
            # Drain any final messages queued after task completion
            while not q.empty():
                last_msg, last_sub_pct = q.get_nowait()
                overall = base_pct + last_sub_pct // total_videos
                yield ProgressEvent(
                    "video_analysis",
                    min(overall, 99),
                    f"{filename}: {last_msg}",
                )
            result = await task
            project.videos.append(result)
            processed += 1
            logger.info(
                "Video %s analyzed in %.1fs",
                filename, time.monotonic() - start,
            )

        yield ProgressEvent("video_analysis", 100, "Video analysis complete")

        # PDF extraction + screenshot analysis
        for blob_path in pdf_blobs:
            filename = blob_path.rsplit("/", 1)[-1]
            pdf_id = filename.rsplit(".", 1)[0]

            if pdf_id in analyzed_pdf_ids:
                processed += 1
                continue

            pct = int(processed / total * 100) if total else 0
            yield ProgressEvent(
                "pdf_extraction", pct, f"Extracting PDF: {filename}"
            )

            if self._settings.LOCAL_DEV:
                file_uri = f"local://{blob_path}"
            else:
                file_uri = f"gs://{self._settings.GCS_BUCKET}/{blob_path}"
            extraction = await extract_pdf(file_uri, pdf_id)

            # Analyze screenshots from extracted images
            for i, img in enumerate(extraction.images):
                image_bytes = get_extracted_image(img.image_id)
                if image_bytes is not None:
                    analyzed_img = await analyze_screenshot(
                        image_bytes, img.image_id,
                    )
                    extraction.images[i] = analyzed_img

            project.pdfs.append(extraction)
            processed += 1

        yield ProgressEvent("pdf_extraction", 100, "PDF extraction complete")

    async def _run_path_merge(self, project: Project) -> None:
        """Phase 3: Merge video analyses into unified decision trees."""
        from walkthrough.ai.tools.merge_paths import merge_paths

        project.decision_trees = await merge_paths(project.videos)
        project.updated_at = _now()
        await write_phase_artifact(
            project.project_id,
            "path_merge",
            {
                "decision_trees": [
                    t.model_dump(mode="json") for t in project.decision_trees
                ]
            },
        )

    async def _run_narrative(self, project: Project) -> None:
        """Phase 4: Synthesize narratives. Preserves full tree structure (M6).

        After synthesis, narrative text is available for compression while
        workflow structures (screens, branches, elements) remain complete.
        """
        from walkthrough.ai.tools.narrative import synthesize_narrative

        project.decision_trees = await synthesize_narrative(
            project.videos, project.pdfs, project.decision_trees,
        )
        project.updated_at = _now()
        await write_phase_artifact(
            project.project_id,
            "narrative",
            {
                "decision_trees": [
                    t.model_dump(mode="json") for t in project.decision_trees
                ]
            },
        )

    async def _run_contradictions(self, project: Project) -> None:
        """Phase 5: Three-way cross-reference contradiction detection.

        Transitions project status to 'clarifying' after completion.
        """
        from walkthrough.ai.tools.detect_contradictions import (
            detect_contradictions,
        )

        project.gaps = await detect_contradictions(
            project.videos, project.pdfs, project.decision_trees,
        )
        project.status = "clarifying"
        project.updated_at = _now()
        await write_phase_artifact(
            project.project_id,
            "contradictions",
            {"gaps": [g.model_dump(mode="json") for g in project.gaps]},
        )

    async def _run_clarification(self, project: Project) -> None:
        """Phase 6: Generate clarification questions from detected gaps.

        Always runs even with zero gaps (N7). Pipeline pauses after this
        phase to wait for user input via API endpoints.
        """
        from walkthrough.ai.tools.clarification import generate_questions
        from walkthrough.ai.tools.consolidator import consolidate_gaps

        project.questions = await generate_questions(
            project.gaps, project.decision_trees,
        )
        project.meta_questions = await consolidate_gaps(
            project.gaps, project.videos, project.pdfs,
        )
        project.updated_at = _now()
        await write_phase_artifact(
            project.project_id,
            "clarification",
            {
                "questions": [
                    q.model_dump(mode="json") for q in project.questions
                ]
            },
        )

    async def _run_generation(
        self, project: Project,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Phase 7-8: Generate final walkthrough JSON output.

        Stores self-contained output on project.walkthrough_output for
        frontend retrieval. Transitions status to 'complete'.
        """
        from walkthrough.ai.tools.generate import generate_walkthrough

        project.status = "generating"
        project.updated_at = _now()
        yield ProgressEvent(
            "generation", 0, "Generating walkthrough output..."
        )

        output = await generate_walkthrough(project)
        project.walkthrough_output = output
        project.status = "complete"
        project.updated_at = _now()
        await write_phase_artifact(project.project_id, "generation", output)

        yield ProgressEvent(
            "generation", 100, "Walkthrough generation complete"
        )

    async def _run_qa(
        self, project: Project,
    ) -> AsyncGenerator[ProgressEvent, None]:
        """Phase 9: Run QA validators in parallel and stash report on output.

        Writes ``phases/qa.json`` and attaches the serialized report under
        ``project.walkthrough_output['qa_report']``. When
        ``Settings().QA_BLOCK_ON_CRITICAL`` is true and the report has
        critical findings, transitions ``project.status`` to ``'qa_blocked'``.
        """
        from walkthrough.ai.qa.runner import run_qa

        yield ProgressEvent("qa", 0, "Running QA validators...")

        report = await run_qa(project)

        if project.walkthrough_output is None:
            project.walkthrough_output = {}
        project.walkthrough_output["qa_report"] = report.model_dump(mode="json")

        if self._settings.QA_BLOCK_ON_CRITICAL and report.has_critical:
            project.status = "qa_blocked"

        project.updated_at = _now()

        critical_count = sum(
            1
            for r in report.results
            for f in r.findings
            if f.severity == "critical"
        )
        yield ProgressEvent(
            "qa", 100, f"QA complete — {critical_count} critical findings"
        )

    async def _save(self, project: Project) -> None:
        """Persist project state to Firestore (M8)."""
        project.updated_at = _now()
        await self._firestore.save_project(project)


# --- Module-level helpers ---


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _phase_index(phase: str) -> int:
    """Return numeric index for a phase name. Unknown phases sort past end."""
    try:
        return PHASE_ORDER.index(phase)
    except ValueError:
        return len(PHASE_ORDER)


def _infer_resume_phase(project: Project) -> str:
    """Determine which phase to resume from based on project state.

    Terminal/paused states (complete, generating, clarifying) short-circuit
    based on status alone. For in-flight analyzing/uploading runs, resume
    is driven by the presence of per-phase artifact files on disk so that
    killed pipelines pick up exactly where they left off.
    """
    if project.status == "complete":
        return "done"

    if project.status == "generating":
        return "generation"

    if project.status == "clarifying":
        # Check if all critical gaps are resolved → ready for generation
        unresolved_critical = any(
            g.severity == "critical" and not g.resolved
            for g in project.gaps
        )
        if project.questions and not unresolved_critical:
            return "generation"
        return "clarification"

    # Status is "uploading" or "analyzing" — drive resume from artifact presence.
    done = set(completed_phases(project.project_id))
    if not done or (not project.videos and not project.pdfs):
        return "ingestion"

    # Ingestion writes no artifact, so skip it — the presence of videos/pdfs
    # above already confirms ingestion ran. Find the first downstream phase
    # whose artifact is absent.
    for phase in PHASE_ORDER:
        if phase == "ingestion":
            continue
        if phase not in done:
            return phase
    # All artifacts present but status hasn't transitioned — resume at
    # generation so the pipeline finalizes walkthrough_output + status.
    return "generation"
