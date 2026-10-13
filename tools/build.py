#!/usr/bin/env python3
"""Economist Digest 构建脚本。

用法：
    python tools/build.py                      # 生成到 site/
    python tools/build.py --base-url https://user.github.io/repo/
    python tools/build.py --out dist --base-url https://example.com/

零第三方依赖（仅标准库），因此 GitHub Actions 里无需 pip install。

产物：
    site/index.html                    首页（期号列表，新的在上）
    site/issues/<期号>/index.html      每期只读页面
    site/feed.xml                      RSS 2.0（含全文）
    site/atom.xml                      Atom 1.0（含全文）
    site/assets/*                      样式与脚本
    site/issues.json                   机器可读索引
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import shutil
import sys
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from markdown import parse_front_matter, plain_text, render, slugify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"
TEMPLATE_DIR = ROOT / "templates"
ASSETS_DIR = ROOT / "assets"

SITE_TITLE = "The Economist Digest"
SITE_DESC = "每期《经济学人》的纯文字整理版，移动优先，可订阅。"
LANG = "en"

# 订阅源内最多放多少期全文。
# 单期全文含图约 425 KB；放 40 期会到 ~16.6 MB，多数 RSS 阅读器
# （NetNewsWire 5 MB、FreshRSS 10 MB、Inoreader 15 MB）会加载失败。
# 5 期约 2.1 MB，安全。旧期仍可在网页版翻阅，只是不进订阅源。
FEED_MAX_ISSUES = 5


# ---------------- 数据结构 ----------------

class Article:
    def __init__(self, title: str, body: str, section: str):
        self.title = title
        self.body = body
        self.section = section
        self.slug = slugify(title)
        self.words = len(plain_text(body).split())


class Issue:
    def __init__(self, meta: dict, body: str, path: Path):
        self.path = path
        self.meta = meta
        self.body = body

        # 期号优先取 issue 字段，其次日期，最后文件名
        self.issue = str(meta.get("issue") or meta.get("date") or path.stem)
        date_raw = str(meta.get("date") or self.issue)
        self.date = _parse_date(date_raw)
        self.title = str(meta.get("title") or f"The Economist · {self.issue}")
        self.source = str(meta.get("source") or "")
        self.articles: list[Article] = []
        self.sections: list[str] = []
        self.cover: str | None = None

        self._parse_body()

    def _parse_body(self) -> None:
        """按 `## 栏目` 与 `### 文章` 两级标题切分正文。

        正文之前若出现 cover.jpg，认作本期封面并从正文移除
        （渲染时单独放在期号头部，避免重复出现）。
        """
        lines = self.body.split("\n")
        for i, line in enumerate(lines):
            s = line.strip()
            if not s:
                continue
            if s.startswith("!["):
                m = re.match(r"^!\[[^\]]*\]\(([^)]+)\)$", s)
                if m and Path(m.group(1)).name.lower() == "cover.jpg":
                    self.cover = m.group(1)
                    lines = lines[:i] + lines[i + 1:]
                    break
            break
        self.body = "\n".join(lines)

        current_section = ""
        current_title: str | None = None
        buf: list[str] = []

        def flush():
            nonlocal current_title, buf
            if current_title is not None:
                art = Article(current_title, "\n".join(buf).strip(),
                              current_section)
                if art.body or art.title:
                    self.articles.append(art)
            current_title, buf = None, []

        for line in self.body.split("\n"):
            m = re.match(r"^##\s+(.*)$", line.strip())
            if m:
                flush()
                current_section = m.group(1).strip()
                if current_section not in self.sections:
                    self.sections.append(current_section)
                continue
            m = re.match(r"^###\s+(.*)$", line.strip())
            if m:
                flush()
                current_title = m.group(1).strip()
                continue
            if current_title is not None:
                buf.append(line)

        flush()

        # 没有 ### 层级时，退化为按栏目整段呈现
        if not self.articles and self.sections:
            for sec in self.sections:
                self.articles.append(Article(sec, "", sec))

    @property
    def minutes(self) -> int:
        words = sum(a.words for a in self.articles)
        return max(1, round(words / 220)) if words else 0

    @property
    def slug(self) -> str:
        return self.issue

    @property
    def url(self) -> str:
        return f"issues/{self.slug}/"

    def sort_key(self):
        return (self.date or dt.date.min, self.issue)


def _parse_date(raw: str) -> dt.date | None:
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", str(raw))
    if not m:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", str(raw))
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def human_date(d: dt.date | None, fallback: str) -> str:
    if not d:
        return fallback
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November",
              "December"]
    suffix = "th" if 4 <= d.day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(
        d.day % 10, "th")
    return f"{months[d.month - 1]} {d.day}{suffix} {d.year}"


# ---------------- 模板 ----------------

def load_templates() -> dict[str, str]:
    """载入模板。HTML 用 .html，订阅源用 .xml。"""
    tpl = {}
    specs = {"base": "base.html", "index": "index.html",
             "issue": "issue.html", "feed": "feed.xml", "atom": "atom.xml"}
    for key, filename in specs.items():
        p = TEMPLATE_DIR / filename
        if not p.is_file():
            raise FileNotFoundError(f"缺少模板: {p}")
        tpl[key] = p.read_text(encoding="utf-8")
    return tpl


def fill(template: str, mapping: dict[str, str]) -> str:
    """把 {{ key }} 占位符替换为值（HTML 已转义）。"""
    out = template
    for key, value in mapping.items():
        out = out.replace("{{ " + key + " }}", value)
    # 清掉未使用的占位符，避免输出裸 {{ }}
    out = re.sub(r"\{\{\s*\w+\s*\}\}", "", out)
    return out


# ---------------- 渲染 ----------------

def render_issue_body(issue: Issue) -> str:
    """把一期渲染为正文 HTML：栏目(h2) + 文章(h3) + 段落。"""
    parts: list[str] = []
    used: set[str] = set()

    def unique(base: str) -> str:
        cand, n = base, 2
        while cand in used:
            cand = f"{base}-{n}"
            n += 1
        used.add(cand)
        return cand

    for sec in issue.sections:
        sec_id = unique(slugify(sec))
        parts.append(f'<h2 id="{html.escape(sec_id, quote=True)}">'
                     + html.escape(sec) + "</h2>")
        for art in issue.articles:
            if art.section != sec:
                continue
            if art.title and art.title != sec:
                art_id = unique(art.slug)
                parts.append(f'<h3 id="{html.escape(art_id, quote=True)}">'
                             + html.escape(art.title) + "</h3>")
            if art.body:
                parts.append(render(art.body))
    return "\n".join(parts)


def build_toc(issue: Issue) -> str:
    """两级目录：栏目标题 + 该栏目下的文章，可点击跳转。

    桌面端常驻侧栏，移动端折叠为抽屉，由 CSS 与 reader.js 控制。
    """
    items = []
    for sec in issue.sections:
        sec_id = slugify(sec)
        arts = [a for a in issue.articles
                if a.section == sec and a.title and a.title != sec]
        subs = "".join(
            f'<li><a class="toc-art" href="#{html.escape(a.slug, quote=True)}">'
            + html.escape(a.title) + "</a></li>"
            for a in arts)
        items.append(
            f'<li class="toc-sec">'
            f'<a class="toc-head" href="#{html.escape(sec_id, quote=True)}">'
            + html.escape(sec) + "</a>"
            + (f'<ul class="toc-subs">{subs}</ul>' if subs else "")
            + "</li>")
    return "\n".join(items)


def build_index_page(issues: list[Issue], tpl: dict[str, str],
                     base_url: str) -> str:
    rows = []
    for i, iss in enumerate(issues):
        badge = ' <span class="new">NEW</span>' if i == 0 else ""
        thumb = ""
        if iss.cover:
            thumb = (f'<img class="thumb" loading="lazy" alt="" '
                     f'src="assets/img/{iss.issue.replace(".", "-")}'
                     f'/cover.jpg">')
        rows.append(
            '<li><a href="' + html.escape(iss.url, quote=True) + '">'
            + thumb
            + '<span class="num">' + html.escape(iss.issue) + "</span>"
            '<span class="ttl">' + html.escape(iss.title) + badge + "</span>"
            '<span class="meta">'
            + html.escape(human_date(iss.date, iss.issue))
            + f" · {len(iss.articles)} 篇 · {iss.minutes} 分钟"
            + "</span></a></li>")

    body = "\n".join(rows)
    # 首页位于站点根目录，相对前缀为空
    content = fill(tpl["index"], {
        "title": SITE_TITLE,
        "heading": SITE_TITLE,
        "intro": SITE_DESC,
        "count": str(len(issues)),
        "issues": body,
        "feed_href": "feed.xml",
        "theme_bar": theme_bar(),
        "footer": footer(base_url, ""),
    })
    return fill(tpl["base"], {
        "title": SITE_TITLE,
        "description": SITE_DESC,
        "canonical": base_url.rstrip("/") + "/",
        "body": content,
        "assets": "assets",
        "lang": LANG,
        "atom_href": "atom.xml",
        "extra_head": "",
    })


def rewrite_images(body: str, root: str, absolute_base: str = "") -> str:
    """把 Markdown 渲染后的图片路径改写为站点路径。

    内容源写作 ![](2026-10-10/xxx.jpg)，相对 content/ 目录；
    构建产物中图片位于 <root>assets/img/2026-10-10/xxx.jpg。
    absolute_base 非空时（RSS/Atom）改为绝对地址，
    否则阅读器无法加载图片。
    """
    import re

    def _sub(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        prefix = absolute_base.rstrip("/") + "/" if absolute_base else root
        return f'src="{prefix}assets/img/{src}"'

    return re.sub(r'src="([^"]+)"', _sub, body)


def build_issue_page(iss: Issue, tpl: dict[str, str], base_url: str) -> str:
    url = base_url.rstrip("/") + "/" + iss.url
    toc = build_toc(iss)
    # 期号页位于 issues/<期号>/ 下，回到站点根需上溯两级
    root = "../../"
    prose = rewrite_images(render_issue_body(iss), root)

    # 封面：内容源里写在正文之前的第一张图
    cover_html = ""
    if iss.cover:
        cover_html = (
            f'<img class="issue-cover" src="{root}assets/img/'
            f'{iss.issue.replace(".", "-")}/cover.jpg" alt="" '
            'fetchpriority="high">')

    content = fill(tpl["issue"], {
        "eyebrow": "The Economist",
        "heading": html.escape(iss.title),
        "meta": (
            f"<span>{html.escape(human_date(iss.date, iss.issue))}</span>"
            f"<span>{len(iss.articles)} 篇</span>"
            f"<span>约 {iss.minutes} 分钟</span>"
            + (f"<span>来源 {html.escape(iss.source)}</span>"
               if iss.source else "")
        ),
        "toc": toc,
        "prose": prose,
        "cover": cover_html,
        "index_href": root,
        "feed_href": root + "feed.xml",
        "theme_bar": theme_bar(),
        "footer": footer(base_url, root),
    })

    return fill(tpl["base"], {
        "title": f"{iss.title} · {SITE_TITLE}",
        "description": f"{SITE_TITLE} {iss.issue}",
        "canonical": url,
        "body": content,
        "assets": root + "assets",
        "lang": LANG,
        "atom_href": root + "atom.xml",
        "extra_head": "",
    })


def theme_bar() -> str:
    return (
        '<div class="themebar" id="themebar" role="group" aria-label="主题">'
        '<button class="tbtn" data-theme-btn="light" aria-pressed="false"'
        ' title="浅色">浅</button>'
        '<button class="tbtn" data-theme-btn="dark" aria-pressed="false"'
        ' title="深色">深</button>'
        '<button class="tbtn" data-theme-btn="sepia" aria-pressed="false"'
        ' title="羊皮纸">羊</button>'
        "</div>")


def footer(base_url: str, root: str = "") -> str:
    """页脚。root 为回到站点根的相对前缀（首页为空，期号页为 '../../'）。"""
    year = dt.date.today().year
    return (
        '<div class="foot"><div class="wrap"><div class="row">'
        f"<span>© {year} {html.escape(SITE_TITLE)}</span>"
        '<span>内容版权归 The Economist 所有，仅供个人学习使用</span>'
        f'<a href="{root}feed.xml">RSS</a>'
        f'<a href="{root}atom.xml">Atom</a>'
        f'<a href="{root}index.html">往期</a>'
        "</div></div></div>")


# ---------------- RSS / Atom ----------------

def _rfc822(d: dt.date) -> str:
    return format_datetime(dt.datetime(d.year, d.month, d.day, 8, 0, 0,
                                       tzinfo=dt.timezone.utc))


def build_feed(issues: list[Issue], base_url: str, tpl: dict[str, str]) -> str:
    base = base_url.rstrip("/")
    items = []
    for iss in issues[:FEED_MAX_ISSUES]:
        url = f"{base}/{iss.url}"
        # RSS 中图片必须用绝对地址，否则阅读器不加载
        body_html = rewrite_images(render_issue_body(iss), "", base)
        summary = _summary(iss)
        items.append(f"""  <item>
    <title>{html.escape(iss.title)}</title>
    <link>{html.escape(url)}</link>
    <guid isPermaLink="true">{html.escape(url)}</guid>
    <pubDate>{_rfc822(iss.date) if iss.date else ''}</pubDate>
    <dc:creator>The Economist</dc:creator>
    <description>{html.escape(summary)}</description>
    <content:encoded><![CDATA[{body_html}]]></content:encoded>
  </item>""")

    return fill(tpl["feed"], {
        "title": html.escape(SITE_TITLE),
        "link": base + "/",
        "description": html.escape(SITE_DESC),
        "last_build": _rfc822(dt.date.today()),
        "items": "\n".join(items),
    })


def build_atom(issues: list[Issue], base_url: str, tpl: dict[str, str]) -> str:
    base = base_url.rstrip("/")
    updated = _iso(issues[0].date) if issues else _iso(dt.date.today())
    entries = []
    for iss in issues[:FEED_MAX_ISSUES]:
        url = f"{base}/{iss.url}"
        body_html = rewrite_images(render_issue_body(iss), "", base)
        entries.append(f"""  <entry>
    <title>{html.escape(iss.title)}</title>
    <link href="{html.escape(url)}"/>
    <id>{html.escape(url)}</id>
    <updated>{_iso(iss.date)}</updated>
    <published>{_iso(iss.date)}</published>
    <summary type="html">{html.escape(_summary(iss))}</summary>
    <content type="html">{html.escape(body_html)}</content>
  </entry>""")

    return fill(tpl["atom"], {
        "title": html.escape(SITE_TITLE),
        "subtitle": html.escape(SITE_DESC),
        "base": base + "/",
        "updated": updated,
        "entries": "\n".join(entries),
    })


def _iso(d: dt.date | None) -> str:
    d = d or dt.date.today()
    return f"{d.isoformat()}T08:00:00Z"


def _summary(iss: Issue) -> str:
    heads = [a.title for a in iss.articles if a.title and a.title != iss.issue]
    head = " · ".join(heads[:8])
    return (f"{iss.issue}｜{len(iss.articles)} 篇｜约 {iss.minutes} 分钟"
            + (f"｜{head}" if head else ""))


# ---------------- 主流程 ----------------

def load_issues() -> list[Issue]:
    issues: list[Issue] = []
    if not CONTENT_DIR.is_dir():
        return issues
    for path in sorted(CONTENT_DIR.glob("*.md")):
        meta, body = parse_front_matter(
            path.read_text(encoding="utf-8"))
        try:
            issues.append(Issue(meta, body, path))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 跳过无法解析的 {path.name}: {exc}", file=sys.stderr)
    issues.sort(key=lambda i: i.sort_key(), reverse=True)
    return issues


def _clean_dir(path: Path) -> None:
    """清空目录。Windows 上若有进程占用（如本地预览服务器），
    退化为逐个删除文件，避免整个构建失败。"""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
        return
    except OSError:
        pass
    # 逐文件删除，忽略被占用的文件（下次构建会覆盖）
    removed = 0
    for item in sorted(path.rglob("*"), reverse=True):
        try:
            if item.is_file() or item.is_symlink():
                item.unlink()
                removed += 1
            elif item.is_dir():
                item.rmdir()
        except OSError:
            continue
    if removed:
        print(f"  提示：{removed} 个旧文件被占用未能删除，已被新内容覆盖")


def build(out_dir: Path, base_url: str) -> int:
    issues = load_issues()
    if not issues:
        print("content/ 下没有期号文件，先生成至少一期", file=sys.stderr)
        return 1

    tpl = load_templates()

    _clean_dir(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "issues").mkdir(parents=True, exist_ok=True)

    # 静态资源
    if ASSETS_DIR.is_dir():
        shutil.copytree(ASSETS_DIR, out_dir / "assets")

    # 首页
    (out_dir / "index.html").write_text(
        build_index_page(issues, tpl, base_url), encoding="utf-8")

    # 每期页面
    for iss in issues:
        d = out_dir / "issues" / iss.slug
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            build_issue_page(iss, tpl, base_url), encoding="utf-8")

        # 复制该期图片到 assets/img/<期号>/
        src_dir = CONTENT_DIR / iss.issue.replace(".", "-")
        if src_dir.is_dir():
            dst_dir = out_dir / "assets" / "img" / iss.issue.replace(".", "-")
            if dst_dir.exists():
                shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)

    # 订阅源
    (out_dir / "feed.xml").write_text(
        build_feed(issues, base_url, tpl), encoding="utf-8")
    (out_dir / "atom.xml").write_text(
        build_atom(issues, base_url, tpl), encoding="utf-8")

    # 机器可读索引
    import json
    (out_dir / "issues.json").write_text(json.dumps({
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "count": len(issues),
        "issues": [{
            "issue": i.issue, "date": i.date.isoformat() if i.date else None,
            "title": i.title, "articles": len(i.articles),
            "minutes": i.minutes, "url": i.url,
        } for i in issues],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Pages 不需要 Jekyll 处理，禁用可避免 _config.yml 干扰
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"构建完成：{len(issues)} 期 → {out_dir}")
    for iss in issues[:3]:
        print(f"  · {iss.issue}  {len(iss.articles)} 篇  {iss.minutes} 分钟")
    if len(issues) > 3:
        print(f"  …… 另有 {len(issues) - 3} 期")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Economist Digest 静态站")
    ap.add_argument("--out", default="site", help="输出目录（默认 site/）")
    ap.add_argument("--base-url", default="/",
                    help="站点根 URL，RSS 需要绝对地址，"
                         "如 https://user.github.io/repo/")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    return build(out, args.base_url)


if __name__ == "__main__":
    sys.exit(main())
