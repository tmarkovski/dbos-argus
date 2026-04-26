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
    const nameByWorkflowId = new Map(family.map((w) => [w.workflow_id, w.name ?? null]));

    function awaitedName(s: Step): string | null {
      if (s.function_name !== "DBOS.getResult" || !s.child_workflow_id) return null;
      return nameByWorkflowId.get(s.child_workflow_id) ?? null;
    }

    // Stage 1: lay each container out independently with its steps stacked
    // top→bottom. This produces per-container width/height and per-step
    // positions relative to the container.
    const containerLayouts = await Promise.all(
      family.map(async (w) => {
        const wfSteps = stepsByWf.get(w.workflow_id) ?? [];
        const containerGraph: ElkNode = {
          id: w.workflow_id,
          layoutOptions: {
            "elk.algorithm": "layered",
            "elk.direction": "DOWN",
            "elk.padding": "[top=60,left=16,right=16,bottom=16]",
            "elk.spacing.nodeNode": "12",
            "elk.layered.spacing.nodeNodeBetweenLayers": "12",
            "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
            "elk.layered.crossingMinimization.forceNodeModelOrder": "true",
          },
          children: wfSteps.map((s) => ({
            id: stepNodeId(s.workflow_id, s.function_id),
            width: STEP_WIDTH,
            height: STEP_HEIGHT,
          })),
          edges: wfSteps.slice(1).map((s, i) => {
            const prev = wfSteps[i];
            return {
              id: `seq:${s.workflow_id}:${prev.function_id}->${s.function_id}`,
              sources: [stepNodeId(prev.workflow_id, prev.function_id)],
              targets: [stepNodeId(s.workflow_id, s.function_id)],
            };
          }),
        };
        return await elk.layout(containerGraph);
      }),
    );

    // Stage 2: lay containers out at the root with direction RIGHT, treating
    // each container as a fixed-size box. Spawn edges are collapsed to
    // container→container so ELK can place children to the right of parents.
    const spawnSteps = steps.filter(
      (s) =>
        s.child_workflow_id !== null &&
        stepKind(s) === "child" &&
        familyIds.has(s.child_workflow_id),
    );
    const seenContainerEdge = new Set<string>();
    const rootGraph: ElkNode = {
      id: "root",
      layoutOptions: {
        "elk.algorithm": "layered",
        "elk.direction": "RIGHT",
        "elk.spacing.nodeNode": "60",
        "elk.layered.spacing.nodeNodeBetweenLayers": "120",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
      },
      children: containerLayouts.map((c) => ({
        id: c.id!,
        width: c.width,
        height: c.height,
      })),
      edges: spawnSteps
        .map((s) => {
          const key = `${s.workflow_id}->${s.child_workflow_id}`;
          if (seenContainerEdge.has(key)) return null;
          seenContainerEdge.add(key);
          return {
            id: `container-spawn:${key}`,
            sources: [s.workflow_id],
            targets: [s.child_workflow_id as string],
          };
        })
        .filter((e): e is NonNullable<typeof e> => e !== null),
    };

    const laidOutRoot = await elk.layout(rootGraph);
    const containerPos = new Map<string, { x: number; y: number }>();
    for (const c of laidOutRoot.children ?? []) {
      containerPos.set(c.id!, { x: c.x ?? 0, y: c.y ?? 0 });
    }

    const nextNodes: Node[] = [];
    const nextEdges: Edge[] = [];

    for (const c of containerLayouts) {
      const w = family.find((f) => f.workflow_id === c.id)!;
      const pos = containerPos.get(c.id!) ?? { x: 0, y: 0 };
      nextNodes.push({
        id: c.id!,
        type: "workflow",
        position: pos,
        data: { workflow: w, isCurrent: w.workflow_id === currentId },
        width: c.width,
        height: c.height,
        draggable: false,
        connectable: false,
        selectable: true,
        style: `width: ${c.width}px; height: ${c.height}px;`,
      });
      for (const stepNode of c.children ?? []) {
        const [, fnStr] = stepNode.id!.split("/");
        const fnId = Number(fnStr);
        const s = (stepsByWf.get(c.id!) ?? []).find((x) => x.function_id === fnId)!;
        const durationMs =
          s.started_at && s.completed_at
            ? new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()
            : null;
        nextNodes.push({
          id: stepNode.id!,
          type: "step",
          parentId: c.id!,
          extent: "parent",
          position: { x: stepNode.x ?? 0, y: stepNode.y ?? 0 },
          data: {
            functionId: s.function_id,
            functionName: s.function_name,
            kind: stepKind(s),
            status: stepStatus(s),
            durationMs,
            awaitsWorkflowId:
              s.function_name === "DBOS.getResult" &&
              s.child_workflow_id &&
              familyIds.has(s.child_workflow_id)
                ? s.child_workflow_id
                : null,
            awaitedWorkflowName: awaitedName(s),
          },
          width: stepNode.width,
          height: stepNode.height,
          draggable: false,
          connectable: false,
          selectable: true,
        });
      }
      for (const edge of c.edges ?? []) {
        nextEdges.push({
          id: edge.id!,
          source: edge.sources![0],
          target: edge.targets![0],
          type: "smoothstep",
          style: "stroke: var(--color-border); stroke-width: 1px;",
        });
      }
    }

    // Spawn edges connect step→child container directly via xyflow handles
    // (right side of the spawning step → left side of the child container).
    for (const s of spawnSteps) {
      const sourceId = stepNodeId(s.workflow_id, s.function_id);
      nextEdges.push({
        id: `spawn:${sourceId}->${s.child_workflow_id}`,
        source: sourceId,
        target: s.child_workflow_id as string,
        sourceHandle: "spawn",
        targetHandle: "spawn",
        type: "bezier",
        animated: true,
        style: "stroke: rgb(99 102 241 / 0.8); stroke-width: 1.5px;",
      });
    }

    // Return edges: child container → DBOS.getResult step that awaited it.
    for (const s of steps) {
      if (s.function_name !== "DBOS.getResult") continue;
      if (!s.child_workflow_id || !familyIds.has(s.child_workflow_id)) continue;
      const targetId = stepNodeId(s.workflow_id, s.function_id);
      nextEdges.push({
        id: `return:${s.child_workflow_id}->${targetId}`,
        source: s.child_workflow_id,
        target: targetId,
        sourceHandle: "return",
        targetHandle: "return",
        type: "bezier",
        animated: true,
        style: "stroke: rgb(99 102 241 / 0.6); stroke-width: 1.25px;",
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
