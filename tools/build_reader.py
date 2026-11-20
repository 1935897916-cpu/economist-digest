#!/usr/bin/env python3
"""精读版构建入口：生成英中对照独立页。

用法：
    python tools/build_reader.py --out site

与 tools/build.py 完全独立：
  - 不清空输出目录，只增量写 site/reading/
  - 不调用 render_issue_body()，现有 19 期页面输出不受影响
  - 无注解的期自动跳过（自动更新链路不会被卡死）

产物：
    site/reading/<期号>/index.html            本期精读目录
    site/reading/<期号>/<文章slug>/index.html  单篇对照页
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
from markdown import render  # noqa: E402
import annotations as annot  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 顶层块切分：渲染输出中每个块独立成行，但列表/引用可能多行，
# 用非贪婪匹配保证按块切。
_BLOCK_RE = re.compile(
    r"(<figure>.*?</figure>|<blockquote>.*?</blockquote>"
    r"|<(?:ul|ol)>.*?</(?:ul|ol)>|<p>.*?</p>|<hr>)", re.S)

# 资源指纹覆盖精读页用到的全部文件
_FINGERPRINT_FILES = ("style.css", "reader.js",
                      "reader-bilingual.css", "reader-bilingual.js")


def reader_version() -> str:
    digest = hashlib.sha256()
    for name in _FINGERPRINT_FILES:
        p = build.ASSETS_DIR / name
        if p.is_file():
            digest.update(p.read_bytes())
    return digest.hexdigest()[:8]


def split_blocks(rendered: str) -> list[tuple[str, str]]:
    """把渲染 HTML 切成顶层块列表，返回 [(kind, html)]。
    kind: p / quote / list / figure / hr"""
    blocks: list[tuple[str, str]] = []
    for m in _BLOCK_RE.finditer(rendered):
        chunk = m.group(0)
        if chunk.startswith("<figure>"):
            kind = "figure"
        elif chunk.startswith("<blockquote>"):
            kind = "quote"
        elif chunk.startswith("<ul>") or chunk.startswith("<ol>"):
            kind = "list"
        elif chunk.startswith("<p>"):
            kind = "p"
        else:
            kind = "hr"
        blocks.append((kind, chunk))
    return blocks


def _infl_sup_pattern(term: str) -> re.Pattern:
    return annot._infl_pattern(term)


def inject_sup(en_html: str, terms: list[dict]) -> str:
    """在英文块的纯文本区按整词匹配，给词条首现处插入上标编号。
    只改动文本节点（按标签切分），不碰标签属性；找不到就静默跳过。"""
    if not terms:
        return en_html
    segs = re.split(r"(<[^>]+>)", en_html)
    used = {g["n"]: False for g in terms}
    for gi, seg in enumerate(segs):
        if seg.startswith("<"):
            continue
        for g in terms:
            if used[g["n"]]:
                continue
            m = _infl_sup_pattern(g.get("match") or g["term"]).search(seg)
            if m:
                sup = (f'<sup class="wg" data-g="{g["n"]}" '
                       f'role="button" tabindex="0">{g["n"]}</sup>')
                seg = seg[:m.end()] + sup + seg[m.end():]
                used[g["n"]] = True
        segs[gi] = seg
    return "".join(segs)


def _rewrite_img_src(fig_html: str, root: str) -> str:
    def _sub(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        return f'src="{root}assets/img/{src}"'
    return re.sub(r'src="([^"]+)"', _sub, fig_html)


def render_article(anno: dict, article, root: str) -> str:
    """渲染单篇精读正文：段落对照 + figure 跨栏。"""
    blocks = split_blocks(render(article.body))
    text_blocks = [b for b in blocks if b[0] in ("p", "quote", "list")]
    figures = [b for b in blocks if b[0] == "figure"]

    annot.validate(anno, article, len(text_blocks), len(figures))

    paras = {p["n"]: p for p in anno["paragraphs"]}
    figs = {f["n"]: f for f in anno.get("figures", [])}
    gloss = anno.get("glossary", [])
    gloss_by_n = {g["n"]: g for g in gloss}

    out: list[str] = []
    ti = 0
    fi = 0
    for kind, chunk in blocks:
        if kind == "figure":
            fi += 1
            fig_html = _rewrite_img_src(chunk, root)
            cap = figs.get(fi, {}).get("caption_zh", "")
            if cap:
                fig_html = re.sub(r"<figcaption>.*?</figcaption>",
                                  "<figcaption>" + html.escape(cap)
                                  + "</figcaption>", fig_html, flags=re.S)
                if "<figcaption>" not in fig_html:
                    fig_html = (fig_html.replace("</figure>",
                                 "<figcaption>" + html.escape(cap)
                                 + "</figcaption></figure>"))
            out.append(f'<figure class="fig">{fig_html[len("<figure>"):-len("</figure>")]}</figure>')
        elif kind == "hr":
            out.append('<hr class="r-hr">')
        else:
            ti += 1
            p = paras.get(ti)
            en = inject_sup(chunk, [gloss_by_n[g] for g in (p or {}).get("gloss", [])
                                    if g in gloss_by_n])
            zh = html.escape((p or {}).get("zh", ""))
            out.append(
                f'<div class="para" data-p="{ti}">'
                f'<div class="en">{en}</div>'
                f'<div class="zh">{zh}</div></div>')
    return "\n".join(out)


def render_vocab(gloss: list[dict]) -> str:
    items = []
    for g in gloss:
        note = ""
        if g.get("note"):
            note = f'<div class="v-note">{html.escape(g["note"])}</div>'
        items.append(
            f'<div class="v-item"><span class="v-n">{g["n"]}</span>'
            f'<span class="v-term">{html.escape(g["term"])}</span>'
            f'<span class="v-ph">{html.escape(g["phonetic"])}</span>'
            f'<span class="v-pos">{html.escape(g["pos"])}</span>'
            f'<span class="v-sense">{html.escape(g["sense"])}</span>'
            f"{note}</div>")
    return "\n".join(items)


def build_article_page(anno: dict, article, iss, tpl: dict[str, str],
                       root: str, ver: str, base_url: str) -> str:
    body = render_article(anno, article, root)
    gloss = anno.get("glossary", [])
    title = html.escape(article.title)
    title_zh = html.escape(anno.get("article_title_zh", ""))
    section = html.escape(article.section)

    issue_slug = iss.issue  # site/issues/<issue>/
    content = {
        "title": title,
        "title_zh": title_zh,
        "section": section,
        "body": body,
        "vocab": render_vocab(gloss),
        "gloss_count": str(len(gloss)),
        "index_href": root,
        "issue_href": root + "issues/" + issue_slug + "/",
        "toc_href": root + "reading/" + annot.issue_key(iss.issue) + "/",
        "theme_bar": build.theme_bar(),
        "footer": build.footer(base_url, root),
    }
    inner = build.fill(tpl["reader"], content)
    gloss_json = json.dumps({str(g["n"]): g for g in gloss},
                            ensure_ascii=False).replace("</", "<\\/")
    url = (base_url.rstrip("/") + "/reading/"
           + annot.issue_key(iss.issue) + "/" + article.slug + "/")
    return build.fill(tpl["base"], {
        "title": f"{title_zh} · 精读 · {build.SITE_TITLE}",
        "description": f"《经济学人》{iss.issue} 精读：{anno.get('article_title_zh', article.title)}",
        "canonical": url,
        "body": inner,
        "assets": root + "assets",
        "lang": "zh-CN",
        "atom_href": root + "atom.xml",
        "extra_head": (
            f'<link rel="stylesheet" href="{root}assets/'
            f'reader-bilingual.css?v={ver}">'
            f'<script src="{root}assets/reader-bilingual.js?v={ver}" defer>'
            f"</script>"
            f'<script type="application/json" id="glossary-data">'
            f"{gloss_json}</script>"
        ),
        "asset_ver": ver,
    })


def build_reading_index(issue_annos: dict[str, dict], iss, art_map: dict,
                        tpl: dict[str, str], root: str, ver: str,
                        base_url: str) -> str:
    rows = []
    for slug, anno in issue_annos.items():
        art = art_map[slug]
        rows.append(
            f'<li><a href="{html.escape(art.slug, quote=True)}/">'
            f'<span class="ttl">{html.escape(anno.get("article_title_zh", art.title))}</span>'
            f'<span class="en-ttl">{html.escape(art.title)}</span>'
            f'<span class="meta">{html.escape(art.section)} · {len(anno.get("glossary", []))} 条生词</span>'
            f"</a></li>")
    content = build.fill(tpl["reading_index"], {
        "heading": html.escape(f"精读目录 · {iss.issue}"),
        "count": str(len(issue_annos)),
        "items": "\n".join(rows),
        "issue_href": root + "issues/" + iss.issue + "/",
        "theme_bar": build.theme_bar(),
        "footer": build.footer(base_url, root),
    })
    return build.fill(tpl["base"], {
        "title": f"精读 · {iss.issue} · {build.SITE_TITLE}",
        "description": f"《经济学人》{iss.issue} 英中对照精读目录",
        "canonical": base_url.rstrip("/") + "/reading/" + annot.issue_key(iss.issue) + "/",
        "body": content,
        "assets": root + "assets",
        "lang": "zh-CN",
        "atom_href": root + "atom.xml",
        "extra_head": (
            f'<link rel="stylesheet" href="{root}assets/'
            f'reader-bilingual.css?v={ver}">'
        ),
        "asset_ver": ver,
    })


def main() -> int:
    ap = argparse.ArgumentParser(description="生成英中对照精读页")
    ap.add_argument("--out", default="site", help="站点输出目录（默认 site/）")
    ap.add_argument("--base-url", default="/",
                    help="站点根 URL（canonical 用）")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    if not out.is_dir():
        print(f"输出目录 {out} 不存在，请先运行 tools/build.py", file=sys.stderr)
        return 1

    tpl = {
        "base": (build.TEMPLATE_DIR / "base.html").read_text(encoding="utf-8"),
        "reader": (build.TEMPLATE_DIR / "reader.html").read_text(encoding="utf-8"),
        "reading_index": (build.TEMPLATE_DIR / "reading_index.html").read_text(encoding="utf-8"),
    }
    ver = reader_version()
    issues = build.load_issues()
    done = 0
    for iss in issues:
        annos = annot.load_for_issue(iss.issue)
        if not annos:
            continue
        art_map = {}
        for a in iss.articles:
            if a.title and a.title != a.section:
                art_map[a.slug] = a
        missing = [s for s in annos if s not in art_map]
        if missing:
            print(f"  ! {iss.issue}: 注解 slug 在正文中找不到: {missing}，跳过该期",
                  file=sys.stderr)
            continue

        base = out / "reading" / annot.issue_key(iss.issue)
        base.mkdir(parents=True, exist_ok=True)
        (base / "index.html").write_text(
            build_reading_index(annos, iss, art_map, tpl, "../../", ver,
                                args.base_url),
            encoding="utf-8")
        for slug, anno in annos.items():
            art = art_map[slug]
            d = base / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "index.html").write_text(
                build_article_page(anno, art, iss, tpl, "../../../", ver,
                                   args.base_url),
                encoding="utf-8")
            done += 1
        print(f"  · 精读 {iss.issue}: {len(annos)} 篇")
    print(f"精读构建完成：{done} 篇 → {out / 'reading'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
