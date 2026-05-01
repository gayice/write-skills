#!/usr/bin/env python3
"""
batch_fetch_wechat.py
批量爬取微信公众号文章列表及正文内容。

用法:
  # 按关键词搜狗搜索
  python3 batch_fetch_wechat.py --keyword "AI写作 技巧" --pages 5 --output data/articles/

  # 指定公众号 + URL 列表文件
  python3 batch_fetch_wechat.py --account "半佛仙人" --urls-file my_urls.txt --output data/articles/

  # 导入搜狗搜索结果 JSON，抓正文
  python3 batch_fetch_wechat.py --load-sogou results.json --fetch-content --output data/articles/

  # 只抓列表不抓正文（快速预览）
  python3 batch_fetch_wechat.py --keyword "AI" --pages 3 --output data/list_only/ --no-fetch
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ---------- 请求库 ----------
try:
    import requests

    SESSION = requests.Session()
    _BROWSER_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    SESSION.headers.update({"User-Agent": _BROWSER_UA})
except ImportError:
    requests = None

# ---------- BeautifulSoup ----------
try:
    from bs4 import BeautifulSoup

    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ---------- Playwright fallback ----------
def _fetch_playwright(url: str, timeout: int = 30000):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout)
            page.wait_for_selector("#js_content", timeout=10000)
            time.sleep(2)
            html = page.content()
            browser.close()
            return html
    except Exception:
        return None


# ---------- Camoufox fallback ----------
def _fetch_camoufox(url: str, timeout: int = 30000):
    try:
        from camoufox.sync_api import Camoufox
    except ImportError:
        return None
    try:
        with Camoufox(headless=True) as browser:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout / 1000)
            page.wait_for_selector("#js_content", timeout=10000)
            time.sleep(2)
            return page.content()
    except Exception:
        return None


# ---------- 常量 ----------
TIMEOUT = 20
FETCH_DELAY = (3.0, 6.0)  # 随机间隔秒


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ArticleRecord:
    title: str = ""
    account: str = ""
    url: str = ""
    date: str = ""
    digest: str = ""
    markdown: str = ""
    status: str = "pending"  # pending | ok | failed
    error: str = ""
    file_saved: str = ""


# ============================================================
# 搜狗微信搜索：批量获取文章列表
# ============================================================

def _init_sogou_session():
    """先访问搜狗首页建立 cookie。"""
    try:
        SESSION.get("https://weixin.sogou.com/", timeout=TIMEOUT)
        time.sleep(1.5)
    except Exception:
        pass


def sogou_search(keyword: str, pages: int = 3) -> list[ArticleRecord]:
    """搜狗微信搜索，返回 ArticleRecord 列表（仅列表字段）。"""
    if not BS4_AVAILABLE:
        print("Error: beautifulsoup4 not installed (pip install beautifulsoup4)", file=sys.stderr)
        return []

    _init_sogou_session()
    results: list[ArticleRecord] = []
    seen_urls = set()

    for page in range(1, pages + 1):
        url = (
            f"https://weixin.sogou.com/weixin?"
            f"query={keyword}&type=2&page={page}&ie=utf8"
        )
        print(f"  [搜索] 第 {page}/{pages} 页: {keyword}", file=sys.stderr)
        try:
            resp = SESSION.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except Exception as e:
            print(f"  [警告] 抓取失败: {e}", file=sys.stderr)
            time.sleep(5)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        all_lis = soup.find_all("li")
        items = [li for li in all_lis if li.find("h3")]

        if not items:
            print(f"  [警告] 第 {page} 页无结果，可能被反爬", file=sys.stderr)
            time.sleep(4)
            continue

        for item in items:
            try:
                title_el = item.select_one("h3 a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                for em in title_el.find_all("em"):
                    title = title.replace(str(em), em.get_text(strip=True))
                title = re.sub(r"\s+", " ", title).strip()

                url_href = title_el.get("href", "")
                if url_href.startswith("/"):
                    article_url = "https://weixin.sogou.com" + url_href
                elif url_href.startswith("http"):
                    article_url = url_href
                else:
                    continue

                if article_url in seen_urls:
                    continue
                seen_urls.add(article_url)

                account_el = item.select_one(".s-p span.all-time-y2")
                account = account_el.get_text(strip=True) if account_el else "未知"

                # 日期解析：timeConvert(timestamp)
                date_el = item.select_one(".s-p span.s2")
                date_str = ""
                if date_el:
                    script_tag = date_el.find("script")
                    if script_tag and script_tag.string:
                        ts_match = re.search(r"timeConvert\(['\"]?(\d+)['\"]?\)", script_tag.string)
                        if ts_match:
                            ts = int(ts_match.group(1))
                            if ts > 1e12:
                                ts //= 1000
                            try:
                                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                            except Exception:
                                date_str = str(ts)
                    if not date_str:
                        date_str = date_el.get_text(strip=True)

                # 摘要
                digest_el = item.select_one("p.txt-info")
                digest = ""
                if digest_el:
                    digest = digest_el.get_text(strip=True)
                    for em in digest_el.find_all("em"):
                        digest = digest.replace(str(em), em.get_text(strip=True))
                    digest = re.sub(r"\s+", " ", digest).strip()

                record = ArticleRecord(
                    title=title,
                    account=account,
                    url=article_url,
                    date=date_str,
                    digest=digest,
                )
                results.append(record)

            except Exception as e:
                print(f"  [警告] 解析文章条目失败: {e}", file=sys.stderr)
                continue

        time.sleep(random.uniform(*FETCH_DELAY))

    return results


# ============================================================
# 抓取单篇文章正文（HTML → Markdown）
# ============================================================

def _has_content(html: str) -> bool:
    if not BS4_AVAILABLE or not html:
        return False
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="js_content")
    if content is None:
        return False
    text = content.get_text(strip=True)
    return len(text) > 50


def _fetch_article_html(url: str) -> str:
    """三级降级抓取：requests → Camoufox → Playwright。"""
    # Level 1: requests
    try:
        resp = SESSION.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        html = resp.text
        if _has_content(html):
            return html
    except Exception:
        pass

    # Level 2: Camoufox
    print("    [降级] Camoufox...", file=sys.stderr)
    html = _fetch_camoufox(url)
    if html and _has_content(html):
        return html

    # Level 3: Playwright
    print("    [降级] Playwright...", file=sys.stderr)
    html = _fetch_playwright(url)
    if html and _has_content(html):
        return html

    return ""


def _elem_to_md(elem, depth: int = 0) -> str:
    """HTML 元素 → Markdown 字符串（递归）。"""
    from bs4 import NavigableString

    if isinstance(elem, NavigableString):
        return str(elem).strip()

    tag = getattr(elem, "name", None)
    if tag is None:
        return ""

    # 跳过隐藏元素
    style = elem.get("style", "")
    if "display:none" in style.replace(" ", "").lower():
        return ""
    if "visibility:hidden" in style.replace(" ", "").lower():
        return ""

    inner = "".join(_elem_to_md(child, depth + 1) for child in elem.children).strip()

    if not inner:
        return ""

    # 标签映射
    if tag in ("h1", "h2", "h3", "h4"):
        return f"\n\n{'#' * int(tag[1])} {inner}\n\n"
    if tag == "p":
        return f"\n\n{inner}\n\n"
    if tag == "br":
        return "\n"
    if tag in ("strong", "b"):
        return f"**{inner}**"
    if tag in ("em", "i"):
        return f"*{inner}*"
    if tag == "a":
        href = elem.get("href", "")
        if href and not href.startswith("javascript:"):
            return f"[{inner}]({href})"
        return inner
    if tag == "img":
        src = elem.get("data-src") or elem.get("src") or ""
        alt = elem.get("alt", "")
        if src:
            return f"\n\n![{alt}]({src})\n\n"
        return ""
    if tag == "blockquote":
        lines = inner.split("\n")
        quoted = "\n".join(f"> {line}" for line in lines if line.strip())
        return f"\n\n{quoted}\n\n"
    if tag in ("ul", "ol"):
        return f"\n\n{inner}\n\n"
    if tag == "li":
        parent = getattr(elem, "parent", None)
        prefix = "1. " if (parent and parent.name == "ol") else "- "
        return f"{prefix}{inner}\n"
    if tag == "code":
        if getattr(elem, "parent", None) and elem.parent.name == "pre":
            return inner
        return f"`{inner}`"
    if tag == "pre":
        return f"\n\n```\n{inner}\n```\n\n"
    if tag == "hr":
        return "\n\n---\n\n"
    if tag in ("section", "div", "span", "article", "main", "figure", "figcaption", "table", "thead", "tbody", "tr"):
        return inner
    if tag in ("td", "th"):
        return f" {inner} |"
    return inner


def html_to_markdown(html: str) -> tuple[dict, str]:
    """HTML → (元数据 dict, Markdown 正文)。"""
    if not BS4_AVAILABLE:
        return {}, ""
    soup = BeautifulSoup(html, "html.parser")

    # 元数据
    title_tag = soup.find("h1", class_="rich_media_title") or soup.find("h1", id="activity-name")
    title = title_tag.get_text(strip=True) if title_tag else ""

    author_tag = soup.find("a", id="js_name") or soup.find("span", class_="rich_media_meta_nickname")
    author = author_tag.get_text(strip=True) if author_tag else ""

    pub_tag = soup.find("em", id="publish_time")
    pub_time = pub_tag.get_text(strip=True) if pub_tag else ""

    # 正文
    content = soup.find(id="js_content")
    if content and content.get("style"):
        del content["style"]

    md = ""
    if content:
        raw = _elem_to_md(content)
        md = re.sub(r"\n{3,}", "\n\n", raw).strip()

    return {"title": title, "author": author, "publish_time": pub_time}, md


# ============================================================
# 批量处理
# ============================================================

def _sanitize_filename(s: str) -> str:
    """把字符串转为安全的文件名。"""
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return s[:80]


def fetch_and_save_article(record: ArticleRecord, output_dir: Path) -> ArticleRecord:
    """抓取正文、转为 Markdown、保存文件。更新 record。"""
    print(f"    抓取: {record.title[:50]}...", file=sys.stderr)

    html = _fetch_article_html(record.url)
    if not html:
        record.status = "failed"
        record.error = "无法获取正文（验证码或网络错误）"
        return record

    meta, md = html_to_markdown(html)
    if not md:
        record.status = "failed"
        record.error = "正文为空"
        return record

    record.markdown = md
    if not record.title and meta.get("title"):
        record.title = meta["title"]
    if not record.account and meta.get("author"):
        record.account = meta["author"]
    if not record.date and meta.get("publish_time"):
        record.date = meta["publish_time"]

    # 保存
    safe_title = _sanitize_filename(record.title)
    md_file = output_dir / f"{safe_title}.md"
    md_file.write_text(md, encoding="utf-8")
    record.file_saved = str(md_file)
    record.status = "ok"

    print(f"    ✅ 保存: {md_file.name}", file=sys.stderr)
    return record


def save_articles_json(articles: list[ArticleRecord], path: Path):
    """保存文章列表为 JSON（不含 markdown 内容，减小体积）。"""
    out = []
    for r in articles:
        d = asdict(r)
        d["markdown"] = ""  # 不存正文，太大
        out.append(d)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# 入口
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="批量爬取微信公众号文章（搜狗搜索列表 + 正文 Markdown）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--keyword", help="搜狗搜索关键词")
    ap.add_argument("--pages", type=int, default=3, help="搜索页数（默认3）")
    ap.add_argument("--account", help="公众号名称（仅作标记用）")
    ap.add_argument("--urls-file", help="URL 列表文件（每行一个 URL）")
    ap.add_argument("--load-sogou", help="导入已有的搜狗搜索 JSON 结果")
    ap.add_argument("--output", required=True, help="输出目录")
    ap.add_argument("--no-fetch", action="store_true", help="只抓列表，不抓正文")
    ap.add_argument("--delay", type=float, default=0, help="每个任务额外等待秒数")

    args = ap.parse_args()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 构建 ArticleRecord 列表
    articles: list[ArticleRecord] = []

    if args.load_sogou:
        # 从已有搜狗 JSON 导入
        data = json.loads(Path(args.load_sogou).read_text(encoding="utf-8"))
        for d in data:
            r = ArticleRecord(
                title=d.get("title", ""),
                account=d.get("account", ""),
                url=d.get("url", ""),
                date=d.get("date", ""),
                digest=d.get("digest", ""),
            )
            articles.append(r)
        print(f"[导入] 从 {args.load_sogou} 加载了 {len(articles)} 条记录")

    elif args.urls_file:
        # 从 URL 文件读取
        urls = [u.strip() for u in Path(args.urls_file).read_text(encoding="utf-8").splitlines() if u.strip()]
        account = args.account or "未知"
        for url in urls:
            r = ArticleRecord(url=url, account=account)
            articles.append(r)
        print(f"[加载] 从文件读取 {len(articles)} 个 URL")

    elif args.keyword:
        # 搜狗搜索
        articles = sogou_search(args.keyword, pages=args.pages)
        print(f"[搜索] 共找到 {len(articles)} 篇文章")
        # 保存搜索结果 JSON
        list_json = output_dir / "article_list.json"
        save_articles_json(articles, list_json)
        print(f"[保存] 搜索列表 → {list_json}")

    else:
        ap.error("请指定 --keyword 或 --urls-file 或 --load-sogou")

    if not articles:
        print("没有文章可处理。", file=sys.stderr)
        return

    # 2. 逐篇抓正文
    if not args.no_fetch:
        print(f"\n[正文] 开始抓取 {len(articles)} 篇文章...\n")
        for i, r in enumerate(articles, 1):
            print(f"[{i}/{len(articles)}]", file=sys.stderr)
            r = fetch_and_save_article(r, output_dir)
            if args.delay:
                time.sleep(args.delay)
            elif r.status == "ok":
                time.sleep(random.uniform(*FETCH_DELAY))

        ok = sum(1 for r in articles if r.status == "ok")
        failed = sum(1 for r in articles if r.status == "failed")
        print(f"\n[完成] 成功 {ok}，失败 {failed}")

    # 3. 保存汇总 JSON（始终保存，含所有字段）
    summary_json = output_dir / "summary.json"
    summary_data = [asdict(r) for r in articles]
    summary_json.write_text(json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[保存] 汇总 JSON → {summary_json}")


if __name__ == "__main__":
    main()
