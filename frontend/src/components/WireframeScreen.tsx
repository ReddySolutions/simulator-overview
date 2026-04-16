import { useMemo } from "react";
import type { UIElement, WorkflowScreen, SourceRef } from "../types";

/* ---------- Element type renderers ---------- */

function WireframeButton({ label, state }: { label: string; state: string | null }) {
  return (
    <div
      className={`inline-flex items-center justify-center rounded-md border px-4 py-2 text-sm font-medium transition-colors ${
        state === "disabled"
          ? "border-gray-200 bg-gray-100 text-gray-400 cursor-not-allowed"
          : "border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100 cursor-pointer"
      }`}
    >
      {label}
    </div>
  );
}

function WireframeDropdown({ label, state }: { label: string; state: string | null }) {
  return (
    <div className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700">
      <span className="flex-1 truncate">{state ?? label}</span>
      <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
      </svg>
    </div>
  );
}

function WireframeTextField({ label, state }: { label: string; state: string | null }) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-medium text-gray-500">{label}</label>
      <div className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-400">
        {state ?? `Enter ${label.toLowerCase()}...`}
      </div>
    </div>
  );
}

function WireframeTab({ label, state }: { label: string; state: string | null }) {
  const isActive = state === "active" || state === "selected";
  return (
    <div
      className={`inline-block border-b-2 px-3 py-2 text-sm font-medium ${
        isActive
          ? "border-blue-500 text-blue-600"
          : "border-transparent text-gray-500"
      }`}
    >
      {label}
    </div>
  );
}

function WireframeLabel({ label }: { label: string }) {
  return <span className="text-sm text-gray-700">{label}</span>;
}

function WireframeCheckbox({ label, state }: { label: string; state: string | null }) {
  const checked = state === "checked" || state === "selected";
  return (
    <div className="flex items-center gap-2">
      <div
        className={`h-4 w-4 shrink-0 rounded border ${
          checked
            ? "border-blue-500 bg-blue-500"
            : "border-gray-300 bg-white"
        }`}
      >
        {checked && (
          <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        )}
      </div>
      <span className="text-sm text-gray-700">{label}</span>
    </div>
  );
}

function WireframeRadio({ label, state }: { label: string; state: string | null }) {
  const checked = state === "checked" || state === "selected";
  return (
    <div className="flex items-center gap-2">
      <div
        className={`h-4 w-4 shrink-0 rounded-full border-2 flex items-center justify-center ${
          checked ? "border-blue-500" : "border-gray-300"
        }`}
      >
        {checked && <div className="h-2 w-2 rounded-full bg-blue-500" />}
      </div>
      <span className="text-sm text-gray-700">{label}</span>
    </div>
  );
}

function WireframeLink({ label }: { label: string }) {
  return (
    <span className="text-sm text-blue-600 underline decoration-blue-300 cursor-pointer">
      {label}
    </span>
  );
}

function WireframeTable({ label }: { label: string }) {
  return (
    <div className="rounded-md border border-gray-200 overflow-hidden">
      <div className="bg-gray-50 px-3 py-1.5 text-xs font-medium text-gray-500 border-b border-gray-200">
        {label}
      </div>
      <div className="grid grid-cols-3 gap-px bg-gray-200">
        {[0, 1, 2].map((col) => (
          <div key={`header-${col}`} className="bg-gray-100 px-2 py-1 text-[10px] font-medium text-gray-500">
            Column {col + 1}
          </div>
        ))}
        {[0, 1, 2].map((row) =>
          [0, 1, 2].map((col) => (
            <div key={`${row}-${col}`} className="bg-white px-2 py-1 text-[10px] text-gray-400">
              &mdash;
            </div>
          )),
        )}
      </div>
    </div>
  );
}

function WireframeOther({ label }: { label: string }) {
  return (
    <div className="rounded border border-dashed border-gray-300 bg-gray-50 px-3 py-2 text-sm text-gray-500">
      {label}
    </div>
  );
}

/* ---------- Element renderer dispatch ---------- */

function WireframeElement({ element }: { element: UIElement }) {
  switch (element.element_type) {
    case "button":
      return <WireframeButton label={element.label} state={element.state} />;
    case "dropdown":
      return <WireframeDropdown label={element.label} state={element.state} />;
    case "text_field":
      return <WireframeTextField label={element.label} state={element.state} />;
    case "tab":
      return <WireframeTab label={element.label} state={element.state} />;
    case "label":
      return <WireframeLabel label={element.label} />;
    case "checkbox":
      return <WireframeCheckbox label={element.label} state={element.state} />;
    case "radio":
      return <WireframeRadio label={element.label} state={element.state} />;
    case "link":
      return <WireframeLink label={element.label} />;
    case "table":
      return <WireframeTable label={element.label} />;
    default:
      return <WireframeOther label={element.label} />;
  }
}

/* ---------- Layout grouping ---------- */

type LayoutGroup = "nav" | "content" | "actions";

const NAV_TYPES = new Set(["tab", "link"]);
const ACTION_TYPES = new Set(["button"]);

function groupElements(elements: UIElement[]): Record<LayoutGroup, UIElement[]> {
  const groups: Record<LayoutGroup, UIElement[]> = {
    nav: [],
    content: [],
    actions: [],
  };

  for (const el of elements) {
    if (NAV_TYPES.has(el.element_type)) {
      groups.nav.push(el);
    } else if (ACTION_TYPES.has(el.element_type)) {
      groups.actions.push(el);
    } else {
      groups.content.push(el);
    }
  }

  return groups;
}

/* ---------- Source reference formatting ---------- */

function formatSourceRef(ref: SourceRef): string {
  if (ref.source_type === "video" || ref.source_type === "audio") {
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) {
      const prefix = ref.source_type === "video" ? "Source" : "Audio";
      return `${prefix}: ${match[1]} @ ${match[2]}:${match[3]}`;
    }
  }
  if (ref.source_type === "pdf") {
    const match = ref.reference.match(/^(.+?):(Section .+|.+)$/);
    if (match) {
      return `Mentioned in: ${match[1]} \u2014 ${match[2]}`;
    }
  }
  return ref.reference;
}

/* ---------- Main component ---------- */

interface WireframeScreenProps {
  screen: WorkflowScreen;
  warnings?: string[];
  warningEvidence?: Array<{ description: string; evidence: SourceRef[] }>;
}

export default function WireframeScreen({
  screen,
  warnings,
  warningEvidence,
}: WireframeScreenProps) {
  const isObserved = screen.evidence_tier === "observed";

  const groups = useMemo(
    () => groupElements(screen.ui_elements),
    [screen.ui_elements],
  );

  const primaryRef = screen.source_refs[0];

  return (
    <div className="relative">
      {/* Warning overlay for unresolved critical gaps */}
      {warnings && warnings.length > 0 && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3">
          <div className="flex items-start gap-2">
            <svg
              className="h-5 w-5 text-red-500 mt-0.5 shrink-0"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
            <div className="flex-1">
              <h4 className="text-sm font-semibold text-red-800">
                Unresolved Critical {warnings.length === 1 ? "Gap" : "Gaps"}
              </h4>
              <ul className="mt-1 space-y-1">
                {(warningEvidence ?? warnings.map((w) => ({ description: w, evidence: [] }))).map(
                  (item, i) => (
                    <li key={i} className="text-sm text-red-700">
                      {item.description}
                      {item.evidence.length > 0 && (
                        <span className="block text-xs text-red-500 mt-0.5">
                          Evidence: {item.evidence.map((e) => formatSourceRef(e)).join(" vs. ")}
                        </span>
                      )}
                    </li>
                  ),
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Screen wireframe */}
      <div
        className={`rounded-lg bg-white shadow-sm overflow-hidden ${
          isObserved
            ? "border-2 border-gray-300"
            : "border-2 border-dashed border-gray-300"
        }`}
      >
        {/* Title bar */}
        <div className="flex items-center justify-between border-b border-gray-200 bg-gray-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-gray-800">{screen.title}</h3>
          {!isObserved && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
              <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 20 20">
                <path
                  fillRule="evenodd"
                  d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z"
                  clipRule="evenodd"
                />
              </svg>
              Mentioned, not observed
            </span>
          )}
        </div>

        {/* Wireframe body */}
        <div className="p-4 space-y-4 min-h-[200px]">
          {/* Nav / tabs group at top */}
          {groups.nav.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 border-b border-gray-100 pb-2">
              {groups.nav.map((el, i) => (
                <WireframeElement key={`nav-${el.element_type}-${el.label}-${i}`} element={el} />
              ))}
            </div>
          )}

          {/* Main content group */}
          {groups.content.length > 0 && (
            <div className="space-y-3">
              {groups.content.map((el, i) => (
                <div key={`content-${el.element_type}-${el.label}-${i}`}>
                  <WireframeElement element={el} />
                </div>
              ))}
            </div>
          )}

          {/* Empty state */}
          {screen.ui_elements.length === 0 && (
            <div className="flex items-center justify-center h-32 text-sm text-gray-400">
              No UI elements recorded for this screen
            </div>
          )}

          {/* Actions group at bottom */}
          {groups.actions.length > 0 && (
            <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3 mt-auto">
              {groups.actions.map((el, i) => (
                <WireframeElement key={`action-${el.element_type}-${el.label}-${i}`} element={el} />
              ))}
            </div>
          )}
        </div>

        {/* Source reference footer */}
        {primaryRef && (
          <div className="border-t border-gray-200 bg-gray-50 px-4 py-2">
            <p className="text-xs font-mono text-gray-400">
              {formatSourceRef(primaryRef)}
              {screen.source_refs.length > 1 && (
                <span className="ml-1 text-gray-300">
                  (+{screen.source_refs.length - 1} more sources)
                </span>
              )}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
