export type ProductRoute = "home" | "input" | "pipeline" | "workspace";

export const productRoutes: Record<ProductRoute, string> = {
  home: "/",
  input: "/analysis/new",
  pipeline: "/analysis/pipeline",
  workspace: "/analysis/workspace",
};
