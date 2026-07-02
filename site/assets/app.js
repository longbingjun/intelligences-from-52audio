// 分类筛选 + 角色透镜 + 搜索筛选 + 矩阵 tab
(function () {
  var LENS_KEY = "role-lens-v2";

  function initFilterBar() {
    var bar = document.querySelector(".filter-bar");
    if (!bar) return;
    var buttons = bar.querySelectorAll(".filter-btn");
    var cards = document.querySelectorAll("#card-grid .card, .card-grid .card");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        buttons.forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        applyAllFilters();
      });
    });

    function categoryFilter(card) {
      var active = bar.querySelector(".filter-btn.active");
      var target = active ? active.getAttribute("data-filter") : "__all__";
      return target === "__all__" || card.getAttribute("data-category") === target;
    }

    window.__categoryFilter = categoryFilter;
  }

  function initRoleLens() {
    var bar = document.getElementById("role-lens");
    if (!bar || !window.ROLE_LENSES) return;
    var sections = document.querySelectorAll(".view-section");
    var saved = null;
    try { saved = localStorage.getItem(LENS_KEY); } catch (e) {}

    function applyLens(lensKey, persist) {
      var cfg = window.ROLE_LENSES[lensKey];
      if (!cfg) return;
      var allowed = cfg.sections || [];
      sections.forEach(function (sec) {
        var id = sec.getAttribute("data-section");
        sec.style.display = allowed.indexOf(id) >= 0 ? "" : "none";
      });
      bar.querySelectorAll(".lens-btn").forEach(function (b) {
        b.classList.toggle("active", b.getAttribute("data-lens") === lensKey);
      });
      if (persist !== false) {
        try { localStorage.setItem(LENS_KEY, lensKey); } catch (e) {}
      }
    }

    bar.querySelectorAll(".lens-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyLens(btn.getAttribute("data-lens"));
      });
    });

    var initial = saved && window.ROLE_LENSES[saved] ? saved : null;
    if (!initial) {
      var active = bar.querySelector(".lens-btn.active");
      initial = active ? active.getAttribute("data-lens") : "pm";
    }
    applyLens(initial, false);
  }

  function initMatrixTabs() {
    var tabs = document.querySelectorAll(".matrix-tab");
    if (!tabs.length) return;
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        var idx = tab.getAttribute("data-matrix-tab");
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        document.querySelectorAll(".matrix-panel").forEach(function (p) {
          p.style.display = p.getAttribute("data-matrix-panel") === idx ? "" : "none";
        });
      });
    });
  }

  var searchIndex = null;

  function loadSearchIndex(path, cb) {
    if (!path) { cb([]); return; }
    fetch(path)
      .then(function (r) { return r.json(); })
      .then(function (data) { cb(data || []); })
      .catch(function () { cb([]); });
  }

  function cardMatchesSearch(card, keyword, brand, indexMap) {
    var id = card.getAttribute("data-id");
    var entry = indexMap[id];
    var kw = (keyword || "").trim().toLowerCase();
    var br = (brand || "").trim();

    if (br && card.getAttribute("data-brand") !== br) return false;
    if (!kw) return true;

    var hay = [
      card.getAttribute("data-brand"),
      card.getAttribute("data-model"),
      card.getAttribute("data-title"),
      card.getAttribute("data-category"),
      card.textContent,
    ].join(" ").toLowerCase();

    if (entry && entry.tags) {
      hay += " " + entry.tags.join(" ").toLowerCase();
    }
    return hay.indexOf(kw) >= 0;
  }

  function applyAllFilters() {
    var toolbar = document.querySelector(".search-toolbar");
    var cards = document.querySelectorAll("#card-grid .card");
    var emptyEl = document.getElementById("search-empty");
    if (!cards.length) return;

    var keyword = "";
    var brand = "";
    if (toolbar) {
      var kwEl = document.getElementById("search-keyword");
      var brEl = document.getElementById("search-brand");
      keyword = kwEl ? kwEl.value : "";
      brand = brEl ? brEl.value : "";
    }

    var indexMap = {};
    if (searchIndex) {
      searchIndex.forEach(function (e) { indexMap[e.id] = e; });
    }

    var catFn = window.__categoryFilter || function () { return true; };
    var visible = 0;
    cards.forEach(function (card) {
      var show = catFn(card) && cardMatchesSearch(card, keyword, brand, indexMap);
      card.style.display = show ? "" : "none";
      if (show) visible++;
    });
    if (emptyEl) emptyEl.style.display = visible === 0 ? "" : "none";
  }

  function initSearch() {
    var toolbar = document.querySelector(".search-toolbar");
    if (!toolbar) return;
    var path = toolbar.getAttribute("data-search-index");
    var kind = toolbar.getAttribute("data-list-kind");

    function bindInputs() {
      var kwEl = document.getElementById("search-keyword");
      var brEl = document.getElementById("search-brand");
      if (kwEl) kwEl.addEventListener("input", applyAllFilters);
      if (brEl) brEl.addEventListener("change", applyAllFilters);
    }

    loadSearchIndex(path, function (data) {
      if (kind) {
        searchIndex = data.filter(function (e) { return e.type === kind; });
      } else {
        searchIndex = data;
      }
      bindInputs();
    });
    bindInputs();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initFilterBar();
    initRoleLens();
    initMatrixTabs();
    initSearch();
  });
})();
