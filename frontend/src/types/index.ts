// Video models
export interface UIElement {
  element_type: string;
  label: string;
  state: string | null;
}

export interface Keyframe {
  video_id: string;
  timestamp_sec: number;
  ui_elements: UIElement[];
  screenshot_description: string;
  transition_from: string | null;
}

export interface TransitionEvent {
  from_timestamp: number;
  to_timestamp: number;
  action: string;
  trigger_element: string | null;
}

export interface AudioSegment {
  start_sec: number;
  end_sec: number;
  text: string;
  intent: string | null;
}

export interface VideoAnalysis {
  video_id: string;
  filename: string;
  keyframes: Keyframe[];
  transitions: TransitionEvent[];
  audio_segments: AudioSegment[];
  temporal_flow: string[];
}

// PDF models
export interface PDFSection {
  heading: string;
  text: string;
  page_number: number;
  confidence: number;
}

export interface PDFTable {
  headers: string[];
  rows: string[][];
  page_number: number;
}

export interface PDFImage {
  image_id: string;
  page_number: number;
  description: string | null;
  ui_elements: UIElement[] | null;
}

export interface PDFExtraction {
  pdf_id: string;
  filename: string;
  sections: PDFSection[];
  tables: PDFTable[];
  images: PDFImage[];
}

// Workflow models
export interface SourceRef {
  source_type: "video" | "audio" | "pdf";
  reference: string;
  excerpt: string | null;
}

export interface Narrative {
  what: string;
  why: string;
  when_condition: string | null;
}

export interface WorkflowScreen {
  screen_id: string;
  title: string;
  ui_elements: UIElement[];
  narrative: Narrative | null;
  evidence_tier: "observed" | "mentioned";
  source_refs: SourceRef[];
}

export interface BranchPoint {
  screen_id: string;
  condition: string;
  paths: Record<string, string>;
}

export interface DecisionTree {
  root_screen_id: string;
  screens: Record<string, WorkflowScreen>;
  branches: BranchPoint[];
}

// Project models
export interface Gap {
  gap_id: string;
  severity: "critical" | "medium" | "low";
  description: string;
  evidence: SourceRef[];
  resolution: string | null;
  resolved: boolean;
}

export interface ClarificationQuestion {
  question_id: string;
  text: string;
  severity: "critical" | "medium" | "low";
  evidence: SourceRef[];
  answer: string | null;
}

export type ProjectStatus =
  | "uploading"
  | "analyzing"
  | "clarifying"
  | "generating"
  | "complete";

export interface Project {
  project_id: string;
  name: string;
  status: ProjectStatus;
  videos: VideoAnalysis[];
  pdfs: PDFExtraction[];
  decision_trees: DecisionTree[];
  gaps: Gap[];
  questions: ClarificationQuestion[];
  walkthrough_output: WalkthroughOutput | null;
  created_at: string;
  updated_at: string;
}

// Walkthrough output (generated JSON)
export interface WalkthroughOutput {
  metadata: Record<string, unknown>;
  decision_trees: DecisionTree[];
  screens: Record<string, WorkflowScreen & { warnings?: string[] }>;
  warnings: WalkthroughWarning[];
  open_questions: OpenQuestion[];
  stats: WalkthroughStats;
  qa_report?: QAReport;
}

// QA report models (mirror backend walkthrough.models.qa)
export interface QAValidatorFinding {
  severity: "critical" | "medium" | "low" | "info";
  code: string;
  message: string;
  screen_id?: string | null;
  evidence: SourceRef[];
}

export interface QAValidatorResult {
  validator: string;
  ok: boolean;
  findings: QAValidatorFinding[];
}

export interface QAReport {
  project_id: string;
  results: QAValidatorResult[];
  has_critical: boolean;
  generated_at: string;
}

export interface WalkthroughWarning {
  screen_id: string;
  gap_id: string;
  description: string;
  evidence: SourceRef[];
}

export interface OpenQuestion {
  gap_id: string;
  severity: "medium" | "low";
  description: string;
  evidence: SourceRef[];
}

export interface WalkthroughStats {
  total_screens: number;
  total_branches: number;
  total_paths: number;
  open_questions: number;
}

// API response types
export interface ProjectSummary {
  project_id: string;
  name: string;
  status: string;
  updated_at: string;
}

export interface CreateProjectResponse {
  project_id: string;
  name: string;
  status: string;
}

export interface FileInfo {
  filename: string;
  content_type: string;
  gcs_uri: string;
}

export interface UploadResponse {
  filename: string;
  content_type: string;
  gcs_uri: string;
  files: FileInfo[];
  ready_for_analysis: boolean;
}

export interface AnalyzeResponse {
  project_id: string;
  message: string;
}

export interface ProgressEvent {
  phase: string;
  percentage: number;
  message: string;
}

export interface Choice {
  label: string;
  description: string | null;
}

export interface QuestionResponse {
  question_id: string;
  text: string;
  severity: string;
  evidence: SourceRef[];
  choices: Choice[];
  answer: string | null;
}

export interface AnswerResponse {
  question_id: string;
  answer: string;
  follow_up_questions: QuestionResponse[];
}

export interface UnanswerableResponse {
  question_id: string;
  marked_unanswerable: boolean;
}

export interface QuestionsStatus {
  total: number;
  answered: number;
  unanswerable: number;
  remaining_critical: number;
  can_generate: boolean;
}

export interface MetaQuestion {
  meta_question_id: string;
  text: string;
  rationale: string;
  affected_gap_ids: string[];
  choices: Choice[];
  answer: string | null;
}

export interface MetaAnswerResult {
  meta_question: MetaQuestion;
  resolved_question_ids: string[];
}

export interface BestGuessResponse {
  question_id: string;
  answer: string;
  rationale: string;
}

export interface SessionState {
  project_id: string;
  phase: string;
  progress: number;
  pending_questions: number;
  can_resume: boolean;
}

export interface ResumeResponse {
  project_id: string;
  message: string;
  resumed_from_phase: string;
}

export interface ReopenResponse {
  project_id: string;
  message: string;
  question_count: number;
}

export interface RegenerateResponse {
  project_id: string;
  message: string;
}
