export interface CompareCell {
  value: string;
  evidence: string;
  source_layer: string;
}

export interface CompareProduct {
  canonical_id: string;
  brand: string;
  model: string;
  best_report_id?: string;
  cells: Record<string, CompareCell>;
}

export interface CompareData {
  category: string;
  param_rows: string[];
  products: CompareProduct[];
}

export interface CategoryItem {
  name: string;
  slug: string;
  file: string;
  product_count: number;
}

export interface ParamLabel {
  label: string;
  why?: string;
}

/** 首页/发现页使用的轻量产品索引条目，来自 products/index.json（不含 cells/evidence）。 */
export interface IndexProduct {
  canonical_id: string;
  brand: string;
  model: string;
  category: string;
  report_count?: number;
  video_count?: number;
  first_seen?: string;
  latest_published?: string;
  cost_completeness?: number;
  bom_row_count?: number;
}

export interface CompareProfiles {
  default_profile: string;
  profiles: Record<
    string,
    { label: string; categories: string[]; p0: string[]; p1: string[] }
  >;
  param_labels: Record<string, ParamLabel>;
}

/** productDisplayName 只需要这三个字段，用最小形状而非 CompareProduct，
 * 这样 IndexProduct（无 cells 字段）等轻量产品对象也能直接复用同一函数。 */
export function productDisplayName(p: {
  canonical_id: string;
  brand: string;
  model: string;
}): string {
  const b = (p.brand || "").trim();
  const m = (p.model || "").trim();
  return `${b} ${m}`.trim() || p.canonical_id;
}

export function profileForCategory(
  profiles: CompareProfiles,
  category: string
): { key: string; p0: string[]; p1: string[] } {
  for (const [key, prof] of Object.entries(profiles.profiles)) {
    if (key === "default") continue;
    if (prof.categories.includes(category)) {
      return { key, p0: prof.p0, p1: prof.p1 };
    }
  }
  const d = profiles.profiles.default;
  return { key: "default", p0: d.p0, p1: d.p1 };
}

export function emptyHint(value: string | undefined): boolean {
  return !value || value === "0" || value === "—";
}

export function sourceLabel(layer: string): string {
  const map: Record<string, string> = {
    technical: "拆解",
    channel: "渠道",
    official: "官方",
    review: "评测",
  };
  return map[layer] || layer;
}
