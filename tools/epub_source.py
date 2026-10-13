"""EPUB → 内容源（Markdown + 图片文件）。

被 tools/fetch_upstream.py（Actions 定时抓取）与 tools/extract_issue.py
（本地手动提取）共用，避免两套逻辑漂移。

输出布局：
    content/2026-10-10.md          每期一个 Markdown
    content/2026-10-10/*.jpg       该期图片（与 md 同级目录）

Markdown 中的图片写作 ![题图](2026-10-10/xxx.jpg)，相对于 content/，
由 build.py 改写为站点路径。
"""
from __future__ import annotations

import base64
import html as htmllib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# 清洗：按 class 精确剥离的噪声（与 te-reader 同一套规则，已实测验证）
DROP_CLASSES = [
    "ad_h1", "ad_div", "ad_li", "ad_image",       # 整页广告
    "link_navbar", "producer_link", "origin_link",  # 下载推广页脚
    "mastheadImage_div", "toc_ul", "sec_index_ul",
]
# 已提取为结构化字段、需从正文移除的标题区
EXTRACT_CLASSES = [
    "te_section_title", "te_article_title", "te_article_rubric",
    "te_article_datePublished", "te_fly_span",
]
# 封面与广告图标，不进正文
COVER_NAMES = ("cover.jpg", "mastheadimage.jpg", "duolingo.png",
               "notability.png", "ereader.png", "en_dic.png")


@dataclass
class ExtractedIssue:
    issue: str
    markdown: str
    images: dict[str, bytes] = field(default_factory=dict)   # 文件名 -> 二进制
    articles: int = 0
    sections: int = 0


# ---------------- 文本工具 ----------------

def strip_tags(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", htmllib.unescape(text)).strip()


def _human_date(issue: str) -> str:
    try:
        y, m, d = (int(x) for x in issue.split("."))
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November",
                  "December"]
        suffix = "th" if 4 <= d % 100 <= 20 else {1: "st", 2: "nd",
                                                  3: "rd"}.get(d % 10, "th")
        return f"{months[m - 1]} {d}{suffix} {y}"
    except (ValueError, IndexError):
        return issue


# ---------------- EPUB 定位 ----------------

def _find_opf(zf: zipfile.ZipFile) -> str:
    if "META-INF/container.xml" in zf.namelist():
        xml = zf.read("META-INF/container.xml").decode("utf-8", "replace")
        m = re.search(r'full-path="([^"]+)"', xml)
        if m:
            return m.group(1)
    for n in zf.namelist():
        if n.lower().endswith(".opf"):
            return n
    raise ValueError("EPUB 中找不到 OPF")


class EpubSource:
    def __init__(self, epub_path: Path):
        self.zf = zipfile.ZipFile(epub_path)
        opf_path = _find_opf(self.zf)
        self.opf = self.zf.read(opf_path).decode("utf-8", "replace")
        self.base = str(Path(opf_path).parent).replace("\\", "/")

        self.manifest: dict[str, str] = {}
        for m in re.finditer(r"<item\s+([^>]*?)/?>", self.opf, re.S):
            attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))
            if "id" in attrs and "href" in attrs:
                self.manifest[attrs["id"]] = attrs["href"]

        spine = re.search(r"<spine[^>]*>(.*?)</spine>", self.opf, re.S)
        self.spine = (re.findall(r'idref="([^"]+)"', spine.group(1))
                      if spine else [])

    def spine_files(self) -> list[str]:
        out = []
        for idref in self.spine:
            href = self.manifest.get(idref)
            if not href:
                continue
            name = f"{self.base}/{href}" if self.base else href
            out.append(name.replace("//", "/"))
        return out

    def read(self, name: str) -> str:
        try:
            return self.zf.read(name.replace("//", "/")).decode("utf-8",
                                                                 "replace")
        except KeyError:
            return ""

    def read_bytes(self, name: str) -> bytes:
        for candidate in (name.replace("//", "/"),
                          name.lstrip("./").replace("../", ""),
                          f"{self.base}/{name}"):
            try:
                return self.zf.read(candidate)
            except KeyError:
                continue
        return b""

    def cover(self) -> bytes:
        m = re.search(r"<item\s+[^>]*properties\s*=\s*[\"'][^\"']*cover-image",
                      self.opf, re.I)
        if m:
            attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(0)))
            if "href" in attrs:
                return self.read_bytes(attrs["href"])
        for n in self.zf.namelist():
            base = Path(n).name.lower()
            if base == "cover.jpg":
                return self.zf.read(n)
        return b""

    def close(self) -> None:
        self.zf.close()


# ---------------- 章节清洗 ----------------

class ChapterCleaner:
    """把章节 HTML 转成 Markdown，保留图片位置。"""

    def __init__(self, src: EpubSource, img_prefix: str,
                 images: dict[str, bytes], keep_images: bool = True):
        self.src = src
        self.img_prefix = img_prefix
        self.images = images
        self.keep_images = keep_images

    def clean(self, html_text: str) -> tuple[str, str, str, list[str]] | None:
        """返回 (栏目, 标题, 正文Markdown, 图片文件��列表)。"""
        section = self._field(html_text, "te_section_title")
        title = self._field(html_text, "te_article_title")
        rubric = self._field(html_text, "te_article_rubric")

        if not title:
            m = re.search(r"<title>(.*?)</title>", html_text, re.S)
            if m:
                title = strip_tags(m.group(1))

        m = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.S | re.I)
        body = m.group(1) if m else html_text

        used_images: list[str] = []
        body = self._strip_noise(body)
        body = self._extract_fields(body)
        body = self._links_to_text(body)
        body = self._images(body, used_images)
        body = self._to_markdown(body)

        text = strip_tags(body)
        if len(text) < 200:
            return None
        if title and title.lower() in ("ad_page", "book_toc", "cover"):
            return None
        if "This article was downloaded by" in text:
            return None

        if rubric and rubric != title:
            body = f"*{rubric}*\n\n{body}"
        return (section, title, body.strip(), used_images)

    # -- 字段提取 --
    @staticmethod
    def _field(html_text: str, cls: str) -> str:
        m = re.search(rf'class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)<',
                      html_text, re.S)
        return strip_tags(m.group(1)) if m else ""

    # -- 剥离噪声 --
    def _strip_noise(self, body: str) -> str:
        for cls in DROP_CLASSES:
            body = re.sub(
                rf"<(\w+)([^>]*\bclass\s*=\s*[\"'][^\"']*\b{cls}\b[^\"']*"
                rf"[\"'][^>]*)>.*?</\1>", "", body, flags=re.S | re.I)
            body = re.sub(
                rf"<\w+[^>]*\bclass\s*=\s*[\"'][^\"']*\b{cls}\b[^\"']*"
                rf"[\"'][^>]*/?>", "", body, flags=re.I)
        return body

    def _extract_fields(self, body: str) -> str:
        for cls in EXTRACT_CLASSES:
            body = re.sub(
                rf"<(p|h1|h2|h3|div|span)\b[^>]*class\s*=\s*[\"'][^\"']*\b"
                rf"{cls}\b[^\"']*[\"'][^>]*>.*?</\1>", "", body,
                flags=re.S | re.I)
            body = re.sub(
                rf"<(span|b)\b[^>]*class\s*=\s*[\"'][^\"']*\b{cls}\b[^\"']*"
                rf"[\"'][\"'][^>]*>[^<]*</\1>\s*(<br\s*/?>)?", "", body,
                flags=re.S | re.I)
        body = re.sub(r"\s+data-[\w-]+\s*=\s*\"[^\"]*\"", "", body)
        return body

    @staticmethod
    def _links_to_text(body: str) -> str:
        """内链只保留文字：<a href=...>文字</a> -> 文字。"""
        body = re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", body, flags=re.S | re.I)
        return body

    # -- 图片 --
    def _images(self, body: str, used: list[str]) -> str:
        """把 <img> 换成 Markdown 图片，并抽取二进制。"""
        if not self.keep_images:
            return re.sub(r"<img\b[^>]*>", "", body, flags=re.I)

        def _sub(m: re.Match) -> str:
            tag = m.group(0)
            src_m = re.search(r'src="([^"]+)"', tag)
            if not src_m:
                return ""
            ref = src_m.group(1)
            if Path(ref).name.lower() in COVER_NAMES:
                return ""                      # 跳过广告图标
            data = self.src.read_bytes(ref)
            if not data:
                # 标题图相对 EPUB 根目录存放时按文件名再找一次
                data = self._find_by_basename(ref)
            if not data:
                return ""
            name = Path(ref).name
            self.images[name] = data
            used.append(name)
            alt = "题图" if 'te_head_image' in tag else "图"
            return f"\n\n![{alt}]({self.img_prefix}/{name})\n\n"

        return re.sub(r"<img\b[^>]*>", _sub, body, flags=re.I)

    def _find_by_basename(self, ref: str) -> bytes:
        base = Path(ref).name
        for n in self.src.zf.namelist():
            if Path(n).name == base:
                try:
                    return self.src.zf.read(n)
                except KeyError:
                    continue
        return b""

    # -- 转 Markdown --
    def _to_markdown(self, body: str) -> str:
        # 段落边界
        body = re.sub(r"</p>|</div>|</h[1-6]>|</blockquote>|</li>|</figcaption>",
                      "\n\n", body, flags=re.I)
        body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
        body = re.sub(r"<li\b[^>]*>", "- ", body, flags=re.I)
        body = re.sub(r"<blockquote\b[^>]*>", "> ", body, flags=re.I)
        body = re.sub(r"<[^>]+>", " ", body)
        body = htmllib.unescape(body)
        # 归一化空白
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n[ \t]+", "\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()


# ---------------- 主入口 ----------------

def extract(epub_path: Path, issue: str, source: str,
            keep_images: bool = True) -> ExtractedIssue:
    """解析 EPUB，产出 Markdown 与图片二进制。

    Markdown 中的图片路径形如 2026-10-10/xxx.jpg，相对 content/ 目录。
    """
    img_prefix = issue.replace(".", "-")
    src = EpubSource(epub_path)
    images: dict[str, bytes] = {}

    cover = src.cover()
    if cover:
        images["cover.jpg"] = cover

    cleaner = ChapterCleaner(src, img_prefix, images, keep_images)
    groups: dict[str, list[tuple[str, str]]] = {}
    order: list[str] = []
    count = 0

    for name in src.spine_files():
        base = Path(name).name.lower()
        if ("ad_page" in base or "book_toc" in base
                or base.startswith("cover")):
            continue
        html_text = src.read(name)
        if not html_text:
            continue
        art = cleaner.clean(html_text)
        if not art:
            continue
        sec, title, body, _ = art
        sec = sec or "Articles"
        if sec not in groups:
            groups[sec] = []
            order.append(sec)
        groups[sec].append((title, body))
        count += 1

    src.close()

    words = sum(len(strip_tags(b).split()) for items in groups.values()
                for _, b in items)
    minutes = max(1, round(words / 220))

    lines = [
        "---",
        f'issue: "{issue}"',
        f"date: {issue}",
        f'title: "The Economist · {_human_date(issue)}"',
        f'source: "{source}"',
        f"articles: {count}",
        f"minutes: {minutes}",
        "---",
        "",
    ]
    if cover:
        lines.append(f"![封面]({img_prefix}/cover.jpg)")
        lines.append("")
    for sec in order:
        lines.append(f"## {sec}")
        lines.append("")
        for title, body in groups[sec]:
            lines.append(f"### {title}")
            lines.append("")
            lines.append(body)
            lines.append("")

    return ExtractedIssue(
        issue=issue,
        markdown="\n".join(lines).rstrip() + "\n",
        images=images,
        articles=count,
        sections=len(order),
    )