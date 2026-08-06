# -*- coding: utf-8 -*-
"""
GitHub Pages 发布 + 微信提醒（云端版）
======================================
每日流水线步骤3（发布）：

  1. 把最新简报复制到仓库 docs/briefings/YYYY-MM-DD.html
  2. 生成 docs/index.html（历史归档索引页）
  3. 通过微信推送简报提醒（含 Pages 网页链接）

真正的"上线"由 GitHub Actions 工作流部署完成（upload-pages-artifact +
deploy-pages），本脚本只负责把文件放到 docs/ 并触发微信提醒。
GitHub Pages 启用方法：仓库 Settings → Pages → Source 选 "GitHub Actions"
（configure-pages 的 enablement: true 会自动创建/切换，无需手动设置）。

环境变量:
  WECHAT_NOTIFY_TYPE / WECHAT_NOTIFY_KEY   见 wechat_notify.py
  GITHUB_REPOSITORY   GitHub Actions 自动注入（形如 user/repo），用于生成链接

用法:
  python publish_pages.py               # 发布 + 微信提醒
  python publish_pages.py --no-notify   # 只发布不提醒（调试用）
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEFINGS_SRC = os.path.join(BASE_DIR, "data", "briefings")
REPO_ROOT = BASE_DIR                    # 项目根 = GitHub 仓库根
DOCS_DIR = os.path.join(REPO_ROOT, "docs")
BRIEFINGS_DIR = os.path.join(DOCS_DIR, "briefings")


def latest_briefing():
    """返回 data/briefings/ 下日期最新的简报路径。"""
    if not os.path.isdir(BRIEFINGS_SRC):
        raise FileNotFoundError(f"{BRIEFINGS_SRC} 目录不存在")
    dates = [d for d in os.listdir(BRIEFINGS_SRC)
             if os.path.isdir(os.path.join(BRIEFINGS_SRC, d))]
    if not dates:
        raise FileNotFoundError(
            f"{BRIEFINGS_SRC} 下无简报目录，请先运行抓取与分析步骤")
    dates.sort()
    date_str = dates[-1]
    src = os.path.join(BRIEFINGS_SRC, date_str, "ai_briefing.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"未找到简报文件: {src}")
    return date_str, src


def publish():
    """复制最新简报到 docs/briefings/，返回 (日期字符串, 目标路径)。"""
    date_str, src = latest_briefing()
    os.makedirs(BRIEFINGS_DIR, exist_ok=True)
    dst = os.path.join(BRIEFINGS_DIR, f"{date_str}.html")
    shutil.copy2(src, dst)
    return date_str, dst


def generate_index():
    """生成 docs/index.html 归档索引页，返回归档期数。"""
    entries = []
    if os.path.isdir(BRIEFINGS_DIR):
        for f in sorted(os.listdir(BRIEFINGS_DIR)):
            if not f.endswith(".html"):
                continue
            d = f[:-5]
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                continue
            entries.append((d, f))
    entries.sort(reverse=True)

    items_html = "".join(
        f'<li><a href="briefings/{f}">{d}</a></li>' for d, f in entries)
    if not items_html:
        items_html = "<li>暂无简报</li>"

    index = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日AI资讯简报 · 归档</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       background: #f5f5f5; color: #333; line-height: 1.7; max-width: 720px; margin: 0 auto; padding: 24px; }}
h1 {{ font-size: 22px; color: #1a1a2e; }}
.sub {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
ul {{ list-style: none; padding: 0; }}
li {{ background: #fff; border-radius: 8px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); }}
a {{ display: block; padding: 12px 16px; color: #5b4cc4; text-decoration: none; font-size: 15px; }}
a:hover {{ background: #f0f7ff; }}
</style>
</head>
<body>
<h1>每日AI资讯简报</h1>
<div class="sub">每日监测美国主流媒体的 AI 产业动态 · 共 {len(entries)} 期</div>
<ul>
{items_html}
</ul>
</body>
</html>"""
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index)
    # .nojekyll：跳过 Jekyll 构建，纯静态文件直接发布
    nojekyll = os.path.join(DOCS_DIR, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w", encoding="utf-8") as f:
            f.write("")
    return len(entries)


def pages_url(date_str):
    """生成当日简报的 Pages 链接。GitHub Actions 中 GITHUB_REPOSITORY=user/repo。"""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/briefings/{date_str}.html"
    return None


def build_notice_content(date_str, url, article_count):
    """构建微信提醒内容（Markdown 格式，链接可点击）。"""
    lines = [f"**{date_str} 每日AI资讯简报已更新**"]
    if url:
        lines.append(f"[点击查看网页版]({url})")
    if article_count:
        lines.append(f"共 {article_count} 条 AI 相关动态，请点击链接查看详情。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="GitHub Pages 发布 + 微信提醒")
    parser.add_argument("--no-notify", action="store_true",
                        help="只发布不发送微信提醒（调试用）")
    args = parser.parse_args()

    date_str, dst = publish()
    print(f"已发布: {dst}")
    count = generate_index()
    print(f"归档索引已更新: {count} 期简报")

    # 读取当天文章数（用于提醒内容）
    article_count = 0
    try:
        with open(os.path.join(BASE_DIR, "data", "today_articles.json"),
                  encoding="utf-8") as f:
            article_count = len(json.load(f).get("articles", []))
    except Exception:
        pass

    if not args.no_notify:
        url = pages_url(date_str)
        content = build_notice_content(date_str, url, article_count)
        sys.path.insert(0, BASE_DIR)
        import wechat_notify
        wechat_notify.send_wechat(
            f"【每日AI资讯】{date_str} 简报已更新", content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
