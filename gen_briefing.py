# -*- coding: utf-8 -*-
"""
简报生成脚本（GitHub 云端版）
==============================
读取 data/today_articles.json（抓取结果）+ data/analysis.json（LLM 分析），
生成 data/briefings/YYYY-MM-DD/ai_briefing.html，结构与 WorkBuddy 版简报一致：
  头部统计 → 今日AI要闻（按重要程度排序）→ 美方战略分析 → 中国影响分析 → 本周关注

用法:
  python gen_briefing.py              # 生成当日简报
  python gen_briefing.py --date 2026-08-06   # 指定日期（调试用）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_JSON = os.path.join(BASE_DIR, "data", "today_articles.json")
ANALYSIS_JSON = os.path.join(BASE_DIR, "data", "analysis.json")

TZ_BJ = timezone(timedelta(hours=8))

# 来源徽章样式映射
SOURCE_BADGES = {
    "TechCrunch": "badge-tc",
    "The Verge": "badge-verge",
    "CNBC Technology": "badge-cnbc",
    "CNBC": "badge-cnbc",
    "Bloomberg Technology": "badge-bloomberg",
    "Bloomberg": "badge-bloomberg",
    "VentureBeat": "badge-vb",
    "Reuters Technology": "badge-reuters",
    "Reuters": "badge-reuters",
    "NYT Technology": "badge-nyt",
    "NYT": "badge-nyt",
}

WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f0f2f5;
    color: #333;
    line-height: 1.6;
    padding: 0;
}
.container { max-width: 1100px; margin: 0 auto; padding: 0 20px; }

/* Header */
.header {
    background: linear-gradient(135deg, #5b4cc4 0%, #7c6ff7 50%, #a29bfe 100%);
    padding: 50px 0 40px;
    text-align: center;
}
.header h1 { font-size: 2.2em; color: #fff; font-weight: 700; letter-spacing: 2px; }
.header .date { font-size: 1.3em; color: rgba(255,255,255,0.9); margin-top: 8px; }
.header .subtitle { font-size: 0.95em; color: rgba(255,255,255,0.75); margin-top: 6px; }

/* Stats */
.stats-bar {
    display: flex; justify-content: center; gap: 30px; flex-wrap: wrap;
    margin-top: 25px;
}
.stat-card {
    background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3);
    border-radius: 10px; padding: 15px 25px; text-align: center; min-width: 120px;
    backdrop-filter: blur(10px);
}
.stat-card .num { font-size: 2em; font-weight: 700; color: #fff; }
.stat-card .label { font-size: 0.8em; color: rgba(255,255,255,0.8); margin-top: 4px; }

/* Section */
.section { margin: 45px 0; }
.section-title {
    font-size: 1.5em; font-weight: 700; color: #5b4cc4;
    border-left: 4px solid #6c5ce7; padding-left: 15px;
    margin-bottom: 25px; display: flex; align-items: center; gap: 8px;
}
.section-title .icon { font-size: 1.1em; }

/* News Cards */
.news-grid { display: grid; grid-template-columns: 1fr; gap: 18px; }
.news-card {
    background: #fff; border: 1px solid #e0e0e0; border-radius: 12px;
    padding: 22px; transition: transform 0.2s, box-shadow 0.2s;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.news-card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(108,92,231,0.12); border-color: #c4b5fd; }
.news-card .top-row { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
.news-card .source-badge {
    font-size: 0.75em; font-weight: 600; padding: 3px 10px;
    border-radius: 20px; text-transform: uppercase; letter-spacing: 0.5px;
}
.badge-tc { background: #0d9e4e; color: #fff; }
.badge-verge { background: #e8472d; color: #fff; }
.badge-cnbc { background: #00559b; color: #fff; }
.badge-bloomberg { background: #1a1a1a; color: #fd8300; border: 1px solid #fd8300; }
.badge-vb { background: #3b5998; color: #fff; }
.badge-reuters { background: #ff8000; color: #fff; }
.badge-nyt { background: #1a1a1a; color: #fff; }

.news-card .score-badge {
    font-size: 0.8em; font-weight: 700; padding: 3px 10px;
    border-radius: 20px;
}
.score-high { background: #e74c3c; color: #fff; }
.score-mid { background: #f39c12; color: #fff; }
.score-low { background: #27ae60; color: #fff; }

.news-card h3 { font-size: 1.15em; color: #1a1a2e; margin-bottom: 8px; font-weight: 600; }
.news-card .category-tag {
    display: inline-block; font-size: 0.75em; color: #5b4cc4;
    background: rgba(108,92,231,0.08); border: 1px solid rgba(108,92,231,0.2);
    padding: 2px 10px; border-radius: 15px; margin-bottom: 10px;
}
.news-card .summary { font-size: 0.95em; color: #555; margin-bottom: 12px; }
.news-card .meta { font-size: 0.8em; color: #999; display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }
.news-card .meta .time { color: #666; font-weight: 500; }
.news-card .meta a { color: #5b4cc4; text-decoration: none; }
.news-card .meta a:hover { text-decoration: underline; }

/* Analysis */
.analysis-box {
    background: #fff; border: 1px solid #e0e0e0; border-radius: 12px;
    padding: 25px; margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.analysis-box .analysis-title {
    font-size: 1.1em; font-weight: 600; color: #5b4cc4; margin-bottom: 10px;
}
.analysis-box .analysis-text { font-size: 0.95em; color: #555; line-height: 1.8; }
.analysis-box .num-badge {
    display: inline-block; width: 24px; height: 24px;
    background: #6c5ce7; color: #fff; border-radius: 50%;
    text-align: center; line-height: 24px; font-size: 0.8em; font-weight: 700;
    margin-right: 8px;
}
.analysis-item { margin-bottom: 14px; }
.analysis-item:last-child { margin-bottom: 0; }

/* Watch Items */
.watch-list { list-style: none; }
.watch-list li {
    background: #fff; border-left: 3px solid #e74c3c; border-radius: 0 8px 8px 0;
    padding: 15px 20px; margin-bottom: 12px; font-size: 0.95em; color: #555;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.watch-list li strong { color: #c0392b; }

/* Footer */
.footer { text-align: center; padding: 30px 0; color: #999; font-size: 0.85em; border-top: 1px solid #e0e0e0; margin-top: 50px; }

@media (max-width: 768px) {
    .header h1 { font-size: 1.6em; }
    .stats-bar { gap: 12px; }
    .stat-card { min-width: 100px; padding: 10px 15px; }
    .news-card { padding: 15px; }
    .news-card h3 { font-size: 1em; }
}
@media print { body { background: #fff; color: #000; } .news-card { break-inside: avoid; } }
"""

FALLBACK_ANALYSIS = {
    "us_strategy": [{
        "point": "今日暂无显著战略动向",
        "detail": "今日未监测到足以支撑深度分析的高价值新闻，请关注明日更新。",
    }],
    "china_impact": [{
        "point": "今日暂无显著影响",
        "detail": "今日新闻对中国AI产业暂无显著直接影响，请关注明日更新。",
    }],
    "weekly_watch": [{
        "point": "关注后续进展",
        "detail": "持续跟踪相关事件的后续发展。",
    }],
}


def load_json(path):
    if not os.path.exists(path):
        print(f"[错误] 未找到 {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def source_badge(source):
    return SOURCE_BADGES.get(source, "badge-nyt")


def score_badge(score):
    if score >= 8:
        return "score-high"
    if score >= 5:
        return "score-mid"
    return "score-low"


def format_time(published, date_str):
    """把 ISO 时间格式化为 '8月6日 00:47'。"""
    if not published:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", published)
    if not m:
        return ""
    y, mo, d, h, mi = m.groups()
    if str(y) == date_str[:4] and int(mo) == int(date_str[5:7]):
        return f"{int(mo)}月{int(d)}日 {h}:{mi}"
    return f"{int(mo)}月{int(d)}日 {h}:{mi}"


def build_news_cards(articles, analyses):
    """生成新闻卡片 HTML，按重要程度降序。返回 (html, 高价值文章数)。"""
    cards = []
    high_value = 0
    for a in articles:
        analysis = analyses.get(a["url"], {})
        score = analysis.get("importance_score", 5)
        if score >= 7:
            high_value += 1
        title = analysis.get("title_cn") or a["title"]
        summary = analysis.get("summary_cn") or a.get("summary", "")
        category = analysis.get("category", "")
        source = a.get("source", "")
        published = a.get("published", "")
        link = a["url"]

        cat_html = (f'<span class="category-tag">{category}</span>'
                    if category else "")
        cards.append(f"""
        <div class="news-card">
            <div class="top-row">
                <span class="source-badge {source_badge(source)}">{source}</span>
                <span class="score-badge {score_badge(score)}">{score:.1f}</span>
            </div>
            {cat_html}
            <h3>{title}</h3>
            <div class="summary">{summary}</div>
            <div class="meta">
                <span class="time">🕐 {format_time(published, '')}</span>
                <span>来源: {source}</span>
                <a href="{link}">阅读原文 →</a>
            </div>
        </div>""")
    return "\n".join(cards), high_value


def build_analysis_block(blocks, title, icon):
    """生成战略分析块 HTML。"""
    items_html = ""
    for i, b in enumerate(blocks, 1):
        items_html += (f'<div class="analysis-item"><span class="num-badge">{i}</span>'
                       f'<strong>{b["point"]}</strong> {b["detail"]}</div>')
    if not items_html:
        items_html = '<div class="analysis-item"><strong>今日暂无显著动态。</strong> 请关注明日更新。</div>'
    return f"""
<div class="section">
    <div class="section-title"><span class="icon">{icon}</span> {title}</div>
    <div class="analysis-box">
        <div class="analysis-title">AI 产业多维透视</div>
        <div class="analysis-text">
            {items_html}
        </div>
    </div>
</div>"""


def build_watch_list(blocks):
    items_html = ""
    for b in blocks:
        items_html += f'<li><strong>{b["point"]}：</strong>{b["detail"]}</li>'
    if not items_html:
        items_html = '<li><strong>关注后续进展：</strong>持续跟踪相关事件的后续发展。</li>'
    return f"""
<div class="section">
    <div class="section-title"><span class="icon">👀</span> 本周重点关注</div>
    <ul class="watch-list">
        {items_html}
    </ul>
</div>"""


def main():
    parser = argparse.ArgumentParser(description="生成每日 AI 简报 HTML")
    parser.add_argument("--date", default="", help="指定简报日期 YYYY-MM-DD（默认今天）")
    args = parser.parse_args()

    articles_payload = load_json(ARTICLES_JSON)
    if articles_payload is None:
        sys.exit(1)
    analysis_payload = load_json(ANALYSIS_JSON) or {"overall": {}, "articles": {}}

    date_str = args.date or articles_payload.get("date", "")
    if not date_str:
        date_str = datetime.now(TZ_BJ).strftime("%Y-%m-%d")
    today = datetime.strptime(date_str, "%Y-%m-%d")
    weekday_cn = WEEKDAYS_CN[today.weekday()]
    date_cn = f"{today.year}年{today.month}月{today.day}日"

    stats = articles_payload.get("stats", {})
    articles = articles_payload.get("articles", [])
    analyses = analysis_payload.get("articles", {})

    # 按重要程度降序排序
    def sort_key(a):
        return analyses.get(a["url"], {}).get("importance_score", 0)
    articles_sorted = sorted(articles, key=sort_key, reverse=True)

    news_html, high_value = build_news_cards(articles_sorted, analyses)
    if not news_html:
        news_html = '<div class="news-card"><h3>今日暂无新增 AI 相关文章</h3><div class="summary">请关注明日更新。</div></div>'

    overall = analysis_payload.get("overall", {}) or {}
    us_strategy = overall.get("us_strategy") or FALLBACK_ANALYSIS["us_strategy"]
    china_impact = overall.get("china_impact") or FALLBACK_ANALYSIS["china_impact"]
    weekly_watch = overall.get("weekly_watch") or FALLBACK_ANALYSIS["weekly_watch"]

    us_html = build_analysis_block(us_strategy, "美方战略方向分析", "🧭")
    china_html = build_analysis_block(china_impact, "对中国AI产业的影响分析", "🇨🇳")
    watch_html = build_watch_list(weekly_watch)

    max_score = max((analyses.get(a["url"], {}).get("importance_score", 0)
                     for a in articles), default=0)
    fetch_count = stats.get("total_fetched", len(articles))
    new_count = stats.get("new_articles", stats.get("after_dedup", len(articles)))
    today_count = stats.get("after_dedup", len(articles))

    now_str = datetime.now(TZ_BJ).strftime("%Y-%m-%d %H:%M")
    sources_str = "TechCrunch / The Verge / CNBC / Bloomberg / VentureBeat / Reuters / NYT"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日AI资讯简报 — {date_cn}</title>
<style>
{CSS}
</style>
</head>
<body>

<div class="header">
    <div class="container">
        <h1>每日AI资讯简报</h1>
        <div class="date">{date_cn} · {weekday_cn}</div>
        <div class="subtitle">监测美国AI产业动态 · 分析对中国AI产业影响</div>
        <div class="stats-bar">
            <div class="stat-card"><div class="num">{fetch_count}</div><div class="label">抓取文章</div></div>
            <div class="stat-card"><div class="num">{new_count}</div><div class="label">本次新增</div></div>
            <div class="stat-card"><div class="num">{today_count}</div><div class="label">当日累计</div></div>
            <div class="stat-card"><div class="num">{max_score:.1f}</div><div class="label">最高评分</div></div>
        </div>
    </div>
</div>

<div class="container">

<!-- ====== 今日要闻 ====== -->
<div class="section">
    <div class="section-title"><span class="icon">🔥</span> 今日AI要闻（按重要程度排序）</div>
    <div class="news-grid">
        {news_html}
    </div>
</div>

{us_html}
{china_html}
{watch_html}

<div class="footer">
    每日AI资讯简报 · 自动生成于 {now_str} (北京时间)<br>
    数据来源: {sources_str}
</div>

</div>
</body>
</html>"""

    out_dir = os.path.join(BASE_DIR, "data", "briefings", date_str)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "ai_briefing.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"简报已生成: {out_path}")
    print(f"统计: 抓取 {fetch_count} | 新增 {new_count} | 高价值(≥7分) {high_value} | 最高分 {max_score:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
