<script lang="ts">
  import { untrack } from "svelte";
  import {
    Background,
    Controls,
    SvelteFlow,
    type Edge,
    type Node,
    type NodeTypes,
  } from "@xyflow/svelte";
  import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";
  import type { Workflow } from "$lib/workflow-tree";
  import WorkflowContainerNode from "./WorkflowContainerNode.svelte";
  import StepNode from "./StepNode.svelte";

  export type FamilyWorkflow = Workflow & {
    output: string | null;
    error: string | null;
    serialization: string | null;
    output_decoded: string | null;
    error_decoded: string | null;
  };

  export type Step = {
    workflow_id: string;
    function_id: number;
    function_name: string;
    output: string | null;
    error: string | null;
    child_workflow_id: string | null;
    started_at: string | null;
    completed_at: string | null;
    serialization: string | null;
    output_decoded: string | null;
    error_decoded: string | null;
  };

  export type FlowSelection =
    | { kind: "workflow"; workflow: FamilyWorkflow }
    | { kind: "step"; step: Step }
    | null;

  let {
    family,
    steps,
    currentId,
    selection = null,
    onSelect,
  }: {
    family: FamilyWorkflow[];
    steps: Step[];
    currentId: string;
    selection?: FlowSelection;
    onSelect?: (sel: FlowSelection) => void;
  } = $props();

  const STEP_WIDTH = 220;
  const STEP_HEIGHT = 32;

  const elk = new ELK();
  const nodeTypes: NodeTypes = {
    workflow: WorkflowContainerNode,
    step: StepNode,
  };

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);

  function stepKind(s: Step): "child" | "system" | "step" {
    if (s.function_name.startsWith("DBOS.")) return "system";
    if (s.child_workflow_id) return "child";
    return "step";
  }

  function stepStatus(s: Step): "error" | "running" | "success" | null {
    if (s.error) return "error";
    if (s.started_at && !s.completed_at) return "running";
    if (s.completed_at) return "success";
    return null;
  }

  function stepNodeId(workflowId: string, functionId: number): string {
    return `${workflowId}/${functionId}`;
  }

  async function layout(family: FamilyWorkflow[], steps: Step[], currentId: string) {
    const stepsByWf = new Map<string, Step[]>();
    for (const s of steps) {
      const list = stepsByWf.get(s.workflow_id) ?? [];
      list.push(s);
      stepsByWf.set(s.workflow_id, list);
    }

    const familyIds = new Set(family.map((w) => w.workflow_id));

    // Root graph: workflows as compound containers, arranged top→down in
    // model order (family is already DFS/time-sorted on the server).
    const rootGraph: ElkNode = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "DOWN",
        "elk.hierarchyHandling": "INCLUDE_CHILDREN",
        "elk.spacing.nodeNode": "48",
        "elk.layered.spacing.nodeNodeBetweenLayers": "72",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
        "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
      },
      children: family.map((w) => {
        const wfSteps = stepsByWf.get(w.workflow_id) ?? [];
        return {
          id: w.workflow_id,
          layoutOptions: {
            "elk.algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.padding": "[top=60,left=16,right=16,bottom=16]",
            "elk.spacing.nodeNode": "16",
            "elk.layered.spacing.nodeNodeBetweenLayers": "24",
          },
          children: wfSteps.map((s) => ({
            id: stepNodeId(s.workflow_id, s.function_id),
            width: STEP_WIDTH,
            height: STEP_HEIGHT,
          })),
          // Sequential edges: step N → step N+1 inside each container.
          edges: wfSteps.slice(1).map((s, i) => {
            const prev = wfSteps[i];
            return {
              id: `seq:${s.workflow_id}:${prev.function_id}->${s.function_id}`,
              sources: [stepNodeId(prev.workflow_id, prev.function_id)],
              targets: [stepNodeId(s.workflow_id, s.function_id)],
            };
          }),
        };
      }),
      // Cross-hierarchy spawn edges: step with child_workflow_id → child
      // workflow container. (Skip if the child isn't part of this family —
      // shouldn't happen, but be defensive.)
      edges: steps
        .filter(
          (s) =>
            s.child_workflow_id !== null &&
            stepKind(s) === "child" &&
            familyIds.has(s.child_workflow_id),
        )
        .map((s) => ({
          id: `spawn:${stepNodeId(s.workflow_id, s.function_id)}->${s.child_workflow_id}`,
          sources: [stepNodeId(s.workflow_id, s.function_id)],
          targets: [s.child_workflow_id as string],
        })),
    };

    const laidOut = await elk.layout(rootGraph);

    const nextNodes: Node[] = [];
    const nextEdges: Edge[] = [];

    for (const wfNode of laidOut.children ?? []) {
      const w = family.find((f) => f.workflow_id === wfNode.id)!;
      nextNodes.push({
        id: wfNode.id,
        type: "workflow",
        position: { x: wfNode.x ?? 0, y: wfNode.y ?? 0 },
        data: { workflow: w, isCurrent: w.workflow_id === currentId },
        width: wfNode.width,
        height: wfNode.height,
        draggable: false,
        connectable: false,
        selectable: true,
        style: `width: ${wfNode.width}px; height: ${wfNode.height}px;`,
      });
      for (const stepNode of wfNode.children ?? []) {
        const [, fnStr] = stepNode.id.split("/");
        const fnId = Number(fnStr);
        const s = (stepsByWf.get(wfNode.id) ?? []).find((x) => x.function_id === fnId)!;
        const durationMs =
          s.started_at && s.completed_at
            ? new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()
            : null;
        nextNodes.push({
          id: stepNode.id,
          type: "step",
          parentId: wfNode.id,
          extent: "parent",
          position: { x: stepNode.x ?? 0, y: stepNode.y ?? 0 },
          data: {
            functionId: s.function_id,
            functionName: s.function_name,
            kind: stepKind(s),
            status: stepStatus(s),
            durationMs,
          },
          width: stepNode.width,
          height: stepNode.height,
          draggable: false,
          connectable: false,
          selectable: true,
        });
      }
      for (const edge of wfNode.edges ?? []) {
        nextEdges.push({
          id: edge.id,
          source: edge.sources[0],
          target: edge.targets[0],
          type: "smoothstep",
          style: "stroke: var(--color-border); stroke-width: 1px;",
        });
      }
    }
    for (const edge of laidOut.edges ?? []) {
      nextEdges.push({
        id: edge.id,
        source: edge.sources[0],
        target: edge.targets[0],
        type: "smoothstep",
        animated: true,
        style: "stroke: rgb(99 102 241 / 0.8); stroke-width: 1.5px;",
      });
    }

    nodes = nextNodes;
    edges = nextEdges;
  }

  $effect(() => {
    layout(family, steps, currentId);
  });

  function handleNodeClick({ node }: { node: Node }) {
    if (!onSelect) return;
    if (node.type === "workflow") {
      const wf = family.find((w) => w.workflow_id === node.id);
      if (wf) onSelect({ kind: "workflow", workflow: wf });
      return;
    }
    if (node.type === "step") {
      const [wfId, fnStr] = node.id.split("/");
      const fnId = Number(fnStr);
      const step = steps.find((s) => s.workflow_id === wfId && s.function_id === fnId);
      if (step) onSelect({ kind: "step", step });
    }
  }

  function handlePaneClick() {
    onSelect?.(null);
  }

  // Reflect external selection state onto the flow so the same node stays
  // visually highlighted across re-layouts. We untrack the nodes read so
  // writing nodes inside the effect doesn't re-trigger it.
  const selectedId = $derived.by(() => {
    if (!selection) return null;
    if (selection.kind === "workflow") return selection.workflow.workflow_id;
    return `${selection.step.workflow_id}/${selection.step.function_id}`;
  });
  $effect(() => {
    const sid = selectedId;
    untrack(() => {
      const current = nodes;
      let changed = false;
      const next = current.map((n) => {
        const shouldSelect = n.id === sid;
        if ((n.selected ?? false) === shouldSelect) return n;
        changed = true;
        return { ...n, selected: shouldSelect };
      });
      if (changed) nodes = next;
    });
  });
</script>

<div class="border-border bg-card h-full w-full overflow-hidden rounded-lg border">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    fitView
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable
    zoomOnDoubleClick={false}
    minZoom={0.2}
    proOptions={{ hideAttribution: true }}
    onnodeclick={handleNodeClick}
    onpaneclick={handlePaneClick}
  >
    <Background />
    <Controls showLock={false} />
  </SvelteFlow>
</div>
