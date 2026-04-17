import { useMemo } from "react";
import type { WorkflowScreen, UIElement } from "../types";

/* ---------- Node data interface ---------- */

export interface GraphNodeData extends Record<string, unknown> {
  screen: WorkflowScreen;
  stepCount: number;
  selected: boolean;
  visited: boolean;
  hasWarning: boolean;
}

/* ---------- Compute node dimensions from content ---------- */

export function computeNodeSize(elementCount: number): {
  width: number;
  height: number;
} {
  const width = Math.min(200, Math.max(120, 130 + elementCount * 6));
  const height = Math.min(140, Math.max(80, 85 + Math.min(elementCount, 6) * 8));
  return { width, height };
}

/* ---------- Mini wireframe element ---------- */

const ELEMENT_STYLES: Record<
  string,
  { bg: string; border: string; icon?: string }
> = {
  button: { bg: "bg-blue-100", border: "border-blue-300", icon: undefined },
  dropdown: { bg: "bg-gray-50", border: "border-gray-300", icon: "\u25BE" },
  text_field: { bg: "bg-white", border: "border-gray-300", icon: undefined },
  tab: { bg: "bg-indigo-50", border: "border-indigo-200", icon: undefined },
  label: { bg: "bg-transparent", border: "border-transparent", icon: undefined },
  checkbox: { bg: "bg-white", border: "border-gray-400", icon: undefined },
  radio: { bg: "bg-white", border: "border-gray-400", icon: undefined },
  link: { bg: "bg-transparent", border: "border-transparent", icon: undefined },
  table: { bg: "bg-gray-50", border: "border-gray-300", icon: "\u2261" },
  other: { bg: "bg-gray-50", border: "border-gray-200", icon: undefined },
};

function MiniElement({ element }: { element: UIElement }) {
  const style = ELEMENT_STYLES[element.element_type] ?? ELEMENT_STYLES.other;
  const truncLabel =
    element.label.length > 8
      ? element.label.slice(0, 7) + "\u2026"
      : element.label;

  if (element.element_type === "label") {
    return (
      <span className="text-[7px] text-gray-500 leading-none truncate max-w-[60px]">
        {truncLabel}
      </span>
    );
  }

  if (element.element_type === "link") {
    return (
      <span className="text-[7px] text-blue-500 leading-none underline truncate max-w-[60px]">
        {truncLabel}
      </span>
    );
  }

  if (element.element_type === "checkbox") {
    return (
      <span className="inline-flex items-center gap-0.5">
        <span className="inline-block w-[7px] h-[7px] border border-gray-400 bg-white rounded-[1px]" />
        <span className="text-[7px] text-gray-500 leading-none truncate max-w-[50px]">
          {truncLabel}
        </span>
      </span>
    );
  }

  if (element.element_type === "radio") {
    return (
      <span className="inline-flex items-center gap-0.5">
        <span className="inline-block w-[7px] h-[7px] border border-gray-400 bg-white rounded-full" />
        <span className="text-[7px] text-gray-500 leading-none truncate max-w-[50px]">
          {truncLabel}
        </span>
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-[2px] border px-1 py-[1px] ${style.bg} ${style.border}`}
    >
      <span className="text-[7px] text-gray-600 leading-none truncate max-w-[50px]">
        {truncLabel}
      </span>
      {style.icon && (
        <span className="text-[7px] text-gray-400 leading-none">
          {style.icon}
        </span>
      )}
    </span>
  );
}

/* ---------- GraphNodePreview component ---------- */

export default function GraphNodePreview({ data }: { data: GraphNodeData }) {
  const { screen, stepCount, selected, visited, hasWarning } = data;
  const isObserved = screen.evidence_tier === "observed";

  const previewElements = useMemo(() => {
    const elements: UIElement[] = [];
    const seen = new Set<string>();
    for (const el of screen.ui_elements) {
      const key = `${el.element_type}:${el.label}`;
      if (!seen.has(key) && elements.length < 6) {
        seen.add(key);
        elements.push(el);
      }
    }
    return elements;
  }, [screen.ui_elements]);

  const { width } = computeNodeSize(screen.ui_elements.length);

  const borderClass = isObserved
    ? "border-2 border-blue-400"
    : "border-2 border-dashed border-gray-300";

  const warningClass = hasWarning ? "bg-red-50" : "bg-white";

  return (
    <div
      style={{ width }}
      className={`rounded-lg px-2.5 py-2 shadow-sm cursor-pointer transition-all ${borderClass} ${warningClass} ${
        selected ? "ring-2 ring-blue-600 ring-offset-2" : "hover:shadow-md"
      }`}
    >
      {/* Title bar + step badge */}
      <div className="flex items-start justify-between gap-1 mb-1">
        <div className="flex items-center gap-1 flex-1 min-w-0">
          {hasWarning && (
            <svg
              className="w-3 h-3 text-red-500 shrink-0"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
                clipRule="evenodd"
              />
            </svg>
          )}
          <h3 className="text-[10px] font-semibold text-gray-800 leading-tight line-clamp-2 flex-1">
            {screen.title}
          </h3>
        </div>
        <span className="shrink-0 inline-flex items-center justify-center rounded-full bg-gray-100 text-[9px] font-medium text-gray-600 w-4 h-4">
          {stepCount}
        </span>
      </div>

      {/* Mini wireframe preview */}
      {previewElements.length > 0 && (
        <div className="rounded border border-gray-100 bg-gray-50/50 px-1.5 py-1 mb-1">
          <div className="flex flex-wrap gap-x-1 gap-y-0.5">
            {previewElements.map((el, i) => (
              <MiniElement key={`${el.element_type}-${el.label}-${i}`} element={el} />
            ))}
          </div>
        </div>
      )}

      {/* Footer: evidence tier + visited dot */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              isObserved ? "bg-blue-400" : "bg-gray-300"
            }`}
          />
          <span className="text-[8px] text-gray-400">
            {isObserved ? "observed" : "mentioned"}
          </span>
        </div>
        <span
          className={`inline-block w-2 h-2 rounded-full border ${
            visited
              ? "bg-green-400 border-green-500"
              : "bg-white border-gray-300"
          }`}
          title={visited ? "Visited" : "Not visited"}
        />
      </div>
    </div>
  );
}
