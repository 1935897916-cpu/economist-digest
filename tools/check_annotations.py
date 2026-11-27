#!/usr/bin/env python3
"""校验某期全部精读注解（段落数、上标编号、词条命中）。

用法：python tools/check_annotations.py 2026-11-28
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import build_reader  # noqa: E402
import annotations  # noqa: E402
from markdown import render  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    norm = sys.argv[1].replace(".", "-")
    issue = next((i for i in build.load_issues()
                  if i.issue.replace(".", "-") == norm), None)
    if not issue:
        print("找不到期号", sys.argv[1])
        return

    d = annotations.annotations_dir(issue.issue)
    files = sorted(d.glob("*.json")) if d.is_dir() else []
    if not files:
        print("该期没有注解")
        return

    by_slug = {a.slug: a for a in issue.articles}
    ok = 0
    for p in files:
        anno = json.loads(p.read_text(encoding="utf-8"))
        slug = anno.get("article_slug", "")
        art = by_slug.get(slug)
        if not art:
            print(f"✗ {p.name}: 正文中找不到 slug {slug}")
            continue
        blocks = build_reader.split_blocks(render(art.body))
        tb = [b for b in blocks if b[0] in ("p", "quote", "list")]
        fg = [b for b in blocks if b[0] == "figure"]
        try:
            annotations.validate(anno, art, len(tb), len(fg))
        except ValueError as e:
            print(f"✗ {p.name}: {e}")
            continue
        # 中文段里夹带整块英文单词的粗查（译文中不应出现英文句子）
        eng = [x for x in anno["paragraphs"]
               if len("".join(ch for ch in x["zh"] if ch.isascii() and ch.isalpha())) > 40]
        warn = f"  ⚠ 第{[x['n'] for x in eng]}段疑似夹带英文" if eng else ""
        print(f"✓ {p.name}: {len(tb)}段 {len(fg)}图 {len(anno['glossary'])}词条{warn}")
        ok += 1
    print(f"\n通过 {ok}/{len(files)}")


if __name__ == "__main__":
    main()
