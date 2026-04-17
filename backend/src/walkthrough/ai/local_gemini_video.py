"""Local Gemini video analysis using google-genai (AI Studio) — no GCP project needed."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from google import genai
from google.genai.types import GenerateContentConfig, Part

from walkthrough.config import Settings
from walkthrough.models.video import (
    AudioSegment,
    Keyframe,
    TransitionEvent,
    UIElement,
    VideoAnalysis,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2

# Callback receives (human-readable message, sub-percentage 0-100 within this video)
ProgressCallback = Callable[[str, int], Awaitable[None]]

# Same prompt as the Vertex AI version
EXTRACTION_PROMPT = """\
Analyze this training video and extract structured data. Return ONLY valid JSON with exactly this schema:

{
  "keyframes": [
    {
      "timestamp_sec": <float>,
      "ui_elements": [
        {
          "element_type": "<button|dropdown|text_field|tab|label|checkbox|radio|link|table|other>",
          "label": "<exact text label>",
          "state": "<enabled|disabled|selected|active or null>"
        }
      ],
      "screenshot_description": "<what is shown on screen>",
      "transition_from": "<description of what triggered arrival at this screen, or null for first>"
    }
  ],
  "transitions": [
    {
      "from_timestamp": <float>,
      "to_timestamp": <float>,
      "action": "<what user did to cause transition>",
      "trigger_element": "<label of element clicked/interacted with, or null>"
    }
  ],
  "audio_segments": [
    {
      "start_sec": <float>,
      "end_sec": <float>,
      "text": "<transcribed speech>",
      "intent": "<what the speaker is explaining or instructing, or null>"
    }
  ],
  "temporal_flow": [
    "<ordered description of each screen/state shown in the video>"
  ]
}

IMPORTANT INSTRUCTIONS:
- For keyframes: Capture EVERY distinct screen state shown in the video. \
List EVERY visible UI element — buttons, dropdowns, text fields, tabs, labels, \
checkboxes, radio buttons, links, tables — with their EXACT text labels as they \
appear on screen.
- For transitions: Record every navigation event between screens, noting which \
element was clicked or interacted with.
- For audio_segments: Transcribe all spoken narration with timestamps. Annotate \
the intent (what concept or procedure the speaker is explaining).
- For temporal_flow: List screens in chronological order as they appear in the video.
- Use precise timestamps in seconds.
- Return ONLY the JSON object, no markdown fencing or extra text.\
"""


async def analyze_video(
    video_path: str,
    video_id: str,
    on_progress: ProgressCallback | None = None,
) -> VideoAnalysis:
    """Analyze a video using Gemini via Google AI Studio (no GCP needed).

    Args:
        video_path: local:// URI or local filesystem path to the MP4 file.
        video_id: Unique identifier for this video.
        on_progress: Optional async callback called with (message, sub_pct) at
            each stage. sub_pct is 0-100 within this single video's analysis.

    Returns:
        VideoAnalysis with extracted keyframes, transitions, audio, and flow.
    """
    settings = Settings()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    local_path = _resolve_path(video_path, settings)
    filename = os.path.basename(local_path)
    size_mb = os.path.getsize(local_path) / (1024 * 1024) if os.path.exists(local_path) else 0.0

    async def _emit(msg: str, pct: int) -> None:
        logger.info("[%s] %d%% %s", video_id, pct, msg)
        if on_progress:
            await on_progress(msg, pct)

    await _emit(f"Uploading {size_mb:.1f} MB to Gemini file API", 0)
    t0 = time.monotonic()
    uploaded = await asyncio.wait_for(
        asyncio.to_thread(client.files.upload, file=local_path),
        timeout=300,
    )
    logger.info("[%s] upload finished in %.1fs", video_id, time.monotonic() - t0)

    await _emit("Upload complete, waiting for Gemini to process video", 25)
    uploaded = await _wait_for_file_active(client, uploaded, on_progress=_emit)

    config = GenerateContentConfig(temperature=0.1)

    await _emit("Extracting structured data with AI", 70)
    response_text = await asyncio.wait_for(
        _call_with_retries(client, settings.GEMINI_MODEL, uploaded, config, _emit),
        timeout=300,
    )

    await _emit("Parsing Gemini response", 95)
    return _parse_response(response_text, video_id, filename)


async def _wait_for_file_active(
    client: genai.Client,
    uploaded_file: object,
    timeout_sec: int = 120,
    on_progress: ProgressCallback | None = None,
) -> object:
    """Poll until the uploaded file reaches ACTIVE state."""
    start = time.monotonic()
    deadline = start + timeout_sec
    while time.monotonic() < deadline:
        f = await asyncio.to_thread(client.files.get, name=uploaded_file.name)
        state = getattr(f.state, "name", str(f.state))
        if state == "ACTIVE":
            if on_progress:
                await on_progress("Gemini finished processing video", 65)
            return f
        if state == "FAILED":
            raise RuntimeError(f"Gemini file processing failed: {uploaded_file.name}")
        elapsed = int(time.monotonic() - start)
        # Glide from 30 → 60 over the expected wait
        sub_pct = min(60, 30 + elapsed // 2)
        if on_progress:
            await on_progress(
                f"Gemini processing video (state={state})",
                sub_pct,
            )
        await asyncio.sleep(2)
    raise TimeoutError(
        f"File {uploaded_file.name} did not become ACTIVE within {timeout_sec}s"
    )


async def _call_with_retries(
    client: genai.Client,
    model: str,
    uploaded_file: object,
    config: GenerateContentConfig,
    on_progress: ProgressCallback | None = None,
) -> str:
    """Call Gemini with exponential backoff on rate limits."""
    for attempt in range(MAX_RETRIES):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[uploaded_file, Part.from_text(text=EXTRACTION_PROMPT)],
                config=config,
            )
            text = response.text
            if not text:
                raise ValueError("Gemini returned an empty response")
            return text
        except Exception as e:
            err_str = str(e)
            is_retriable = (
                "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                or "503" in err_str or "UNAVAILABLE" in err_str
            )
            if is_retriable:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = INITIAL_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Gemini transient error, retrying in %ds (attempt %d/%d): %s",
                    wait, attempt + 1, MAX_RETRIES, err_str[:100],
                )
                if on_progress:
                    await on_progress(
                        f"Transient error, retrying in {wait}s "
                        f"(attempt {attempt + 2}/{MAX_RETRIES})",
                        70,
                    )
                await asyncio.sleep(wait)
            else:
                raise

    raise RuntimeError("Rate limit exceeded after retries")


def _resolve_path(video_path: str, settings: Settings) -> str:
    """Resolve local:// URIs to filesystem paths."""
    if video_path.startswith("local://"):
        relative = video_path.removeprefix("local://")
        return str(Path(settings.LOCAL_DATA_DIR) / "uploads" / relative)
    if video_path.startswith("gs://"):
        parts = video_path.split("/", 3)
        local_name = parts[3] if len(parts) > 3 else parts[-1]
        return str(Path(settings.LOCAL_DATA_DIR) / "uploads" / local_name)
    return video_path


def _parse_response(
    response_text: str, video_id: str, filename: str
) -> VideoAnalysis:
    """Parse Gemini JSON response into VideoAnalysis model."""
    text = response_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned invalid JSON for video '{video_id}': {e}\n"
            f"Response: {response_text[:500]}"
        ) from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Gemini response for video '{video_id}' is not a JSON object"
        )

    try:
        keyframes = [
            Keyframe(
                video_id=video_id,
                timestamp_sec=kf["timestamp_sec"],
                ui_elements=[UIElement(**el) for el in kf.get("ui_elements", [])],
                screenshot_description=kf["screenshot_description"],
                transition_from=kf.get("transition_from"),
            )
            for kf in data.get("keyframes", [])
        ]
        transitions = [TransitionEvent(**t) for t in data.get("transitions", [])]
        audio_segments = [AudioSegment(**a) for a in data.get("audio_segments", [])]
        temporal_flow: list[str] = data.get("temporal_flow", [])

        return VideoAnalysis(
            video_id=video_id,
            filename=filename,
            keyframes=keyframes,
            transitions=transitions,
            audio_segments=audio_segments,
            temporal_flow=temporal_flow,
        )
    except Exception as e:
        from pydantic import ValidationError
        if not isinstance(e, (KeyError, TypeError, ValidationError)):
            raise
        raise ValueError(
            f"Gemini response for video '{video_id}' does not match expected "
            f"schema: {e}"
        ) from e
