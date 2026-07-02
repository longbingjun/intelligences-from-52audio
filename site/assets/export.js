// CSV 导出：成本透镜 BOM / 硬件透镜 specs
(function () {
  function escCsv(val) {
    var s = String(val == null ? "" : val);
    if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadCsv(filename, rows) {
    var bom = "\uFEFF";
    var body = rows.map(function (row) {
      return row.map(escCsv).join(",");
    }).join("\r\n");
    var blob = new Blob([bom + body], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function activeLens() {
    var btn = document.querySelector(".lens-btn.active");
    return btn ? btn.getAttribute("data-lens") : "pm";
  }

  function exportBom(data) {
    var cost = (data && data.cost) || {};
    var rows = [["部件类型", "型号/描述", "数量提示"]];
    (cost.major_parts || []).forEach(function (p) {
      rows.push([p, "", ""]);
    });
    (cost.chip_modules || []).forEach(function (c) {
      rows.push([c.part || "芯片", c.model || "", c.qty_hint || ""]);
    });
    (cost.packaging_notes || []).forEach(function (n) {
      rows.push(["包装/附件", n, ""]);
    });
  (cost.process_hints || []).forEach(function (n) {
      rows.push(["工艺", n, ""]);
    });
    if (rows.length === 1) return false;
    var name = (data.brand || "") + "_" + (data.model || data.id || "export");
    downloadCsv(name.replace(/\s+/g, "_") + "_bom.csv", rows);
    return true;
  }

  function exportSpecs(data) {
    var specs = ((data && data.hardware) || {}).specs || [];
    var rows = [["部件", "参数", "单位", "来源"]];
    specs.forEach(function (s) {
      rows.push([
        s.part || "",
        s.value || s.model || "",
        s.unit || "",
        s.source_ref || "",
      ]);
    });
    if (rows.length === 1) return false;
    var name = (data.brand || "") + "_" + (data.model || data.id || "export");
    downloadCsv(name.replace(/\s+/g, "_") + "_specs.csv", rows);
    return true;
  }

  function initExportButton() {
    var btn = document.getElementById("export-csv-btn");
    if (!btn || !window.EXPORT_DATA) return;
    btn.addEventListener("click", function () {
      var lens = activeLens();
      var ok = false;
      if (lens === "cost") ok = exportBom(window.EXPORT_DATA);
      else if (lens === "hardware") ok = exportSpecs(window.EXPORT_DATA);
      else {
        ok = exportBom(window.EXPORT_DATA) || exportSpecs(window.EXPORT_DATA);
      }
      if (!ok) alert("当前透镜下暂无可导出数据");
    });
  }

  document.addEventListener("DOMContentLoaded", initExportButton);
})();
