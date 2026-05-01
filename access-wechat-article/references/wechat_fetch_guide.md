# 微信公众号批量爬取指南

## 爬取链路

```
关键词/公众号名
    │
    ▼
搜狗微信搜索 (weixin.sogou.com)
  ─ 获取文章 URL 列表 + 标题/摘要/日期/公众号名
    │
    ▼
逐篇抓取正文 HTML
  ─ requests (90%) → Camoufox (8%) → Playwright (2%)
    │
    ▼
HTML → Markdown 转换
  ─ 保留标题/作者/发布时间
    │
    ▼
结构化数据提取
  ─ 阅读量/点赞/在看/评论 (需登录或特殊接口)
    │
    ▼
输出：articles/ 原始文件 + results/ 结构化 JSON
```

---

## 1. 搜狗微信搜索：批量获取文章列表

**无需登录，直接爬取。**

### 请求参数

```
GET https://weixin.sogou.com/weixin?query=<关键词>&type=2&page=<页码>&ie=utf8
```

### 请求头（必须）

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://weixin.sogou.com/",
}
```

> **反爬注意**：先访问 `https://weixin.sogou.com/` 建立 cookie，间隔 2-3 秒翻页。

### 解析字段

| 字段 | CSS 选择器 | 说明 |
|------|-----------|------|
| 标题 | `li h3 a` (去 `<em>` 高亮) | 需还原被高亮的关键词 |
| 文章 URL | `li h3 a/@href` | 搜狗重定向，加前缀 `https://weixin.sogou.com` |
| 公众号名 | `.s-p span.all-time-y2` | |
| 日期 | `.s-p span.s2` 含 `timeConvert(timestamp)` | JS 函数，需提取时间戳转日期 |
| 摘要 | `p.txt-info` (去 `<em>` 高亮) | |

### 低粉爆文识别规则

来自 `wewrite/scripts/wechat_viral_finder.py` 的启发：

```
同一账号出现 ≥2 篇高阅读文章
+ 公众号名为个人风格（非"杂志/官方/集团"）
+ 评论少但阅读量异常高（评论数/阅读量 < 1%）
→ 标记为低粉爆文
```

---

## 2. 抓取文章正文：三级降级策略

来源：`wewrite/scripts/fetch_article.py`

### Level 1: requests（优先，5 秒超时）

```python
resp = requests.get(url, headers={"User-Agent": _BROWSER_UA}, timeout=20)
resp.encoding = "utf-8"
html = resp.text
```

**成功率：~90%。** 需验证 `#js_content` 有实质内容（>50 字）。

### Level 2: Camoufox 反检测浏览器（降级，30 秒）

```python
from camoufox.sync_api import Camoufox
with Camoufox(headless=True) as browser:
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector("#js_content", timeout=10000)
    time.sleep(2)
    html = page.content()
```

> 绕过微信机器人验证码。

### Level 3: Playwright（最终降级，30 秒）

```python
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_selector("#js_content", timeout=10000)
    html = page.content()
```

### Level 4: 手动兜底

遇验证码时：浏览器打开 → 另存为 HTML → `--file` 参数传入。

---

## 3. HTML → Markdown 转换

来源：`wewrite/scripts/fetch_article.py` 的 `html_to_markdown()`。

### 元数据提取

```python
title    = soup.find("h1", class_="rich_media_title").get_text()
author   = soup.find("a", id="js_name").get_text()
pub_time = soup.find("em", id="publish_time").get_text()
```

### 正文提取

```python
content = soup.find(id="js_content")
# 微信懒加载用 visibility:hidden，strip 掉 style 后正常解析
del content["style"]
```

### 标签映射

| HTML 标签 | Markdown |
|-----------|----------|
| `h1-h4` | `# ## ### ####` |
| `p` | `\n\n` 包裹 |
| `img` | `![alt](data-src or src)` |
| `a` | `[text](href)` |
| `blockquote` | `> 引用` |
| `ul/ol li` | `- / 1.` |
| `code/pre` | `` ` `` / ``` |
| `strong/b` | `**bold**` |

---

## 4. 数据提取：阅读量 / 点赞 / 评论

> ⚠️ **重要说明**：微信文章页面上公开可见的数据极为有限，以下方法各有局限。

### 4.1 搜狗微信搜索页面（有阅读量估算）

搜狗搜索结果中部分条目含**热度指数**：

```
https://weixin.sogou.com/weixin?query=关键词&type=2
```

热度以相对值呈现，无法换算为真实阅读量，但可作为文章间横向比较的依据。

### 4.2 微信「在看」列表（需抓包）

打开文章后点击"在看"（或朋友在看），可获取点赞列表。
**需要微信 PC 客户端或抓包工具**，非公开接口。

### 4.3 公众号后台数据（需授权）

通过 [新榜](https://www.newrank.cn)、[清博指数](http://www.gsdata.cn) 等第三方平台查询，
**需账号登录，部分数据付费**。

### 4.4 搜狗抓取字段一览

| 字段 | 可获取性 |
|------|---------|
| 文章标题 | ✅ 直接获取 |
| 公众号名 | ✅ 直接获取 |
| 发布日期 | ✅ 直接获取 |
| 文章摘要 | ✅ 直接获取 |
| 正文内容 | ✅ 需抓取 |
| 阅读量 | ⚠️ 需登录/付费接口 |
| 点赞量 | ⚠️ 需登录/付费接口 |
| 在看数 | ⚠️ 需登录/付费接口 |
| 评论内容 | ⚠️ 需登录/付费接口 |

### 4.5 实际可行方案

```
推荐做法：
1. 用搜狗搜索批量拿文章列表（标题/摘要/日期/公众号）
2. 用 fetch_article.py 批量抓正文（Markdown）
3. 阅读/点赞数据：通过新榜 API 或手动查询
4. 评论区：通过搜狗的评论接口（部分支持）
```

---

## 5. 批量爬取脚本用法

```bash
# 按关键词爬取文章列表（搜狗搜索）
python3 scripts/batch_fetch_wechat.py \
  --keyword "AI写作 技巧" \
  --pages 5 \
  --output data/articles/

# 指定公众号 + URL 列表
python3 scripts/batch_fetch_wechat.py \
  --account "半佛仙人" \
  --urls-file my_urls.txt \
  --output data/articles/

# 从已有搜狗搜索结果导入
python3 scripts/batch_fetch_wechat.py \
  --load-sogou results.json \
  --fetch-content \
  --output data/articles/

# 提取文章中的数据字段（阅读/点赞/评论）
python3 scripts/extract_stats.py \
  --input data/articles/ \
  --output data/results/stats.json
```

---

## 6. 已知限制与应对

| 问题 | 原因 | 解决 |
|------|------|------|
| 搜狗返回空结果 | 反爬封禁 IP / Cookie 过期 | 换 IP 或加长间隔（5-10s） |
| 抓取到空白正文 | 微信懒加载未渲染 | 降级到 Camoufox / Playwright |
| 验证码拦截 | 请求过于频繁 | 加延时、换 User-Agent、换 IP |
| 无阅读量数据 | 微信不公开 | 用新榜 / 手动查 / 忽略 |
| 公众号迁移/封禁 | 账号异常 | 跳过该账号 |
