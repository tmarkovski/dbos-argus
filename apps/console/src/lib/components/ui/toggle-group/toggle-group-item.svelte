<script lang="ts">
	import { ToggleGroup as ToggleGroupPrimitive } from "bits-ui";
	import { getToggleGroupCtx } from "./toggle-group.svelte";
	import { cn } from "$lib/utils.js";
	import { type ToggleVariants, toggleVariants } from "$lib/components/ui/toggle/index.js";

	let {
		ref = $bindable(null),
		value = $bindable(),
		class: className,
		size,
		variant,
		...restProps
	}: ToggleGroupPrimitive.ItemProps & ToggleVariants = $props();

	const ctx = getToggleGroupCtx();

	// Outline groups are segmented controls (muted track + card chips), so the
	// joined-border/squared-corner treatment below must not apply to them.
	const isOutline = $derived((ctx.variant || variant) === "outline");

	// bits-ui lets a single-type group deselect its active item, leaving the
	// group with no selection. Our single groups act as radios, so swallow the
	// interaction before bits-ui's own handler runs (its mergeProps skips
	// internal handlers once default is prevented). Single-mode items carry
	// role="radio", so the mode is readable off the element itself.
	function preventDeselect(e: Event) {
		const el = e.currentTarget as HTMLElement;
		if (el.getAttribute("role") === "radio" && el.dataset.state === "on") {
			e.preventDefault();
		}
	}
</script>

<ToggleGroupPrimitive.Item
	bind:ref
	onclick={preventDeselect}
	onkeydown={(e) => {
		if (e.key === "Enter" || e.key === " ") preventDeselect(e);
	}}
	data-slot="toggle-group-item"
	data-variant={ctx.variant || variant}
	data-size={ctx.size || size}
	data-spacing={ctx.spacing}
	class={cn(
		isOutline
			? "shrink-0 focus:z-10 focus-visible:z-10"
			: "data-[state=on]:bg-muted group-data-[spacing=0]/toggle-group:rounded-none group-data-[spacing=0]/toggle-group:px-3 group-data-[spacing=0]/toggle-group:shadow-none group-data-[spacing=0]/toggle-group:has-data-[icon=inline-end]:pr-2.5 group-data-[spacing=0]/toggle-group:has-data-[icon=inline-start]:pl-2.5 group-data-horizontal/toggle-group:data-[spacing=0]:first:rounded-l-md group-data-vertical/toggle-group:data-[spacing=0]:first:rounded-t-md group-data-horizontal/toggle-group:data-[spacing=0]:last:rounded-r-md group-data-vertical/toggle-group:data-[spacing=0]:last:rounded-b-md shrink-0 focus:z-10 focus-visible:z-10",
		toggleVariants({
			variant: ctx.variant || variant,
			size: ctx.size || size,
		}),
		className
	)}
	{value}
	{...restProps}
/>
