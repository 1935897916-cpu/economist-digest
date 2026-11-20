/* 精读页交互：词条弹卡。
   独立脚本，不触碰 reader.js；弹卡用 position:fixed，
   不新增滚动容器，不影响 window 滚动监听。 */
(function () {
  "use strict";

  var card, elTerm, elPh, elPos, elSense, elNote;
  var data = null;
  var hideTimer = null;

  function init() {
    card = document.getElementById("wg-card");
    if (!card) return;
    elTerm = document.getElementById("wg-term");
    elPh = document.getElementById("wg-ph");
    elPos = document.getElementById("wg-pos");
    elSense = document.getElementById("wg-sense");
    elNote = document.getElementById("wg-note");

    var script = document.getElementById("glossary-data");
    if (script) {
      try { data = JSON.parse(script.textContent); }
      catch (e) { data = null; }
    }

    // 事件委托：点按（含触屏）上标
    document.addEventListener("click", function (e) {
      var sup = e.target.closest("sup.wg");
      if (sup) { e.preventDefault(); show(sup); return; }
      if (!card.hidden && !card.contains(e.target)) hide();
    });

    // 键盘可达：Enter/Space 触发，Esc 关闭
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { hide(); return; }
      var sup = e.target.closest && e.target.closest("sup.wg");
      if (sup && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault(); show(sup);
      }
    });

    // 滚动即收起，避免弹卡漂移
    window.addEventListener("scroll", hide, { passive: true });
    window.addEventListener("resize", hide);
  }

  function show(sup) {
    if (!data) return;
    var g = data[sup.getAttribute("data-g")];
    if (!g) return;
    if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }

    elTerm.textContent = g.term;
    elPh.textContent = g.phonetic || "";
    elPos.textContent = g.pos || "";
    elSense.textContent = g.sense || "";
    if (g.note) {
      elNote.textContent = g.note;
      elNote.hidden = false;
    } else {
      elNote.hidden = true;
    }

    card.hidden = false;

    // 定位：上标正下方，越界翻转/收边
    var r = sup.getBoundingClientRect();
    var cw = card.offsetWidth, ch = card.offsetHeight;
    var margin = 10;
    var left = r.left + r.width / 2 - cw / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - cw - margin));
    var top = r.bottom + 8;
    if (top + ch > window.innerHeight - margin) {
      top = r.top - ch - 8;           // 翻到上标上方
      if (top < margin) top = margin;  // 实在放不下就贴顶
    }
    card.style.left = left + "px";
    card.style.top = top + "px";
  }

  function hide() {
    if (!card || card.hidden) return;
    hideTimer = setTimeout(function () { card.hidden = true; }, 60);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
