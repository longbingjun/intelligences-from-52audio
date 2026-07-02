// 分类筛选 + 角色透镜（子级详情页）
(function () {
  function initFilterBar() {
    var bar = document.querySelector(".filter-bar");
    if (!bar) return;
    var buttons = bar.querySelectorAll(".filter-btn");
    var cards = document.querySelectorAll("[data-category]");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        buttons.forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        var target = btn.getAttribute("data-filter");
        cards.forEach(function (card) {
          card.style.display = (target === "__all__" || card.getAttribute("data-category") === target) ? "" : "none";
        });
      });
    });
  }

  function initRoleLens() {
    var bar = document.getElementById("role-lens");
    if (!bar || !window.ROLE_LENSES) return;
    var sections = document.querySelectorAll(".view-section");

    function applyLens(lensKey) {
      var cfg = window.ROLE_LENSES[lensKey];
      if (!cfg) return;
      var allowed = cfg.sections || [];
      sections.forEach(function (sec) {
        var id = sec.getAttribute("data-section");
        sec.style.display = allowed.indexOf(id) >= 0 ? "" : "none";
      });
    }

    bar.querySelectorAll(".lens-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        bar.querySelectorAll(".lens-btn").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        applyLens(btn.getAttribute("data-lens"));
      });
    });

    var active = bar.querySelector(".lens-btn.active");
    applyLens(active ? active.getAttribute("data-lens") : "pm");
  }

  document.addEventListener("DOMContentLoaded", function () {
    initFilterBar();
    initRoleLens();
  });
})();
