# PRD — Agentic QA + LLM Critics (Ralph execution)

**Status:** Draft, ready for Ralph
**Target executor:** Ralph (autonomous loop)
**Target branch:** `ralph/agentic-qa-v1`
**Companion file:** `docs/ralph-prd-agentic-qa.json` (actual prd.json Ralph reads — archive current `prd.json` and swap when ready)

---

## Executive summary

Add agentic quality assurance and LLM-powered critics to the `simulator-overview` pipeline, without rewriting the existing `PhaseOrchestrator`. This closes two visible quality bugs (decision-tree self-loops, output-schema field mismatches) and lays groundwork for iterative prompt/output improvement. Five concerns, ~21 user stories, executable one-at-a-time via Ralph.

---

## Background

### What prompted this

In the current session the user hit two bugs that should never have reached the UI:

1. `generate.py` wrote `"elements"` instead of `"ui_elements"`, `"total_branch_points"` instead of `"total_branches"`, and `"open_questions_count"` instead of `"open_questions"` — the walkthrough page rendered blank.
2. The walkthrough produced a decision-tree self-loop at `screen_d3af07fa2d51` (branch whose path pointed back to itself).

Both are obvious in hindsight. Neither was caught because the pipeline has **no QA phase**. Output generation is serialization-plus-severity-sort; whatever shape it emits goes straight to the frontend.

### What the POC showed

A separate internal POC (recipe-orchestrator + recipe-qa-lead + source-conflict-detector) uses a multi-agent pipeline with parallel QA, self-critique, and an authority hierarchy for source conflicts. Five of those patterns port cleanly without rewriting our orchestrator:

- Gate artifacts on disk per phase (resumable, inspectable)
- Parallel QA team after generation
- Authority hierarchy for sources (video > SOP > training) as evidence weighting, NOT adjudication
- Reusable "fidelity standard" prompt block
- Self-critique → surgical v2 on LLM output

### What's in the codebase today

- Pipeline phases: `ingestion → path_merge → narrative → contradictions → clarification → generation`
- LLM calls today are **only** video/screenshot/PDF extraction (Gemini). Everything else (`merge_paths`, `narrative`, `detect_contradictions`, `clarification`) is pure Python heuristics.
- `backend/src/walkthrough/ai/agent.py` defines an unwired `WalkthroughAgent` tool-use loop with an excellent `SYSTEM_PROMPT` containing `M1-M9` invariants and `N1-N7` negative invariants. Harvest these into the fidelity block; don't revive the agent.
- State is a monolithic `{project_id}.json` written by `LocalFirestoreClient.save_project()` at every phase. Resume logic (`_infer_resume_phase` in `orchestrator.py:367-413`) uses fragile state-matching heuristics.

---

## Architecture decisions (non-negotiable)

1. **Use raw `anthropic` SDK, not `claude-agent-sdk`.** The CLI-subprocess Agent SDK composes poorly with FastAPI async + SSE. `anthropic>=0.42` is already in `pyproject.toml`. All POC patterns are prompt/control patterns; they don't require the CLI runtime.
2. **Wrap, don't rewrite algorithmic tools.** LLM critics emit **additional** `Gap` objects; they cannot modify/delete deterministic output. Deterministic logic stays authoritative and testable.
3. **Reuse existing clarification path.** Improving question prompts, not question delivery. `/api/projects/{id}/questions/{qid}/answer` stays.
4. **Authority hierarchy = evidence weighting + UI presentation priority only.** N4 (`No source is inherently authoritative`) still holds. Critics surface disagreements; they never silently resolve them.
5. **Per-phase artifact files live beside the monolith, not replacing it.** `save_project()` keeps writing the whole JSON; artifacts are a read-optimized projection per phase.
6. **All new LLM features default-off via Settings flags.** `QA_ENABLE_LLM_CRITIC`, `ENABLE_SELF_CRITIQUE`, `QA_BLOCK_ON_CRITICAL` all start `False`. Pipeline must still ship without `ANTHROPIC_API_KEY` set.

---

## Scope

### In scope

Five concerns adopted incrementally, each independently deployable:

1. **Per-phase artifact files + resume-by-presence** (unblocks everything else)
2. **Parallel QA phase** (the highest-leverage user-visible piece)
3. **Fidelity + authority prompt module** (prerequisite for critics)
4. **LLM critic wrappers** over `detect_contradictions` and `narrative`
5. **Self-critique (v1 → surgical v2)** on new LLM callsites

### Explicit out of scope

- Replacing `PhaseOrchestrator` with an Agent-SDK loop
- Migrating from `anthropic` → `claude-agent-sdk` package
- Wrapping `merge_paths`, `clarification`, or `generate.py` with critics
- Reviving `agent.py` as the entry point
- Touching `storage/firestore.py` (GCP path) — local-dev only
- Frontend UI to render `qa_report` (type only, no UI)
- Silently resolving conflicts via authority hierarchy (N4 holds)

---

## Ralph execution protocol

Ralph reads `prd.json`, picks the first `passes: false` story in priority order, implements it, runs quality checks, commits, flips `passes: true`, appends to `progress.txt`. Each story must fit in one context window.

### Model selection

Stories tag `"model"` explicitly. Ralph uses it.

| Purpose | Model | Reason |
|---|---|---|
| Mechanical file I/O, pure-Python validators, test fixtures, config tweaks | `sonnet` | Fast, cheap, handles boilerplate cleanly |
| Prompt engineering (critics, fidelity block, self-critique design) | `opus` | Better at subtle prompt work and invariant reasoning |

### Runtime model (what the code calls)

Not the same as the implementation model. Set via `Settings`:

| Callsite | Runtime model | Reason |
|---|---|---|
| `narrative_fidelity_critic` (per-screen claim check) | `claude-haiku-4-5-20251001` | Cheap, repetitive |
| `detect_contradictions_critic` | `claude-sonnet-4-6` | Semantic cross-source reasoning |
| `narrative_critic` | `claude-sonnet-4-6` | Semantic claim-vs-source comparison |
| `surgical_review` (v1 → v2) | `claude-sonnet-4-6` | Edit-list output |

### Acceptance criteria template

Every story ends with at minimum:

- `Typecheck passes` (pyright in backend, tsc in frontend)
- `Tests pass` (pytest for backend stories; `pytest backend/tests/<new file>.py -v` specifically)

No frontend stories in this PRD change UI (only types), so no `dev-browser` verification needed.

---

## User stories (summary)

Full acceptance criteria live in the JSON. This is the human-readable overview.

### Step 1 — Gate artifacts + resume (3 stories)

- **US-001** — Create `storage/phase_artifacts.py` with read/write/exists/completed_phases helpers
- **US-002** — Wire artifact writes into orchestrator phase methods (path_merge, narrative, contradictions, clarification, generation)
- **US-003** — Rewrite `_infer_resume_phase` to use `phase_artifact_exists`

### Step 2 — Parallel QA phase (8 stories)

- **US-004** — `models/qa.py` (ValidatorFinding / ValidatorResult / QAReport)
- **US-005** — `ai/qa/decision_tree_structure.py` (catches self-loops, orphans, unreachable, dangling targets)
- **US-006** — `ai/qa/output_schema.py` (catches missing fields, legacy keys like `"elements"`, stats-field regressions)
- **US-007** — `ai/qa/video_coverage.py` (observed screens must have video refs; all screens must have ≥1 ref)
- **US-008** — `ai/qa/narrative_fidelity_critic.py` (LLM: each screen's narrative supported by its cited excerpts)
- **US-009** — `ai/qa/runner.py` (asyncio.gather fan-out, writes `phases/qa.json`)
- **US-010** — New `_run_qa` phase in orchestrator (after generation; non-blocking by default)
- **US-011** — `frontend/src/types/index.ts` adds `qa_report?` to `WalkthroughOutput` (typedef only)

### Step 3 — Prompt module (3 stories)

- **US-012** — `ai/prompts/fidelity.py` with FIDELITY_STANDARD, INVARIANTS (harvested from agent.py), AUTHORITY_HIERARCHY, EVIDENCE_CITATION_RULES
- **US-013** — `ai/prompts/compose.py` deterministic system-prompt composer
- **US-014** — Tombstone `agent.py` with SCAFFOLDING-ONLY docstring

### Step 4 — LLM critic wrappers (5 stories)

- **US-015** — `ai/llm/client.py` (AsyncAnthropic factory, `run_structured_json` helper with retry + caching)
- **US-016** — `ai/tools/detect_contradictions_critic.py` (LLM: additional gaps from cross-source comparison)
- **US-017** — Wire critic into `_run_contradictions` (additive, de-duplicated)
- **US-018** — `ai/tools/narrative_critic.py` (LLM: unsupported-claim gaps)
- **US-019** — Wire narrative critic into `_run_narrative`

### Step 5 — Self-critique (2 stories)

- **US-020** — `ai/llm/review_pass.py` with `surgical_review` helper (idempotent)
- **US-021** — Thread `surgical_review` into all three critics (flag-gated)

---

## Data contracts

### QAReport

```python
class ValidatorFinding(BaseModel):
    severity: Literal["critical", "medium", "low", "info"]
    code: str  # machine-readable: "self_loop", "legacy_elements_key", "narrative_unsupported_claim"
    message: str
    screen_id: str | None = None
    evidence: list[SourceRef] = []

class ValidatorResult(BaseModel):
    validator: str  # e.g., "decision_tree_structure"
    ok: bool
    findings: list[ValidatorFinding] = []

class QAReport(BaseModel):
    project_id: str
    results: list[ValidatorResult]
    has_critical: bool
    generated_at: datetime
```

### Phase artifact paths

`{LOCAL_DATA_DIR}/projects/{FIRESTORE_COLLECTION}/{project_id}/phases/{phase}.json`

- `path_merge.json`: `{"decision_trees": [...]}`
- `narrative.json`: `{"decision_trees": [...]}` (after narratives populate)
- `contradictions.json`: `{"gaps": [...]}`
- `clarification.json`: `{"questions": [...]}`
- `generation.json`: full `generate_walkthrough(project)` dict
- `qa.json`: `QAReport.model_dump(mode="json")`

---

## Settings to add (backend/src/walkthrough/config.py)

```python
QA_BLOCK_ON_CRITICAL: bool = False
QA_ENABLE_LLM_CRITIC: bool = False
ENABLE_SELF_CRITIQUE: bool = False
ANTHROPIC_API_KEY: str = ""
NARRATIVE_FIDELITY_MODEL: str = "claude-haiku-4-5-20251001"
CONTRADICTION_CRITIC_MODEL: str = "claude-sonnet-4-6"
NARRATIVE_CRITIC_MODEL: str = "claude-sonnet-4-6"
SELF_CRITIQUE_MODEL: str = "claude-sonnet-4-6"
```

Stories add these incrementally (only the flag needed by that story).

---

## Architectural risks (Ralph should respect)

1. **Prompt cache stability** — `compose_system_prompt` must be deterministic. Dynamic payload goes in the user message, never the system block.
2. **`_active_pipelines` is in-process** (`projects.py:28`). Don't put LLM message history there; use artifact files for durable state.
3. **Whole-JSON save per phase** (`local_firestore.py:26-30`) — quadratic write cost as QA reports grow. Tracked follow-up, not blocker.
4. **`asyncio.create_task` without tracking** (`projects.py:179`) — OK today. Add task registry only if QA phase starts adding >30s LLM calls.
5. **Quota pressure** — Steps 4 + 5 stack LLM calls per pipeline run. Flags default off; flip per environment.

---

## End-to-end verification

After Steps 1 + 2 ship (MVP, ~3 engineering days):

1. Stop backend. Delete `phases/` directory for known-broken project `685a2cda0fe142f2b92369da1d006037`.
2. Restart; re-trigger pipeline via `/analyze`.
3. Per-phase files appear in `data/projects/walkthrough_projects/685a.../phases/`.
4. Kill mid-`_run_narrative` (Ctrl-C). Restart. Pipeline resumes at `narrative`, not `ingestion`.
5. On completion, inspect `phases/qa.json`. Contains `self_loop` finding at `screen_d3af07fa2d51` + `legacy_elements_key` / `stats_field_mismatch` if output still has those.
6. `project.walkthrough_output["qa_report"]` is present via `/api/projects/{id}`.

After Step 4 ships:

7. `QA_ENABLE_LLM_CRITIC=true`. Run pipeline. `project.gaps` contains critic-emitted gaps alongside deterministic gaps, de-duplicated.

After Step 5 ships:

8. `ENABLE_SELF_CRITIQUE=true`. Confirm via logs that v1→v2 review passes run and v2 output is used.

---

## Success metrics

- **Zero** of the two bug classes from the current session regress to UI (self-loop, output-schema mismatch) — automated catch in `qa.json`.
- **Resume reliability**: killing the pipeline mid-phase N, restarting, produces identical output vs. uninterrupted run. (Integration test.)
- **Critic precision**: in Step 4 acceptance testing, critic-emitted gaps should be ≥80% accepted by user review on a fixture dataset (measured qualitatively on first run).
- **Pipeline still ships without ANTHROPIC_API_KEY**: all new LLM features default-off; deterministic pipeline path unchanged.
