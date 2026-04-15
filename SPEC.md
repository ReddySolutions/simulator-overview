# Walkthrough — SOP-to-Simulation Pipeline

## 1. What This Is

Transform call-center training materials — screen-recording videos (MP4s with audio narration) and SOP PDFs — into a dynamic, interactive web app called **Walkthrough**. The app lets users navigate realistic, branching simulations of call-center software exactly as observed in the training videos.

This is not a static export. It is a single-page application with live navigation through wireframe-style screens, branching decision trees assembled from multiple recordings, embedded narrative guidance, and hierarchical drill-down diagrams.

**Minimum input**: At least one MP4 video and one PDF. The system's core value is cross-referencing independent sources — a single source type is insufficient. The system will reject uploads that don't include both.

---

## 2. Goals

| # | Goal | Why It Matters |
|---|------|---------------|
| G1 | **Surface what the training materials hide** — contradictions, missing branches, shallow assumptions, gaps between what the video shows, what the narrator says, and what the PDF documents | Raw training materials look complete. They aren't. The system's job is to *prove* they aren't by cross-referencing three independent sources. |
| G2 | **Produce a faithful simulation** — every screen, branch, and label in the output traces back to something observed or mentioned in the source material | The output must reflect reality, not the model's imagination. If it wasn't in the video, audio, or PDF, it doesn't exist in the simulation. Content mentioned but not directly observed is included but visually distinguished (see M9). |
| G3 | **Resolve ambiguity before generating** — never produce output that contains unresolved critical contradictions | A simulation with silently-resolved contradictions is worse than no simulation. The user must decide. |
| G4 | **Make branching workflows explorable** — merge multiple single-path recordings into a complete decision tree that users can freely navigate | Training videos are linear. Real workflows aren't. The system must reconstruct the full branching structure. |
| G5 | **Provide certainty** — every step in the output should answer "what happens?", "why?", and "under what conditions?" with cited evidence | Vague guidance is the disease. Cited, cross-referenced, contradiction-checked guidance is the cure. |

---

## 3. How to Prove Success

These are the acceptance tests. If any fail, the system is not done.

| # | Criterion | How to Verify |
|---|-----------|---------------|
| S1 | Every screen in the generated simulation maps to a specific video keyframe with a timestamp | Audit any screen → trace it to `video_filename:timestamp`. No orphan screens. |
| S2 | Every branch point traces to an observed divergence across two or more videos | Pick any fork in the decision tree → confirm two videos show different behavior from the same starting screen. |
| S3 | All critical contradictions were surfaced to the user before generation | Review the clarification log. Every critical gap was either resolved by the user or explicitly marked as unanswerable — with a visible warning placed on the affected output. No critical gap was silently skipped. |
| S4 | A subject-matter expert can walk the simulation and confirm it matches the real software | Sit a trainer down with the Walkthrough and the original videos. Every path they explore should match. |
| S5 | The system asked questions the human didn't think to ask | Compare the clarification questions to what the user knew going in. The system should have uncovered at least one blind spot. |
| S6 | Medium/low gaps are explicitly visible in the output, not hidden | The generated app contains an "Open Questions" section listing every unresolved non-critical gap with source references. |
| S7 | Three-source cross-referencing actually happened | Every contradiction flag includes evidence from at least two of: video keyframe, audio transcript excerpt, PDF section reference. |

---

## 4. The System Must Always

These are invariants. They hold in every run, for every input, with no exceptions.

| # | Invariant |
|---|-----------|
| M1 | **Cross-reference all three sources independently.** Video-observed behavior, audio narration, and PDF documentation are treated as separate witnesses. Agreement is verified, not assumed. |
| M2 | **Flag every contradiction with evidence from both sides.** The contradiction is the finding — include the video timestamp, the audio excerpt, and/or the PDF section that disagree. |
| M3 | **Classify every gap by severity** — Critical (blocks generation), Medium (surfaced in output), Low (cosmetic). |
| M4 | **Ask the user to resolve critical ambiguity before generating.** Never guess. Never pick a side silently. |
| M5 | **Reconstruct screens from video keyframes, not from general knowledge.** The wireframe for a Salesforce screen comes from what Gemini saw in the video, not from what Claude knows about Salesforce. Wireframe fidelity means: correct UI elements (buttons, dropdowns, text fields, tabs), correct labels, and correct control types. Spatial layout is approximate — elements appear in roughly the right arrangement but pixel-level positioning is not required. |
| M6 | **Preserve full workflow structure and keyframe UI descriptions without lossy compression.** Narrative text can be summarized between phases. Decision trees, transition sequences, and UI state descriptions cannot. |
| M7 | **Cite sources.** Every narrative explanation, screen label, and branch condition traces to a video timestamp, audio transcript segment, or PDF section. |
| M8 | **Persist full agent state.** The user can close their browser mid-clarification and resume exactly where they left off. |
| M9 | **Distinguish evidence tiers visually.** Every element in the simulation belongs to one of three tiers: (1) **Observed** — directly shown in video, (2) **Mentioned** — referenced in audio narration or PDF but never shown in video, (3) **Inferred** — not in any source material (prohibited by N1). Mentioned-tier screens and branches are included in the simulation but carry a visible "mentioned, not observed" indicator so users know the difference. |

---

## 5. The System Must Never

Violations of these rules are bugs, regardless of how good the output looks.

| # | Prohibition | Why |
|---|-------------|-----|
| N1 | **Never invent screens, steps, or branches not observed or mentioned in source material.** | A plausible-looking screen that doesn't exist in the real software is actively harmful. Paths *mentioned* in audio or PDF but never shown in video are allowed — but must be visually marked as "mentioned, not observed" (M9). Paths the AI infers on its own are never included. |
| N2 | **Never silently resolve a contradiction.** | If video says "Save & Continue" and PDF says "Submit", the user decides which is correct. The system does not. |
| N3 | **Never generate the final output with silently unresolved critical gaps.** | If the user cannot answer a critical question, the system generates but places a prominent, unmissable warning on every affected screen and branch. The warning identifies the unresolved gap, cites the conflicting evidence, and states that this path is unverified. The simulation never looks complete when it isn't. |
| N4 | **Never treat one source as inherently authoritative over another.** | Video, audio, and PDF can each be wrong. When they disagree, the disagreement is escalated, not adjudicated. |
| N5 | **Never compress or summarize workflow/decision-tree data between phases.** | Lossy compression of structural data produces hallucinated branches and missing paths. |
| N6 | **Never present AI-inferred information as observed fact.** | If the system infers a likely path that wasn't shown in any video, it must be clearly marked as inferred, not presented alongside observed paths. |
| N7 | **Never skip the clarification phase.** | Even if zero contradictions are detected, the system confirms this with the user rather than silently proceeding. |

---

## 6. AI Architecture: Claude + Vertex AI

The system uses a **dual-model architecture**. Each model does what it's best at; neither does the other's job.

**Claude (Reasoning Layer)** — via Claude Agent SDK
- Multi-step agent reasoning and tool orchestration
- Multi-video path merging and branch-point identification
- Narrative synthesis from audio transcripts and PDF text
- Workflow/decision-tree construction from structured perception data
- Three-way contradiction detection (video vs. audio vs. PDF)
- Clarification question generation with timestamp/section references
- HTML/JS code generation for the final simulation

**Vertex AI (Perception Layer)** — via Google Cloud Vertex AI APIs
- **Gemini (multimodal — video + audio)**: Processes each MP4 in a single pass to extract keyframes, UI state per keyframe, transition events, temporal flow, and timestamped audio transcript with intent annotations. Also classifies PDF-extracted images.
- **Google Document AI**: PDF extraction — structured text, tables, form fields, layout analysis from SOP documents.
- **Vertex AI Vision**: Extraction confidence scoring — assesses quality of each extracted element to flag what needs user review.

**Why two models?**
Claude cannot see video or images in the Agent SDK tool-use loop. Gemini cannot reason across multiple sources, merge branching paths, or generate code. Together: Gemini perceives → Claude reasons over what Gemini perceived.

---

## 7. Agent Architecture

One stateful multi-step agent, powered by the Claude Agent SDK. Not multi-agent.

**Why one agent?**
- The task is sequential and context-heavy — full conversation history is needed across all phases.
- Easier to maintain, debug, and iterate.
- Sub-agents can be added later if scale demands it.

**Agent Tools**

| Tool | Purpose | Backed By |
|------|---------|-----------|
| `analyze_video` | Send MP4 to Gemini for unified video + audio analysis. Returns keyframes with UI state descriptions, transition events, temporal flow, timestamped audio transcript. | Vertex AI Gemini |
| `extract_pdf` | Send PDF for structured extraction. Returns text, tables, images, layout with confidence scores. | Google Document AI |
| `analyze_screenshot` | Send PDF-extracted images for UI element identification and classification. Not used for video keyframes. | Vertex AI Gemini |
| `merge_paths` | Align multiple single-path video analyses, identify shared screens and branch points, output unified decision tree. | Claude reasoning |
| `detect_contradictions` | Three-way cross-reference. Flag inconsistencies with severity classification and source references. | Claude reasoning |
| `ask_user_question` | Batched, adaptive clarification via the web UI. Includes keyframe screenshots, audio excerpts, PDF sections as evidence. | Claude Agent SDK |
| `generate_walkthrough` | Produce the final code bundle + JSON data. Wireframe screens reconstructed from video keyframe UI descriptions. | Claude reasoning |

**Context Window Management**
When context approaches token limits:
- **Compress**: Audio transcripts and narrative content → structured condensed form after each phase transition
- **Preserve in full**: Workflow/decision-tree data, video keyframe UI descriptions, transition event sequences (M6)

---

## 8. Agent Workflow

### Phase 1 — Ingestion & Video Analysis
User uploads MP4s (primary) and PDFs (required — at least one of each). Each MP4 is sent to Gemini via `analyze_video`. Returns keyframes with UI states, transition events, temporal flow, and timestamped audio transcript — all from a single Gemini pass per video.

### Phase 2 — PDF Extraction
Each PDF is sent to Document AI via `extract_pdf`. Returns structured text, tables, extracted images with confidence scores. PDF-extracted images are sent to Gemini via `analyze_screenshot` for UI element identification.

### Phase 3 — Multi-Video Path Merge
Claude aligns temporal flows from multiple videos:
- Identifies shared screens (same UI state appearing in multiple paths)
- Detects branch points (last shared screen before paths diverge)
- Records what action in each video caused the divergence
- Outputs a unified branching structure — shared prefixes collapsed, branches fanning from decision points

Result: a complete tree-of-trees representing all observed paths.

### Phase 4 — Narrative Synthesis
Claude merges audio transcripts (primary) with PDF text (supplementary) into structured narrative per workflow step:
- **What**: The observed action (from video)
- **Why**: The rationale (from audio narration + PDF policy references)
- **When**: Conditions under which this step applies (from branch logic)

After completion, narrative is compressed into structured summary. Workflow structures are not compressed (M6).

### Phase 5 — Three-Way Contradiction & Gap Detection
Cross-reference all three sources (M1). Example contradictions:
- **Video vs. PDF**: Button labeled "Save & Continue" in video but "Submit" in PDF. Video shows 7 steps, PDF documents 5.
- **Audio vs. Video**: Narrator says "click the dropdown" but video shows a radio button group.
- **Audio vs. PDF**: Narrator explains a policy exception not in documentation.
- **Cross-video**: Two videos show different behavior at the same decision point without explanation.

Every gap is classified by severity (M3):
- **Critical**: Blocks generation — ambiguous routing, conflicting procedures, missing decision outcomes
- **Medium**: Won't block — unclear labels, minor ambiguity, wording differences that don't change meaning
- **Low**: Cosmetic — formatting, colors, non-functional details

### Phase 6 — Adaptive Clarification
- Agent batches questions by severity, critical first (M4).
- Every question includes evidence from the relevant sources (M2, M7): video keyframe screenshots with timestamps, audio transcript excerpts, PDF section references.
- Low-confidence extractions are surfaced with the original media + Gemini's analysis for user review.
- Contradictions are presented with both versions and their sources; user picks the authoritative answer (N2).
- Each answer feeds back into the agent and can trigger follow-up questions.
- Loop continues until all critical gaps are either resolved or explicitly acknowledged as unanswerable by the user. Resolved gaps are applied silently. Unanswerable critical gaps trigger prominent warnings on affected screens/branches in the output (N3). Medium/low gaps become "Open Questions" in the output (S6).
- Agent state is fully persisted — session can resume after browser closure (M8).

### Phase 7 — Final Synthesis & Generation
Claude produces a structured JSON project file + all assets for the web app. Wireframe screen components are generated from video keyframe UI descriptions (M5) — button labels, field names, navigation layouts, and transitions match what was observed.

### Phase 8 — Web App Rendering
The frontend renders the Walkthrough and saves the project.

---

## 9. Prompt Framework

Specialized, chained prompts — each scoped to one job:

| Prompt | Scope |
|--------|-------|
| **A — Video Analyzer** | Structure Gemini's raw output into normalized keyframe sequences with aligned audio |
| **B — Path Merger** | Align multiple single-path analyses, identify shared screens and branch points |
| **C — Narrative Synthesizer** | Merge audio + PDF into per-step what/why/when narrative |
| **D — Workflow Mapper** | Exhaustive enumeration of all observed paths + edge cases mentioned but not observed in video |
| **E — Contradiction Hunter** | Three-way cross-reference with severity classification and source citations |
| **F — Clarification Generator** | Turn critical gaps + low-confidence extractions into batched questions with evidence |
| **G — HTML Generator** | Produce React/Vite code + React Flow graphs + JSON with wireframe screens from keyframes |

Phase transitions include context compression for narrative data. Workflow structures, keyframe descriptions, and transition sequences are never compressed (M6).

---

## 10. Generated Web App

### Features
- **Hero + Stats Dashboard**
- **High-Level Routing Diagram** — React Flow graph with zoom/pan/minimap, clickable custom nodes, tooltips
- **Drill-Down Sub-Diagrams** — clicking a node transitions into its detailed branching sub-graph with breadcrumb navigation
- **Sub-Type Explorer** — clickable cards leading to full branching simulations
- **Simulated App Screens** — wireframe-style screens reconstructed from video keyframes (M5): labeled boxes, buttons, fields matching observations. Click to advance with branching logic.
- **Graph Node Previews** — custom React Flow nodes displaying mini wireframe previews, step counts, completion status
- **Side-by-side Narrative Panel** — toggleable "why" panel showing audio narration + PDF context per step (M7)
- **Shared Phases Table** — with variant highlighting
- **Open Questions Section** — unresolved medium/low gaps with severity and source references (S6)
- **Progress Tracker**
- **Save / Load / Regenerate** — projects stored in the web app; regeneration overwrites. Users can reopen the clarification phase of a completed project, change any previous answer, and regenerate from that point forward without re-uploading or re-analyzing source files.

All diagrams and screens are fully interactive — users can freely explore any path.

### User Experience Flow
1. **Upload Screen**: Drag-and-drop for MP4s (primary) and PDFs (required). Upload is blocked until at least one of each is provided.
2. **Analysis Progress**: Real-time phase status with estimated time
3. **Clarification Chat**: Batched questions with video keyframe screenshots, audio excerpts, PDF references. Answer one-by-one or all at once.
4. **Session Resumption**: Leave mid-clarification, return later, pick up exactly where you left off (M8)
5. **Generation Complete**: Auto-opens the Walkthrough
6. **Project Management**: Save, load previous, reopen clarification to change answers, regenerate from clarification forward

---

## 11. Technical Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React + Tailwind + Vite + React Flow (dagre/elkjs layout) |
| Backend | Python/FastAPI on Google Cloud Run |
| Reasoning AI | Claude Agent SDK |
| Perception AI | Vertex AI: Gemini (video+audio+images), Document AI (PDFs), Vision (confidence scoring) |
| State Persistence | Google Cloud Firestore or Cloud Storage — full agent state for session resumption |
| File Storage | Google Cloud Storage — uploaded MP4s, PDFs, extracted keyframes, generated bundles |
| Video Limits | MP4s up to 40MB; Gemini processes video + audio in a single pass per file |
| Output Format | JSON + assets folder per project, instantly renderable by the same web app |

---

## 12. Data Flow

```
MP4 videos (primary) + PDFs (supplementary)
  │
  ├──→ Gemini (video + audio) ──→ Keyframes + UI states + transitions
  │                                + timestamped audio transcript
  │
  ├──→ Google Document AI ──→ Structured text, tables, images
  │         │                  + confidence scores
  │         ▼
  │    Gemini (images) ──→ Screenshot analysis for PDF-extracted images
  │
  ▼
Claude Agent (reasoning over structured perception data)
  ├──→ Multi-video path merge (align shared screens, detect branch points)
  ├──→ Narrative synthesis (audio transcript + PDF text → per-step what/why/when)
  ├──→ Workflow/decision-tree mapping (tree-of-trees from merged paths)
  ├──→ Three-way contradiction detection (video vs. audio vs. PDF)
  ├──→ Clarification questions → User answers → Loop until no critical gaps
  └──→ Final code generation (wireframes reconstructed from video keyframes)
  │
  ▼
React SPA (rendered Walkthrough)
```

---

## 13. What Is Not in V1

- Version history for projects (overwrite model only)
- Offline capability
- Multi-agent architecture
- Sub-agent specialists

These are explicitly deferred, not forgotten. They can be added when scale or user feedback demands them.
