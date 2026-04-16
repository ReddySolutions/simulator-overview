import { useCallback, useMemo, useState } from "react";
import type {
  DecisionTree,
  WorkflowScreen,
  BranchPoint,
  WalkthroughWarning,
} from "../types";
import WireframeScreen from "./WireframeScreen";
import NarrativePanel from "./NarrativePanel";

/* ---------- Tree navigation helpers ---------- */

/** Build adjacency map: screen_id -> list of { action, targetId } */
function buildAdjacency(
  branches: BranchPoint[],
): Map<string, Array<{ action: string; targetId: string; condition: string }>> {
  const adj = new Map<
    string,
    Array<{ action: string; targetId: string; condition: string }>
  >();
  for (const bp of branches) {
    const paths: Array<{ action: string; targetId: string; condition: string }> =
      [];
    for (const [action, targetId] of Object.entries(bp.paths)) {
      paths.push({ action, targetId, condition: bp.condition });
    }
    adj.set(bp.screen_id, paths);
  }
  return adj;
}

/** Collect all branches from all trees. */
function getAllBranches(trees: DecisionTree[]): BranchPoint[] {
  return trees.flatMap((t) => t.branches);
}

/** Count total screens on the longest path from a given screen. */
function countPathLength(
  screenId: string,
  adjacency: Map<string, Array<{ action: string; targetId: string }>>,
  visited: Set<string>,
): number {
  if (visited.has(screenId)) return 0;
  visited.add(screenId);
  const children = adjacency.get(screenId);
  if (!children || children.length === 0) return 1;
  let maxChild = 0;
  for (const child of children) {
    maxChild = Math.max(
      maxChild,
      countPathLength(child.targetId, adjacency, new Set(visited)),
    );
  }
  return 1 + maxChild;
}

/** Get all screen IDs reachable from root for the mini-map tree. */
function getReachableScreens(
  rootId: string,
  adjacency: Map<string, Array<{ action: string; targetId: string }>>,
): Set<string> {
  const visited = new Set<string>();
  const queue = [rootId];
  while (queue.length > 0) {
    const current = queue.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    for (const child of adjacency.get(current) ?? []) {
      queue.push(child.targetId);
    }
  }
  return visited;
}

/* ---------- Mini-map tree node ---------- */

interface TreeNodeProps {
  screenId: string;
  screens: Record<string, WorkflowScreen>;
  adjacency: Map<string, Array<{ action: string; targetId: string }>>;
  visitedScreens: Set<string>;
  currentScreenId: string;
  pathScreenIds: Set<string>;
  onJump: (screenId: string) => void;
  depth: number;
  maxDepth: number;
}

function TreeNode({
  screenId,
  screens,
  adjacency,
  visitedScreens,
  currentScreenId,
  pathScreenIds,
  onJump,
  depth,
  maxDepth,
}: TreeNodeProps) {
  const screen = screens[screenId];
  const title = screen?.title ?? screenId.slice(0, 8);
  const isCurrent = screenId === currentScreenId;
  const isOnPath = pathScreenIds.has(screenId);
  const isVisited = visitedScreens.has(screenId);
  const children = adjacency.get(screenId) ?? [];

  if (depth > maxDepth) return null;

  return (
    <div className="ml-3 first:ml-0">
      <button
        type="button"
        onClick={() => isVisited && onJump(screenId)}
        disabled={!isVisited}
        className={`flex items-center gap-1.5 rounded px-1.5 py-0.5 text-left text-xs transition-colors w-full ${
          isCurrent
            ? "bg-blue-100 text-blue-800 font-semibold"
            : isOnPath
              ? "bg-blue-50 text-blue-600 font-medium"
              : isVisited
                ? "text-gray-700 hover:bg-gray-100 cursor-pointer"
                : "text-gray-400 cursor-default"
        }`}
      >
        <span
          className={`inline-block w-2 h-2 rounded-full shrink-0 ${
            isCurrent
              ? "bg-blue-600"
              : isVisited
                ? "bg-green-400"
                : "bg-gray-300 ring-1 ring-gray-200"
          }`}
        />
        <span className="truncate">{title}</span>
      </button>
      {children.length > 0 && (
        <div className="border-l border-gray-200 ml-2 mt-0.5 space-y-0.5">
          {children.map((child) => (
            <TreeNode
              key={child.targetId}
              screenId={child.targetId}
              screens={screens}
              adjacency={adjacency}
              visitedScreens={visitedScreens}
              currentScreenId={currentScreenId}
              pathScreenIds={pathScreenIds}
              onJump={onJump}
              depth={depth + 1}
              maxDepth={maxDepth}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------- Main component ---------- */

interface SimulationNavigatorProps {
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen>;
  warnings: WalkthroughWarning[];
}

export default function SimulationNavigator({
  trees,
  screens,
  warnings,
}: SimulationNavigatorProps) {
  // Navigation history: list of screen IDs representing the path taken
  const [history, setHistory] = useState<string[]>(() => {
    if (trees.length === 0) return [];
    return [trees[0].root_screen_id];
  });
  // Set of all screens the user has ever visited in this session
  const [visitedScreens, setVisitedScreens] = useState<Set<string>>(() => {
    if (trees.length === 0) return new Set();
    return new Set([trees[0].root_screen_id]);
  });
  // Narrative panel open/closed state
  const [narrativeOpen, setNarrativeOpen] = useState(false);

  const allBranches = useMemo(() => getAllBranches(trees), [trees]);
  const adjacency = useMemo(() => buildAdjacency(allBranches), [allBranches]);

  const currentScreenId = history[history.length - 1] ?? "";
  const currentScreen = screens[currentScreenId] ?? null;

  // Available paths from current screen
  const availablePaths = useMemo(
    () => adjacency.get(currentScreenId) ?? [],
    [adjacency, currentScreenId],
  );

  // Warnings for current screen
  const screenWarnings = useMemo(() => {
    return warnings.filter((w) => w.screen_id === currentScreenId);
  }, [warnings, currentScreenId]);

  // Path screen IDs for highlighting in mini-map
  const pathScreenIds = useMemo(() => new Set(history), [history]);

  // Total reachable screens for progress calculation
  const totalScreens = useMemo(() => {
    if (trees.length === 0) return 0;
    return getReachableScreens(trees[0].root_screen_id, adjacency).size;
  }, [trees, adjacency]);

  // Step counter: current position on this path
  const pathLength = useMemo(() => {
    if (!currentScreenId) return 0;
    return (
      history.length -
      1 +
      countPathLength(currentScreenId, adjacency, new Set())
    );
  }, [currentScreenId, adjacency, history]);

  const navigateTo = useCallback(
    (screenId: string) => {
      setHistory((prev) => [...prev, screenId]);
      setVisitedScreens((prev) => new Set(prev).add(screenId));
    },
    [],
  );

  const goBack = useCallback(() => {
    setHistory((prev) => {
      if (prev.length <= 1) return prev;
      return prev.slice(0, -1);
    });
  }, []);

  const reset = useCallback(() => {
    if (trees.length === 0) return;
    const rootId = trees[0].root_screen_id;
    setHistory([rootId]);
    // Keep visited screens (don't reset exploration progress)
  }, [trees]);

  const toggleNarrative = useCallback(() => {
    setNarrativeOpen((prev) => !prev);
  }, []);

  const closeNarrative = useCallback(() => {
    setNarrativeOpen(false);
  }, []);

  const jumpToScreen = useCallback(
    (screenId: string) => {
      // Only allow jumping to visited screens
      if (!visitedScreens.has(screenId)) return;
      // Find if screenId is in history; if so, truncate to that point
      const idx = history.indexOf(screenId);
      if (idx >= 0) {
        setHistory(history.slice(0, idx + 1));
      } else {
        // Append as new navigation
        setHistory((prev) => [...prev, screenId]);
      }
    },
    [visitedScreens, history],
  );

  if (trees.length === 0 || !currentScreen) {
    return (
      <div className="flex items-center justify-center h-[400px] text-gray-400 text-sm">
        No simulation data available.
      </div>
    );
  }

  return (
    <div className="flex gap-4 min-h-[500px]">
      {/* Mini-map sidebar */}
      <div className="w-56 shrink-0 rounded-lg border border-gray-200 bg-white p-3 overflow-y-auto max-h-[700px]">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
            Decision Tree
          </h3>
          <span className="text-[10px] text-gray-400">
            {visitedScreens.size}/{totalScreens}
          </span>
        </div>

        {/* Progress bar */}
        <div className="mb-3">
          <div className="h-1.5 w-full rounded-full bg-gray-100">
            <div
              className="h-1.5 rounded-full bg-blue-500 transition-all"
              style={{
                width: `${totalScreens > 0 ? (visitedScreens.size / totalScreens) * 100 : 0}%`,
              }}
            />
          </div>
          <p className="text-[10px] text-gray-400 mt-1">
            Explored {visitedScreens.size} of {totalScreens} screens (
            {totalScreens > 0
              ? Math.round((visitedScreens.size / totalScreens) * 100)
              : 0}
            %)
          </p>
        </div>

        {/* Tree structure */}
        <div className="space-y-0.5">
          {trees.map((tree) => (
            <TreeNode
              key={tree.root_screen_id}
              screenId={tree.root_screen_id}
              screens={screens}
              adjacency={adjacency}
              visitedScreens={visitedScreens}
              currentScreenId={currentScreenId}
              pathScreenIds={pathScreenIds}
              onJump={jumpToScreen}
              depth={0}
              maxDepth={10}
            />
          ))}
        </div>

        {/* Unvisited hint */}
        {visitedScreens.size < totalScreens && (
          <div className="mt-3 rounded bg-amber-50 px-2 py-1.5 text-[10px] text-amber-700">
            <span className="font-medium">
              {totalScreens - visitedScreens.size}
            </span>{" "}
            screens left to explore. Try different branches!
          </div>
        )}
      </div>

      {/* Main simulation area */}
      <div className="flex-1 min-w-0">
        {/* Navigation controls */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={goBack}
              disabled={history.length <= 1}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M15 19l-7-7 7-7"
                />
              </svg>
              Back
            </button>
            <button
              type="button"
              onClick={reset}
              disabled={history.length <= 1}
              className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
              Reset
            </button>
          </div>

          <div className="flex items-center gap-3">
            {/* Why? toggle */}
            <button
              type="button"
              data-narrative-toggle
              onClick={toggleNarrative}
              className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium shadow-sm transition-colors ${
                narrativeOpen
                  ? "border-blue-300 bg-blue-50 text-blue-700"
                  : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
              </svg>
              Why?
            </button>

            {/* Step counter */}
            <span className="text-sm text-gray-500">
              Step {history.length} of {pathLength} on this path
            </span>
          </div>
        </div>

        {/* Breadcrumb trail */}
        <nav
          className="mb-4 flex items-center gap-1 text-sm overflow-x-auto pb-1"
          aria-label="Simulation path"
        >
          {history.map((screenId, idx) => {
            const screen = screens[screenId];
            const title = screen?.title ?? screenId.slice(0, 8);
            const isLast = idx === history.length - 1;

            return (
              <span key={`${screenId}-${idx}`} className="flex items-center gap-1 shrink-0">
                {idx > 0 && (
                  <svg
                    className="h-3.5 w-3.5 text-gray-400"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                )}
                {isLast ? (
                  <span className="font-medium text-gray-900">{title}</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => setHistory(history.slice(0, idx + 1))}
                    className="text-blue-600 hover:text-blue-800 font-medium transition-colors"
                  >
                    {title}
                  </button>
                )}
              </span>
            );
          })}
        </nav>

        {/* Current wireframe screen */}
        <WireframeScreen
          screen={currentScreen}
          warnings={
            screenWarnings.length > 0
              ? screenWarnings.map((w) => w.description)
              : undefined
          }
          warningEvidence={
            screenWarnings.length > 0
              ? screenWarnings.map((w) => ({
                  description: w.description,
                  evidence: w.evidence,
                }))
              : undefined
          }
          onToggleNarrative={toggleNarrative}
          narrativeOpen={narrativeOpen}
        />

        {/* Branch point: available paths */}
        {availablePaths.length > 0 && (
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
            <h4 className="text-sm font-semibold text-blue-800 mb-1">
              Choose your next action
            </h4>
            <p className="text-xs text-blue-600 mb-3">
              {availablePaths[0].condition || "Select a path to continue the simulation"}
            </p>
            <div className="flex flex-wrap gap-2">
              {availablePaths.map((path) => (
                <button
                  key={path.targetId}
                  type="button"
                  onClick={() => navigateTo(path.targetId)}
                  className="inline-flex items-center gap-2 rounded-md border border-blue-300 bg-white px-4 py-2 text-sm font-medium text-blue-700 shadow-sm hover:bg-blue-100 hover:border-blue-400 transition-colors"
                >
                  {path.action}
                  <svg
                    className="h-4 w-4"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 5l7 7-7 7"
                    />
                  </svg>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Linear next screen (no branch, but has a single child via branchless chain) */}
        {availablePaths.length === 0 && findLinearNext(currentScreenId, trees) && (
          <div className="mt-4 flex justify-center">
            <button
              type="button"
              onClick={() => {
                const next = findLinearNext(currentScreenId, trees);
                if (next) navigateTo(next);
              }}
              className="inline-flex items-center gap-2 rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
            >
              Continue to next screen
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M9 5l7 7-7 7"
                />
              </svg>
            </button>
          </div>
        )}

        {/* End of path */}
        {availablePaths.length === 0 && !findLinearNext(currentScreenId, trees) && history.length > 1 && (
          <div className="mt-4 rounded-lg border border-green-200 bg-green-50 p-4 text-center">
            <p className="text-sm font-medium text-green-800">
              End of this path
            </p>
            <p className="text-xs text-green-600 mt-1">
              Use the Back button or click a different branch to explore other
              paths.
            </p>
          </div>
        )}
      </div>

      {/* Narrative panel (slide-out from right) */}
      <NarrativePanel
        screen={currentScreen}
        open={narrativeOpen}
        onClose={closeNarrative}
      />
    </div>
  );
}

/* ---------- Linear chain helper ---------- */

/**
 * For branchless trees, find the next screen after currentId in the linear chain.
 * Returns null if at end or if the current screen has branch paths.
 */
function findLinearNext(
  currentId: string,
  trees: DecisionTree[],
): string | null {
  for (const tree of trees) {
    // Skip if this tree has branch paths for the current screen
    if (tree.branches.some((bp) => bp.screen_id === currentId)) {
      return null;
    }

    const screenIds = Object.keys(tree.screens);
    if (!screenIds.includes(currentId)) continue;

    // Build linear order: root first, then remaining in dict order
    const ordered = [tree.root_screen_id];
    for (const id of screenIds) {
      if (id !== tree.root_screen_id) {
        ordered.push(id);
      }
    }

    const idx = ordered.indexOf(currentId);
    if (idx >= 0 && idx < ordered.length - 1) {
      return ordered[idx + 1];
    }
  }
  return null;
}
