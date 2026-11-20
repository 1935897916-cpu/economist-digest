# 精读注解 schema 与翻译准则

注解数据存放于 `annotations/<期号>-<月>-<日>/<文章slug>.json`
（期号目录名与 `content/` 下的图片目录名一致，如 `2026-10-17/`）。
`tools/build_reader.py` 构建时逐篇校验，任一硬性校验失败即中止构建。

## 文件结构

```json
{
  "issue": "2026-10-17",                  // 期号（与 content 目录名一致，用连字符）
  "section": "Finance & economics",        // 所属栏目（须与 md 中的 ## 标题一致）
  "article_slug": "a-shortage-of-sulphur-...",
  "article_title_zh": "硫磺短缺可能冲击全球矿山与农田",
  "paragraphs": [
    { "n": 1, "zh": "……", "gloss": [1, 2] }
  ],
  "figures": [
    { "n": 1, "caption_zh": "题图" }
  ],
  "glossary": [
    { "n": 1, "term": "by-product", "phonetic": "/ˈbaɪˌprɒdʌkt/",
      "pos": "n.", "sense": "副产品——主工艺顺带产出之物",
      "note": "可选的背景注释" }
  ]
}
```

## 编号规则

- `paragraphs[].n`：按渲染后**顶层文字块**（`<p>`/`<blockquote>`/`<ul>`）顺序从 1 连续编号。
  文章开头的斜体副标题行也算一个文字块（通常是 n=1）。
  `<figure>` 不占段落编号，单独计入 `figures[].n`。
- `figures[].n`：按图片出现顺序从 1 连续。
- `glossary[].n`：全篇从 1 连续。
- `paragraphs[].gloss`：该段出现的词条编号数组；构建时据此在英文段注入上标。

## 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| term | ✓ | 词条原形（允许后缀变形：-ed/-s/-ing/-er 等，整词匹配） |
| phonetic | ✓ | IPA 音标，用 `/…/` 包裹 |
| pos | ✓ | 词性缩写：n. / v. / adj. / adv. / conj. / prep. / phr.（词组）/ id.（习语） |
| sense | ✓ | **在这篇文章语境里的意思**，不是词典全义 |
| note | – | 背景注释 / 熟词僻义提示（照样张第 56 条风格） |
| match | – | 可选。词组在原文中间插入宾语、无法连续命中时，填更短的匹配词（如词条 `plough into` 配 `"match": "plough"`）；卡片仍显示完整词条 |

## 翻译准则

1. **逐段忠实客观直译**，不增不减、不加译者评论。用户目的是学英语，不设题材回避。
2. 专有名词按 `annotations/terms.json` 统一译名；表中 translation 为空的保留英文。
3. 数字与单位照原文（4.8m tonnes → 480万吨可读性优先，全篇统一一种风格）。
4. 唯一底线：涉及国家主权、领土完整及港澳台的表述，按官方规范表述处理，
   不照搬原文的错误说法。
5. 译文力求通顺但不意译过度——读者要能对照出原文句法。

## 选词准则

- 每篇 8–15 条，克制；不标四六级以下的基础词。
- 优先：影响理解的习语词组（`in force`、`come online`）、熟词僻义
  （`fetch` 售得、`tight` 吃紧、`ferry` 动词运送）、带背景的术语（`leach` 浸出）。
- `sense` 给"这句话里的意思"；确有背景价值的才写 `note`。

## 硬性校验（build_reader 构建前执行，失败即报错退出）

1. 译文块数与原文顶层文字块数一致，`n` 连续无缺。
2. `figures[].n` 数量与原文 figure 数一致。
3. `glossary[].n` 连续；`paragraphs[].gloss` 引用的编号全部存在。
4. 每个 `term` 能在文章全文中按整词（允许常规后缀变形、忽略大小写）命中。
5. slug 与 `tools/markdown.py` 的 `slugify(title)` 一致，否则报错提醒人工对齐。
