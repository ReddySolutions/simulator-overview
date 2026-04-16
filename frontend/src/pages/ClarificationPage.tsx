import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import {
  answerQuestion,
  listQuestions,
  markUnanswerable,
  questionsStatus,
  triggerGeneration,
} from "../api/client";
import type { QuestionResponse, QuestionsStatus, SourceRef } from "../types";

type SeverityGroup = "critical" | "medium" | "low";

const SEVERITY_ORDER: SeverityGroup[] = ["critical", "medium", "low"];

const SEVERITY_STYLES: Record<
  SeverityGroup,
  { badge: string; border: string; label: string }
> = {
  critical: {
    badge: "bg-red-100 text-red-700",
    border: "border-red-200",
    label: "Critical",
  },
  medium: {
    badge: "bg-amber-100 text-amber-700",
    border: "border-amber-200",
    label: "Medium",
  },
  low: {
    badge: "bg-gray-100 text-gray-600",
    border: "border-gray-200",
    label: "Low",
  },
};

function formatSourceRef(ref: SourceRef): { label: string; excerpt: string | null } {
  if (ref.source_type === "video") {
    // Extract filename and timestamp from reference like "video1.mp4:01:23"
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) {
      return {
        label: `Video: ${match[1]} @ ${match[2]}:${match[3]}`,
        excerpt: ref.excerpt,
      };
    }
    return { label: `Video: ${ref.reference}`, excerpt: ref.excerpt };
  }
  if (ref.source_type === "audio") {
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) {
      return {
        label: `Audio: ${match[1]} @ ${match[2]}:${match[3]}`,
        excerpt: ref.excerpt,
      };
    }
    return { label: `Audio: ${ref.reference}`, excerpt: ref.excerpt };
  }
  // PDF reference like "SOP.pdf:Section 3.2"
  const pdfMatch = ref.reference.match(/^(.+?):(Section .+|.+)$/);
  if (pdfMatch) {
    return {
      label: `PDF: ${pdfMatch[1]} \u2014 ${pdfMatch[2]}`,
      excerpt: ref.excerpt,
    };
  }
  return { label: `PDF: ${ref.reference}`, excerpt: ref.excerpt };
}

export default function ClarificationPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const [questions, setQuestions] = useState<QuestionResponse[]>([]);
  const [status, setStatus] = useState<QuestionsStatus | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const fetchData = useCallback(async () => {
    if (!id) return;
    try {
      const [qs, st] = await Promise.all([
        listQuestions(id),
        questionsStatus(id),
      ]);
      setQuestions(qs);
      setStatus(st);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load questions");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAnswer = useCallback(
    async (questionId: string) => {
      if (!id) return;
      const answer = drafts[questionId]?.trim();
      if (!answer) return;

      setSubmitting((prev) => ({ ...prev, [questionId]: true }));
      try {
        const res = await answerQuestion(id, questionId, answer);
        // Update local question state
        setQuestions((prev) =>
          prev.map((q) =>
            q.question_id === questionId ? { ...q, answer: res.answer } : q,
          ),
        );
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[questionId];
          return next;
        });
        // Refresh status
        const st = await questionsStatus(id);
        setStatus(st);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to submit answer",
        );
      } finally {
        setSubmitting((prev) => ({ ...prev, [questionId]: false }));
      }
    },
    [id, drafts],
  );

  const handleUnanswerable = useCallback(
    async (questionId: string) => {
      if (!id) return;
      setSubmitting((prev) => ({ ...prev, [questionId]: true }));
      try {
        await markUnanswerable(id, questionId);
        // Update local question state
        setQuestions((prev) =>
          prev.map((q) =>
            q.question_id === questionId
              ? { ...q, answer: "Marked unanswerable by user" }
              : q,
          ),
        );
        // Refresh status
        const st = await questionsStatus(id);
        setStatus(st);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to mark unanswerable",
        );
      } finally {
        setSubmitting((prev) => ({ ...prev, [questionId]: false }));
      }
    },
    [id],
  );

  const handleGenerate = useCallback(async () => {
    if (!id) return;
    setGenerating(true);
    try {
      await triggerGeneration(id);
      navigate(`/progress/${id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start generation",
      );
      setGenerating(false);
    }
  }, [id, navigate]);

  // Group questions by severity
  const grouped = SEVERITY_ORDER.map((sev) => ({
    severity: sev,
    questions: questions.filter((q) => q.severity === sev),
  })).filter((g) => g.questions.length > 0);

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto">
        <h2 className="text-2xl font-semibold mb-6">Clarification Questions</h2>
        <div className="space-y-4">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="rounded-lg border border-gray-200 p-6 animate-pulse"
            >
              <div className="h-4 bg-gray-200 rounded w-3/4 mb-3" />
              <div className="h-3 bg-gray-100 rounded w-1/2" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h2 className="text-2xl font-semibold mb-6">Clarification Questions</h2>

      {/* Error banner */}
      {error && (
        <div className="mb-6 rounded-md bg-red-50 px-4 py-3 text-sm text-red-700 flex items-center gap-2">
          <svg
            className="h-4 w-4 shrink-0"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
          <span className="flex-1">{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-red-700 underline hover:text-red-800 text-xs"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Status bar */}
      {status && (
        <div className="mb-6 rounded-lg bg-gray-50 border border-gray-200 px-4 py-3 flex items-center justify-between">
          <p className="text-sm text-gray-700">
            {status.answered + status.unanswerable} of {status.total} questions
            answered.{" "}
            {status.remaining_critical > 0 && (
              <span className="text-red-600 font-medium">
                {status.remaining_critical} critical remaining.
              </span>
            )}
            {status.remaining_critical === 0 && status.total > 0 && (
              <span className="text-green-600 font-medium">
                All critical questions resolved.
              </span>
            )}
          </p>

          {status.can_generate && (
            <button
              type="button"
              disabled={generating}
              onClick={handleGenerate}
              className="rounded-md bg-green-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {generating ? "Starting..." : "Generate Walkthrough"}
            </button>
          )}
        </div>
      )}

      {/* Questions grouped by severity */}
      {grouped.length === 0 && !loading && (
        <div className="text-center py-12 text-gray-500">
          <p className="text-lg font-medium">No clarification questions</p>
          <p className="mt-1 text-sm">
            The analysis found no gaps requiring clarification.
          </p>
        </div>
      )}

      <div className="space-y-8">
        {grouped.map((group) => {
          const style = SEVERITY_STYLES[group.severity];
          return (
            <section key={group.severity}>
              <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style.badge}`}
                >
                  {style.label}
                </span>
                <span className="ml-2 text-gray-400">
                  ({group.questions.length})
                </span>
              </h3>

              <div className="space-y-4">
                {group.questions.map((q) => {
                  const isAnswered = q.answer !== null;
                  const isUnanswerable =
                    q.answer === "Marked unanswerable by user";
                  const isBusy = submitting[q.question_id] ?? false;

                  return (
                    <div
                      key={q.question_id}
                      className={`rounded-lg border p-5 ${style.border} ${
                        isAnswered ? "bg-gray-50/50" : "bg-white"
                      }`}
                    >
                      {/* Question text */}
                      <p className="text-sm font-medium text-gray-900 leading-relaxed">
                        {q.text}
                      </p>

                      {/* Evidence section */}
                      {q.evidence.length > 0 && (
                        <div className="mt-3 rounded-md bg-gray-50 border border-gray-100 p-3">
                          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                            Evidence
                          </p>
                          <ul className="space-y-2">
                            {q.evidence.map((ref, i) => {
                              const formatted = formatSourceRef(ref);
                              return (
                                <li key={i} className="text-xs">
                                  <span className="font-medium text-gray-700">
                                    {formatted.label}
                                  </span>
                                  {formatted.excerpt && (
                                    <p className="mt-0.5 text-gray-500 italic pl-3 border-l-2 border-gray-200">
                                      {formatted.excerpt}
                                    </p>
                                  )}
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      )}

                      {/* Answer display (if already answered) */}
                      {isAnswered && !isUnanswerable && (
                        <div className="mt-3 rounded-md bg-green-50 border border-green-100 px-3 py-2">
                          <p className="text-xs font-semibold text-green-700 mb-1">
                            Your answer
                          </p>
                          <p className="text-sm text-green-800">{q.answer}</p>
                        </div>
                      )}

                      {/* Unanswerable indicator */}
                      {isUnanswerable && (
                        <div className="mt-3 rounded-md bg-amber-50 border border-amber-100 px-3 py-2">
                          <p className="text-xs font-semibold text-amber-700">
                            Marked as unanswerable
                          </p>
                          {q.severity === "critical" && (
                            <p className="text-xs text-amber-600 mt-0.5">
                              A warning will be placed on affected screens.
                            </p>
                          )}
                        </div>
                      )}

                      {/* Answer input (if not yet answered) */}
                      {!isAnswered && (
                        <div className="mt-3 space-y-2">
                          <textarea
                            rows={2}
                            placeholder="Type your answer..."
                            value={drafts[q.question_id] ?? ""}
                            onChange={(e) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [q.question_id]: e.target.value,
                              }))
                            }
                            disabled={isBusy}
                            className="block w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder:text-gray-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:opacity-50 resize-none"
                          />
                          <div className="flex gap-2">
                            <button
                              type="button"
                              disabled={
                                isBusy || !(drafts[q.question_id]?.trim())
                              }
                              onClick={() => handleAnswer(q.question_id)}
                              className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                              {isBusy ? "Submitting..." : "Submit Answer"}
                            </button>
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => handleUnanswerable(q.question_id)}
                              className="rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                            >
                              Mark Unanswerable
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
