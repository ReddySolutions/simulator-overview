---
module: PhaseOrchestrator
date: 2026-04-17
problem_type: developer_experience
component: background_job
symptoms:
  - "Progress bar stuck at 0% for minutes during video analysis"
  - "Status message frozen at 'Uploading to Gemini file API...'"
  - "No way to tell whether the pipeline is stuck or progressing"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: medium
tags: [progress, sse, gemini, observability, heartbeat, video-analysis]
---

# Progress bar stuck at 0% during multi-minute Gemini video upload

## Problem
The analysis progress page for the walkthrough pipeline displayed "Video Analysis — 0% — Uploading to Gemini file API..." and never moved, sometimes for several minutes. The pipeline was actually working, but the UI provided no signal to distinguish "still working" from "hung".

## Environment
- Module: Walkthrough backend pipeline (`PhaseOrchestrator`)
- Affected Files:
  - `backend/src/walkthrough/ai/local_gemini_video.py`
  - `backend/src/walkthrough/ai/gemini_video.py`
  - `backend/src/walkthrough/ai/orchestrator.py`
- Date: 2026-04-17
- Stack: FastAPI + SSE + Google GenAI SDK (AI Studio) / Vertex AI

## Symptoms
- Progress bar pegged at 0% throughout Gemini upload + file-activation wait
- Single frozen status string: "Uploading to Gemini file API..."
- Video analysis can legitimately take 2–5 minutes; users assume the app is broken
- Backend logs were sparse (DEBUG-level only) so tailing didn't help either

## What Didn't Work

**Direct solution:** Identified and fixed on first pass once the progress pipeline was traced end-to-end.

## Solution

Three coordinated changes:

1. **Callback signature carries a sub-percentage.** Changed `on_progress` from `Callable[[str], Awaitable[None]]` to `Callable[[str, int], Awaitable[None]]`, where the int is a 0–100 sub-percentage within this single video's analysis.

2. **Emit progress at every stage**, not just the upload start:

   ```python
   await _emit(f"Uploading {size_mb:.1f} MB to Gemini file API", 0)
   # ... upload ...
   await _emit("Upload complete, waiting for Gemini to process video", 25)
   # Inside _wait_for_file_active, emit on every poll tick:
   sub_pct = min(60, 30 + elapsed // 2)
   await on_progress(f"Gemini processing video (state={state})", sub_pct)
   # ...
   await _emit("Extracting structured data with AI", 70)
   await _emit("Parsing Gemini response", 95)
   ```

   Retries also emit progress so a throttled run doesn't look frozen.

3. **Orchestrator heartbeat with elapsed time.** The orchestrator loop now polls the progress queue with a 2-second timeout and yields a `ProgressEvent` on every tick — even if nothing new arrived — with the elapsed seconds appended to the message:

   ```python
   overall = base_pct + last_sub_pct // total_videos
   yield ProgressEvent(
       "video_analysis",
       min(overall, 99),
       f"{filename}: {last_msg} ({elapsed}s)",
   )
   ```

   Because the message string changes every 2 seconds (the `(Xs)` counter), React re-renders the bar even when the backend stage hasn't advanced. The bar also glides 30→60 during the wait as sub_pct increases.

4. **INFO-level logging** at each stage tagged by `video_id`, so tailing backend logs shows live stage transitions without enabling DEBUG.

## Why This Works

The UI's perception of "stuck" was really a failure of *liveness signaling*. Two independent fixes in combination:

- **Resolution**: a single long-running step was previously represented as one `(msg, 0%)` event. Now it's a sequence of `(msg, sub_pct)` events at stage boundaries, plus continuous mid-stage polls, plus per-retry updates — so the pct actually climbs through upload, file-activation, extraction, and parse.
- **Liveness**: even when the system is legitimately blocked on one I/O call (e.g., the Gemini file-upload HTTP request), the heartbeat produces a fresh message every 2 seconds containing an incrementing elapsed-time counter. The user gets a proof-of-life signal without the backend needing to know anything new.

## Prevention

- Any pipeline step that can legitimately take longer than ~5 seconds must emit either (a) an incrementing sub-percentage or (b) a heartbeat with a changing token (elapsed time, poll count, etc.). "Silent success" over a long wait is indistinguishable from "hung" to a user.
- When designing progress callbacks, pass a numeric percentage alongside the message. A message-only callback forces the caller to invent percentages from stage names, which doesn't scale.
- Backend logs for long operations should default to INFO, not DEBUG — the operator shouldn't have to change log level to check on a multi-minute job.
- See also: `ProgressPage.tsx` SSE consumer — it re-renders on any `(phase, pct, message)` change, so changing *any* of those three (e.g., the elapsed counter in `message`) is enough to keep the UI alive.
