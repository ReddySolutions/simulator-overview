"""Tests for local_gemini_video — parse, resolve, wait, retry, and live analysis."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from walkthrough.ai.local_gemini_video import (
    _call_with_retries,
    _parse_response,
    _resolve_path,
    _wait_for_file_active,
)
from walkthrough.config import Settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "keyframes": [
        {
            "timestamp_sec": 0.0,
            "ui_elements": [
                {"element_type": "button", "label": "Submit", "state": "enabled"}
            ],
            "screenshot_description": "Login screen",
            "transition_from": None,
        }
    ],
    "transitions": [
        {
            "from_timestamp": 0.0,
            "to_timestamp": 5.0,
            "action": "Clicked Submit",
            "trigger_element": "Submit",
        }
    ],
    "audio_segments": [
        {
            "start_sec": 0.0,
            "end_sec": 3.0,
            "text": "Welcome to the system.",
            "intent": "Greeting",
        }
    ],
    "temporal_flow": ["Login screen", "Dashboard"],
}


def _json(payload: dict) -> str:
    return json.dumps(payload)


def _make_file(state: str, name: str = "files/abc123") -> SimpleNamespace:
    return SimpleNamespace(name=name, state=SimpleNamespace(name=state))


def _make_client_with_file_states(*states: str) -> MagicMock:
    """Return a mock Gemini client whose files.get cycles through states."""
    client = MagicMock()
    client.files.get.side_effect = [_make_file(s) for s in states]
    return client


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_valid_full_payload(self):
        result = _parse_response(_json(VALID_PAYLOAD), "vid1", "demo.mp4")
        assert result.video_id == "vid1"
        assert result.filename == "demo.mp4"
        assert len(result.keyframes) == 1
        assert result.keyframes[0].timestamp_sec == 0.0
        assert result.keyframes[0].ui_elements[0].label == "Submit"
        assert len(result.transitions) == 1
        assert len(result.audio_segments) == 1
        assert result.temporal_flow == ["Login screen", "Dashboard"]

    def test_markdown_fenced_json(self):
        fenced = "```json\n" + _json(VALID_PAYLOAD) + "\n```"
        result = _parse_response(fenced, "vid1", "demo.mp4")
        assert len(result.keyframes) == 1

    def test_markdown_fenced_no_lang(self):
        fenced = "```\n" + _json(VALID_PAYLOAD) + "\n```"
        result = _parse_response(fenced, "vid1", "demo.mp4")
        assert len(result.keyframes) == 1

    def test_leading_trailing_whitespace(self):
        result = _parse_response("  \n" + _json(VALID_PAYLOAD) + "\n  ", "v", "f.mp4")
        assert result.video_id == "v"

    def test_empty_arrays(self):
        payload = {
            "keyframes": [],
            "transitions": [],
            "audio_segments": [],
            "temporal_flow": [],
        }
        result = _parse_response(_json(payload), "vid2", "empty.mp4")
        assert result.keyframes == []
        assert result.transitions == []
        assert result.audio_segments == []
        assert result.temporal_flow == []

    def test_optional_nulls(self):
        payload = {
            "keyframes": [
                {
                    "timestamp_sec": 1.5,
                    "ui_elements": [
                        {"element_type": "label", "label": "Status", "state": None}
                    ],
                    "screenshot_description": "Main screen",
                    "transition_from": None,
                }
            ],
            "transitions": [
                {
                    "from_timestamp": 1.5,
                    "to_timestamp": 4.0,
                    "action": "Pressed Enter",
                    "trigger_element": None,
                }
            ],
            "audio_segments": [
                {"start_sec": 1.0, "end_sec": 2.0, "text": "OK", "intent": None}
            ],
            "temporal_flow": ["Main screen"],
        }
        result = _parse_response(_json(payload), "vid3", "nulls.mp4")
        assert result.keyframes[0].transition_from is None
        assert result.keyframes[0].ui_elements[0].state is None
        assert result.transitions[0].trigger_element is None
        assert result.audio_segments[0].intent is None

    def test_missing_keys_in_keyframe_raises(self):
        payload = {
            "keyframes": [{"timestamp_sec": 0.0}],  # missing required fields
            "transitions": [],
            "audio_segments": [],
            "temporal_flow": [],
        }
        with pytest.raises(ValueError, match="schema"):
            _parse_response(_json(payload), "vid4", "bad.mp4")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            _parse_response("not json at all", "vid5", "bad.mp4")

    def test_json_array_not_object_raises(self):
        with pytest.raises(ValueError, match="not a JSON object"):
            _parse_response("[1, 2, 3]", "vid6", "bad.mp4")

    def test_missing_ui_element_fields_raises(self):
        payload = {
            "keyframes": [
                {
                    "timestamp_sec": 0.0,
                    "ui_elements": [{"element_type": "button"}],  # missing label
                    "screenshot_description": "screen",
                }
            ],
            "transitions": [],
            "audio_segments": [],
            "temporal_flow": [],
        }
        with pytest.raises(ValueError, match="schema"):
            _parse_response(_json(payload), "vid7", "bad.mp4")


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------


class TestResolvePath:
    def _settings(self, data_dir: str = "/tmp/data") -> Settings:
        return Settings(LOCAL_DATA_DIR=data_dir)

    def test_local_uri(self):
        s = self._settings("/tmp/data")
        result = _resolve_path("local://projects/p1/uploads/vid.mp4", s)
        assert result == "/tmp/data/uploads/projects/p1/uploads/vid.mp4"

    def test_gs_uri(self):
        s = self._settings("/tmp/data")
        result = _resolve_path("gs://my-bucket/projects/p1/vid.mp4", s)
        assert result == "/tmp/data/uploads/projects/p1/vid.mp4"

    def test_plain_path_returned_as_is(self):
        s = self._settings("/tmp/data")
        path = "/Users/gw/Downloads/video.mp4"
        assert _resolve_path(path, s) == path

    def test_gs_uri_single_segment(self):
        s = self._settings("/tmp/data")
        result = _resolve_path("gs://bucket/file.mp4", s)
        assert result.endswith("file.mp4")


# ---------------------------------------------------------------------------
# _wait_for_file_active
# ---------------------------------------------------------------------------


class TestWaitForFileActive:
    async def test_already_active(self):
        client = _make_client_with_file_states("ACTIVE")
        uploaded = _make_file("PROCESSING")
        result = await _wait_for_file_active(client, uploaded, timeout_sec=10)
        assert result.state.name == "ACTIVE"
        client.files.get.assert_called_once()

    async def test_becomes_active_after_polling(self):
        client = _make_client_with_file_states("PROCESSING", "PROCESSING", "ACTIVE")
        uploaded = _make_file("PROCESSING")
        with patch("asyncio.sleep", return_value=None):
            result = await _wait_for_file_active(client, uploaded, timeout_sec=30)
        assert result.state.name == "ACTIVE"
        assert client.files.get.call_count == 3

    async def test_failed_state_raises(self):
        client = _make_client_with_file_states("FAILED")
        uploaded = _make_file("PROCESSING")
        with pytest.raises(RuntimeError, match="failed"):
            await _wait_for_file_active(client, uploaded, timeout_sec=10)

    async def test_timeout_raises(self):
        client = MagicMock()
        client.files.get.return_value = _make_file("PROCESSING")
        uploaded = _make_file("PROCESSING")
        # timeout_sec=-1 means deadline is already past before the loop starts
        with pytest.raises(TimeoutError):
            await _wait_for_file_active(client, uploaded, timeout_sec=-1)


# ---------------------------------------------------------------------------
# _call_with_retries
# ---------------------------------------------------------------------------


class TestCallWithRetries:
    def _make_response(self, text: str) -> MagicMock:
        r = MagicMock()
        r.text = text
        return r

    def _make_error(self, message: str) -> Exception:
        return RuntimeError(message)

    async def test_success_first_attempt(self):
        client = MagicMock()
        client.models.generate_content.return_value = self._make_response(
            _json(VALID_PAYLOAD)
        )
        config = MagicMock()
        text = await _call_with_retries(client, "gemini-flash", MagicMock(), config)
        assert text == _json(VALID_PAYLOAD)
        assert client.models.generate_content.call_count == 1

    async def test_retries_on_429(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            self._make_error("429 RESOURCE_EXHAUSTED"),
            self._make_response("{}"),
        ]
        config = MagicMock()
        with patch("asyncio.sleep", return_value=None):
            text = await _call_with_retries(client, "gemini-flash", MagicMock(), config)
        assert text == "{}"
        assert client.models.generate_content.call_count == 2

    async def test_retries_on_503(self):
        client = MagicMock()
        client.models.generate_content.side_effect = [
            self._make_error("503 UNAVAILABLE"),
            self._make_response("{}"),
        ]
        config = MagicMock()
        with patch("asyncio.sleep", return_value=None):
            text = await _call_with_retries(client, "gemini-flash", MagicMock(), config)
        assert text == "{}"
        assert client.models.generate_content.call_count == 2

    async def test_non_retriable_error_raises_immediately(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("404 NOT_FOUND")
        config = MagicMock()
        with pytest.raises(RuntimeError, match="404"):
            await _call_with_retries(client, "gemini-flash", MagicMock(), config)
        assert client.models.generate_content.call_count == 1

    async def test_exhausts_retries_and_raises(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("503 UNAVAILABLE")
        config = MagicMock()
        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RuntimeError, match="503"):
                await _call_with_retries(client, "gemini-flash", MagicMock(), config)
        assert client.models.generate_content.call_count == 3  # MAX_RETRIES

    async def test_empty_response_raises(self):
        client = MagicMock()
        client.models.generate_content.return_value = self._make_response("")
        config = MagicMock()
        with pytest.raises(ValueError, match="empty"):
            await _call_with_retries(client, "gemini-flash", MagicMock(), config)

    async def test_none_response_raises(self):
        client = MagicMock()
        r = MagicMock()
        r.text = None
        client.models.generate_content.return_value = r
        config = MagicMock()
        with pytest.raises(ValueError, match="empty"):
            await _call_with_retries(client, "gemini-flash", MagicMock(), config)


# ---------------------------------------------------------------------------
# Progress callback — verifies the bar moves through stages, not just 0→100%.
# Regression test for the "stuck at 0%, Uploading to Gemini..." UX bug.
# ---------------------------------------------------------------------------


class TestProgressCallback:
    async def test_wait_for_file_active_emits_percentages(self):
        client = _make_client_with_file_states("PROCESSING", "PROCESSING", "ACTIVE")
        uploaded = _make_file("PROCESSING")
        calls: list[tuple[str, int]] = []

        async def cb(msg: str, pct: int) -> None:
            calls.append((msg, pct))

        with patch("asyncio.sleep", return_value=None):
            await _wait_for_file_active(
                client, uploaded, timeout_sec=30, on_progress=cb,
            )

        assert calls, "expected at least one progress callback"
        # Each polling tick reports a state+elapsed message
        processing_calls = [c for c in calls if "PROCESSING" in c[0]]
        assert len(processing_calls) >= 1
        # Final ACTIVE tick jumps to a higher percentage
        assert calls[-1][1] == 65
        assert "finished" in calls[-1][0].lower()
        # All sub-percentages stay in the 25-65 band this stage is assigned
        assert all(25 <= pct <= 65 for _, pct in calls)

    async def test_call_with_retries_emits_progress_on_retry(self):
        from walkthrough.ai.local_gemini_video import _call_with_retries

        client = MagicMock()
        response = MagicMock()
        response.text = "{}"
        client.models.generate_content.side_effect = [
            RuntimeError("429 RESOURCE_EXHAUSTED"),
            response,
        ]
        config = MagicMock()
        calls: list[tuple[str, int]] = []

        async def cb(msg: str, pct: int) -> None:
            calls.append((msg, pct))

        with patch("asyncio.sleep", return_value=None):
            result = await _call_with_retries(
                client, "gemini-flash", MagicMock(), config, cb,
            )

        assert result == "{}"
        retry_calls = [c for c in calls if "retry" in c[0].lower()]
        assert retry_calls, "expected a retry progress update"
        assert retry_calls[0][1] == 70


# ---------------------------------------------------------------------------
# Integration test — requires live Gemini API and the test video
# ---------------------------------------------------------------------------

VIDEO_PATH = "/Users/gw/Downloads/CXone Recording Erin Turner Jan 2 2026.mp4"


@pytest.mark.integration
async def test_analyze_video_live():
    """End-to-end: uploads video, waits for ACTIVE, calls Gemini, parses result."""
    from walkthrough.ai.local_gemini_video import analyze_video

    result = await analyze_video(VIDEO_PATH, "erin-jan2-live")

    assert result.video_id == "erin-jan2-live"
    assert result.filename == "CXone Recording Erin Turner Jan 2 2026.mp4"
    assert len(result.keyframes) > 0, "Expected at least one keyframe"
    assert len(result.audio_segments) > 0, "Expected at least one audio segment"
    assert len(result.temporal_flow) > 0, "Expected temporal flow entries"

    # Keyframes must have valid timestamps and descriptions
    for kf in result.keyframes:
        assert kf.timestamp_sec >= 0
        assert kf.screenshot_description

    # Audio segments must have valid time ranges and text
    for seg in result.audio_segments:
        assert seg.end_sec >= seg.start_sec
        assert seg.text
