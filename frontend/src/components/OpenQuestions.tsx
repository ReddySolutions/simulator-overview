import { useMemo } from "react";
import type {
  OpenQuestion,
  SourceRef,
  DecisionTree,
  WorkflowScreen,
} from "../types";

/* ---------- Source reference formatting ---------- */

function formatSourceRef(ref: SourceRef): string {
  if (ref.source_type === "video" || ref.source_type === "audio") {
    const match = ref.reference.match(/^(.+):(\d{2}):(\d{2})$/);
    if (match) {
      const prefix = ref.source_type === "video" ? "Video" : "Audio";
      return `${prefix}: ${match[1]} @ ${match[2]}:${match[3]}`;
    }
  }
  if (ref.source_type === "pdf") {
    const match = ref.reference.match(/^(.+?):(Section .+|.+)$/);
    if (match) {
      return `PDF: ${match[1]} \u2014 ${match[2]}`;
    }
  }
  return ref.reference;
}

/* ---------- Evidence Tier Legend ---------- */

function EvidenceTierLegend() {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
      <h3 className="text-sm font-semibold text-gray-800 mb-3">
        Evidence Tier Legend
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Each screen in the walkthrough is marked by how it was sourced from your
        training materials.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 h-10 w-16 shrink-0 rounded border-2 border-gray-300 bg-white" />
          <div>
            <p className="text-sm font-medium text-gray-700">Observed</p>
            <p className="text-xs text-gray-500">
              Solid border. Screen was directly visible in a training video with
              timestamped keyframe evidence.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3">
          <div className="mt-0.5 h-10 w-16 shrink-0 rounded border-2 border-dashed border-gray-300 bg-white" />
          <div>
            <p className="text-sm font-medium text-gray-700">Mentioned</p>
            <p className="text-xs text-gray-500">
              Dashed border. Screen was referenced in audio narration or PDF
              documentation but never shown on-screen.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------- Shared Phases Table ---------- */

interface PhaseEntry {
  screenId: string;
  title: string;
  treeIndices: number[];
  isShared: boolean;
}

function buildSharedPhases(
  trees: DecisionTree[],
  screens: Record<string, WorkflowScreen & { warnings?: string[] }>,
): PhaseEntry[] {
  if (trees.length === 0) return [];

  // Collect ordered screen IDs per tree by walking root -> branches
  const treePaths: string[][] = trees.map((tree) => {
    const ordered: string[] = [];
    const visited = new Set<string>();
    const queue = [tree.root_screen_id];
    while (queue.length > 0) {
      const id = queue.shift()!;
      if (visited.has(id)) continue;
      visited.add(id);
      ordered.push(id);
      // Find branches from this screen
      for (const bp of tree.branches) {
        if (bp.screen_id === id) {
          for (const nextId of Object.values(bp.paths)) {
            if (!visited.has(nextId)) queue.push(nextId);
          }
        }
      }
    }
    return ordered;
  });

  // Build a set of all screen IDs per tree for membership checks
  const treeSets = treePaths.map((path) => new Set(path));

  // Collect unique screen IDs preserving first-appearance order
  const allIds: string[] = [];
  const seen = new Set<string>();
  for (const path of treePaths) {
    for (const id of path) {
      if (!seen.has(id)) {
        seen.add(id);
        allIds.push(id);
      }
    }
  }

  return allIds.map((id) => {
    const treeIndices: number[] = [];
    for (let i = 0; i < treeSets.length; i++) {
      if (treeSets[i].has(id)) treeIndices.push(i);
    }
    return {
      screenId: id,
      title: screens[id]?.title ?? id.slice(0, 8),
      treeIndices,
      isShared: treeIndices.length > 1,
    };
  });
}

function SharedPhasesTable({
  trees,
  screens,
}: {
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen & { warnings?: string[] }>;
}) {
  const phases = useMemo(
    () => buildSharedPhases(trees, screens),
    [trees, screens],
  );

  if (trees.length < 2 || phases.length === 0) return null;

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 mb-6">
      <h3 className="text-sm font-semibold text-gray-800 mb-1">
        Shared Phases Across Videos
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Screens present in multiple training videos appear highlighted. Variants
        only in a single video are dimmed.
      </p>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="py-2 pr-4 text-left font-medium text-gray-600">
                Screen
              </th>
              {trees.map((_, i) => (
                <th
                  key={i}
                  className="py-2 px-3 text-center font-medium text-gray-600"
                >
                  Video {i + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {phases.map((phase) => (
              <tr
                key={phase.screenId}
                className={
                  phase.isShared
                    ? "bg-blue-50"
                    : "bg-white text-gray-400"
                }
              >
                <td className="py-1.5 pr-4 text-gray-700 font-medium">
                  {phase.title}
                </td>
                {trees.map((_, i) => (
                  <td key={i} className="py-1.5 px-3 text-center">
                    {phase.treeIndices.includes(i) ? (
                      <span
                        className={
                          phase.isShared
                            ? "inline-block h-2.5 w-2.5 rounded-full bg-blue-500"
                            : "inline-block h-2.5 w-2.5 rounded-full bg-gray-300"
                        }
                      />
                    ) : (
                      <span className="text-gray-200">&mdash;</span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-blue-500" />
          Shared across videos
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-300" />
          Single video only
        </span>
      </div>
    </div>
  );
}

/* ---------- Gap Card ---------- */

function GapCard({ gap }: { gap: OpenQuestion }) {
  const isMedium = gap.severity === "medium";
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium shrink-0 ${
            isMedium
              ? "bg-amber-100 text-amber-700"
              : "bg-gray-100 text-gray-600"
          }`}
        >
          {gap.severity}
        </span>
        <p className="text-sm text-gray-800">{gap.description}</p>
      </div>

      {gap.evidence.length > 0 && (
        <div className="mt-3 ml-[calc(2.5rem+0.75rem)] space-y-1.5">
          {gap.evidence.map((ref, i) => (
            <div key={i} className="text-xs">
              <span className="font-mono text-gray-500">
                {formatSourceRef(ref)}
              </span>
              {ref.excerpt && (
                <p className="mt-0.5 text-gray-400 italic pl-2 border-l-2 border-gray-200">
                  {ref.excerpt}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Main Component ---------- */

interface OpenQuestionsProps {
  openQuestions: OpenQuestion[];
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen & { warnings?: string[] }>;
}

export default function OpenQuestions({
  openQuestions,
  trees,
  screens,
}: OpenQuestionsProps) {
  const grouped = useMemo(() => {
    const medium = openQuestions.filter((q) => q.severity === "medium");
    const low = openQuestions.filter((q) => q.severity === "low");
    return { medium, low };
  }, [openQuestions]);

  return (
    <div>
      <EvidenceTierLegend />
      <SharedPhasesTable trees={trees} screens={screens} />

      {openQuestions.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
          <svg
            className="mx-auto h-10 w-10 text-green-400 mb-3"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
            />
          </svg>
          <p className="text-sm font-medium text-gray-700">
            No open questions
          </p>
          <p className="mt-1 text-xs text-gray-500">
            All gaps were resolved during the clarification phase.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.medium.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-amber-400" />
                Medium Severity ({grouped.medium.length})
              </h3>
              <div className="space-y-3">
                {grouped.medium.map((q) => (
                  <GapCard key={q.gap_id} gap={q} />
                ))}
              </div>
            </section>
          )}

          {grouped.low.length > 0 && (
            <section>
              <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-400" />
                Low Severity ({grouped.low.length})
              </h3>
              <div className="space-y-3">
                {grouped.low.map((q) => (
                  <GapCard key={q.gap_id} gap={q} />
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
