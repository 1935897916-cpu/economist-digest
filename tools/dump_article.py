#!/usr/bin/env python3
"""打印某篇文章的顶层文字块（用于编写精读注解时核对段落结构）。

用法：
    python tools/dump_article.py 2026-11-28 "Robots will have"
    python tools/dump_article.py 2026-11-28 --list        # 只列标题
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import build_reader  # noqa: E402
from markdown import render, plain_text  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        return
    issue_id, needle = sys.argv[1], sys.argv[2]
    norm = issue_id.replace(".", "-")
    issue = next((i for i in build.load_issues()
                  if i.issue.replace(".", "-") == norm), None)
    if not issue:
        print("找不到期号", issue_id)
        return

    if needle == "--list":
        for a in issue.articles:
            print(f"{a.section} | {a.title} | {a.slug} | {a.words}词")
        return

    art = next((a for a in issue.articles if needle.lower() in a.title.lower()), None)
    if not art:
        print("找不到文章", needle)
        return

    blocks = build_reader.split_blocks(render(art.body))
    texts = [(k, h) for k, h in blocks if k in ("p", "quote", "list")]
    figs = [h for k, h in blocks if k == "figure"]
    print(f"# {art.title}\n# section={art.section}\n# slug={art.slug}")
    print(f"# 文字块 {len(texts)} 个，图片 {len(figs)} 个\n")
    for i, (kind, html) in enumerate(texts, 1):
        print(f"[{i}] ({kind}) {plain_text(html)}")
        print()


if __name__ == "__main__":
    main()
