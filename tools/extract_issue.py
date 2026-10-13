#!/usr/bin/env python3
"""从本地 EPUB 生成一期内容源（Markdown + 图片）。

用法：
    python tools/extract_issue.py <path/to/xxx.epub> [--issue 2026.10.10]

issue 未指定时从文件名推断（支持 2026.10.10 / 2026-10-10 / 20261010）。

产物：
    content/<期号>.md
    content/<期号>/*.jpg
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from epub_source import extract  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = ROOT / "content"


def guess_issue(path: Path) -> str | None:
    m = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", path.stem)
    if not m:
        m = re.search(r"(\d{4})(\d{2})(\d{2})", path.stem)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def main() -> int:
    ap = argparse.ArgumentParser(description="从 EPUB 生成内容源")
    ap.add_argument("epub", help="EPUB 文件路径")
    ap.add_argument("--issue", help="期号，默认从文件名推断")
    ap.add_argument("--source", default="local", help="来源标记")
    ap.add_argument("--no-images", action="store_true", help="不提取图片")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的期号")
    args = ap.parse_args()

    epub = Path(args.epub)
    if not epub.is_file():
        print(f"找不到文件: {epub}", file=sys.stderr)
        return 1

    issue = args.issue or guess_issue(epub)
    if not issue:
        print("无法推断期号，请用 --issue 指定", file=sys.stderr)
        return 1

    md_path = CONTENT_DIR / f"{issue.replace('.', '-')}.md"
    img_dir = CONTENT_DIR / issue.replace(".", "-")
    if md_path.exists() and not args.force:
        print(f"{md_path.name} 已存在，加 --force 覆盖")
        return 1

    print(f"解析 {epub.name} ...")
    result = extract(epub, issue, args.source,
                     keep_images=not args.no_images)

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    md_path.write_text(result.markdown, encoding="utf-8")

    img_dir.mkdir(parents=True, exist_ok=True)
    for name, data in result.images.items():
        (img_dir / name).write_bytes(data)

    total_mb = sum(len(d) for d in result.images.values()) / 1024 / 1024
    print(f"✓ {md_path.name}")
    print(f"  {result.articles} 篇 / {result.sections} 栏目")
    print(f"  {len(result.images)} 张图片，{total_mb:.1f} MB → {img_dir.name}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())