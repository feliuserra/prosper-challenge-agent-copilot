import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useConnection,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type OnBeforeDelete,
  type OnDelete,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { nearestFreeSpot, NODE_HEIGHT, NODE_WIDTH } from "../agent/layout";
import { stagesOf } from "../agent/stages";
import { useCallStore } from "../call/callStore";
import { useAgentStore } from "../store/agentStore";
import { useProblems } from "../validation/problems";
import { handleEdgeChanges, handleNodeChanges } from "./changes";
import {
  edgeId,
  parseEdgeId,
  stageFrames,
  statusBadges,
  toFlowEdges,
  toFlowNodes,
  type AgentFlowEdge,
  type CanvasFlowNode,
  type Dimensions,
} from "./derive";
import { FunctionEdge } from "./FunctionEdge";
import { NodeCard } from "./NodeCard";
import { ProblemsList } from "./ProblemsList";
import { StageCard } from "./StageCard";
import { StageFrames } from "./StageFrames";
import { canvasView } from "./view";

const nodeTypes = { agent: NodeCard, stage: StageCard };
const edgeTypes = { function: FunctionEdge };
// Fit small agents at 100% instead of blowing up a single card.
const fitViewOptions = { maxZoom: 1 };
const store = () => useAgentStore.getState();

export function Canvas() {
  const agentId = useAgentStore((s) => s.agentId);
  const hasAgent = useAgentStore((s) => s.agent !== null);
  if (!hasAgent) return <p className="muted empty">No agent open.</p>;
  // A fresh React Flow per agent: its own measurements, and fit view on open.
  return (
    <ReactFlowProvider key={agentId}>
      <Flow />
    </ReactFlowProvider>
  );
}

function Flow() {
  const agent = useAgentStore((s) => s.agent)!;
  const agentId = useAgentStore((s) => s.agentId);
  const selection = useAgentStore((s) => s.selection);
  const collapsed = useAgentStore((s) => s.collapsed);
  const problems = useProblems();
  // Where a test call of this agent is; another agent's call is not shown.
  const live = useCallStore((s) => (s.live && s.live.agentId === agentId ? s.live : null));
  const activeNode = live?.node ?? null;
  const activeEdge = live?.edge ? edgeId(live.edge.source, live.edge.function) : null;
  const [measured, setMeasured] = useState<Record<string, Dimensions>>({});
  const [notice, setNotice] = useState("");
  const wrapper = useRef<HTMLDivElement>(null);
  const { fitView, screenToFlowPosition } = useReactFlow();
  // Handles are hidden until a card is hovered; while a connection is dragged, all show.
  const connecting = useConnection((c) => c.inProgress);

  // What is shown with the collapsed stages folded (#51). The change handlers read
  // the latest one through a ref, so they do not change identity on every render.
  const view = useMemo(() => canvasView(agent, collapsed, measured), [agent, collapsed, measured]);
  const viewRef = useRef(view);
  viewRef.current = view;
  const hasStages = useMemo(() => stagesOf(agent).length > 0, [agent]);

  const badges = useMemo(() => statusBadges(agent, problems, view), [agent, problems, view]);
  const nodes = useMemo(
    () => toFlowNodes(agent, selection, measured, badges.nodes, activeNode, view),
    [agent, selection, measured, badges, activeNode, view],
  );
  const edges = useMemo(
    () => toFlowEdges(agent, selection, badges.edges, activeEdge, measured, view),
    [agent, selection, badges, activeEdge, measured, view],
  );
  const frames = useMemo(() => stageFrames(agent, measured, view), [agent, measured, view]);
  const selectedStage = selection?.kind === "stage" ? selection.name : null;

  // Notices (e.g. a blocked delete) fade after a few seconds.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const onNodesChange = useCallback(
    (changes: NodeChange<CanvasFlowNode>[]) =>
      handleNodeChanges(changes, (id, size) => setMeasured((m) => ({ ...m, [id]: size })), viewRef.current),
    [],
  );
  const onEdgesChange = useCallback((changes: EdgeChange<AgentFlowEdge>[]) => handleEdgeChanges(changes), []);

  // Edges join nodes, never a collapsed stage's card (its handles do not connect; this is a guard).
  const isCard = (id: string) => viewRef.current.cardStage.has(id);

  const onConnect = useCallback(({ source, target }: Connection) => {
    if (!isCard(source) && !isCard(target)) store().connect(source, target);
  }, []);

  const onReconnect = useCallback((edge: AgentFlowEdge, { source, target }: Connection) => {
    if (source !== edge.source || target === edge.target || isCard(target) || !edge.data) return;
    // By the edge's id: `edge.source` is a card when the edge leaves a collapsed stage.
    store().updateEdge(parseEdgeId(edge.id).source, edge.data.function, { target });
  }, []);

  const onBeforeDelete: OnBeforeDelete<CanvasFlowNode, AgentFlowEdge> = useCallback(async ({ nodes }) => {
    const start = store().agent?.initial_node;
    if (nodes.some((n) => n.id === start)) {
      setNotice(`'${start}' is the start node. Choose another start node before deleting it.`);
      return false;
    }
    return true;
  }, []);

  const onDelete: OnDelete<CanvasFlowNode, AgentFlowEdge> = useCallback(({ nodes, edges }) => {
    // Stage cards are not deletable, so these are nodes.
    const deleted = new Set(nodes.map((n) => n.id));
    for (const node of nodes) {
      const result = store().deleteNode(node.id);
      if (!result.ok) setNotice(result.error);
    }
    // Edges into or out of a deleted node went with it (deleteNode cascades).
    for (const edge of edges) {
      const { source, function: fn } = parseEdgeId(edge.id);
      if (!deleted.has(source) && !deleted.has(edge.target)) store().deleteEdge(source, fn);
    }
  }, []);

  // At the centre of the view, or the nearest free spot that is still in view.
  function addNode() {
    const box = wrapper.current!.getBoundingClientRect();
    // A margin keeps the card off the edges of the view.
    const topLeft = screenToFlowPosition({ x: box.left + 24, y: box.top + 24 });
    const bottomRight = screenToFlowPosition({ x: box.right - 24, y: box.bottom - 24 });
    const visible = { x: topLeft.x, y: topLeft.y, width: bottomRight.x - topLeft.x, height: bottomRight.y - topLeft.y };
    const centre = {
      x: visible.x + visible.width / 2 - NODE_WIDTH / 2,
      y: visible.y + visible.height / 2 - NODE_HEIGHT / 2,
    };
    // Found among what is shown (nodes and stage cards), then stored as if no stage were collapsed.
    const taken = nodes.map((n) => n.position);
    store().addNode(viewRef.current.stored(nearestFreeSpot(centre, taken, visible)));
  }

  function tidy() {
    store().tidyLayout();
    refit();
  }

  function collapseAll(collapse: boolean) {
    store().setAllCollapsed(collapse);
    refit();
  }

  // After React Flow has the new positions.
  function refit() {
    requestAnimationFrame(() => void fitView({ ...fitViewOptions, duration: 300 }));
  }

  return (
    <div className="canvas">
      <div className={connecting ? "canvas-flow connecting" : "canvas-flow"} ref={wrapper}>
        <ReactFlow<CanvasFlowNode, AgentFlowEdge>
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onReconnect={onReconnect}
          onBeforeDelete={onBeforeDelete}
          onDelete={onDelete}
          // React Flow clears its own selection on a pane click; a stage is not one of its elements.
          onPaneClick={() => selectedStage && store().select(null)}
          deleteKeyCode={["Backspace", "Delete"]}
          reconnectRadius={12}
          // The selected edge (and its reconnect knob) draws above the others,
          // which may end at the same handle.
          elevateEdgesOnSelect
          // One selected element at a time, like the store's selection.
          multiSelectionKeyCode={null}
          selectionKeyCode={null}
          minZoom={0.2}
          fitView
          fitViewOptions={fitViewOptions}
        >
          <Panel position="top-left" className="canvas-actions">
            <button onClick={addNode}>Add node</button>
            <button onClick={tidy} title="Lay out all nodes again">
              Tidy layout
            </button>
            {hasStages && (
              <>
                <button onClick={() => collapseAll(true)} title="Show each stage as one card">
                  Collapse stages
                </button>
                <button onClick={() => collapseAll(false)} title="Show every node">
                  Expand stages
                </button>
              </>
            )}
          </Panel>
          {notice && (
            <Panel position="bottom-center" className="notice" role="status">
              {notice}
            </Panel>
          )}
          <Controls showInteractive={false} fitViewOptions={fitViewOptions} />
          <Background color="#d5d9de" gap={16} size={1} />
          <StageFrames frames={frames} selected={selectedStage} />
        </ReactFlow>
      </div>
      {/* Below the graph, not over it, so it never hides a node or its badge. */}
      <ProblemsList problems={problems} />
    </div>
  );
}
