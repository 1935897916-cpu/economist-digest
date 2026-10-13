#!/usr/bin/env python3
"""从上游仓库抓取最新一期并生成 content/*.md。

设计目标：在 GitHub Actions 中定时运行，实现"我不需要手动去 GitHub 查看"。

流程：
  1. 列出上游 01_economist/ 下的期号目录（含年份子目录）
  2. 与本地 content/ 比对，找出未收录的期号
  3. 下载 EPUB（多通道回退）→ 解析 → 清洗 → 转 Markdown
  4. 写入 content/YYYY-MM-DD.md
  5. 退出码 0 = 有新内容，1 = 无新内容（供 Actions 判断是否提交）

只用标准库，无需 pip install。

配置（环境变量）：
  UPSTREAM_REPO    上游仓库，默认 hehonghui/awesome-english-ebooks
  UPSTREAM_REF     分支，默认 master
  UPSTREAM_PATH    《经济学人》子目录，默认 01_economist
  CONTENT_DIR      本地内容目录，默认 ./content
  GITHUB_TOKEN     可选，提升 API 限额
  MAX_ISSUES       单次最多抓取几期，默认 1
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(os.environ.get("CONTENT_DIR", str(ROOT / "content")))

REPO = os.environ.get("UPSTREAM_REPO", "hehonghui/awesome-english-ebooks")
REF = os.environ.get("UPSTREAM_REF", "master")
BASE_PATH = os.environ.get("UPSTREAM_PATH", "01_economist")
MAX_ISSUES = int(os.environ.get("MAX_ISSUES", "1"))
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
# 是否抽取原文插图（《经济学人》的数据图表是内容的一部分，默认保留）
KEEP_IMAGES = os.environ.get("KEEP_IMAGES", "1") not in ("0", "false", "no")

API = "https://api.github.com"
UA = "economist-digest/1.0 (github-actions)"
DATE_RE = re.compile(r"(\d{4})\.(\d{2})\.(\d{2})")
DIR_RE = re.compile(r"^te_(\d{4}\.\d{2}\.\d{2})$")

# 清洗规则与 EPUB 解析统一放在 epub_source.py，此处不再重复定义


# ---------------- HTTP ----------------

def _request(url: str, accept: str | None = None,
             timeout: int = 90) -> tuple[int, bytes]:
    headers = {"User-Agent": UA}
    if accept:
        headers["Accept"] = accept
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionError(f"{type(e).__name__}: {e}") from e


def get_json(url: str, retries: int = 3):
    last = None
    for attempt in range(retries):
        try:
            status, body = _request(
                url, accept="application/vnd.github+json")
            if status == 200:
                return json.loads(body.decode("utf-8"))
            last = f"HTTP {status}"
            if status == 403:      # 限流：等一会儿再试
                wait = 5 * (attempt + 1)
                print(f"    API 限流，{wait}s 后重试", file=sys.stderr)
                time.sleep(wait)
        except ConnectionError as e:
            last = str(e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last}")


def list_dir(path: str) -> list[dict]:
    url = (f"{API}/repos/{REPO}/contents/{urllib.parse.quote(path)}"
           f"?ref={REF}&per_page=100")
    data = get_json(url)
    return data if isinstance(data, list) else []


def download_blob(sha: str, dest: Path) -> int:
    """通过 git blob API 下载任意大小文件（最可靠通道）。"""
    url = f"{API}/repos/{REPO}/git/blobs/{sha}"
    headers = {"User-Agent": UA, "Accept": "application/vnd.github.raw"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# ---------------- 期号发现 ----------------

def discover_issues() -> list[tuple[str, str, str]]:
    """返回 [(期号, 文件路径, blob_sha)]，按日期降序。"""
    found: dict[str, tuple[str, str, str]] = {}

    def scan(prefix: str, entries: list[dict]) -> None:
        for item in entries:
            if item.get("type") != "dir":
                continue
            m = DIR_RE.match(item["name"])
            if not m:
                continue
            issue = m.group(1)
            if issue in found:
                continue
            # 该期下的 epub
            try:
                files = list_dir(f"{prefix}/{item['name']}")
            except Exception as e:  # noqa: BLE001
                print(f"    列举 {item['name']} 失败: {e}", file=sys.stderr)
                continue
            for f in files:
                name = f.get("name", "")
                if f.get("type") == "file" and name.endswith(".epub"):
                    found[issue] = (issue, f"{prefix}/{item['name']}/{name}",
                                    f.get("sha"))
                    break

    try:
        top = list_dir(BASE_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"列举 {BASE_PATH} 失败: {e}", file=sys.stderr)
        return []

    scan(BASE_PATH, top)

    # 年份子目录（如 01_economist/2025/）
    for item in top:
        if item.get("type") == "dir" and re.fullmatch(r"\d{4}", item["name"]):
            try:
                sub = list_dir(f"{BASE_PATH}/{item['name']}")
            except Exception:  # noqa: BLE001
                continue
            scan(f"{BASE_PATH}/{item['name']}", sub)

    return sorted(found.values(), key=lambda x: x[0], reverse=True)


def local_issues() -> set[str]:
    if not CONTENT_DIR.is_dir():
        return set()
    out = set()
    for p in CONTENT_DIR.glob("*.md"):
        text = p.read_text(encoding="utf-8")[:2000]
        m = re.search(r"^issue\s*:\s*[\"']?([\d.\-]+)", text, re.M)
        if m:
            out.add(m.group(1).replace("-", "."))
        else:
            out.add(p.stem.replace("-", "."))
    return out


# ---------------- EPUB 解析与清洗 ----------------
# ---------------- EPUB 解析（复用 epub_source，含插图抽取） ----------------

from epub_source import extract  # noqa: E402


# ---------------- 主流程 ----------------

def main() -> int:
    print(f"上游: {REPO}@{REF}:{BASE_PATH}")
    local = local_issues()
    print(f"本地已有 {len(local)} 期")

    try:
        available = discover_issues()
    except Exception as e:  # noqa: BLE001
        print(f"发现期号失败: {e}", file=sys.stderr)
        return 1

    print(f"上游可用 {len(available)} 期，最新: "
          f"{available[0][0] if available else '无'}")

    pending = [x for x in available if x[0] not in local]
    if not pending:
        print("没有新内容")
        return 1

    todo = pending[:MAX_ISSUES]
    print(f"待抓取 {len(todo)} 期: {', '.join(t[0] for t in todo)}")

    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(os.environ.get("RUNNER_TEMP",
                                  os.environ.get("TMPDIR", "/tmp")))
    tmpdir.mkdir(parents=True, exist_ok=True)
    made = 0
    for issue, path, sha in todo:
        dest = tmpdir / f"te_{issue}.epub"
        try:
            size = download_blob(sha, dest)
            print(f"  下载 {issue}: {size / 1e6:.1f} MB")
            result = extract(dest, issue, REPO, keep_images=KEEP_IMAGES)
            if not result.articles:
                print(f"  ! {issue} 解析出 0 篇文章，跳过", file=sys.stderr)
                continue

            out = CONTENT_DIR / f"{issue.replace('.', '-')}.md"
            out.write_text(result.markdown, encoding="utf-8")

            img_dir = CONTENT_DIR / issue.replace(".", "-")
            img_dir.mkdir(parents=True, exist_ok=True)
            for name, data in result.images.items():
                (img_dir / name).write_bytes(data)

            total = sum(len(d) for d in result.images.values()) / 1e6
            print(f"  ✓ {out.name}  {result.articles} 篇 / "
                  f"{result.sections} 栏目  "
                  f"{len(result.images)} 图 ({total:.1f} MB)")
            made += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ! {issue} 处理失败: {e}", file=sys.stderr)
        finally:
            if dest.exists():
                dest.unlink()

    print(f"新增 {made} 期")
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
