#!/usr/bin/env python3
"""
extract_stats.py
从已爬取的文章目录中提取结构化数据：
- 读取 summary.json 中的元数据（标题/公众号/日期/摘要）
- 读取每篇 .md 正文，提取 AI 味分数（调用 humanness_score）
- 读取 HTML 原始文件（如有），尝试提取阅读量/点赞/评论

用法:
  python3 extract_stats.py --input data/articles/ --output data/results/stats.json
  python3 extract_stats.py --input data/articles/ --output data/results/stats.json --score --verbose
"""

import argparse
import json
import re
import sys
from pathlib import Path
from dataclasses import dataclass, asdict


# ============================================================
# 工具函数
# ============================================================

def _sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return s[:80]


def safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="gbk")
        except Exception:
            return ""


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ArticleStats:
    title: str = ""
    account: str = ""
    url: str = ""
    date: str = ""
    digest: str = ""
    status: str = "pending"
    error: str = ""

    # humanness score（可选）
    humanness_score: float = -1.0   # 0=人写, 100=AI味重
    humanness_tier1_mean: float = -1.0
    humanness_tier2_mean: float = -1.0
    humanness_suggestions: list = None

    # 公开数据（有限）
    word_count: int = 0
    image_count: int = 0

    # 阅读量/点赞（需登录接口，以下为尝试解析）
    read_count: str = ""
    like_count: str = ""
    comment_count: str = ""

    # 文件路径
    md_file: str = ""
    html_file: str = ""

    def __post_init__(self):
        if self.humanness_suggestions is None:
            self.humanness_suggestions = []


# ============================================================
# 统计函数
# ============================================================

def _count_words(text: str) -> int:
    """中文字符数 + 英文单词数（粗略）。"""
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_words = len(re.findall(r'[a-zA-Z]{2,}', text))
    return cjk + en_words


def _extract_html_stats(html_text: str) -> dict:
    """从原始 HTML 中尝试提取阅读量/点赞/评论数据。
    
    说明：微信文章页面上这些数据大多需要登录态才能获取，
    此处只能提取页面上明确可见的有限信息（若有）。
    """
    stats = {
        "read_count": "",
        "like_count": "",
        "comment_count": "",
    }

    # 方法1：页面中直接内嵌的数据（如某些旧版微信）
    # 常见格式：var appmsg_like_type = {count: xxx}
    for pattern, key in [
        (r'appmsg_like_type\s*=\s*\{[^}]*?count\s*:\s*(\d+)', "like_count"),
        (r'comment_count\s*:\s*["\']?(\d+)', "comment_count"),
        (r'"read_count["\']\s*:\s*["\']?(\d+)', "read_count"),
    ]:
        m = re.search(pattern, html_text)
        if m:
            stats[key] = m.group(1)

    # 方法2：data-src 中包含的统计数据（部分文章）
    # 格式：<div class="read_statistics">1234</div>
    for pattern, key in [
        (r'阅读["\'\s:：]+(\d+)', "read_count"),
        (r'点赞["\'\s:：]+(\d+)', "like_count"),
        (r'在看["\'\s:：]+(\d+)', "like_count"),
    ]:
        if not stats[key]:
            m = re.search(pattern, html_text)
            if m:
                stats[key] = m.group(1)

    return stats


def _try_score_article(text: str) -> dict:
    """调用 humanness_score.py 打分。失败则返回空 dict。"""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "wewrite" / "scripts"))
        from humanness_score import score_article
        result = score_article(text, verbose=False)
        return {
            "humanness_score": result["composite_score"],
            "humanness_tier1_mean": result["tier1"]["_summary"]["mean_score"],
            "humanness_tier2_mean": result["tier2"]["_summary"]["mean_score"],
            "humanness_suggestions": result.get("suggestions", [])[:3],  # 只取前3条
            "humanness_ok": True,
        }
    except ImportError:
        # humanness_score 不在默认路径
        return {"humanness_ok": False}
    except Exception as e:
        return {"humanness_ok": False, "error": str(e)}


# ============================================================
# 主处理逻辑
# ============================================================

def process_article(record: dict, articles_dir: Path, do_score: bool) -> ArticleStats:
    """处理单篇文章，返回 ArticleStats。"""
    stats = ArticleStats(
        title=record.get("title", ""),
        account=record.get("account", ""),
        url=record.get("url", ""),
        date=record.get("date", ""),
        digest=record.get("digest", ""),
        status=record.get("status", "unknown"),
        error=record.get("error", ""),
        md_file=record.get("file_saved", ""),
    )

    # 读取 Markdown 正文
    md_path = Path(stats.md_file) if stats.md_file else None
    if not md_path or not md_path.exists():
        # 尝试在 articles_dir 中查找同名文件
        if stats.title:
            safe_name = _sanitize_filename(stats.title) + ".md"
            md_path = articles_dir / safe_name
            if not md_path.exists():
                md_path = None

    text = ""
    if md_path and md_path.exists():
        text = safe_read(md_path)
        stats.md_file = str(md_path)

    if not text:
        stats.error = stats.error or "未找到正文文件"
        return stats

    # 基础统计
    stats.word_count = _count_words(text)
    stats.image_count = len(re.findall(r'!\[.*?\]\(.*?\)', text))

    # 读取同名 HTML（尝试提取阅读量）
    if stats.title:
        html_name = _sanitize_filename(stats.title) + ".html"
        html_path = articles_dir / html_name
        if html_path.exists():
            html_text = safe_read(html_path)
            html_stats = _extract_html_stats(html_text)
            stats.read_count = html_stats["read_count"]
            stats.like_count = html_stats["like_count"]
            stats.comment_count = html_stats["comment_count"]
            stats.html_file = str(html_path)

    # AI 味打分
    if do_score and text:
        score_result = _try_score_article(text)
        if score_result.get("humanness_ok"):
            stats.humanness_score = score_result["humanness_score"]
            stats.humanness_tier1_mean = score_result["humanness_tier1_mean"]
            stats.humanness_tier2_mean = score_result["humanness_tier2_mean"]
            stats.humanness_suggestions = score_result.get("humanness_suggestions", [])

    return stats


def process_directory(articles_dir: Path, output_path: Path, do_score: bool, verbose: bool):
    """扫描目录，处理所有文章，输出 JSON。"""
    summary_json = articles_dir / "summary.json"

    if not summary_json.exists():
        print(f"Error: {summary_json} not found. Run batch_fetch_wechat.py first.", file=sys.stderr)
        sys.exit(1)

    records = json.loads(summary_json.read_text(encoding="utf-8"))
    print(f"[处理] 共 {len(records)} 篇文章...\n", file=sys.stderr)

    results: list[ArticleStats] = []
    for i, rec in enumerate(records, 1):
        stats = process_article(rec, articles_dir, do_score)
        results.append(stats)
        if verbose or stats.status == "failed":
            print(f"[{i}/{len(records)}] {stats.title[:40]}...", file=sys.stderr)
            if stats.error:
                print(f"  ❌ {stats.error}", file=sys.stderr)
            if stats.humanness_score >= 0:
                print(f"  🤖 humanness={stats.humanness_score:.1f}", file=sys.stderr)

    # 排序：humanness_score 降序（AI味重的排前面，方便重点改写）
    scored = [r for r in results if r.humanness_score >= 0]
    unscored = [r for r in results if r.humanness_score < 0]
    scored.sort(key=lambda x: x.humanness_score, reverse=True)
    ordered = scored + unscored

    # 输出
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(r) for r in ordered], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n[完成] 保存到 {output_path}", file=sys.stderr)

    # 摘要
    total = len(ordered)
    ok = sum(1 for r in ordered if r.status == "ok")
    if scored:
        avg_score = sum(r.humanness_score for r in scored) / len(scored)
        top_3 = scored[:3]
        print(f"\n[摘要] AI味评分 (平均={avg_score:.1f}/100)")
        for s in top_3:
            print(f"  {s.humanness_score:.1f} — {s.title[:50]}")


# ============================================================
# 入口
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="从已爬文章目录中提取结构化数据（humanness评分 + 基础统计）"
    )
    ap.add_argument("--input", required=True, help="文章目录（含 summary.json）")
    ap.add_argument("--output", required=True, help="输出 JSON 路径")
    ap.add_argument("--score", action="store_true", help="启用 humanness AI味打分")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    args = ap.parse_args()

    articles_dir = Path(args.input)
    output_path = Path(args.output)

    if not articles_dir.exists():
        print(f"Error: directory not found: {articles_dir}", file=sys.stderr)
        sys.exit(1)

    process_directory(articles_dir, output_path, do_score=args.score, verbose=args.verbose)


if __name__ == "__main__":
    main()
