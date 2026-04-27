export type BreadcrumbItem = {
  label: string;
  href?: string;
  // undefined → no status dot rendered. null → renders muted/unknown dot.
  status?: string | null;
  tooltip?: string;
  // When set, the layout renders the icon in place of the label.
  icon?: "home" | "workflow";
};

class BreadcrumbState {
  items = $state<BreadcrumbItem[]>([]);
}

export const breadcrumb = new BreadcrumbState();
