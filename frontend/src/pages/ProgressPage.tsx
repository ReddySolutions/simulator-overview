import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { analyzeProject, streamProgress } from "../api/client";

interface PhaseInfo {
  id: string;
  label: string;
}

interface PhaseState extends PhaseInfo {
  status: "pending" | "active" | "complete";
  percentage: number;
  message: string;
}

const PHASES: PhaseInfo[] = [
  { id: "ingestion", label: "Ingestion" },
  { id: "video_analysis", label: "Video Analysis" },
  { id: "pdf_extraction", label: "PDF Extraction" },
  { id: "path_merge", label: "Path Merge" },
  { id: "narrative", label: "Narrative" },
  { id: "contradictions", label: "Contradictions" },
  { id: "clarification", label: "Clarification" },
  { id: "generation", label: "Generation" },
];

function phaseIndex(id: string): number {
  return PHASES.findIndex((p) => p.id === id);
}

function buildPhases(
  activeId: string,
  percentage: number,
  message: string,
): PhaseState[] {
  const idx = phaseIndex(activeId);
  return PHASES.map((p, i) => {
    if (idx < 0) {
      return {
        ...p,
        status: "pending" as const,
        percentage: 0,
        message: "",
      };
    }
    if (i < idx) {
      return { ...p, status: "complete" as const, percentage: 100, message: "" };
    }
    if (i === idx) {
      return {
        ...p,
        status: percentage >= 100 ? ("complete" as const) : ("active" as const),
        percentage,
        message,
      };
    }
    return { ...p, status: "pending" as const, percentage: 0, message: "" };
  });
}

export default function ProgressPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [phases, setPhases] = useState<PhaseState[]>(
    buildPhases("ingestion", 0, "Starting analysis..."),
  );
  const [error, setError] = useState<string | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!id) return;

    closedRef.current = false;
    let es: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closedRef.current) return;

      es = streamProgress(
        id,
        (event) => {
          if (closedRef.current) return;
          setError(null);

          // Pipeline error
          if (event.phase === "error") {
            setError(event.message);
            return;
          }

          // Status-only events (no active pipeline — project already past this point)
          if (event.phase === "complete") {
            closedRef.current = true;
            es?.close();
            navigate(`/walkthrough/${id}`);
            return;
          }
          if (event.phase === "clarifying") {
            closedRef.current = true;
            es?.close();
            navigate(`/clarify/${id}`);
            return;
          }
          if (event.phase === "analyzing") {
            setPhases(buildPhases("video_analysis", 0, "Analysis in progress..."));
            return;
          }
          if (event.phase === "generating") {
            setPhases(buildPhases("generation", 0, "Generation in progress..."));
            return;
          }

          // Normal progress events
          setPhases(buildPhases(event.phase, event.percentage, event.message));

          // Auto-navigate: clarification complete -> questions page
          if (event.phase === "clarification" && event.percentage >= 100) {
            closedRef.current = true;
            es?.close();
            setTimeout(() => navigate(`/clarify/${id}`), 1500);
            return;
          }

          // Auto-navigate: generation complete -> walkthrough page
          if (event.phase === "generation" && event.percentage >= 100) {
            closedRef.current = true;
            es?.close();
            setTimeout(() => navigate(`/walkthrough/${id}`), 1500);
            return;
          }
        },
        () => {
          // SSE connection error — close current and reconnect after delay
          if (closedRef.current) return;
          es?.close();
          reconnectTimer = setTimeout(connect, 3000);
        },
      );
    };

    // Trigger analysis, then open SSE stream
    analyzeProject(id)
      .then(() => connect())
      .catch((err) => {
        const msg = err instanceof Error ? err.message : "Failed to start analysis";
        // 409 = already running — just connect to SSE for existing events
        if (!msg.includes("already running")) {
          setError(msg);
        }
        connect();
      });

    return () => {
      closedRef.current = true;
      es?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [id, navigate]);

  return (
    <div className="max-w-2xl mx-auto">
      <h2 className="text-2xl font-semibold mb-8">Analysis Progress</h2>

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
            onClick={() => window.location.reload()}
            className="text-red-700 underline hover:text-red-800 text-xs"
          >
            Retry
          </button>
        </div>
      )}

      {/* Vertical phase timeline */}
      <div className="relative">
        {phases.map((phase, i) => (
          <div key={phase.id} className="flex gap-4 pb-8 last:pb-0">
            {/* Timeline column: indicator + connecting line */}
            <div className="flex flex-col items-center">
              {phase.status === "complete" ? (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-100">
                  <svg
                    className="h-5 w-5 text-green-600"
                    fill="currentColor"
                    viewBox="0 0 20 20"
                  >
                    <path
                      fillRule="evenodd"
                      d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
              ) : phase.status === "active" ? (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100">
                  <svg
                    className="h-5 w-5 text-blue-600 animate-spin"
                    fill="none"
                    viewBox="0 0 24 24"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                </div>
              ) : (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100">
                  <div className="h-2.5 w-2.5 rounded-full bg-gray-300" />
                </div>
              )}

              {i < phases.length - 1 && (
                <div
                  className={`w-0.5 flex-1 min-h-6 ${
                    phase.status === "complete" ? "bg-green-200" : "bg-gray-200"
                  }`}
                />
              )}
            </div>

            {/* Phase label and progress */}
            <div className="pt-1 flex-1 min-w-0">
              <p
                className={`text-sm font-medium ${
                  phase.status === "complete"
                    ? "text-green-700"
                    : phase.status === "active"
                      ? "text-blue-700"
                      : "text-gray-400"
                }`}
              >
                {phase.label}
              </p>

              {phase.status === "active" && (
                <div className="mt-2 space-y-1">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-blue-500 transition-all duration-500 ease-out"
                        style={{ width: `${phase.percentage}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-500 tabular-nums w-8 text-right">
                      {phase.percentage}%
                    </span>
                  </div>
                  {phase.message && (
                    <p className="text-xs text-gray-500 truncate">
                      {phase.message}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
