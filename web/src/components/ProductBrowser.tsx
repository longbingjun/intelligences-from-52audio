import { useEffect, useMemo, useState } from "react";
import type { IndexProduct } from "../lib/types";
import { productDisplayName } from "../lib/types";
import { withBase } from "../lib/paths";

const UNKNOWN_BRAND_KEY = "__unknown__";
const TOP_BRAND_VISIBLE = 14;

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

const CATEGORY_COLORS: Record<string, { bg: string; text: string }> = {
  头戴式耳机: { bg: "#f3e8ff", text: "#7c3aed" },
  开放式耳机: { bg: "#e0f2f1", text: "#0f766e" },
  有线耳机: { bg: "#f1f5f9", text: "#475569" },
  真无线耳机TWS: { bg: "#eef3ff", text: "#1f3fbf" },
  颈挂式蓝牙耳机: { bg: "#fff3e0", text: "#b45309" },
  骨传导耳机: { bg: "#ffe4e6", text: "#be123c" },
};

function categoryTagStyle(name: string) {
  return CATEGORY_COLORS[name] || { bg: "#f1f5f9", text: "#475569" };
}

function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#eef3ff] px-3 py-1 text-sm text-[var(--primary-dark)]">
      {label}
      <button
        type="button"
        onClick={onRemove}
        aria-label="移除筛选"
        className="text-[var(--primary-dark)] hover:text-[var(--primary)]"
      >
        ×
      </button>
    </span>
  );
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
  const [showMoreBrands, setShowMoreBrands] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);

  // 首屏只内嵌了每个品类的一个小切片（用于默认状态的卡片行），完整的 1027 款
  // 产品轻量索引在挂载后才通过 fetch 拉取，用于搜索/筛选——绝不在构建期把全量
  // 索引内嵌进首页 HTML。
  useEffect(() => {
    let cancelled = false;
    fetch(fullIndexUrl)
      .then((res) => {
        if (!res.ok) throw new Error(`fetch product index failed: ${res.status}`);
        return res.json();
      })
      .then((data: { products: IndexProduct[] }) => {
        if (!cancelled) setFullIndex(data.products);
      })
      .catch((err) => {
        console.error("加载完整产品索引失败", err);
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fullIndexUrl]);

  const isFiltering = Boolean(search.trim() || categoryFilter || brandFilter);

  const visibleBrands = showMoreBrands ? brands : brands.slice(0, TOP_BRAND_VISIBLE);

  const filteredPool = useMemo(() => {
    if (!fullIndex) return [];
    const q = search.trim().toLowerCase();
    return fullIndex.filter((p) => {
      if (q) {
        const haystack = `${p.brand || ""} ${p.model || ""} ${p.category || ""}`.toLowerCase();
        if (!haystack.includes(q) && !p.canonical_id.toLowerCase().includes(q)) return false;
      }
      if (categoryFilter && p.category !== categoryFilter) return false;
      const brand = (p.brand || "").trim();
      if (brandFilter === UNKNOWN_BRAND_KEY) {
        if (brand) return false;
      } else if (brandFilter) {
        if (brand !== brandFilter) return false;
      }
      return true;
    });
  }, [fullIndex, search, categoryFilter, brandFilter]);

  // 已选产品可能来自默认卡片行（只有切片数据）或已加载的完整索引，两边都要能查到，
  // 这样在完整索引加载完成前从卡片行产生的选择也不会丢失展示信息。
  const productById = useMemo(() => {
    const map = new Map<string, IndexProduct>();
    initialSlices.forEach((slice) => slice.products.forEach((p) => map.set(p.canonical_id, p)));
    (fullIndex || []).forEach((p) => map.set(p.canonical_id, p));
    return map;
  }, [initialSlices, fullIndex]);

  const selectedProducts = useMemo(
    () => selected.map((id) => productById.get(id)).filter((p): p is IndexProduct => Boolean(p)),
    [selected, productById]
  );

  const compareHref =
    selected.length > 0
      ? withBase(`/compare?ids=${selected.join(",")}`)
      : withBase("/compare");

  const toggleProduct = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const clearSelection = () => setSelected([]);

  const selectAllFiltered = () => {
    setSelected(filteredPool.map((p) => p.canonical_id));
  };

  const toggleBrandFilter = (name: string) => {
    setBrandFilter((prev) => (prev === name ? "" : name));
  };

  return (
    <div className="space-y-5">
      {/* 搜索栏 */}
      <form
        onSubmit={(e) => e.preventDefault()}
        className="flex flex-wrap gap-3 rounded-2xl border border-[var(--line)] bg-white p-4 shadow-sm"
      >
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="输入品牌/型号关键词…"
          className="min-w-[220px] flex-1 rounded-xl border border-[var(--line)] px-3 py-2 text-sm outline-none focus:border-[var(--primary)]"
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-xl border border-[var(--line)] px-3 py-2 text-sm"
        >
          <option value="">类型: 不限</option>
          {categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name} ({c.product_count})
            </option>
          ))}
        </select>
        <button
          type="submit"
          className="rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--primary-dark)]"
        >
          搜索
        </button>
      </form>

      <div className="flex flex-col gap-5 lg:flex-row">
        {/* 侧边栏 */}
        <aside className="shrink-0 lg:w-60">
          <div className="rounded-2xl border border-[var(--line)] bg-white p-4 shadow-sm">
            <button
              type="button"
              onClick={() => setCategoryFilter("")}
              className={`block w-full rounded-lg px-2.5 py-1.5 text-left text-sm font-semibold ${
                categoryFilter === ""
                  ? "bg-[#eef3ff] text-[var(--primary-dark)]"
                  : "text-[var(--text)] hover:bg-[#f8faff]"
              }`}
            >
              全部产品 ({totalCount})
            </button>
            <div className="mt-1 flex flex-col gap-1">
              {categories.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  onClick={() => setCategoryFilter((prev) => (prev === c.name ? "" : c.name))}
                  className={`block w-full rounded-lg px-2.5 py-1.5 text-left text-sm ${
                    categoryFilter === c.name
                      ? "bg-[#eef3ff] font-semibold text-[var(--primary-dark)]"
                      : "text-[var(--muted)] hover:bg-[#f8faff]"
                  }`}
                >
                  {c.name} ({c.product_count})
                </button>
              ))}
            </div>

            <div className="mt-5 border-t border-[var(--line)] pt-4">
              <h3 className="m-0 text-sm font-semibold text-[var(--muted)]">热门品牌</h3>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {visibleBrands.map((b) => (
                  <button
                    key={b.name}
                    type="button"
                    onClick={() => toggleBrandFilter(b.name)}
                    className={`rounded-full border px-2.5 py-1 text-xs ${
                      brandFilter === b.name
                        ? "border-[var(--primary)] bg-[#eef3ff] text-[var(--primary-dark)] font-semibold"
                        : "border-[var(--line)] bg-white text-[var(--muted)] hover:bg-[#f8faff]"
                    }`}
                  >
                    {b.name} ({b.count})
                  </button>
                ))}
              </div>
              {brands.length > TOP_BRAND_VISIBLE && (
                <button
                  type="button"
                  onClick={() => setShowMoreBrands((v) => !v)}
                  className="mt-2 text-xs text-[var(--primary)] underline"
                >
                  {showMoreBrands ? "收起品牌 ▲" : "更多品牌 ▾"}
                </button>
              )}
              <button
                type="button"
                onClick={() => toggleBrandFilter(UNKNOWN_BRAND_KEY)}
                className={`mt-3 block w-fit rounded-full border px-2.5 py-1 text-xs ${
                  brandFilter === UNKNOWN_BRAND_KEY
                    ? "border-[var(--primary)] bg-[#eef3ff] text-[var(--primary-dark)] font-semibold"
                    : "border-dashed border-[var(--line)] bg-white text-[var(--muted)] hover:bg-[#f8faff]"
                }`}
              >
                未知品牌 ({unknownBrandCount})
              </button>
            </div>
          </div>
        </aside>

        {/* 主内容区 */}
        <div className="min-w-0 flex-1 space-y-5">
          {!isFiltering ? (
            <div className="flex flex-col gap-6">
              {initialSlices.map((slice) => {
                const color = categoryTagStyle(slice.category);
                const catInfo = categories.find((c) => c.name === slice.category);
                return (
                  <section
                    key={slice.category}
                    className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-sm"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <h3 className="m-0 flex items-center gap-2 text-lg font-bold">
                        <span
                          style={{ background: color.bg, color: color.text }}
                          className="rounded-full px-2.5 py-0.5 text-xs font-semibold"
                        >
                          {slice.category}
                        </span>
                        <span className="text-[var(--text)]">
                          共 {catInfo?.product_count ?? slice.products.length} 款
                        </span>
                      </h3>
                      <a
                        href={withBase(`/category/${encodeURIComponent(slice.category)}`)}
                        className="text-sm text-[var(--primary)] no-underline hover:underline"
                      >
                        查看全部对比 →
                      </a>
                    </div>
                    <div className="mt-4 flex gap-3 overflow-x-auto pb-1">
                      {slice.products.map((p) => (
                        <div
                          key={p.canonical_id}
                          className="relative w-56 flex-shrink-0 rounded-2xl border border-[var(--line)] bg-white p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
                        >
                          <label className="absolute right-3 top-3 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={selected.includes(p.canonical_id)}
                              onChange={() => toggleProduct(p.canonical_id)}
                              className="h-4 w-4"
                              aria-label={`选择 ${productDisplayName(p)}`}
                            />
                          </label>
                          <a
                            href={withBase(`/product/${p.canonical_id}`)}
                            className="block no-underline"
                          >
                            <div className="flex items-center justify-between pr-6">
                              <span
                                style={{ background: color.bg, color: color.text }}
                                className="rounded-full px-2 py-0.5 text-xs font-medium"
                              >
                                {p.category}
                              </span>
                              <span className="text-xs text-[var(--muted)]">{p.first_seen || ""}</span>
                            </div>
                            <div className="mt-2 font-semibold text-[var(--text)]">
                              {productDisplayName(p)}
                            </div>
                          </a>
                        </div>
                      ))}
                      {slice.products.length === 0 && (
                        <p className="text-sm text-[var(--muted)]">该品类暂无产品数据</p>
                      )}
                    </div>
                  </section>
                );
              })}
            </div>
          ) : (
            <div className="rounded-2xl border border-[var(--line)] bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  {search.trim() && (
                    <FilterChip label={`搜索: ${search.trim()}`} onRemove={() => setSearch("")} />
                  )}
                  {categoryFilter && (
                    <FilterChip
                      label={`类型: ${categoryFilter}`}
                      onRemove={() => setCategoryFilter("")}
                    />
                  )}
                  {brandFilter && (
                    <FilterChip
                      label={`品牌: ${brandFilter === UNKNOWN_BRAND_KEY ? "未知品牌" : brandFilter}`}
                      onRemove={() => setBrandFilter("")}
                    />
                  )}
                </div>
                <span className="text-sm text-[var(--muted)]">
                  {fullIndex ? (
                    `共匹配 ${filteredPool.length} 款`
                  ) : loadFailed ? (
                    <span className="text-[var(--warn)]">产品索引加载失败，请刷新重试</span>
                  ) : (
                    "产品索引加载中…"
                  )}
                </span>
              </div>

              <div className="mt-3 flex items-center gap-4 text-sm">
                <button
                  type="button"
                  onClick={selectAllFiltered}
                  disabled={!fullIndex}
                  className="text-[var(--primary)] underline disabled:cursor-not-allowed disabled:text-[var(--muted)] disabled:no-underline"
                >
                  全选当前结果
                </button>
                <button type="button" onClick={clearSelection} className="text-[var(--muted)] underline">
                  清空
                </button>
              </div>

              <div className="mt-3 grid max-h-[480px] grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2 lg:grid-cols-3">
                {!fullIndex && !loadFailed && (
                  <p className="col-span-full text-sm text-[var(--muted)]">产品索引加载中…</p>
                )}
                {fullIndex && filteredPool.length === 0 && (
                  <p className="col-span-full text-sm text-[var(--muted)]">
                    没有找到匹配的产品，试试更换关键词或筛选条件。
                  </p>
                )}
                {filteredPool.map((p) => {
                  const color = categoryTagStyle(p.category);
                  return (
                    <label
                      key={p.canonical_id}
                      className="flex cursor-pointer items-start gap-2 rounded-lg border border-transparent bg-[#fafbff] px-2 py-1.5 text-sm hover:border-[var(--line)]"
                    >
                      <input
                        type="checkbox"
                        checked={selected.includes(p.canonical_id)}
                        onChange={() => toggleProduct(p.canonical_id)}
                        className="mt-0.5"
                      />
                      <span>
                        <span
                          style={{ background: color.bg, color: color.text }}
                          className="mr-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium"
                        >
                          {p.category}
                        </span>
                        <span className="font-medium">{productDisplayName(p)}</span>
                        {!p.report_count && (
                          <span className="ml-1 text-xs text-[var(--warn)]">无报告</span>
                        )}
                      </span>
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 底部选中悬浮条 */}
      {selected.length > 0 && (
        <>
          <div className="h-20" aria-hidden="true" />
          <div className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--line)] bg-white/95 shadow-[0_-4px_16px_rgba(0,0,0,0.08)] backdrop-blur-md">
            <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-3 px-5 py-3">
              <span className="text-sm font-semibold text-[var(--text)]">已选 {selected.length} 款</span>
              <div className="flex max-h-16 max-w-[45%] flex-wrap gap-1.5 overflow-y-auto">
                {selectedProducts.map((p) => (
                  <button
                    key={p.canonical_id}
                    type="button"
                    onClick={() => toggleProduct(p.canonical_id)}
                    className="rounded-full bg-[#eef3ff] px-2.5 py-1 text-xs text-[var(--primary-dark)] hover:bg-[#dce6ff]"
                  >
                    {productDisplayName(p)} ×
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={clearSelection}
                className="text-sm text-[var(--muted)] underline"
              >
                清空
              </button>
              <div className="ml-auto flex flex-wrap gap-2">
                <a
                  href={compareHref}
                  className="rounded-full bg-[var(--primary)] px-4 py-2 text-sm font-medium text-white no-underline hover:bg-[var(--primary-dark)]"
                >
                  去对比 {selected.length} 款 →
                </a>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
