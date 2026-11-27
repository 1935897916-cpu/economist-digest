#!/usr/bin/env python
"""当 github.com:443 直连不通时，用 GitHub Contents API 把远端内容拉到本地。

build.py 依赖 content/<期号>.md 与 content/<期号>/（图片）。git fetch 走不通时，
CI 仍会更新远端仓库，本地却停在旧期号，导致自动任务以为"没有新一期"。本脚本补这个洞。

用法：
    python tools/pull_via_api.py                 # 检查并拉取远端最新一期（只拉 .md）
    python tools/pull_via_api.py 2026-11-28      # 指定期号
    python tools/pull_via_api.py --all           # 补齐本地缺失的所有期号（.md）
    python tools/pull_via_api.py 2026-11-28 --with-images   # 连图片一起拉
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import urllib.error
import urllib.request

OWNER = "1935897916-cpu"
REPO = "economist-digest"
API = "https://api.github.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")


def cred_read(target: str) -> str:
    """从 Windows 凭据管理器读一条普通凭据（GCM 在非交互环境常失效）。"""
    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_int), ("Type", ctypes.c_int),
            ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
            ("LastWritten", wt.FILETIME), ("CredentialBlobSize", ctypes.c_int),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", ctypes.c_int), ("AttributeCount", ctypes.c_int),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    adv = ctypes.windll.advapi32
    adv.CredReadW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_void_p)]
    ptr = ctypes.c_void_p()
    if not adv.CredReadW(target, 1, 0, ctypes.byref(ptr)) or not ptr.value:
        return ""
    try:
        cred = ctypes.cast(ptr, ctypes.POINTER(CREDENTIAL)).contents
        size = cred.CredentialBlobSize
        buf = (ctypes.c_byte * size).from_address(
            ctypes.addressof(cred.CredentialBlob.contents))
        raw = bytes(buf)
        return raw.decode("utf-16-le", "replace") if size >= 2 and raw[1] == 0 \
            else raw.decode("utf-8", "replace")
    finally:
        adv.CredFree(ptr)


TOKEN = cred_read("git:https://github.com")

HEADERS = {"Accept": "application/vnd.github+json",
           "User-Agent": "workbuddy-pull"}
if TOKEN:
    HEADERS["Authorization"] = "Bearer " + TOKEN


def api_get(path: str, raw: bool = False):
    h = dict(HEADERS)
    if raw:
        h["Accept"] = "application/vnd.github.raw"
    req = urllib.request.Request(API + path, headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read() if raw else json.loads(r.read())


def list_dir(path: str) -> list[dict]:
    return api_get(f"/repos/{OWNER}/{REPO}/contents/{path}")


def save(rel_path: str, data: bytes) -> None:
    dest = os.path.join(ROOT, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  ↓ {rel_path} ({len(data) // 1024} KB)")


def fetch_issue(issue: str, with_images: bool = False) -> bool:
    md_path = f"content/{issue}.md"
    local_md = os.path.join(CONTENT, f"{issue}.md")
    if os.path.exists(local_md) and not with_images:
        print(f"{issue}: 本地已有，跳过")
        return False
    if not os.path.exists(local_md):
        save(md_path, api_get(f"/repos/{OWNER}/{REPO}/contents/{md_path}", raw=True))
        print(f"{issue}: 正文已拉取")
    else:
        print(f"{issue}: 正文已存在")

    if with_images:
        items = list_dir(f"content/{issue}")
        n = 0
        for it in items:
            if it["type"] != "file":
                continue
            rel = it["path"]
            if os.path.exists(os.path.join(ROOT, rel.replace("/", os.sep))):
                continue
            save(rel, api_get(f"/repos/{OWNER}/{REPO}/contents/{rel}", raw=True))
            n += 1
        print(f"{issue}: 图片 {n} 张")
    return True


def remote_issues() -> list[str]:
    names = []
    for it in list_dir("content"):
        n = it["name"]
        if it["type"] == "dir" and len(n) == 10 and n[4] == "-" and n[7] == "-":
            names.append(n)
    return sorted(names)


def main() -> None:
    args = [a for a in sys.argv[1:]]
    with_images = "--with-images" in args
    args = [a for a in args if not a.startswith("--")]
    issues = remote_issues()
    if not issues:
        print("远端 content/ 为空")
        return
    print(f"远端共 {len(issues)} 期，最新 {issues[-1]}")

    if args:
        targets = args
    elif "--all" in sys.argv:
        targets = issues
    else:
        targets = [issues[-1]]

    changed = 0
    for t in targets:
        if t not in issues:
            print(f"{t}: 远端不存在，跳过")
            continue
        if fetch_issue(t, with_images):
            changed += 1

    if changed:
        print("PULL_OK")
    else:
        print("PULL_NOTHING_NEW")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as e:
        print("PULL_FAILED:", e.code, e.read().decode("utf-8", "replace")[:200])
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print("PULL_FAILED:", str(e)[:300])
        sys.exit(1)
