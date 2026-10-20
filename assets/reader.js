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

  /* 目录的滚动容器在两种布局下不是同一个元素：
     移动端是 .toc ol（有 max-height），侧栏布局是 .toc 本身。
     以前写死滚 ol，侧栏下 ol 没有溢出，等于什么都没滚，
     高亮项就跑出可视区了。这里改成找真正能滚的祖先。 */
  function scrollHost(el) {
    var n = el.parentElement;
    while (n && n !== document.body && n !== document.documentElement) {
      var st = window.getComputedStyle(n);
      if ((st.overflowY === "auto" || st.overflowY === "scroll") &&
          n.scrollHeight > n.clientHeight + 1) {
        return n;
      }
      n = n.parentElement;
    }
    return null;
  }

  // 用户正在手动翻目录时不要自动跳，否则会跟手指打架
  var tocTouchedAt = 0;
  var tocBox = document.querySelector(".toc");
  if (tocBox) {
    ["pointerdown", "touchstart", "wheel"].forEach(function (ev) {
      tocBox.addEventListener(ev, function () { tocTouchedAt = Date.now(); },
                             { passive: true });
    });
  }

  function revealInToc(link) {
    if (Date.now() - tocTouchedAt < 1800) return;   // 刚手动操作过，让用户自己滚
    var host = scrollHost(link);
    if (!host) return;
    var lr = link.getBoundingClientRect();
    var hr = host.getBoundingClientRect();
    var top = lr.top - hr.top + host.scrollTop;
    var visible = lr.top >= hr.top + 4 && lr.bottom <= hr.bottom - 4;
    if (!visible) {
      host.scrollTop = top - host.clientHeight / 2 + lr.height / 2;
    }
  }

  /* 高亮当前文章所属的栏目，让侧栏能看出读到哪个板块 */
  var lastSec = null;
  function setSection(link) {
    var sec = null;
    if (link) {
      var box = link.closest(".toc-sec");
      if (box) sec = box.querySelector(".toc-head");
    }
    if (sec === lastSec) return;
    if (lastSec) lastSec.classList.remove("sec-active");
    if (sec) sec.classList.add("sec-active");
    lastSec = sec;
  }

  function setActive(id) {
    if (id === lastId) return;
    if (lastId && links[lastId]) links[lastId].classList.remove("active");
    var link = id ? links[id] : null;
    if (link) {
      link.classList.add("active");
      revealInToc(link);
    }
    setSection(link);
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

  /* 顶栏是 sticky，高度随字号与是否换行变化；
     判定线必须在运行时实测，不能写死。 */
  var topbar = document.querySelector(".topbar");
  var barH = 52;
  var anchorMargin = 0;
  function measureBar() {
    if (topbar) barH = Math.round(topbar.getBoundingClientRect().height);
    // 标题上的 scroll-margin-top 决定了点进来后标题停在哪
    var probe = heads[0];
    if (probe) {
      anchorMargin = parseFloat(
        window.getComputedStyle(probe).scrollMarginTop) || 0;
    }
  }
  measureBar();

  function topOffset() {
    // 判定线必须**略大于**锚点补偿量。
    // 两者相等时，刚点进来的标题会被判在线上方 1px，高亮就停在前一条，
    // 看起来像「点了 A 却高亮 B」。
    return Math.max(barH + 14, anchorMargin + 6);
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

      // 判定线取顶栏实际高度 + 少量余量。
      // 写死 100px 时，窗口变窄/字号变大顶栏会变高，
      // 判定线就落进顶栏里，高亮提前跳到下一篇 —— 表现为「目录不准」。
      var offset = topOffset();
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
  // 旋转屏幕 / 改窗口大小后顶栏高度会变，重新测量并刷新高亮
  window.addEventListener("resize", function () {
    measureBar();
    onScroll();
  }, { passive: true });
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