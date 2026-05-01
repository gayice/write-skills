---
name: access-wechat-article
description: 批量爬取微信公众号文章内容、阅读量、点赞量、评论等数据，并支持爆款标题生成、内容总结、封面图设计、文章转小红书卡片等下游任务。
category: social-media
tags: [微信, 公众号, 爬虫, 数据分析, 内容运营]
version: 1.0.0
author: wewrite-extend
---

# Access_Wechat_Article

微信公众号文章批量爬取 + 多维度数据分析 + 内容运营工具箱。

## 核心能力

| 能力 | 说明 |
|------|------|
| 批量爬取 | 按关键词/公众号批量抓取文章，含正文内容 |
| 数据提取 | 抽取阅读量、点赞量、在看数、评论数 |
| 爆款标题 | 基于文章内容生成 5-10 个微信公众号爆款标题 |
| 内容总结 | 结构化提取核心观点、金句、思维导图、关键数据 |
| 封面图生成 | 10 种风格自动匹配，生成公众号/小红书封面 HTML |
| 转小红书卡片 | 将长文转化为小红书多图风格（5 种排版风格） |
| 文章推荐语 | 生成引发"不读不行"紧迫感的认知能量场推荐序 |

## 目录结构

```
access-wechat-article/
├── SKILL.md                           # 本文件
├── references/
│   ├── wechat_fetch_guide.md          # 批量爬取指南（URL/关键词→文章列表→正文）
│   └── wechat_analysis_prompts.md     # 下游分析 Prompt 库（标题/总结/封面/转图）
├── scripts/
│   ├── batch_fetch_wechat.py           # 批量爬取主脚本
│   └── extract_stats.py               # 从 HTML/JSON 提取阅读/点赞/评论数据
└── data/                              # 运行时数据（自动创建）
    ├── articles/                       # 爬取的原始文章 HTML/Markdown
    ├── results/                        # 提取后的结构化数据 JSON
    └── output/                         # 封面图/卡片图输出
```

## 快速开始

### 1. 批量爬取文章

**方式 A：按关键词批量爬取（搜狗微信搜索）**

```bash
cd ~/.agents/skills/access-wechat-article
python3 scripts/batch_fetch_wechat.py \
  --keyword "AI写作 技巧" \
  --pages 5 \
  --output data/articles/
```

**方式 B：指定公众号 + 文章链接列表**

```bash
python3 scripts/batch_fetch_wechat.py \
  --account "半佛仙人" \
  --urls-file my_urls.txt \
  --output data/articles/
```

> `my_urls.txt` 每行一个微信文章 URL。

**方式 C：导入搜狗微信搜索导出的结果文件**

```bash
python3 scripts/batch_fetch_wechat.py \
  --load-sogou results.json \
  --fetch-content \
  --output data/articles/
```

---

### 2. 提取数据（阅读量/点赞/评论）

```bash
python3 scripts/extract_stats.py \
  --input data/articles/ \
  --output data/results/stats.json
```

---

### 3. 下游分析（用 AI Agent）

将 `references/wechat_analysis_prompts.md` 中的对应 Prompt 发给 AI，
粘贴文章内容或文件路径，即可获得：

- **爆款标题**：5-10 个评分排序标题 + 敏感词检测
- **内容总结**：推荐度、新颖度、金句、思维导图、关键问答
- **封面图**：10 种风格自动匹配，输出 HTML（含下载按钮）
- **转小红书卡片**：5 种风格（手账/杂志/几何/淡黄/文艺），HTML 输出
- **推荐语**：认知能量场推荐序，引发点击欲望

---

## 依赖

```bash
pip install requests beautifulsoup4 lxml camoufox playwright
playwright install chromium  # 如需无头浏览器兜底
```

> 推荐优先用 requests（搜狗/直接抓取），遇验证码自动降级到 camoufox。
