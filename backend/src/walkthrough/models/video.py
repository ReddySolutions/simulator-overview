from __future__ import annotations

from pydantic import BaseModel


class UIElement(BaseModel):
    element_type: str  # button|dropdown|text_field|tab|label|checkbox|radio|link|table|other
    label: str
    state: str | None = None


class Keyframe(BaseModel):
    video_id: str
    timestamp_sec: float
    ui_elements: list[UIElement]
    screenshot_description: str
    transition_from: str | None = None


class TransitionEvent(BaseModel):
    from_timestamp: float
    to_timestamp: float
    action: str
    trigger_element: str | None = None


class AudioSegment(BaseModel):
    start_sec: float
    end_sec: float
    text: str
    intent: str | None = None


class VideoAnalysis(BaseModel):
    video_id: str
    filename: str
    keyframes: list[Keyframe]
    transitions: list[TransitionEvent]
    audio_segments: list[AudioSegment]
    temporal_flow: list[str]
