/* 阅读增强：主题切换、目录高亮、阅读进度、位置记忆。
   无广告、无统计、无第三方请求。 */
(function () {
  "use strict";

  var PREF_KEY = "econ-digest-theme";
  var TOC_KEY = "econ-digest-toc";

  /* ---------- 主题 ---------- */
  function applyTheme(mode) {
    var root = document.documentElement;
    if (mode === "auto") {
      root.removeAttribute("data-theme");
    } else {
      root.setAttribute("data-theme", mode);
    }
    var btns = document.querySelectorAll("[data-theme-btn]");
    for (var i = 0; i < btns.length; i++) {
      var on = btns[i].getAttribute("data-theme-btn") === mode;
      btns[i].setAttribute("aria-pressed", on ? "true" : "false");
      if (on) { btns[i].classList.add("active"); }
      else { btns[i].classList.remove("active"); }
    }
    try { localStorage.setItem(PREF_KEY, mode); } catch (e) {}
  }

  var saved = "auto";
  try { saved = localStorage.getItem(PREF_KEY) || "auto"; } catch (e) {}
  applyTheme(saved);

  var bar = document.getElementById("themebar");
  if (bar) {
    bar.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-theme-btn]");
      if (btn) applyTheme(btn.getAttribute("data-theme-btn"));
    });
  }

  /* ---------- 目录：桌面常驻展开，移动端默认折叠 ---------- */
  var toc = document.querySelector(".toc");
  if (toc) {
    var isDesktop = window.matchMedia("(min-width: 1000px)");
    var stored = null;
    try { stored = localStorage.getItem(TOC_KEY); } catch (e) {}

    function syncToc() {
      // 桌面端始终展开；移动端按用户偏好，默认折叠
      if (isDesktop.matches) {
        toc.open = true;
        toc.setAttribute("data-locked", "1");
      } else {
        toc.removeAttribute("data-locked");
        toc.open = stored === "open";
      }
    }
    syncToc();
    if (isDesktop.addEventListener) {
      isDesktop.addEventListener("change", syncToc);
    } else if (isDesktop.addListener) {
      isDesktop.addListener(syncToc);
    }
    toc.addEventListener("toggle", function () {
      if (toc.hasAttribute("data-locked")) return;
      try { localStorage.setItem(TOC_KEY, toc.open ? "open" : "closed"); }
      catch (e) {}
    });
  }

  /* ---------- 阅读进度 + 当前文章高亮 ---------- */
  var progress = document.getElementById("progress");
  // 文章用 h3，栏目用 h2；两者都参与定位，优先高亮更细粒度的文章
  var heads = [].slice.call(document.querySelectorAll(".prose h2[id], .prose h3[id]"));
  var links = {};
  var tocLinks = document.querySelectorAll('.toc a[href^="#"]');
  for (var j = 0; j < tocLinks.length; j++) {
    links[tocLinks[j].getAttribute("href").slice(1)] = tocLinks[j];
  }

  var lastId = null;
  var ticking = false;

  function setActive(id) {
    if (id === lastId) return;
    if (lastId && links[lastId]) links[lastId].classList.remove("active");
    if (id && links[id]) {
      links[id].classList.add("active");
      // 目录内部也滚动到可见处（移动端长目录时有用）
      var a = links[id];
      var list = a.closest("ol");
      if (list && list.scrollHeight > list.clientHeight) {
        var top = a.offsetTop;
        if (top < list.scrollTop || top > list.scrollTop + list.clientHeight - 40) {
          list.scrollTop = top - list.clientHeight / 2;
        }
      }
    }
    lastId = id;
  }

  /* ---------- 回到顶部 ---------- */
  var toTop = document.getElementById("to-top");
  var TO_TOP_AT = 600;          // 滚动超过这个距离才出现
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  if (toTop) {
    toTop.addEventListener("click", function () {
      try {
        window.scrollTo({
          top: 0,
          behavior: reduceMotion.matches ? "auto" : "smooth"
        });
      } catch (e) {
        window.scrollTo(0, 0);   // 老浏览器不支持 options
      }
      // 无障碍：按钮滚回顶部后会隐藏，把焦点交给期号标题，
      // 否则键盘用户的焦点会落在被隐藏的元素上。
      var h1 = document.querySelector(".issue-head h1");
      if (h1) {
        h1.setAttribute("tabindex", "-1");
        h1.focus({ preventScroll: true });
      }
    });
  }

  function onScroll() {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(function () {
      var doc = document.documentElement;
      var y = window.scrollY || doc.scrollTop || 0;
      var max = doc.scrollHeight - doc.clientHeight;
      var pct = max > 0 ? (doc.scrollTop / max) * 100 : 0;
      if (progress) progress.style.width = pct.toFixed(2) + "%";

      // 回顶按钮显隐
      if (toTop) {
        if (y > TO_TOP_AT) toTop.classList.add("show");
        else toTop.classList.remove("show");
      }

      var offset = 100;
      var current = null;
      for (var k = 0; k < heads.length; k++) {
        if (heads[k].getBoundingClientRect().top <= offset) {
          current = heads[k].id;
        } else {
          break;
        }
      }
      setActive(current);
      ticking = false;
    });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- 长文滚动定位：记住并恢复阅读位置 ---------- */
  var posKey = "econ-digest-pos:" + location.pathname;
  var restored = false;

  window.addEventListener("scroll", function () {
    if (restored) return;
    try { sessionStorage.setItem(posKey, String(window.scrollY)); } catch (e) {}
  }, { passive: true });

  window.addEventListener("load", function () {
    try {
      var y = parseInt(sessionStorage.getItem(posKey) || "0", 10);
      if (y > 240) {
        restored = true;
        window.scrollTo(0, y);
      }
    } catch (e) {}
  });
})();