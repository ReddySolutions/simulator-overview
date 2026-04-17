from __future__ import annotations

import asyncio
import json
import logging
import os

import vertexai
from google.api_core.exceptions import ResourceExhausted
from vertexai.generative_models import Content, GenerationConfig, GenerativeModel, Part

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


async def analyze_video(video_path: str, video_id: str) -> VideoAnalysis:
    """Analyze a video using Gemini and extract structured perception data.

    Args:
        video_path: GCS URI (gs://...) to the MP4 file.
        video_id: Unique identifier for this video.

    Returns:
        VideoAnalysis with extracted keyframes, transitions, audio, and flow.

    Raises:
        ValueError: If Gemini response cannot be parsed into the expected schema.
        ResourceExhausted: If rate limits exceeded after all retries.
    """
    settings = Settings()
    vertexai.init(project=settings.GCP_PROJECT_ID, location="us-central1")

    model = GenerativeModel(settings.GEMINI_MODEL)
    video_part = Part.from_uri(uri=video_path, mime_type="video/mp4")

    generation_config = GenerationConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    prompt_part = Part.from_text(EXTRACTION_PROMPT)
    content = Content(role="user", parts=[video_part, prompt_part])
    response_text = await _call_with_retries(model, [content], generation_config)

    filename = os.path.basename(video_path)
    return _parse_response(response_text, video_id, filename)


async def _call_with_retries(
    model: GenerativeModel,
    contents: list[Content],
    generation_config: GenerationConfig,
) -> str:
    """Call Gemini with exponential backoff on rate limits."""
    for attempt in range(MAX_RETRIES):
        try:
            response = await asyncio.to_thread(
                lambda: model.generate_content(
                    contents,
                    generation_config=generation_config,
                )
            )
            text = response.text
            if not text:
                raise ValueError("Gemini returned an empty response")
            return text
        except ResourceExhausted:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = INITIAL_BACKOFF_SECONDS * (2**attempt)
            logger.warning(
                "Gemini rate limit hit, retrying in %ds (attempt %d/%d)",
                wait,
                attempt + 1,
                MAX_RETRIES,
            )
            await asyncio.sleep(wait)

    raise ResourceExhausted("Rate limit exceeded after retries")


def _parse_response(
    response_text: str, video_id: str, filename: str
) -> VideoAnalysis:
    """Parse Gemini JSON response into VideoAnalysis model."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned invalid JSON for video '{video_id}': {e}\n"
            f"Response: {response_text[:500]}"
        ) from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Gemini response for video '{video_id}' is not a JSON object: "
            f"{type(data).__name__}"
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

        transitions = [
            TransitionEvent(**t) for t in data.get("transitions", [])
        ]

        audio_segments = [
            AudioSegment(**a) for a in data.get("audio_segments", [])
        ]

        temporal_flow: list[str] = data.get("temporal_flow", [])

        return VideoAnalysis(
            video_id=video_id,
            filename=filename,
            keyframes=keyframes,
            transitions=transitions,
            audio_segments=audio_segments,
            temporal_flow=temporal_flow,
        )
    except (KeyError, TypeError) as e:
        raise ValueError(
            f"Gemini response for video '{video_id}' does not match expected "
            f"schema: {e}\n"
            f"Response keys: {list(data.keys())}"
        ) from e
