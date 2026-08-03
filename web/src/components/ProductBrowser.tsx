import { useEffect, useMemo, useState } from "react";
import type { IndexProduct } from "../lib/types";
import { productDisplayName, researchPriorityRank } from "../lib/types";
import { withBase } from "../lib/paths";

const UNKNOWN_BRAND_KEY = "__unknown__";
const MAX_COMPARE = 6;

interface CategorySummary { name: string; slug: string; product_count: number; }
interface BrandSummary { name: string; count: number; }
interface CategorySlice { category: string; products: IndexProduct[]; }
interface Props {
  categories: CategorySummary[];
  totalCount: number;
  brands: BrandSummary[];
  unknownBrandCount: number;
  initialSlices: CategorySlice[];
  fullIndexUrl: string;
}

function categoryStyle(category: string) {
  const styles = [
    { bg: "#eef2ff", text: "#4f46e5" }, { bg: "#ecfeff", text: "#0f766e" },
    { bg: "#fff7ed", text: "#c2410c" }, { bg: "#fff1f2", text: "#be123c" },
  ];
  const code = Array.from(category).reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return styles[code % styles.length];
}

function productInitial(product: IndexProduct) {
  return (product.brand || product.model || "?").trim().slice(0, 1).toUpperCase();
}

function statusLabel(product: IndexProduct) {
  if (product.official_page_status === "found") return "Official page found";
  if (product.research_priority === "official_current") return "Officially current";
  if (product.research_priority === "recent_pending_check") return "Recent / verify";
  return "Historical reference";
}

export default function ProductBrowser({ categories, totalCount, brands, unknownBrandCount, initialSlices, fullIndexUrl }: Props) {
  const [fullIndex, setFullIndex] = useState<IndexProduct[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [brandFilter, setBrandFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState<"all" | "official_current" | "recent_pending_check">("all");
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetch(fullIndexUrl)
      .then((res) => { if (!res.ok) throw new Error("Product index unavailable"); return res.json(); })
      .then((data: { products: IndexProduct[] }) => { if (!cancelled) setFullIndex(data.products); })
      .catch(() => { if (!cancelled) setLoadFailed(true); });
    return () => { cancelled = true; };
  }, [fullIndexUrl]);

  const seedProducts = useMemo(() => initialSlices.flatMap((slice) => slice.products), [initialSlices]);
  const products = fullIndex || seedProducts;
  const isFiltering = Boolean(search.trim() || categoryFilter || brandFilter || priorityFilter !== "all");
  const sorted = (items: IndexProduct[]) => [...items].sort((a, b) =>
    researchPriorityRank(a) - researchPriorityRank(b) || (b.latest_published || "").localeCompare(a.latest_published || ""));
  const filteredProducts = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sorted(products.filter((product) => {
      const brand = (product.brand || "").trim();
      const text = `${brand} ${product.model || ""} ${product.category || ""} ${product.canonical_id}`.toLowerCase();
      return (!query || text.includes(query))
        && (!categoryFilter || product.category === categoryFilter)
        && (!brandFilter || (brandFilter === UNKNOWN_BRAND_KEY ? !brand : brand === brandFilter))
        && (priorityFilter === "all" || product.research_priority === priorityFilter);
    }));
  }, [products, search, categoryFilter, brandFilter, priorityFilter]);
  const visibleProducts = isFiltering ? filteredProducts.slice(0, 30) : sorted(seedProducts).slice(0, 12);
  const productById = useMemo(() => new Map([...seedProducts, ...(fullIndex || [])].map((product) => [product.canonical_id, product])), [seedProducts, fullIndex]);
  const selectedProducts = selected.map((id) => productById.get(id)).filter((item): item is IndexProduct => Boolean(item));
  const attentionProducts = sorted(seedProducts).slice(0, 5);
  const compareHref = selected.length ? withBase(`/compare?ids=${selected.join(",")}`) : withBase("/compare");
  const toggleProduct = (id: string) => setSelected((current) => current.includes(id)
    ? current.filter((item) => item !== id)
    : current.length >= MAX_COMPARE ? current : [...current, id]);
  const resetFilters = () => { setSearch(""); setCategoryFilter(""); setBrandFilter(""); setPriorityFilter("all"); };

  return (
    <section id="workspace" className="workspace-shell">
      <div className="workspace-toolbar">
        <div><p className="eyebrow">PRODUCT RESEARCH</p><h2>Product discovery &amp; comparison</h2><p>Start from products with recent activity or a traceable official presence.</p></div>
        <div className="workspace-search"><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search brand, model or product ID" aria-label="Search products" />{isFiltering && <button type="button" onClick={resetFilters} className="workspace-text-button">Clear</button>}</div>
      </div>
      <div className="workspace-layout">
        <aside className="workspace-filter-card">
          <div className="filter-section"><div className="filter-heading"><span>Category</span><button type="button" onClick={() => setCategoryFilter("")}>All</button></div><div className="filter-list">{categories.map((category) => <button key={category.name} type="button" onClick={() => setCategoryFilter((current) => current === category.name ? "" : category.name)} className={categoryFilter === category.name ? "is-active" : ""}><span>{category.name}</span><em>{category.product_count}</em></button>)}</div></div>
          <div className="filter-section"><div className="filter-heading"><span>Research status</span></div><div className="filter-pills"><button type="button" className={priorityFilter === "official_current" ? "is-active" : ""} onClick={() => setPriorityFilter((value) => value === "official_current" ? "all" : "official_current")}>Official current</button><button type="button" className={priorityFilter === "recent_pending_check" ? "is-active" : ""} onClick={() => setPriorityFilter((value) => value === "recent_pending_check" ? "all" : "recent_pending_check")}>Recent to verify</button></div></div>
          <div className="filter-section"><div className="filter-heading"><span>Key brands</span><button type="button" onClick={() => setBrandFilter("")}>Reset</button></div><div className="filter-list filter-list--brands">{brands.slice(0, 8).map((brand) => <button key={brand.name} type="button" onClick={() => setBrandFilter((value) => value === brand.name ? "" : brand.name)} className={brandFilter === brand.name ? "is-active" : ""}><span>{brand.name}</span><em>{brand.count}</em></button>)}</div><button type="button" onClick={() => setBrandFilter(UNKNOWN_BRAND_KEY)} className="data-health-link">Data quality: {unknownBrandCount} brands to normalize</button></div>
        </aside>
        <main className="workspace-results">
          <div className="results-heading"><div><strong>{isFiltering ? `${filteredProducts.length} matched products` : `${visibleProducts.length} priority products`}</strong><span>{fullIndex ? `${totalCount} products in the library` : "Loading the complete library..."}</span></div><span className="results-status">{loadFailed ? "Index unavailable - refresh to retry" : "Ranked by research priority"}</span></div>
          <div className="product-card-grid">{visibleProducts.map((product) => { const color = categoryStyle(product.category); const active = selected.includes(product.canonical_id); return <article key={product.canonical_id} className={`research-product-card ${active ? "is-selected" : ""}`}><button type="button" onClick={() => toggleProduct(product.canonical_id)} className="selection-toggle" aria-label={`${active ? "Remove" : "Add"} ${productDisplayName(product)}`}>{active ? "✓" : "+"}</button><a href={withBase(`/product/${product.canonical_id}`)} className="research-product-link"><div className="product-visual" style={{ background: color.bg, color: color.text }} aria-hidden="true">{productInitial(product)}</div><div className="product-copy"><div className="product-meta"><span style={{ background: color.bg, color: color.text }}>{product.category}</span><time>{product.first_seen?.slice(0, 4) || "-"}</time></div><h3>{productDisplayName(product)}</h3><div className="product-foot"><span className={`priority-badge ${product.research_priority || "historical_reference"}`}>{statusLabel(product)}</span><span>{product.report_count || 0} reports</span></div></div></a></article>; })}</div>
          {visibleProducts.length === 0 && <div className="workspace-empty">No products matched these filters.</div>}
        </main>
        <aside className="priority-panel"><div className="priority-panel-head"><div><span className="priority-star">✦</span><strong>Focus queue</strong></div><span>Auto ranked</span></div><p>Recent products and products with a traceable official presence are placed first.</p><ol>{attentionProducts.map((product, index) => <li key={product.canonical_id}><span className="priority-rank">{index + 1}</span><a href={withBase(`/product/${product.canonical_id}`)}><strong>{productDisplayName(product)}</strong><small>{statusLabel(product)} · {product.latest_published || product.first_seen || "Date pending"}</small></a></li>)}</ol><a href={withBase("/teardown-details")} className="priority-panel-link">Browse research library →</a></aside>
      </div>
      {selected.length > 0 && <div className="compare-tray" aria-live="polite"><div className="compare-tray-summary"><strong>{selected.length} selected</strong><span>Up to {MAX_COMPARE}</span></div><div className="compare-tray-items">{selectedProducts.map((product) => <button key={product.canonical_id} type="button" onClick={() => toggleProduct(product.canonical_id)}>{productDisplayName(product)} <span>×</span></button>)}</div><button type="button" className="workspace-text-button" onClick={() => setSelected([])}>Clear</button><a href={compareHref} className={`compare-primary ${selected.length < 2 ? "is-disabled" : ""}`} aria-disabled={selected.length < 2} onClick={(event) => { if (selected.length < 2) event.preventDefault(); }}>Compare <span>→</span></a></div>}
    </section>
  );
}
