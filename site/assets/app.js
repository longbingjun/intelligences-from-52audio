// 极简客户端交互：分类筛选 tab（列表页用）。
// 不依赖 fetch/本地 JSON（避免 file:// 协议下的 CORS 限制），
// 只对页面里已经渲染好的 .card 元素做显示/隐藏切换。
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
          if (target === "__all__" || card.getAttribute("data-category") === target) {
            card.style.display = "";
          } else {
            card.style.display = "none";
          }
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", initFilterBar);
})();
