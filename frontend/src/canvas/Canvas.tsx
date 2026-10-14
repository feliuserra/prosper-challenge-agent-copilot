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
import { useDetectionStore } from "../detection/detectionStore";
import { canvasHeat } from "../detection/heat";
import { useAgentStore } from "../store/agentStore";
import { useProblems } from "../validation/problems";
import { connectNodes, deleteElements, handleEdgeChanges, handleNodeChanges, reconnectEdge } from "./changes";
import {
  edgeId,
  stageFrames,
  statusBadges,
  toFlowEdges,
  toFlowNodes,
  type CanvasFlowEdge,
  type CanvasFlowNode,
  type Dimensions,
} from "./derive";
import { FunctionEdge } from "./FunctionEdge";
import { NodeCard } from "./NodeCard";
import { ProblemsList } from "./ProblemsList";
import { StageCard } from "./StageCard";
import { StageFrames } from "./StageFrames";
import { TerminalNode } from "./TerminalNode";
import { canvasView } from "./view";

const nodeTypes = { agent: NodeCard, stage: StageCard, terminal: TerminalNode };
const edgeTypes = { function: FunctionEdge };
// Fit small agents at 100% instead of blowing up a single card. Room at the top for
// the buttons over the canvas and a stage frame's header, which fitting does not count.
const fitViewOptions = { maxZoom: 1, padding: { top: "80px", right: "5%", bottom: "5%", left: "5%" } } as const;
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

  // The call heatmap (#59): numbers from the call logs over the graph, never stored in it.
  const heatOn = useDetectionStore((s) => s.open);
  const detection = useDetectionStore((s) => (s.load.state === "ready" ? s.load.data : null));
  const heatOptions = useDetectionStore((s) => s.options);
  const heat = useMemo(
    () => (heatOn && detection && heatOptions ? canvasHeat(detection, heatOptions, agent, view) : null),
    [heatOn, detection, heatOptions, agent, view],
  );

  const badges = useMemo(() => statusBadges(agent, problems, view), [agent, problems, view]);
  const nodes = useMemo(
    () => toFlowNodes(agent, selection, measured, badges.nodes, activeNode, view, heat),
    [agent, selection, measured, badges, activeNode, view, heat],
  );
  const edges = useMemo(
    () => toFlowEdges(agent, selection, badges.edges, activeEdge, measured, view, heat),
    [agent, selection, badges, activeEdge, measured, view, heat],
  );
  const frames = useMemo(() => stageFrames(agent, measured, view), [agent, measured, view]);
  const selectedStage = selection?.kind === "stage" ? selection.name : null;

  // Fit the view after Tidy layout or collapsing stages, once every card shown has
  // been measured: a stage card that has just appeared has no size until then.
  const fitPending = useRef(false);
  // The issues panel takes the canvas's right side (#59): fit the graph to what is left.
  // Before the fit below, which then runs in the same commit.
  const heatWas = useRef(heatOn);
  useEffect(() => {
    if (heatWas.current !== heatOn) fitPending.current = true;
    heatWas.current = heatOn;
  }, [heatOn]);
  useEffect(() => {
    if (!fitPending.current || !nodes.every((n) => n.measured)) return;
    fitPending.current = false;
    void fitView({ ...fitViewOptions, duration: 300 });
  }, [nodes, fitView]);

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
  const onEdgesChange = useCallback(
    (changes: EdgeChange<CanvasFlowEdge>[]) => handleEdgeChanges(changes, viewRef.current),
    [],
  );
  const onConnect = useCallback((connection: Connection) => connectNodes(connection, viewRef.current), []);
  const onReconnect = useCallback(
    (edge: CanvasFlowEdge, connection: Connection) => reconnectEdge(edge, connection, viewRef.current),
    [],
  );

  const onBeforeDelete: OnBeforeDelete<CanvasFlowNode, CanvasFlowEdge> = useCallback(async ({ nodes }) => {
    const start = store().agent?.initial_node;
    if (nodes.some((n) => n.id === start)) {
      setNotice(`'${start}' is the start node. Choose another start node before deleting it.`);
      return false;
    }
    return true;
  }, []);

  const onDelete: OnDelete<CanvasFlowNode, CanvasFlowEdge> = useCallback((deleted) => {
    const [error] = deleteElements(deleted);
    if (error) setNotice(error);
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

  function refit() {
    fitPending.current = true;
  }

  return (
    <div className="canvas">
      <div className={connecting ? "canvas-flow connecting" : "canvas-flow"} ref={wrapper}>
        <ReactFlow<CanvasFlowNode, CanvasFlowEdge>
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
            <button
              aria-pressed={heatOn}
              className={heatOn ? "pressed" : undefined}
              onClick={() => void useDetectionStore.getState().setOpen(!heatOn)}
              title="Tint the graph with numbers from the call logs, and list the issues found in them"
            >
              Call heatmap
            </button>
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
