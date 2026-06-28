<script lang="ts">
  import { onDestroy, onMount, untrack } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import {
    Controls,
    SvelteFlow,
    type ColorMode,
    type Edge,
    type Node,
    type NodeTypes,
  } from "@xyflow/svelte";
  import ELK, { type ElkNode } from "elkjs/lib/elk.bundled.js";
  import type { Workflow } from "$lib/workflow-tree";
  import WorkflowContainerNode from "./WorkflowContainerNode.svelte";
  import StepNode from "./StepNode.svelte";
  import EllipsisNode from "./EllipsisNode.svelte";

  // Family-row shape from /api/workflows/{id}. Drops `operation_count` (the
  // detail endpoint inlines steps directly) and replaces output/error
  // payloads with presence flags — the actual content is fetched lazily
  // via /api/workflows/{id}/result on click.
  export type FamilyWorkflow = Omit<Workflow, "operation_count"> & {
    has_output: boolean;
    has_error: boolean;
    recovery_attempts: number | null;
    workflow_timeout_ms: number | null;
    schedule_name: string | null;
    attributes: unknown | null;
  };

  export type Step = {
    workflow_id: string;
    function_id: number;
    function_name: string;
    has_output: boolean;
    has_error: boolean;
    child_workflow_id: string | null;
    started_at: string | null;
    completed_at: string | null;
    event_key: string | null;
    sleep_requested_ms: number | null;
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
  const ELLIPSIS_HEIGHT = 22;
  const HEAD = 5;
  const TAIL = 5;
  const LAYOUT_ANIMATION_MS = 240;
  // Minimum container size — ELK collapses empty containers to ~0, which hides
  // the workflow header (name + id). Floor the layout output so a workflow
  // with zero steps yet still renders a proper container box.
  const CONTAINER_MIN_WIDTH = STEP_WIDTH + 32; // step width + L/R padding
  const CONTAINER_MIN_HEIGHT = 108; // top padding 60 + 1 step (32) + bottom 16

  const elk = new ELK();
  const nodeTypes: NodeTypes = {
    workflow: WorkflowContainerNode,
    step: StepNode,
    ellipsis: EllipsisNode,
  };

  let nodes = $state.raw<Node[]>([]);
  let edges = $state.raw<Edge[]>([]);
  let expanded = new SvelteSet<string>();
  let colorMode = $state<ColorMode>("light");
  let layoutRun = 0;
  let layoutAnimationRun = 0;
  let layoutAnimationFrame: number | null = null;

  onMount(() => {
    const sync = () => {
      colorMode = document.documentElement.classList.contains("dark") ? "dark" : "light";
    };
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  });

  onDestroy(() => {
    if (layoutAnimationFrame !== null) {
      cancelAnimationFrame(layoutAnimationFrame);
    }
  });

  type VisibleItem =
    | { kind: "step"; step: Step }
    | { kind: "ellipsis"; from: number; to: number; count: number };
  type NodePose = Pick<Node, "position" | "width" | "height">;

  function ellipsisNodeId(wfId: string, from: number, to: number): string {
    return `${wfId}/ellipsis/${from}-${to}`;
  }

  function buildVisibleItems(
    wfSteps: Step[],
    isExpanded: boolean,
    importantIds: Set<string>,
  ): VisibleItem[] {
    if (isExpanded || wfSteps.length <= HEAD + TAIL) {
      return wfSteps.map((step) => ({ kind: "step", step }));
    }
    const head = wfSteps.slice(0, HEAD);
    const tail = wfSteps.slice(-TAIL);
    const middleVisible = wfSteps
      .slice(HEAD, wfSteps.length - TAIL)
      .filter((s) => importantIds.has(stepNodeId(s.workflow_id, s.function_id)));
    const visible: Step[] = [...head, ...middleVisible, ...tail];

    const indexOf = new Map(wfSteps.map((s, i) => [s.function_id, i]));
    const items: VisibleItem[] = [];
    for (let i = 0; i < visible.length; i++) {
      if (i > 0) {
        const prevIdx = indexOf.get(visible[i - 1].function_id)!;
        const curIdx = indexOf.get(visible[i].function_id)!;
        if (curIdx - prevIdx > 1) {
          items.push({
            kind: "ellipsis",
            from: prevIdx + 1,
            to: curIdx - 1,
            count: curIdx - prevIdx - 1,
          });
        }
      }
      items.push({ kind: "step", step: visible[i] });
    }
    return items;
  }

  function stepKind(s: Step): "child" | "system" | "step" {
    if (s.function_name.startsWith("DBOS.")) return "system";
    if (s.child_workflow_id) return "child";
    return "step";
  }

  function eventDirection(s: Step): "set" | "get" | null {
    if (s.function_name === "DBOS.setEvent") return "set";
    if (s.function_name === "DBOS.getEvent") return "get";
    return null;
  }

  function stepStatus(s: Step): "error" | "running" | "success" | null {
    if (s.has_error) return "error";
    if (s.started_at && !s.completed_at) return "running";
    if (s.completed_at) return "success";
    return null;
  }

  function stepNodeId(workflowId: string, functionId: number): string {
    return `${workflowId}/${functionId}`;
  }

  // Reflect external selection state onto the flow so the same node stays
  // visually highlighted across re-layouts.
  const selectedId = $derived.by(() => {
    if (!selection) return null;
    if (selection.kind === "workflow") return selection.workflow.workflow_id;
    return `${selection.step.workflow_id}/${selection.step.function_id}`;
  });

  function withCurrentSelection(nextNodes: Node[]): Node[] {
    const sid = selectedId;
    return nextNodes.map((n) => {
      const shouldSelect = n.id === sid;
      if ((n.selected ?? false) === shouldSelect) return n;
      return { ...n, selected: shouldSelect };
    });
  }

  function shouldReduceMotion(): boolean {
    return (
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function easeOutCubic(t: number): number {
    return 1 - Math.pow(1 - t, 3);
  }

  function lerp(from: number, to: number, t: number): number {
    return from + (to - from) * t;
  }

  function nodeWidth(n: Node): number | undefined {
    return typeof n.width === "number" ? n.width : undefined;
  }

  function nodeHeight(n: Node): number | undefined {
    return typeof n.height === "number" ? n.height : undefined;
  }

  function nodeCenter(n: Node): { x: number; y: number } {
    return {
      x: n.position.x + (nodeWidth(n) ?? 0) / 2,
      y: n.position.y + (nodeHeight(n) ?? 0) / 2,
    };
  }

  function poseCenteredOn(source: Node, sizedLike: Node): NodePose {
    const center = nodeCenter(source);
    const width = nodeWidth(sizedLike);
    const height = nodeHeight(sizedLike);
    return {
      position: {
        x: center.x - (width ?? 0) / 2,
        y: center.y - (height ?? 0) / 2,
      },
      width,
      height,
    };
  }

  function parseStepFunctionId(nodeId: string): number | null {
    const slash = nodeId.lastIndexOf("/");
    const raw = slash >= 0 ? nodeId.slice(slash + 1) : nodeId;
    const id = Number(raw);
    return Number.isFinite(id) ? id : null;
  }

  function parseEllipsisRange(nodeId: string): { from: number; to: number } | null {
    const marker = "/ellipsis/";
    const markerIndex = nodeId.lastIndexOf(marker);
    if (markerIndex < 0) return null;
    const [fromRaw, toRaw] = nodeId.slice(markerIndex + marker.length).split("-");
    const from = Number(fromRaw);
    const to = Number(toRaw);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    return { from, to };
  }

  function findContainingEllipsis(step: Node, candidates: Node[]): Node | null {
    const functionId = parseStepFunctionId(step.id);
    if (functionId === null) return null;
    return (
      candidates.find((n) => {
        if (n.type !== "ellipsis" || n.parentId !== step.parentId) return false;
        const range = parseEllipsisRange(n.id);
        return !!range && functionId >= range.from && functionId <= range.to;
      }) ?? null
    );
  }

  function collapsedRangePose(
    ellipsis: Node,
    candidates: Node[],
  ): NodePose | null {
    const range = parseEllipsisRange(ellipsis.id);
    if (!range) return null;

    const collapsedSteps = candidates.filter((n) => {
      if (n.type !== "step" || n.parentId !== ellipsis.parentId) return false;
      const functionId = parseStepFunctionId(n.id);
      return functionId !== null && functionId >= range.from && functionId <= range.to;
    });
    if (collapsedSteps.length === 0) return null;

    const center = collapsedSteps.reduce(
      (acc, n) => {
        const c = nodeCenter(n);
        acc.x += c.x;
        acc.y += c.y;
        return acc;
      },
      { x: 0, y: 0 },
    );
    center.x /= collapsedSteps.length;
    center.y /= collapsedSteps.length;

    const width = nodeWidth(ellipsis);
    const height = nodeHeight(ellipsis);
    return {
      position: {
        x: center.x - (width ?? 0) / 2,
        y: center.y - (height ?? 0) / 2,
      },
      width,
      height,
    };
  }

  function startPoseForEnteringNode(
    target: Node,
    currentNodes: Node[],
  ): NodePose {
    if (target.type === "step") {
      const ellipsis = findContainingEllipsis(target, currentNodes);
      if (ellipsis) return poseCenteredOn(ellipsis, target);
    }
    if (target.type === "ellipsis") {
      const pose = collapsedRangePose(target, currentNodes);
      if (pose) return pose;
    }
    return {
      position: target.position,
      width: target.width,
      height: target.height,
    };
  }

  function targetPoseForExitingNode(
    exiting: Node,
    targetNodes: Node[],
  ): NodePose {
    if (exiting.type === "step") {
      const ellipsis = findContainingEllipsis(exiting, targetNodes);
      if (ellipsis) return poseCenteredOn(ellipsis, exiting);
    }
    return {
      position: exiting.position,
      width: exiting.width,
      height: exiting.height,
    };
  }

  function withOpacity(node: Node, opacity: number): Node {
    if (opacity >= 0.999) return node;
    const baseStyle = typeof node.style === "string" ? node.style.trim() : "";
    const separator = baseStyle && !baseStyle.endsWith(";") ? "; " : "";
    return {
      ...node,
      selectable: false,
      style: `${baseStyle}${separator}opacity: ${opacity.toFixed(3)}; pointer-events: none;`,
    };
  }

  function interpolateNode(
    target: Node,
    start: NodePose,
    t: number,
    opacity = 1,
  ): Node {
    const width =
      typeof start.width === "number" && typeof target.width === "number"
        ? lerp(start.width, target.width, t)
        : target.width;
    const height =
      typeof start.height === "number" && typeof target.height === "number"
        ? lerp(start.height, target.height, t)
        : target.height;

    return withOpacity(
      {
        ...target,
        position: {
          x: lerp(start.position.x, target.position.x, t),
          y: lerp(start.position.y, target.position.y, t),
        },
        width,
        height,
      },
      opacity,
    );
  }

  function animateToLayout(targetNodes: Node[], targetEdges: Edge[]) {
    const currentNodes = nodes;

    if (layoutAnimationFrame !== null) {
      cancelAnimationFrame(layoutAnimationFrame);
      layoutAnimationFrame = null;
    }
    const animationRun = ++layoutAnimationRun;

    if (currentNodes.length === 0 || shouldReduceMotion()) {
      nodes = withCurrentSelection(targetNodes);
      edges = targetEdges;
      return;
    }

    const currentById = new Map(currentNodes.map((n) => [n.id, n]));
    const targetById = new Map(targetNodes.map((n) => [n.id, n]));
    const exitingNodes = currentNodes.filter((n) => !targetById.has(n.id));
    const startedAt = performance.now();
    edges = targetEdges;

    const tick = (now: number) => {
      if (animationRun !== layoutAnimationRun) return;
      const rawT = Math.min(1, (now - startedAt) / LAYOUT_ANIMATION_MS);
      const t = easeOutCubic(rawT);

      const animatedTargets = targetNodes.map((target) => {
        const existing = currentById.get(target.id);
        const start = existing ?? startPoseForEnteringNode(target, currentNodes);
        return interpolateNode(target, start, t, existing ? 1 : rawT);
      });

      const animatedExits =
        rawT < 1
          ? exitingNodes.map((exiting) => {
              const target = targetPoseForExitingNode(exiting, targetNodes);
              const exitTarget = {
                ...exiting,
                position: target.position,
                width: target.width,
                height: target.height,
              };
              return interpolateNode(exitTarget, exiting, t, 1 - rawT);
            })
          : [];

      nodes = withCurrentSelection([...animatedTargets, ...animatedExits]);

      if (rawT < 1) {
        layoutAnimationFrame = requestAnimationFrame(tick);
        return;
      }

      nodes = withCurrentSelection(targetNodes);
      edges = targetEdges;
      layoutAnimationFrame = null;
    };

    tick(startedAt);
  }

  async function layout(
    family: FamilyWorkflow[],
    steps: Step[],
    currentId: string,
    expandedSet: Set<string>,
  ) {
    const run = ++layoutRun;
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

    function spawnedName(s: Step): string | null {
      if (stepKind(s) !== "child" || !s.child_workflow_id) return null;
      return nameByWorkflowId.get(s.child_workflow_id) ?? null;
    }

    // Steps that connect to other family workflows (spawn or getResult) must
    // remain visible even if they fall in the truncated middle range, otherwise
    // their cross-container edges would lose an endpoint.
    const importantIds = new Set<string>();
    for (const s of steps) {
      if (!s.child_workflow_id || !familyIds.has(s.child_workflow_id)) continue;
      if (stepKind(s) === "child" || s.function_name === "DBOS.getResult") {
        importantIds.add(stepNodeId(s.workflow_id, s.function_id));
      }
    }

    const itemsByWf = new Map<string, VisibleItem[]>();
    for (const w of family) {
      const wfSteps = stepsByWf.get(w.workflow_id) ?? [];
      itemsByWf.set(
        w.workflow_id,
        buildVisibleItems(wfSteps, expandedSet.has(w.workflow_id), importantIds),
      );
    }

    function itemId(wfId: string, it: VisibleItem): string {
      return it.kind === "step"
        ? stepNodeId(it.step.workflow_id, it.step.function_id)
        : ellipsisNodeId(wfId, it.from, it.to);
    }

    // Stage 1: lay each container out independently with its (possibly
    // truncated) items stacked top→bottom.
    const containerLayouts = await Promise.all(
      family.map(async (w) => {
        const items = itemsByWf.get(w.workflow_id) ?? [];
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
          children: items.map((it) => ({
            id: itemId(w.workflow_id, it),
            width: STEP_WIDTH,
            height: it.kind === "step" ? STEP_HEIGHT : ELLIPSIS_HEIGHT,
          })),
          edges: items.slice(1).map((it, i) => {
            const prev = items[i];
            const sourceId = itemId(w.workflow_id, prev);
            const targetId = itemId(w.workflow_id, it);
            return {
              id: `seq:${w.workflow_id}:${sourceId}->${targetId}`,
              sources: [sourceId],
              targets: [targetId],
            };
          }),
        };
        const laidOut = await elk.layout(containerGraph);
        if ((laidOut.width ?? 0) < CONTAINER_MIN_WIDTH) {
          laidOut.width = CONTAINER_MIN_WIDTH;
        }
        if ((laidOut.height ?? 0) < CONTAINER_MIN_HEIGHT) {
          laidOut.height = CONTAINER_MIN_HEIGHT;
        }
        return laidOut;
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
      const wfStepCount = stepsByWf.get(c.id!)?.length ?? 0;
      nextNodes.push({
        id: c.id!,
        type: "workflow",
        position: pos,
        data: {
          workflow: w,
          isCurrent: w.workflow_id === currentId,
          isCollapsible: wfStepCount > HEAD + TAIL,
          isExpanded: expandedSet.has(c.id!),
          onToggle: () => toggleExpansion(c.id!),
        },
        width: c.width,
        height: c.height,
        draggable: false,
        connectable: false,
        selectable: true,
        style: `width: ${c.width}px; height: ${c.height}px;`,
      });
      const items = itemsByWf.get(c.id!) ?? [];
      const itemByNodeId = new Map<string, VisibleItem>();
      for (const it of items) {
        itemByNodeId.set(itemId(c.id!, it), it);
      }
      const firstStepItem = items.find((it) => it.kind === "step");
      const lastStepItem = [...items].reverse().find((it) => it.kind === "step");
      const firstStepNodeId = firstStepItem ? itemId(c.id!, firstStepItem) : null;
      const lastStepNodeId = lastStepItem ? itemId(c.id!, lastStepItem) : null;
      for (const childNode of c.children ?? []) {
        const item = itemByNodeId.get(childNode.id!);
        if (!item) continue;
        if (item.kind === "ellipsis") {
          nextNodes.push({
            id: childNode.id!,
            type: "ellipsis",
            parentId: c.id!,
            extent: "parent",
            position: { x: childNode.x ?? 0, y: childNode.y ?? 0 },
            data: { workflowId: c.id!, hiddenCount: item.count },
            width: childNode.width,
            height: childNode.height,
            draggable: false,
            connectable: false,
            selectable: false,
          });
          continue;
        }
        const s = item.step;
        const durationMs =
          s.started_at && s.completed_at
            ? new Date(s.completed_at).getTime() - new Date(s.started_at).getTime()
            : null;
        nextNodes.push({
          id: childNode.id!,
          type: "step",
          parentId: c.id!,
          extent: "parent",
          position: { x: childNode.x ?? 0, y: childNode.y ?? 0 },
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
            spawnedWorkflowName: spawnedName(s),
            eventDirection: eventDirection(s),
            eventKey: s.event_key,
            sleepRequestedMs: s.sleep_requested_ms,
            startedAt: s.started_at,
            isFirst: childNode.id === firstStepNodeId,
            isLast: childNode.id === lastStepNodeId,
          },
          width: childNode.width,
          height: childNode.height,
          draggable: false,
          connectable: false,
          selectable: true,
        });
      }
      let previousStepId: string | null = null;
      for (const it of items) {
        if (it.kind !== "step") continue;
        const stepId = itemId(c.id!, it);
        if (!previousStepId) {
          previousStepId = stepId;
          continue;
        }
        nextEdges.push({
          id: `seq:${c.id}:${previousStepId}->${stepId}`,
          source: previousStepId,
          target: stepId,
          type: "straight",
          style: "stroke: var(--color-border); stroke-width: 1px;",
        });
        previousStepId = stepId;
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
        style:
          "stroke: color-mix(in oklab, var(--color-workflow-accent) 80%, transparent); stroke-width: 2.5px;",
      });
    }

    // Return edges: child container → DBOS.getResult step that awaited it.
    // Recolor based on the child's terminal status so the failure / cancel
    // path is visually obvious.
    const statusByWorkflowId = new Map(family.map((w) => [w.workflow_id, w.status]));
    for (const s of steps) {
      if (s.function_name !== "DBOS.getResult") continue;
      if (!s.child_workflow_id || !familyIds.has(s.child_workflow_id)) continue;
      const targetId = stepNodeId(s.workflow_id, s.function_id);
      const childStatus = statusByWorkflowId.get(s.child_workflow_id);
      let edgeStyle =
        "stroke: color-mix(in oklab, var(--color-workflow-accent) 60%, transparent); stroke-width: 2.25px;";
      if (childStatus === "ERROR") {
        edgeStyle =
          "stroke: color-mix(in oklab, var(--color-status-error) 85%, transparent); stroke-width: 2.5px;";
      } else if (childStatus === "CANCELLED") {
        edgeStyle =
          "stroke: color-mix(in oklab, var(--color-status-warning) 85%, transparent); stroke-width: 2.5px;";
      }
      nextEdges.push({
        id: `return:${s.child_workflow_id}->${targetId}`,
        source: s.child_workflow_id,
        target: targetId,
        sourceHandle: "return",
        targetHandle: "return",
        type: "bezier",
        animated: true,
        style: edgeStyle,
      });
    }

    if (run !== layoutRun) return;
    animateToLayout(nextNodes, nextEdges);
  }

  $effect(() => {
    // Snapshot expanded so the effect re-runs when it changes.
    const snapshot = new Set(expanded);
    layout(family, steps, currentId, snapshot);
  });

  function toggleExpansion(wfId: string) {
    if (expanded.has(wfId)) expanded.delete(wfId);
    else expanded.add(wfId);
  }

  function handleNodeClick({ node }: { node: Node }) {
    if (node.type === "ellipsis") {
      const wfId = (node.data as { workflowId: string }).workflowId;
      toggleExpansion(wfId);
      return;
    }
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

  // We untrack the nodes read so writing nodes inside the effect doesn't
  // re-trigger it.
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

<div class="bg-card h-full w-full overflow-hidden">
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    {colorMode}
    fitView
    fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable
    zoomOnDoubleClick={false}
    minZoom={0.2}
    proOptions={{ hideAttribution: true }}
    onnodeclick={handleNodeClick}
    onpaneclick={handlePaneClick}
  >
    <Controls showLock={false} />
  </SvelteFlow>
</div>

<style>
  /* Handles are non-interactive anchor points for edges; render them
     invisible so connector lines terminate flush against the pill
     outline rather than overlapping the selection ring. */
  :global(.svelte-flow__handle) {
    width: 1px;
    height: 1px;
    min-width: 1px;
    min-height: 1px;
    background: transparent;
    border: none;
    opacity: 0;
  }

  /* Subtle ambient gradient on the flow surface — uses chart tokens so it
     tracks the active preset's palette and gives the canvas depth without
     competing with the workflow nodes. */
  :global(.svelte-flow) {
    background:
      radial-gradient(
        ellipse 80% 60% at 25% 0%,
        color-mix(in oklab, var(--color-chart-1) 14%, transparent),
        transparent 60%
      ),
      radial-gradient(
        ellipse 65% 50% at 0% 100%,
        color-mix(in oklab, var(--color-chart-2) 12%, transparent),
        transparent 55%
      ),
      radial-gradient(
        ellipse 70% 55% at 100% 100%,
        color-mix(in oklab, var(--color-chart-5) 12%, transparent),
        transparent 55%
      ),
      var(--color-card) !important;
  }
</style>
