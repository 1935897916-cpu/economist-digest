#!/usr/bin/env python3
"""精读注解的加载与强制校验。

被 tools/build_reader.py 调用；任一硬性校验失败抛出 ValueError，
构建即中止——宁可构建失败，也不能让译文错位上线。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from markdown import plain_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ANNOT_DIR = ROOT / "annotations"

REQUIRED_GLOSS_FIELDS = ("term", "phonetic", "pos", "sense")

# 允许的常规后缀变形（整词匹配时）
_SUFFIX = r"(?:s|es|ed|d|ing|er|ers|est)?"
# 辅音字母 + y 结尾：ferry → ferried / ferries
_Y = r"(?:(?:i(?:es|ed|er|est))|(?:ying))?"


def issue_key(issue: str) -> str:
    """期号目录名：与 content/ 下图片目录一致（用连字符）。"""
    return issue.replace(".", "-")


def annotations_dir(issue: str) -> Path:
    return ANNOT_DIR / issue_key(issue)


def load_for_issue(issue: str) -> dict[str, dict]:
    """载入某期的全部注解，返回 {article_slug: anno}。无目录则返回空。"""
    d = annotations_dir(issue)
    if not d.is_dir():
        return {}
    out: dict[str, dict] = {}
    for p in sorted(d.glob("*.json")):
        anno = json.loads(p.read_text(encoding="utf-8"))
        out[anno.get("article_slug") or p.stem] = anno
    return out


def _infl_pattern(term: str) -> re.Pattern:
    """构造词条的整词变形匹配：每个单词允许常规后缀（fetch→fetched、
    exacerbate→exacerbated、tight→tighter、ferry→ferried）。"""
    parts = []
    for w in term.split():
        esc = re.escape(w)
        if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
            parts.append(f"{esc[:-len('y')]}(?:y{_SUFFIX}|{_Y})")
        else:
            parts.append(esc + _SUFFIX)
    return re.compile(r"\b" + r"[\s-]+".join(parts) + r"\b", re.I)


def validate(anno: dict, article, n_text_blocks: int, n_figures: int) -> None:
    """对照渲染后的原文块数校验注解。article 为 build.Article。"""
    slug = anno.get("article_slug", "")
    if slug != article.slug:
        raise ValueError(f"[{slug}] article_slug 与正文 slug 不一致"
                         f"（正文为 {article.slug}），请人工对齐")

    paras = anno.get("paragraphs") or []
    nums = [p.get("n") for p in paras]
    if nums != list(range(1, n_text_blocks + 1)):
        raise ValueError(
            f"[{slug}] 段落编号应为 1..{n_text_blocks} 连续，实际为 {nums}。"
            f"译文块数必须与原文顶层文字块数严格一致")

    figs = anno.get("figures") or []
    fnums = [f.get("n") for f in figs]
    if fnums != list(range(1, n_figures + 1)):
        raise ValueError(f"[{slug}] 图注编号应为 1..{n_figures}，实际为 {fnums}")

    gloss = anno.get("glossary") or []
    gnums = [g.get("n") for g in gloss]
    if gnums != list(range(1, len(gloss) + 1)):
        raise ValueError(f"[{slug}] 词条编号不连续：{gnums}")
    gids = {g.get("n") for g in gloss}
    for p in paras:
        for g in p.get("gloss", []):
            if g not in gids:
                raise ValueError(f"[{slug}] 第{p.get('n')}段引用了不存在的词条 {g}")

    for g in gloss:
        for field in REQUIRED_GLOSS_FIELDS:
            if not str(g.get(field, "")).strip():
                raise ValueError(f"[{slug}] 词条 {g.get('n')} 缺少 {field}")

    # 词条必须能在文章全文中整词命中（允许变形）。
    # "match" 用于形如 plough into 但原文中间插了宾语（ploughed so much
    # cash into ...）的情况，指定更短的匹配词，卡片仍显示完整词条。
    text = plain_text(article.body)
    for g in gloss:
        match = g.get("match") or g["term"]
        if not _infl_pattern(match).search(text):
            raise ValueError(
                f"[{slug}] 词条 {g['n']}「{g['term']}」在原文中未找到"
                f"（含常规变形 / match={match}），请核对拼写或选词")
