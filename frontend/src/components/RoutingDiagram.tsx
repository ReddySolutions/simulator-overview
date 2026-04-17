import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type NodeTypes,
  Position,
} from "@xyflow/react";
import dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";
import type { DecisionTree, WalkthroughWarning, WorkflowScreen } from "../types";
import GraphNodePreview, {
  type GraphNodeData,
  computeNodeSize,
} from "./GraphNodePreview";

type PreviewNode = Node<GraphNodeData>;

/* ---------- Dagre layout ---------- */

function getLayoutedElements(
  nodes: PreviewNode[],
  edges: Edge[],
): { nodes: PreviewNode[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 60 });

  for (const node of nodes) {
    const size = computeNodeSize(node.data.screen.ui_elements.length);
    g.setNode(node.id, { width: size.width, height: size.height });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    const size = computeNodeSize(node.data.screen.ui_elements.length);
    return {
      ...node,
      position: {
        x: pos.x - size.width / 2,
        y: pos.y - size.height / 2,
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });

  return { nodes: layoutedNodes, edges };
}

/* ---------- Build graph from decision trees ---------- */

function buildGraph(
  trees: DecisionTree[],
  screens: Record<string, WorkflowScreen>,
  selectedScreenId: string | null,
  warningScreenIds: Set<string>,
  visitedScreens: Set<string>,
): { nodes: PreviewNode[]; edges: Edge[] } {
  const nodeMap = new Map<string, PreviewNode>();
  const edgeSet = new Set<string>();
  const edges: Edge[] = [];

  for (const tree of trees) {
    const adjacency = new Map<string, string[]>();
    for (const bp of tree.branches) {
      adjacency.set(bp.screen_id, Object.values(bp.paths));
    }

    function countSteps(screenId: string, visited: Set<string>): number {
      if (visited.has(screenId)) return 0;
      visited.add(screenId);
      let count = 1;
      for (const child of adjacency.get(screenId) ?? []) {
        count += countSteps(child, visited);
      }
      return count;
    }

    for (const screenId of Object.keys(tree.screens)) {
      if (nodeMap.has(screenId)) continue;
      const screen = screens[screenId] ?? tree.screens[screenId];
      if (!screen) continue;

      nodeMap.set(screenId, {
        id: screenId,
        type: "graphNodePreview",
        position: { x: 0, y: 0 },
        data: {
          screen,
          stepCount: countSteps(screenId, new Set()),
          selected: screenId === selectedScreenId,
          hasWarning: warningScreenIds.has(screenId),
          visited: visitedScreens.has(screenId),
        },
      });
    }

    for (const bp of tree.branches) {
      for (const [action, targetId] of Object.entries(bp.paths)) {
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
          labelStyle: { fontSize: 10, fill: "#64748b" },
          labelBgStyle: { fill: "#f8fafc", fillOpacity: 0.9 },
          labelBgPadding: [4, 2] as [number, number],
        });
      }
    }

    // For branchless trees, chain screens linearly from root
    if (tree.branches.length === 0) {
      const screenIds = Object.keys(tree.screens);
      if (screenIds.length > 1) {
        const ordered = [tree.root_screen_id];
        const remaining = new Set(
          screenIds.filter((id) => id !== tree.root_screen_id),
        );
        for (const id of screenIds) {
          if (remaining.has(id)) {
            ordered.push(id);
            remaining.delete(id);
          }
        }
        for (let i = 0; i < ordered.length - 1; i++) {
          const edgeId = `${ordered[i]}->${ordered[i + 1]}`;
          if (!edgeSet.has(edgeId)) {
            edgeSet.add(edgeId);
            edges.push({
              id: edgeId,
              source: ordered[i],
              target: ordered[i + 1],
              type: "default",
              style: { strokeWidth: 2, stroke: "#94a3b8" },
            });
          }
        }
      }
    }
  }

  return getLayoutedElements(Array.from(nodeMap.values()), edges);
}

/* ---------- Tooltip on hover ---------- */

function NodeTooltip({
  screen,
  position,
}: {
  screen: WorkflowScreen;
  position: { x: number; y: number };
}) {
  const firstRef = screen.source_refs[0];

  return (
    <div
      className="fixed z-50 max-w-xs rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg pointer-events-none"
      style={{ left: position.x + 12, top: position.y - 8 }}
    >
      <p className="font-medium mb-1">{screen.title}</p>
      {screen.narrative?.what && (
        <p className="text-gray-300 mb-1 line-clamp-3">
          {screen.narrative.what}
        </p>
      )}
      {firstRef && (
        <p className="text-gray-400 text-[10px]">
          Source: {firstRef.reference}
        </p>
      )}
    </div>
  );
}

/* ---------- Main component ---------- */

const nodeTypes: NodeTypes = {
  graphNodePreview: GraphNodePreview,
};

interface RoutingDiagramProps {
  trees: DecisionTree[];
  screens: Record<string, WorkflowScreen>;
  warnings?: WalkthroughWarning[];
  visitedScreens?: Set<string>;
  onSelectScreen?: (screenId: string) => void;
}

export default function RoutingDiagram({
  trees,
  screens,
  warnings = [],
  visitedScreens = new Set(),
  onSelectScreen,
}: RoutingDiagramProps) {
  const [selectedScreenId, setSelectedScreenId] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<{
    screen: WorkflowScreen;
    position: { x: number; y: number };
  } | null>(null);

  const warningScreenIds = useMemo(
    () => new Set(warnings.map((w) => w.screen_id)),
    [warnings],
  );

  const { nodes, edges } = useMemo(
    () => buildGraph(trees, screens, selectedScreenId, warningScreenIds, visitedScreens),
    [trees, screens, selectedScreenId, warningScreenIds, visitedScreens],
  );

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedScreenId(node.id);
      onSelectScreen?.(node.id);
    },
    [onSelectScreen],
  );

  const onNodeMouseEnter: NodeMouseHandler = useCallback(
    (event, node) => {
      const screen = screens[node.id];
      if (screen) {
        setTooltip({
          screen,
          position: { x: event.clientX, y: event.clientY },
        });
      }
    },
    [screens],
  );

  const onNodeMouseLeave = useCallback(() => {
    setTooltip(null);
  }, []);

  if (trees.length === 0) {
    return (
      <div className="flex items-center justify-center h-[500px] text-gray-400 text-sm">
        No decision trees to display.
      </div>
    );
  }

  return (
    <div className="relative h-[600px] w-full rounded-lg border border-gray-200 bg-gray-50">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={(n) => {
            const data = n.data as GraphNodeData;
            if (data?.hasWarning) return "#f87171";
            if (data?.selected) return "#2563eb";
            return data?.screen?.evidence_tier === "observed"
              ? "#60a5fa"
              : "#d1d5db";
          }}
          pannable
          zoomable
        />
      </ReactFlow>

      {tooltip && (
        <NodeTooltip screen={tooltip.screen} position={tooltip.position} />
      )}
    </div>
  );
}
