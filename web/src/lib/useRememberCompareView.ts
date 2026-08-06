import { useEffect } from "react";

const LAST_VIEW_KEY = "cost-compare-last-view";

/** Preserve the exact comparison URL so product details can return to it. */
export function useRememberCompareView(ids: string[]): void {
  const key = ids.join(",");
  useEffect(() => {
    try {
      const url = new URL(window.location.href);
      if (ids.length) url.searchParams.set("ids", key);
      else url.searchParams.delete("ids");
      sessionStorage.setItem(LAST_VIEW_KEY, url.pathname + url.search);
    } catch {
      // Browsers that disable sessionStorage keep the detail page's static fallback.
    }
    // key is a stable scalar representation of the ordered selection.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
