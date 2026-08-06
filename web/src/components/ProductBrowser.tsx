import { useEffect, useMemo, useState } from "react";
import type { IndexProduct } from "../lib/types";
import { productDisplayName, researchPriorityRank } from "../lib/types";
import { withBase } from "../lib/paths";

const UNKNOWN_BRAND_KEY = "__unknown__";
const MAX_COMPARE = 6;

interface CategorySummary {
  name: string;
  slug: string;
  product_count: number;
}

interface BrandSummary {
  name: string;
  count: number;
}

interface CategorySlice {
  category: string;
  products: IndexProduct[];
}

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
    { bg: "#eef2ff", text: "#4f46e5" },
    { bg: "#ecfeff", text: "#0f766e" },
    { bg: "#fff7ed", text: "#c2410c" },
    { bg: "#fff1f2", text: "#be123c" },
  ];
  const code = Array.from(category).reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return styles[code % styles.length];
}

function productFallbackLabel(product: IndexProduct) {
  // 没有可用外观图时，品牌名比单个首字母更容易辨识；保留型号兜底以兼容未治理记录。
  return (product.brand || product.model || "产品图片待补").trim();
}

function statusLabel(product: IndexProduct) {
  if (product.official_page_status === "found") return "官网页面可溯源";
  if (product.research_priority === "official_current") return "官方在售优先";
  if (product.research_priority === "recent_pending_check") return "近两年待核验";
  return "历史产品参考";
}

export default function ProductBrowser({
  categories,
  totalCount,
  brands,
  unknownBrandCount,
  initialSlices,
  fullIndexUrl,
}: Props) {
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
      .then((response) => {
        if (!response.ok) throw new Error("产品索引不可用");
        return response.json();
      })
      .then((data: { products: IndexProduct[] }) => {
        if (!cancelled) setFullIndex(data.products);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fullIndexUrl]);

  const seedProducts = useMemo(() => initialSlices.flatMap((slice) => slice.products), [initialSlices]);
  const products = fullIndex || seedProducts;
  const isFiltering = Boolean(search.trim() || categoryFilter || brandFilter || priorityFilter !== "all");
  const sorted = (items: IndexProduct[]) =>
    [...items].sort(
      (a, b) =>
        researchPriorityRank(a) - researchPriorityRank(b) ||
        (b.latest_published || "").localeCompare(a.latest_published || ""),
    );
  const filteredProducts = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sorted(
      products.filter((product) => {
        const brand = (product.brand || "").trim();
        const text = `${brand} ${product.model || ""} ${product.category || ""} ${product.canonical_id}`.toLowerCase();
        return (
          (!query || text.includes(query)) &&
          (!categoryFilter || product.category === categoryFilter) &&
          (!brandFilter || (brandFilter === UNKNOWN_BRAND_KEY ? !brand : brand === brandFilter)) &&
          (priorityFilter === "all" || product.research_priority === priorityFilter)
        );
      }),
    );
  }, [products, search, categoryFilter, brandFilter, priorityFilter]);
  const visibleProducts = isFiltering ? filteredProducts.slice(0, 30) : sorted(seedProducts).slice(0, 12);
  const productById = useMemo(
    () => new Map([...seedProducts, ...(fullIndex || [])].map((product) => [product.canonical_id, product])),
    [seedProducts, fullIndex],
  );
  const selectedProducts = selected
    .map((id) => productById.get(id))
    .filter((item): item is IndexProduct => Boolean(item));
  const attentionProducts = sorted(seedProducts).slice(0, 5);
  const compareHref = selected.length ? withBase(`/compare?ids=${selected.join(",")}`) : withBase("/compare");

  const toggleProduct = (id: string) =>
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= MAX_COMPARE
          ? current
          : [...current, id],
    );
  const resetFilters = () => {
    setSearch("");
    setCategoryFilter("");
    setBrandFilter("");
    setPriorityFilter("all");
  };

  return (
    <section id="workspace" className="workspace-shell">
      <div className="workspace-toolbar">
        <div>
          <p className="eyebrow">产品研究工作台</p>
          <h2>发现产品，建立对比</h2>
          <p>优先查看近两年有动态或可追溯官方页面的产品。</p>
        </div>
        <div className="workspace-search">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索品牌、型号或产品 ID"
            aria-label="搜索产品"
          />
          {isFiltering && (
            <button type="button" onClick={resetFilters} className="workspace-text-button">
              清除
            </button>
          )}
        </div>
      </div>

      <div className="workspace-layout">
        <aside className="workspace-filter-card">
          <div className="filter-section">
            <div className="filter-heading">
              <span>产品分类</span>
              <button type="button" onClick={() => setCategoryFilter("")}>全部</button>
            </div>
            <div className="filter-list filter-list--categories">
              {categories.map((category) => (
                <button
                  key={category.name}
                  type="button"
                  onClick={() => setCategoryFilter((current) => (current === category.name ? "" : category.name))}
                  className={categoryFilter === category.name ? "is-active" : ""}
                >
                  <span>{category.name}</span><em>{category.product_count}</em>
                </button>
              ))}
            </div>
          </div>
          <div className="filter-section">
            <div className="filter-heading"><span>研究优先级</span></div>
            <div className="filter-pills">
              <button type="button" className={priorityFilter === "official_current" ? "is-active" : ""} onClick={() => setPriorityFilter((value) => (value === "official_current" ? "all" : "official_current"))}>官网在售优先</button>
              <button type="button" className={priorityFilter === "recent_pending_check" ? "is-active" : ""} onClick={() => setPriorityFilter((value) => (value === "recent_pending_check" ? "all" : "recent_pending_check"))}>近两年待核验</button>
            </div>
          </div>
          <div className="filter-section">
            <div className="filter-heading"><span>重点品牌</span><button type="button" onClick={() => setBrandFilter("")}>重置</button></div>
            <div className="filter-list filter-list--brands">
              {brands.slice(0, 8).map((brand) => (
                <button key={brand.name} type="button" onClick={() => setBrandFilter((value) => (value === brand.name ? "" : brand.name))} className={brandFilter === brand.name ? "is-active" : ""}>
                  <span>{brand.name}</span><em>{brand.count}</em>
                </button>
              ))}
            </div>
            <button type="button" onClick={() => setBrandFilter(UNKNOWN_BRAND_KEY)} className="data-health-link">数据治理：{unknownBrandCount} 款待统一品牌</button>
          </div>
        </aside>

        <main className="workspace-results">
          <div className="results-heading">
            <div>
              <strong>{isFiltering ? `匹配到 ${filteredProducts.length} 款产品` : `优先展示 ${visibleProducts.length} 款产品`}</strong>
              <span>{fullIndex ? `全库共 ${totalCount} 款产品` : "正在加载完整产品库…"}</span>
            </div>
            <span className="results-status">{loadFailed ? "索引加载失败，请刷新重试" : "按研究优先级排序"}</span>
          </div>
          <div className="product-card-grid">
            {visibleProducts.map((product) => {
              const color = categoryStyle(product.category);
              const active = selected.includes(product.canonical_id);
              const imageSrc = product.card_image_path ? withBase(product.card_image_path) : null;
              return (
                <article key={product.canonical_id} className={`research-product-card ${active ? "is-selected" : ""}`}>
                  <button type="button" onClick={() => toggleProduct(product.canonical_id)} className="selection-toggle" aria-label={`${active ? "从对比中移除" : "加入对比"} ${productDisplayName(product)}`}>{active ? "✓" : "+"}</button>
                  <a href={withBase(`/product/${product.canonical_id}`)} className="research-product-link">
                    <div className="product-visual" style={{ background: color.bg, color: color.text }}>
                      {imageSrc && <img src={imageSrc} alt={`${productDisplayName(product)} 产品图片`} loading="lazy" decoding="async" onError={(event) => { event.currentTarget.hidden = true; event.currentTarget.nextElementSibling?.removeAttribute("hidden"); }} />}
                      <span hidden={Boolean(imageSrc)} className="product-visual-fallback" aria-label={`${productFallbackLabel(product)} 暂无产品图片`}>{productFallbackLabel(product)}</span>
                    </div>
                    <div className="product-copy">
                      <div className="product-meta"><span style={{ background: color.bg, color: color.text }}>{product.category}</span><time>{product.first_seen?.slice(0, 4) || "-"}</time></div>
                      <h3>{productDisplayName(product)}</h3>
                      <div className="product-foot"><span className={`priority-badge ${product.research_priority || "historical_reference"}`}>{statusLabel(product)}</span><span>{product.report_count || 0} 篇报告</span></div>
                    </div>
                  </a>
                </article>
              );
            })}
          </div>
          {visibleProducts.length === 0 && <div className="workspace-empty">没有符合当前筛选条件的产品。</div>}
        </main>

        <aside className="priority-panel">
          <div className="priority-panel-head"><div><span className="priority-star">★</span><strong>重点研究队列</strong></div><span>自动排序</span></div>
          <p>近两年新品，以及存在可追溯官网页面的产品，会优先进入此队列。</p>
          <ol>
            {attentionProducts.map((product, index) => (
              <li key={product.canonical_id}>
                <span className="priority-rank">{index + 1}</span>
                <a href={withBase(`/product/${product.canonical_id}`)}><strong>{productDisplayName(product)}</strong><small>{statusLabel(product)} · {product.latest_published || product.first_seen || "日期待补充"}</small></a>
              </li>
            ))}
          </ol>
          <a href={withBase("/teardown-details")} className="priority-panel-link">浏览研究资料库 →</a>
        </aside>
      </div>

      {selected.length > 0 && (
        <div className="compare-tray" aria-live="polite">
          <div className="compare-tray-summary"><strong>已选择 {selected.length} 款</strong><span>最多 {MAX_COMPARE} 款</span></div>
          <div className="compare-tray-items">{selectedProducts.map((product) => <button key={product.canonical_id} type="button" onClick={() => toggleProduct(product.canonical_id)}>{productDisplayName(product)} <span>×</span></button>)}</div>
          <button type="button" className="workspace-text-button" onClick={() => setSelected([])}>清空</button>
          <a href={compareHref} className={`compare-primary ${selected.length < 2 ? "is-disabled" : ""}`} aria-disabled={selected.length < 2} onClick={(event) => { if (selected.length < 2) event.preventDefault(); }}>开始对比 <span>→</span></a>
        </div>
      )}
    </section>
  );
}
