import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type OnBeforeDelete,
  type OnDelete,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { nearestFreeSpot, NODE_HEIGHT, NODE_WIDTH } from "../agent/layout";
import { useAgentStore } from "../store/agentStore";
import { handleEdgeChanges, handleNodeChanges } from "./changes";
import { toFlowEdges, toFlowNodes, type AgentFlowEdge, type AgentFlowNode, type Dimensions } from "./derive";
import { FunctionEdge } from "./FunctionEdge";
import { NodeCard } from "./NodeCard";

const nodeTypes = { agent: NodeCard };
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
  const selection = useAgentStore((s) => s.selection);
  const [measured, setMeasured] = useState<Record<string, Dimensions>>({});
  const [notice, setNotice] = useState("");
  const wrapper = useRef<HTMLDivElement>(null);
  const { fitView, screenToFlowPosition } = useReactFlow();

  const nodes = useMemo(() => toFlowNodes(agent, selection, measured), [agent, selection, measured]);
  const edges = useMemo(() => toFlowEdges(agent, selection), [agent, selection]);

  // Notices (e.g. a blocked delete) fade after a few seconds.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4000);
    return () => clearTimeout(timer);
  }, [notice]);

  const onNodesChange = useCallback(
    (changes: NodeChange<AgentFlowNode>[]) =>
      handleNodeChanges(changes, (name, size) => setMeasured((m) => ({ ...m, [name]: size }))),
    [],
  );
  const onEdgesChange = useCallback((changes: EdgeChange<AgentFlowEdge>[]) => handleEdgeChanges(changes), []);

  const onConnect = useCallback(({ source, target }: Connection) => {
    store().connect(source, target);
  }, []);

  const onReconnect = useCallback((edge: AgentFlowEdge, { source, target }: Connection) => {
    if (source !== edge.source || target === edge.target || !edge.data) return;
    store().updateEdge(edge.source, edge.data.function, { target });
  }, []);

  const onBeforeDelete: OnBeforeDelete<AgentFlowNode, AgentFlowEdge> = useCallback(async ({ nodes }) => {
    const start = store().agent?.initial_node;
    if (nodes.some((n) => n.id === start)) {
      setNotice(`'${start}' is the start node. Choose another start node before deleting it.`);
      return false;
    }
    return true;
  }, []);

  const onDelete: OnDelete<AgentFlowNode, AgentFlowEdge> = useCallback(({ nodes, edges }) => {
    const deleted = new Set(nodes.map((n) => n.id));
    for (const node of nodes) {
      const result = store().deleteNode(node.id);
      if (!result.ok) setNotice(result.error);
    }
    // Edges into or out of a deleted node went with it (deleteNode cascades).
    for (const edge of edges) {
      if (!deleted.has(edge.source) && !deleted.has(edge.target) && edge.data) {
        store().deleteEdge(edge.source, edge.data.function);
      }
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
    const taken = store().agent!.nodes.flatMap((n) => (n.ui ? [n.ui] : []));
    store().addNode(nearestFreeSpot(centre, taken, visible));
  }

  function tidy() {
    store().tidyLayout();
    // After React Flow has the new positions.
    requestAnimationFrame(() => void fitView({ ...fitViewOptions, duration: 300 }));
  }

  return (
    <div className="canvas" ref={wrapper}>
      <ReactFlow<AgentFlowNode, AgentFlowEdge>
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
        deleteKeyCode={["Backspace", "Delete"]}
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
        </Panel>
        {notice && (
          <Panel position="bottom-center" className="notice" role="status">
            {notice}
          </Panel>
        )}
        <Controls showInteractive={false} fitViewOptions={fitViewOptions} />
        <MiniMap pannable zoomable />
        <Background />
      </ReactFlow>
    </div>
  );
}
