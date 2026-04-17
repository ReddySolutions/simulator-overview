import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type NodeTypes,
  Position,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import type { DecisionTree, WorkflowScreen, BranchPoint } from "../types";

const NODE_WIDTH = 260;
const NODE_HEIGHT = 180;

/* ---------- Subtree extraction ---------- */

/** Collect all descendant screen IDs from a root, using branch adjacency. */
function getSubtreeIds(
  rootId: string,
  branches: BranchPoint[],
): Set<string> {
  const adjacency = new Map<string, string[]>();
  for (const bp of branches) {
    adjacency.set(bp.screen_id, Object.values(bp.paths));
  }

  const visited = new Set<string>();
  const queue = [rootId];
  while (queue.length > 0) {
    const current = queue.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    for (const child of adjacency.get(current) ?? []) {
      queue.push(child);
    }
  }
  return visited;
}

/** Check if a screen has children in the branch graph. */
function hasChildren(
  screenId: string,
  branches: BranchPoint[],
): boolean {
  return branches.some(
    (bp) => bp.screen_id === screenId && Object.keys(bp.paths).length > 0,
  );
}

/** Find the parent screen ID for a given screen in the branch graph. */
function findParent(
  screenId: string,
  branches: BranchPoint[],
): string | null {
  for (const bp of branches) {
    for (const targetId of Object.values(bp.paths)) {
      if (targetId === screenId) return bp.screen_id;
    }
  }
  return null;
}

/* ---------- Detailed node data ---------- */

interface DetailedNodeData extends Record<string, unknown> {
  screen: WorkflowScreen;
  hasChildren: boolean;
  selected: boolean;
}

type DetailedNode = Node<DetailedNodeData>;

/* ---------- Detailed node component ---------- */

function DetailedNodeComponent({ data }: { data: DetailedNodeData }) {
  const { screen, hasChildren: expandable, selected } = data;
  const isObserved = screen.evidence_tier === "observed";

  return (
    <div
      className={`rounded-lg bg-white px-3 py-2.5 shadow-sm w-[260px] transition-all ${
        isObserved
          ? "border-2 border-blue-400"
          : "border-2 border-dashed border-gray-300"
      } ${selected ? "ring-2 ring-blue-600 ring-offset-2" : "hover:shadow-md"} ${
        expandable ? "cursor-pointer" : "cursor-default"
      }`}
    >
      {/* Title row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <h3 className="text-sm font-semibold text-gray-800 leading-tight line-clamp-2 flex-1">
          {screen.title}
        </h3>
        <div className="flex items-center gap-1 shrink-0">
          <span
            className={`inline-block w-2 h-2 rounded-full ${
              isObserved ? "bg-blue-400" : "bg-gray-300"
            }`}
          />
          <span className="text-[10px] text-gray-400">
            {isObserved ? "observed" : "mentioned"}
          </span>
        </div>
      </div>

      {/* UI elements list */}
      {screen.ui_elements.length > 0 && (
        <div className="mb-2">
          <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wider mb-1">
            UI Elements
          </p>
          <div className="flex flex-wrap gap-1 max-h-[48px] overflow-hidden">
            {screen.ui_elements.slice(0, 12).map((el, i) => (
              <span
                key={`${el.element_type}-${el.label}-${i}`}
                className="inline-flex items-center gap-0.5 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600"
              >
                <span className="font-mono text-gray-400">
                  {el.element_type.slice(0, 3)}
                </span>
                <span className="truncate max-w-[80px]">{el.label}</span>
              </span>
            ))}
            {screen.ui_elements.length > 12 && (
              <span className="text-[10px] text-gray-400">
                +{screen.ui_elements.length - 12} more
              </span>
            )}
          </div>
        </div>
      )}

      {/* Narrative summary */}
      {screen.narrative && (
        <div className="mb-2">
          <p className="text-[10px] font-medium text-gray-500 uppercase tracking-wider mb-0.5">
            Summary
          </p>
          <p className="text-[10px] text-gray-600 line-clamp-2 leading-relaxed">
            {screen.narrative.what}
          </p>
        </div>
      )}

      {/* Source refs */}
      {screen.source_refs.length > 0 && (
        <div className="border-t border-gray-100 pt-1.5">
          <p className="text-[9px] text-gray-400 truncate">
            {screen.source_refs[0].reference}
            {screen.source_refs.length > 1 && (
              <span> +{screen.source_refs.length - 1} more</span>
            )}
          </p>
        </div>
      )}

      {/* Drill-down indicator */}
      {expandable && (
        <div className="mt-1.5 flex items-center gap-1 text-blue-500">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
          <span className="text-[10px] font-medium">Click to drill down</span>
        </div>
      )}
    </div>
  );
}

/* ---------- Dagre layout ---------- */

function getLayoutedElements(
  nodes: DetailedNode[],
  edges: Edge[],
): { nodes: DetailedNode[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 50, ranksep: 80 });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: {
        x: pos.x - NODE_WIDTH / 2,
        y: pos.y - NODE_HEIGHT / 2,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });

  return { nodes: layoutedNodes, edges };
}

/* ---------- Build subtree graph ---------- */

function buildSubtreeGraph(
  rootScreenId: string,
  trees: DecisionTree[],
  screens: Record<string, WorkflowScreen>,
  allBranches: BranchPoint[],
  selectedId: string | null,
): { nodes: DetailedNode[]; edges: Edge[] } {
  const subtreeIds = getSubtreeIds(rootScreenId, allBranches);
  const nodes: DetailedNode[] = [];
  const edges: Edge[] = [];
  const edgeSet = new Set<string>();

  for (const screenId of subtreeIds) {
    const screen =
      screens[screenId] ??
      trees.reduce<WorkflowScreen | undefined>(
        (found, t) => found ?? t.screens[screenId],
        undefined,
      );
    if (!screen) continue;

    nodes.push({
      id: screenId,
      type: "detailedNode",
      position: { x: 0, y: 0 },
      data: {
        screen,
        hasChildren: hasChildren(screenId, allBranches),
        selected: screenId === selectedId,
      },
    });
  }

  for (const bp of allBranches) {
    if (!subtreeIds.has(bp.screen_id)) continue;
    for (const [action, targetId] of Object.entries(bp.paths)) {
      if (!subtreeIds.has(targetId)) continue;
      const edgeId = `${bp.screen_id}->${targetId}`;
      if (edgeSet.has(edgeId)) continue;
      edgeSet.add(edgeId);
      edges.push({
        id: edgeId,
        source: bp.screen_id,
        target: targetId,
        label: action,
        type: "default",
        style: { strokeWidth: 2, stroke: "#94a3b8" },
        labelStyle: { fontSize: 11, fill: "#64748b" },
        labelBgStyle: { fill: "#f8fafc", fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
      });
    }
  }

  // For branchless subtrees (single child chains), link linearly
  if (edges.length === 0 && nodes.length > 1) {
    const ids = [rootScreenId, ...Array.from(subtreeIds).filter((id) => id !== rootScreenId)];
    for (let i = 0; i < ids.length - 1; i++) {
      const edgeId = `${ids[i]}->${ids[i + 1]}`;
      edges.push({
        id: edgeId,
        source: ids[i],
        target: ids[i + 1],
        type: "default",
        style: { strokeWidth: 2, stroke: "#94a3b8" },
      });
    }
  }

  return getLayoutedElements(nodes, edges);
}

/* ---------- Collect all branches from all trees ---------- */

function getAllBranches(trees: DecisionTree[]): BranchPoint[] {
  return trees.flatMap((t) => t.branches);
}

/* ---------- Breadcrumb item ---------- */

interface BreadcrumbItem {
  screenId: string;
  title: string;
}

/* ---------- Node types ---------- */

const nodeTypes: NodeTypes = {
  detailedNode: DetailedNodeComponent,
};

/* ---------- Main component ---------- */

interface SubDiagramProps {
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen>;
  initialScreenId: string;
  onBack: () => void;
}

export default function SubDiagram({
  trees,
  screens,
  initialScreenId,
  onBack,
}: SubDiagramProps) {
  const [drillStack, setDrillStack] = useState<string[]>([initialScreenId]);
  const currentRootId = drillStack[drillStack.length - 1];
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const allBranches = useMemo(() => getAllBranches(trees), [trees]);

  // Build breadcrumb path
  const breadcrumbs = useMemo((): BreadcrumbItem[] => {
    return drillStack.map((screenId) => {
      const screen =
        screens[screenId] ??
        trees.reduce<WorkflowScreen | undefined>(
          (found, t) => found ?? t.screens[screenId],
          undefined,
        );
      return {
        screenId,
        title: screen?.title ?? screenId.slice(0, 8),
      };
    });
  }, [drillStack, screens, trees]);

  const { nodes, edges } = useMemo(
    () =>
      buildSubtreeGraph(currentRootId, trees, screens, allBranches, selectedId),
    [currentRootId, trees, screens, allBranches, selectedId],
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedId(node.id);
      // If the clicked node has children and isn't the current root, drill down
      if (
        hasChildren(node.id, allBranches) &&
        node.id !== currentRootId
      ) {
        setDrillStack((prev) => [...prev, node.id]);
        setSelectedId(null);
      }
    },
    [allBranches, currentRootId],
  );

  const navigateToBreadcrumb = useCallback((index: number) => {
    setDrillStack((prev) => prev.slice(0, index + 1));
    setSelectedId(null);
  }, []);

  const goBack = useCallback(() => {
    if (drillStack.length > 1) {
      setDrillStack((prev) => prev.slice(0, -1));
      setSelectedId(null);
    } else {
      onBack();
    }
  }, [drillStack.length, onBack]);

  // Find parent of the initial screen for the "Root" breadcrumb
  const rootParent = useMemo(() => {
    return findParent(initialScreenId, allBranches);
  }, [initialScreenId, allBranches]);

  return (
    <div className="space-y-3">
      {/* Navigation bar */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={goBack}
          className="inline-flex items-center gap-1.5 rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 transition-colors"
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

        {/* Breadcrumbs */}
        <nav className="flex items-center gap-1.5 text-sm" aria-label="Breadcrumb">
          <button
            type="button"
            onClick={onBack}
            className="text-blue-600 hover:text-blue-800 font-medium transition-colors"
          >
            {rootParent ? "..." : "Root"}
          </button>

          {breadcrumbs.map((crumb, index) => (
            <span key={crumb.screenId} className="flex items-center gap-1.5">
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
              {index === breadcrumbs.length - 1 ? (
                <span className="font-medium text-gray-900">
                  {crumb.title}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => navigateToBreadcrumb(index)}
                  className="text-blue-600 hover:text-blue-800 font-medium transition-colors"
                >
                  {crumb.title}
                </button>
              )}
            </span>
          ))}
        </nav>
      </div>

      {/* Sub-diagram */}
      <div className="relative h-[600px] w-full rounded-lg border border-gray-200 bg-gray-50">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.2}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} size={1} color="#e2e8f0" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}
