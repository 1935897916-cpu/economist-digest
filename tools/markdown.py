"""零依赖 Markdown 子集解析器。

只实现内容源需要的语法，避免引入第三方依赖：
  - ATX 标题（# ## ### ####）
  - 段落（空行分隔）
  - 行内：**粗体** *斜体* `代码` [链接](url)
  - 引用块（> 开头）
  - 无序/有序列表
  - 分隔线（---）
  - 自动识别 URL

HTML 全部转义，防止内容破坏页面结构。
"""
from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# 行内图片（与文字同段）
_IMAGE_INLINE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_AUTOLINK = re.compile(r"(?<![\"'=])(https?://[^\s<>\)\]]+)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
# 独占一行的图片：![alt](src)
_IMAGE_ONLY = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)$")


def _figure(text: str) -> str:
    """把独占成段的图片渲染为 <figure>，alt 作为图注。"""
    m = _IMAGE_ONLY.match(text)
    if not m:
        return "<p>" + _inline(text) + "</p>"
    alt, src = escape_html(m.group(1)), escape_html(m.group(2), quote=True)
    cap = f"<figcaption>{alt}</figcaption>" if m.group(1) else ""
    return f'<figure><img src="{src}" alt="{alt}" loading="lazy">{cap}</figure>'


def escape_html(text: str, quote: bool = False) -> str:
    return html.escape(text, quote=quote)


def _inline(text: str) -> str:
    """行内格式转换。先转义再应用标记，保证安全。"""
    out = escape_html(text)
    out = _INLINE_CODE.sub(
        lambda m: "<code>" + m.group(1) + "</code>", out)
    out = _IMAGE_INLINE.sub(
        lambda m: '<img src="' + m.group(2) + '" alt="' + m.group(1)
                  + '" loading="lazy">', out)
    out = _BOLD.sub(lambda m: "<strong>" + m.group(1) + "</strong>", out)
    out = _ITALIC.sub(lambda m: "<em>" + m.group(1) + "</em>", out)
    out = _LINK.sub(
        lambda m: '<a href="' + m.group(2) + '" rel="noopener">'
                  + m.group(1) + "</a>", out)
    out = _AUTOLINK.sub(
        lambda m: '<a href="' + m.group(1) + '" rel="noopener">'
                  + m.group(1) + "</a>", out)
    return out


def slugify(text: str) -> str:
    """生成锚点 ID。保留字母数字与连字符，中文保留原字符。"""
    s = re.sub(r"<[^>]+>", "", text)
    s = html.unescape(s).strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "", s)
    s = re.sub(r"[\s]+", "-", s.strip())
    return s or "section"


def render(markdown_text: str) -> str:
    """把 Markdown 渲染为 HTML 片段。

    返回的 HTML 中标题带 id 属性（由调用方保证唯一性）。
    """
    lines = (markdown_text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    list_stack: list[str] = []   # 'ul' / 'ol'
    in_quote = False
    quote_lines: list[str] = []

    def flush_para() -> None:
        if para:
            chunk = para[:]
            # 独占成段的图片 → figure
            while chunk and _IMAGE_ONLY.match(chunk[0].strip()):
                out.append(_figure(chunk.pop(0).strip()))
            if chunk:
                text = " ".join(p.strip() for p in chunk).strip()
                if text:
                    out.append("<p>" + _inline(text) + "</p>")
            para.clear()

    def flush_quote() -> None:
        nonlocal in_quote
        if in_quote and quote_lines:
            out.append("<blockquote><p>"
                       + _inline(" ".join(quote_lines)) + "</p></blockquote>")
        quote_lines.clear()
        in_quote = False

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        # 空行：段落边界
        if not stripped:
            flush_para()
            flush_quote()
            close_lists()
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para(); flush_quote(); close_lists()
            out.append("<hr>")
            continue

        # 标题
        m = _HEADING.match(stripped)
        if m:
            flush_para(); flush_quote(); close_lists()
            level = len(m.group(1))
            out.append(f'<h{level} data-h="{level}">'
                       + _inline(m.group(2)) + f"</h{level}>")
            continue

        # 引用
        if stripped.startswith(">"):
            flush_para(); close_lists()
            in_quote = True
            quote_lines.append(stripped.lstrip(">").strip())
            continue
        flush_quote()

        # 列表
        lm = re.match(r"^[-*+]\s+(.*)$", stripped)
        om = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if lm or om:
            flush_para()
            want = "ul" if lm else "ol"
            if not list_stack or list_stack[-1] != want:
                close_lists()
                out.append(f"<{want}>")
                list_stack.append(want)
            item = (lm or om).group(1)
            out.append("<li>" + _inline(item) + "</li>")
            continue
        close_lists()

        # 普通段落行
        para.append(stripped)

    flush_para(); flush_quote(); close_lists()
    return "\n".join(out)


# ---------------- front matter ----------------

def parse_front_matter(text: str) -> tuple[dict, str]:
    """解析文件开头的 --- ... --- 元数据块。

    支持标量（带或不带引号）与简单的 `- item` 列表。
    返回 (meta, body)。
    """
    meta: dict = {}
    body = text
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return meta, body

    block = m.group(1)
    body = text[m.end():]
    key: str | None = None
    collecting: list[str] | None = None

    for line in block.split("\n"):
        if not line.strip() or line.strip().startswith("#"):
            continue
        if collecting is not None:
            item = re.match(r"^\s+-\s+(.*)$", line)
            if item:
                collecting.append(_scalar(item.group(1)))
                continue
            meta[key] = collecting
            collecting = None
        kv = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            val = kv.group(2).strip()
            if val == "":
                collecting = []
                meta[key] = collecting
            else:
                meta[key] = _scalar(val)
    if collecting is not None and key:
        meta[key] = collecting
    return meta, body


def _scalar(value: str):
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d*\.\d+", v):
        return float(v)
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    return v


def plain_text(html_fragment: str) -> str:
    """取纯文本，用于摘要。"""
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()
