import type {
  AnalyzeResponse,
  AnswerResponse,
  BestGuessResponse,
  CreateProjectResponse,
  MetaQuestion,
  Project,
  ProjectSummary,
  QuestionsStatus,
  QuestionResponse,
  RegenerateResponse,
  ReopenResponse,
  ResumeResponse,
  SessionState,
  UnanswerableResponse,
  UploadResponse,
} from "../types";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// --- Projects ---

export function listProjects(): Promise<ProjectSummary[]> {
  return request("/projects");
}

export function getProject(id: string): Promise<Project> {
  return request(`/projects/${id}`);
}

export function createProject(name: string): Promise<CreateProjectResponse> {
  return request("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function deleteProject(id: string): Promise<{ detail: string }> {
  return request(`/projects/${id}`, { method: "DELETE" });
}

// --- Upload ---

export async function uploadFile(
  projectId: string,
  file: File,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  return request(`/projects/${projectId}/upload`, {
    method: "POST",
    body: form,
  });
}

// --- Analysis ---

export function analyzeProject(id: string): Promise<AnalyzeResponse> {
  return request(`/projects/${id}/analyze`, { method: "POST" });
}

export function streamProgress(
  id: string,
  onEvent: (event: { phase: string; percentage: number; message: string }) => void,
  onError?: (err: Event) => void,
): EventSource {
  const es = new EventSource(`${BASE}/projects/${id}/progress`);
  es.addEventListener("progress", (e) => {
    onEvent(JSON.parse(e.data));
  });
  es.addEventListener("status", (e) => {
    onEvent(JSON.parse(e.data));
  });
  if (onError) {
    es.onerror = onError;
  }
  return es;
}

// --- Clarification ---

export function listQuestions(projectId: string): Promise<QuestionResponse[]> {
  return request(`/projects/${projectId}/questions`);
}

export function answerQuestion(
  projectId: string,
  questionId: string,
  answer: string,
): Promise<AnswerResponse> {
  return request(`/projects/${projectId}/questions/${questionId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
}

export function bestGuessQuestion(
  projectId: string,
  questionId: string,
): Promise<BestGuessResponse> {
  return request(
    `/projects/${projectId}/questions/${questionId}/best-guess`,
    { method: "POST" },
  );
}

export function markUnanswerable(
  projectId: string,
  questionId: string,
): Promise<UnanswerableResponse> {
  return request(`/projects/${projectId}/questions/${questionId}/unanswerable`, {
    method: "POST",
  });
}

export function questionsStatus(projectId: string): Promise<QuestionsStatus> {
  return request(`/projects/${projectId}/questions/status`);
}

export function listMetaQuestions(
  projectId: string,
): Promise<MetaQuestion[]> {
  return request(`/projects/${projectId}/meta-questions`);
}

export function answerMetaQuestion(
  projectId: string,
  metaQuestionId: string,
  answer: string,
): Promise<MetaQuestion> {
  return request(
    `/projects/${projectId}/meta-questions/${metaQuestionId}/answer`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    },
  );
}

export function triggerGeneration(
  projectId: string,
): Promise<{ project_id: string; message: string }> {
  return request(`/projects/${projectId}/generate`, { method: "POST" });
}

// --- Session ---

export function getSession(projectId: string): Promise<SessionState> {
  return request(`/projects/${projectId}/session`);
}

export function resumePipeline(projectId: string): Promise<ResumeResponse> {
  return request(`/projects/${projectId}/resume`, { method: "POST" });
}

export function reopenClarification(
  projectId: string,
): Promise<ReopenResponse> {
  return request(`/projects/${projectId}/reopen-clarification`, {
    method: "POST",
  });
}

export function regenerateWalkthrough(
  projectId: string,
): Promise<RegenerateResponse> {
  return request(`/projects/${projectId}/regenerate`, { method: "POST" });
}
