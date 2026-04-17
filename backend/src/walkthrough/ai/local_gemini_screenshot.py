"""Local Gemini screenshot analysis using google-genai (AI Studio) — no GCP project needed."""

from __future__ import annotations

import asyncio
import json
import logging

from google import genai
from google.genai.types import GenerateContentConfig, Part

from walkthrough.config import Settings
from walkthrough.models.pdf import PDFImage
from walkthrough.models.video import UIElement

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2

# Same prompt as the Vertex AI version
SCREENSHOT_PROMPT = """\
Analyze this screenshot image from a PDF document. Identify any software UI elements visible \
in the image. Return ONLY valid JSON with exactly this schema:

{
  "description": "<brief description of what the image shows>",
  "is_ui_screenshot": <true if the image shows a software interface, false otherwise>,
  "ui_elements": [
    {
      "element_type": "<button|dropdown|text_field|tab|label|checkbox|radio|link|table|other>",
      "label": "<exact text label visible on the element>",
      "state": "<enabled|disabled|selected|active or null>"
    }
  ]
}

IMPORTANT INSTRUCTIONS:
- If the image shows a software UI (application screen, web page, dialog, form), set \
is_ui_screenshot to true and list EVERY visible UI element — buttons, dropdowns, text fields, \
tabs, labels, checkboxes, radio buttons, links, tables — with their EXACT text labels.
- If the image is NOT a UI screenshot (e.g. a chart, diagram, photo, logo, decorative image), \
set is_ui_screenshot to false and return an empty ui_elements array.
- Always provide a description regardless of image type.
- Return ONLY the JSON object, no markdown fencing or extra text.\
"""


async def analyze_screenshot(image_bytes: bytes, image_id: str) -> PDFImage:
    """Analyze a PDF-extracted screenshot using Gemini via Google AI Studio.

    Args:
        image_bytes: Raw image bytes (PNG format).
        image_id: Unique identifier for this image (format: {pdf_id}_page_{N}).

    Returns:
        PDFImage with description and classified UI elements.
    """
    settings = Settings()
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    config = GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
    )

    response_text = await _call_with_retries(
        client, settings.GEMINI_MODEL, image_bytes, config,
    )

    page_number = _extract_page_number(image_id)
    return _parse_response(response_text, image_id, page_number)


async def _call_with_retries(
    client: genai.Client,
    model: str,
    image_bytes: bytes,
    config: GenerateContentConfig,
) -> str:
    """Call Gemini with exponential backoff on rate limits."""
    for attempt in range(MAX_RETRIES):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[
                    Part.from_bytes(data=image_bytes, mime_type="image/png"),
                    Part.from_text(text=SCREENSHOT_PROMPT),
                ],
                config=config,
            )
            text = response.text
            if not text:
                raise ValueError("Gemini returned an empty response")
            return text
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = INITIAL_BACKOFF_SECONDS * (2**attempt)
                logger.warning(
                    "Gemini rate limit hit, retrying in %ds (attempt %d/%d)",
                    wait, attempt + 1, MAX_RETRIES,
                )
                await asyncio.sleep(wait)
            else:
                raise

    raise RuntimeError("Rate limit exceeded after retries")


def _extract_page_number(image_id: str) -> int:
    """Extract page number from image_id format: {pdf_id}_page_{N}."""
    parts = image_id.rsplit("_page_", 1)
    if len(parts) == 2:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


def _parse_response(
    response_text: str, image_id: str, page_number: int,
) -> PDFImage:
    """Parse Gemini JSON response into PDFImage model."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned invalid JSON for image '{image_id}': {e}\n"
            f"Response: {response_text[:500]}"
        ) from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Gemini response for image '{image_id}' is not a JSON object"
        )

    description = data.get("description", "")
    is_ui = data.get("is_ui_screenshot", False)

    ui_elements: list[UIElement] | None = None
    if is_ui:
        raw_elements = data.get("ui_elements", [])
        if raw_elements:
            try:
                ui_elements = [UIElement(**el) for el in raw_elements]
            except (TypeError, KeyError) as e:
                raise ValueError(
                    f"Gemini response for image '{image_id}' has invalid "
                    f"ui_elements: {e}"
                ) from e

    return PDFImage(
        image_id=image_id,
        page_number=page_number,
        description=description or None,
        ui_elements=ui_elements,
    )
