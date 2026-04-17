import type { DecisionTree, WorkflowScreen, BranchPoint } from "../types";

/* ---------- Tree navigation helpers ---------- */

/** Build adjacency map: screen_id -> list of { action, targetId } */
function buildAdjacency(
  branches: BranchPoint[],
): Map<string, Array<{ action: string; targetId: string }>> {
  const adj = new Map<string, Array<{ action: string; targetId: string }>>();
  for (const bp of branches) {
    const paths: Array<{ action: string; targetId: string }> = [];
    for (const [action, targetId] of Object.entries(bp.paths)) {
      paths.push({ action, targetId });
    }
    adj.set(bp.screen_id, paths);
  }
  return adj;
}

/** Get all screen IDs reachable from root. */
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

/* ---------- Tree node ---------- */

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

/* ---------- Main ProgressTracker component ---------- */

interface ProgressTrackerProps {
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen>;
  visitedScreens: Set<string>;
  currentScreenId: string;
  pathScreenIds: Set<string>;
  onJump: (screenId: string) => void;
}

export default function ProgressTracker({
  trees,
  screens,
  visitedScreens,
  currentScreenId,
  pathScreenIds,
  onJump,
}: ProgressTrackerProps) {
  const allBranches = trees.flatMap((t) => t.branches);
  const adjacency = buildAdjacency(allBranches);

  const totalScreens =
    trees.length === 0
      ? 0
      : getReachableScreens(trees[0].root_screen_id, adjacency).size;

  const visitedCount = visitedScreens.size;
  const percentage =
    totalScreens > 0 ? Math.round((visitedCount / totalScreens) * 100) : 0;

  return (
    <div className="w-56 shrink-0 rounded-lg border border-gray-200 bg-white p-3 overflow-y-auto max-h-[700px]">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Decision Tree
        </h3>
        <span className="text-[10px] text-gray-400">
          {visitedCount}/{totalScreens}
        </span>
      </div>

      {/* Progress bar */}
      <div className="mb-3">
        <div className="h-1.5 w-full rounded-full bg-gray-100">
          <div
            className="h-1.5 rounded-full bg-blue-500 transition-all"
            style={{ width: `${percentage}%` }}
          />
        </div>
        <p className="text-[10px] text-gray-400 mt-1">
          Explored {visitedCount} of {totalScreens} screens ({percentage}%)
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
            onJump={onJump}
            depth={0}
            maxDepth={10}
          />
        ))}
      </div>

      {/* Unvisited hint */}
      {visitedCount < totalScreens && (
        <div className="mt-3 rounded bg-amber-50 px-2 py-1.5 text-[10px] text-amber-700">
          <span className="font-medium">{totalScreens - visitedCount}</span>{" "}
          screens left to explore. Try different branches!
        </div>
      )}
    </div>
  );
}
