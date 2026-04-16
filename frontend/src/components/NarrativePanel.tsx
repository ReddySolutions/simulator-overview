import { useEffect, useRef } from "react";
import type { WorkflowScreen, SourceRef } from "../types";

/* ---------- Source reference formatting ---------- */

function formatCitation(ref: SourceRef): string {
  if (ref.source_type === "video") {
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) return `Source: ${match[1]} @ ${match[2]}:${match[3]}`;
  }
  if (ref.source_type === "audio") {
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) return `Audio @ ${match[2]}:${match[3]}`;
  }
  if (ref.source_type === "pdf") {
    const match = ref.reference.match(/^(.+?):(Section .+|.+)$/);
    if (match) return `PDF ${match[2]}`;
  }
  return ref.reference;
}

/* ---------- Section component ---------- */

function NarrativeSection({
  label,
  content,
  icon,
  refs,
}: {
  label: string;
  content: string;
  icon: React.ReactNode;
  refs: SourceRef[];
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        {icon}
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          {label}
        </h4>
      </div>
      <p className="text-sm text-gray-700 leading-relaxed">{content}</p>
      {refs.length > 0 && (
        <div className="space-y-1">
          {refs.map((ref, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs text-gray-400">
              <span className="shrink-0 mt-0.5">
                {ref.source_type === "video" && "🎬"}
                {ref.source_type === "audio" && "🔊"}
                {ref.source_type === "pdf" && "📄"}
              </span>
              <span className="font-mono">
                {formatCitation(ref)}
                {ref.excerpt && (
                  <span className="block mt-0.5 text-gray-500 not-italic">
                    &ldquo;{ref.excerpt}&rdquo;
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Main component ---------- */

interface NarrativePanelProps {
  screen: WorkflowScreen;
  open: boolean;
  onClose: () => void;
}

export default function NarrativePanel({
  screen,
  open,
  onClose,
}: NarrativePanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (
        panelRef.current &&
        !panelRef.current.contains(e.target as Node) &&
        // Don't close if clicking a Why? toggle button
        !(e.target as HTMLElement).closest("[data-narrative-toggle]")
      ) {
        onClose();
      }
    }
    // Delay listener so the opening click doesn't immediately close it
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", handleClick);
    }, 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handleClick);
    };
  }, [open, onClose]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  const narrative = screen.narrative;

  // Categorize source refs by type for citation display
  const videoRefs = screen.source_refs.filter((r) => r.source_type === "video");
  const audioRefs = screen.source_refs.filter((r) => r.source_type === "audio");
  const pdfRefs = screen.source_refs.filter((r) => r.source_type === "pdf");

  return (
    <div
      ref={panelRef}
      className={`fixed top-0 right-0 h-full w-96 max-w-[90vw] bg-white border-l border-gray-200 shadow-xl z-50 transition-transform duration-300 ease-in-out ${
        open ? "translate-x-0" : "translate-x-full"
      }`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Why?</h3>
          <p className="text-xs text-gray-500 mt-0.5 truncate max-w-[260px]">
            {screen.title}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          aria-label="Close narrative panel"
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Scrollable content */}
      <div className="overflow-y-auto h-[calc(100%-65px)] px-5 py-4 space-y-6">
        {!narrative ? (
          <div className="flex flex-col items-center justify-center h-48 text-center">
            <svg className="h-10 w-10 text-gray-300 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
            </svg>
            <p className="text-sm text-gray-400">
              No narrative data available for this screen.
            </p>
          </div>
        ) : (
          <>
            {/* What */}
            <NarrativeSection
              label="What"
              content={narrative.what}
              icon={
                <svg className="h-4 w-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
              }
              refs={videoRefs}
            />

            {/* Why */}
            <NarrativeSection
              label="Why"
              content={narrative.why}
              icon={
                <svg className="h-4 w-4 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                </svg>
              }
              refs={[...audioRefs, ...pdfRefs]}
            />

            {/* When (conditional) */}
            {narrative.when_condition && (
              <NarrativeSection
                label="When"
                content={narrative.when_condition}
                icon={
                  <svg className="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                  </svg>
                }
                refs={[]}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
