---
module: ProjectListPage
date: 2026-04-17
problem_type: ui_bug
component: frontend_stimulus
symptoms:
  - "Clicking the trash icon on a project card does nothing"
  - "No network request is made to DELETE /api/projects/{id}"
  - "Backend DELETE endpoint works correctly via curl"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
tags: [window-confirm, react, delete-flow, agent-browser]
---

# Delete icon silently fails due to native window.confirm

## Problem
The trash icon on project cards in the project list page appeared to do nothing when clicked. The backend DELETE endpoint was confirmed working via `curl`, and the React click handler was wired correctly, but the deletion never fired.

## Environment
- Module: Walkthrough frontend
- Affected Component: `frontend/src/pages/ProjectListPage.tsx:230`
- Date: 2026-04-17
- Stack: React 19 + Vite 8

## Symptoms
- Click trash icon → nothing visible happens
- Backend logs show no incoming DELETE request
- Curl against `DELETE /api/projects/{id}` succeeds and returns 200
- No JavaScript console errors

## What Didn't Work

**Assumed card-click propagation bug:** Initially suspected `e.stopPropagation()` was failing and the parent card's `onClick` was navigating before delete could run. Wrong — `stopPropagation` works correctly between React synthetic handlers.

## Solution

The click handler used native `window.confirm()`:
```tsx
if (!confirm(`Delete project "${name}"? This cannot be undone.`)) return;
```

Native confirm dialogs are suppressed or auto-cancelled in several contexts (agent-browser headless mode returned `false` by default; some browser settings/extensions block them outright). Verified by overriding `window.confirm = () => true` — delete then worked immediately.

**Fix:** Replaced with in-page two-step confirmation (first click reveals a red Delete + Cancel pair, second click commits):

```tsx
const [pendingDelete, setPendingDelete] = useState<string | null>(null);

// On first click
onClick={(e) => { e.stopPropagation(); setPendingDelete(project.project_id); }}

// On confirm click (reveals after first click)
onClick={(e) => { e.stopPropagation(); handleDelete(project.project_id); }}
```

See the pattern already used in `frontend/src/components/ProjectControls.tsx` for the same in-page confirmation approach.

## Why This Works

`window.confirm()` is a modal primitive controlled by the browser, not by the app — if the browser or an automation layer suppresses it, the handler short-circuits with no error. In-page confirmation keeps state inside React, so:
1. No reliance on browser modal behavior.
2. The UI explicitly shows the pending-delete state — no invisible failure mode.
3. Works identically in real browsers, test harnesses, and headless automation.

## Prevention

- Avoid `window.confirm`/`window.alert`/`window.prompt` for any action the user expects to work reliably. Use in-page confirmation components instead.
- When a click handler appears to do nothing, verify with `window.confirm = () => true` before chasing propagation/event-ordering theories — the fastest way to isolate confirm-blocking from other click-path bugs.
- Always verify UI fixes in a real browser (or agent-browser + confirm override), not just via curl on the underlying endpoint.
