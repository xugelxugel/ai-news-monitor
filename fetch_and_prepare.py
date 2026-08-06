#!/usr/bin/env python3
"""
每日AI资讯 - RSS抓取与预处理脚本

职责：
1. 并发抓取5个美国科技媒体RSS源
2. 解析为标准化文章结构
3. URL + 标题相似度去重
4. 缓存管理（已见文章记录）
5. 输出 today_articles.json 供 WorkBuddy AI 分析
"""

import os
import sys
import json
import hashlib
import logging
import logging.handlers
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 路径设置
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = BASE_DIR / "config.yaml"


# ──────────────────────────────────────────────
# 日志配置
# ──────────────────────────────────────────────
def setup_logger(config: dict) -> logging.Logger:
    logger = logging.getLogger("ai_news_fetcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    log_file = BASE_DIR / config.get("logging", {}).get("file", "logs/fetch.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    return logger


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────
@dataclass
class Article:
    title: str
    url: str
    source: str
    summary: str = ""
    published: str = ""

    def fingerprint(self) -> str:
        """生成URL的唯一指纹"""
        return hashlib.md5(self.url.encode()).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────
# RSS 抓取
# ──────────────────────────────────────────────
class RSSFetcher:
    """并发抓取多个RSS源"""

    # 模拟浏览器请求头，避免被部分源拒绝
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def __init__(self, feeds: list, timeout: int = 30, max_per_feed: int = 50,
                 logger: logging.Logger = None):
        self.feeds = feeds
        self.timeout = timeout
        self.max_per_feed = max_per_feed
        self.logger = logger or logging.getLogger("ai_news_fetcher")

    def fetch_one(self, feed: dict) -> list:
        """抓取单个RSS源，返回Article列表"""
        name = feed["name"]
        url = feed["url"]
        articles = []

        try:
            self.logger.info(f"正在抓取: {name} ({url})")

            # feedparser可以直接解析URL，但先手动获取以设置headers
            try:
                resp = requests.get(url, headers=self.HEADERS,
                                    timeout=self.timeout)
                resp.raise_for_status()
                feed_data = feedparser.parse(resp.content)
            except requests.RequestException as e:
                self.logger.warning(f"HTTP请求失败 {name}: {e}, 尝试直接解析")
                feed_data = feedparser.parse(url)

            if feed_data.bozo and not feed_data.entries:
                self.logger.warning(f"{name} RSS解析异常: {feed_data.bozo_exception}")
                return []

            count = 0
            for entry in feed_data.entries:
                if count >= self.max_per_feed:
                    break

                title = getattr(entry, "title", "").strip()
                link = getattr(entry, "link", "").strip()

                if not title or not link:
                    continue

                # ── Google News 代理源清理 ──
                # Reuters 等源通过 Google News 抓取时，标题会带 " - Reuters" 后缀
                if "news.google.com" in link:
                    import re
                    title = re.sub(r'\s+-\s+\w+\s*$', '', title).strip()

                # Bloomberg feeds 有时 link 是空字符串，尝试从 entry.links 获取
                if not link:
                    links = getattr(entry, "links", [])
                    for l in links:
                        href = l.get("href", "")
                        if href and "news.google.com" not in href:
                            link = href
                            break

                # 提取摘要 - 尝试多个字段
                summary = ""
                for field_name in ["summary", "description", "content"]:
                    val = getattr(entry, field_name, None)
                    if val:
                        if isinstance(val, list) and val:
                            val = val[0].get("value", "") if isinstance(val[0], dict) else str(val[0])
                        summary = str(val)
                        break

                # 清理HTML标签
                if summary:
                    soup = BeautifulSoup(summary, "html.parser")
                    summary = soup.get_text(separator=" ", strip=True)

                # 截断过长的摘要
                if len(summary) > 500:
                    summary = summary[:497] + "..."

                # 解析发布时间
                published = ""
                for date_field in ["published_parsed", "updated_parsed", "created_parsed"]:
                    time_struct = getattr(entry, date_field, None)
                    if time_struct:
                        try:
                            dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
                            published = dt.isoformat()
                            break
                        except Exception:
                            continue

                # 如果结构化时间解析失败，尝试字符串字段
                if not published:
                    for str_field in ["published", "updated", "created"]:
                        date_str = getattr(entry, str_field, None)
                        if date_str:
                            published = str(date_str)
                            break

                articles.append(Article(
                    title=title,
                    url=link,
                    source=name,
                    summary=summary,
                    published=published
                ))
                count += 1

            self.logger.info(f"{name}: 获取 {len(articles)} 篇文章")
            return articles

        except Exception as e:
            self.logger.error(f"抓取 {name} 失败: {e}", exc_info=True)
            return []

    def fetch_all(self) -> list:
        """并发抓取所有源"""
        all_articles = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            future_map = {
                executor.submit(self.fetch_one, feed): feed["name"]
                for feed in self.feeds
            }

            for future in as_completed(future_map):
                source_name = future_map[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                except Exception as e:
                    self.logger.error(f"线程异常 {source_name}: {e}")

        self.logger.info(f"所有源抓取完成，共 {len(all_articles)} 篇文章")
        return all_articles


# ──────────────────────────────────────────────
# 去重
# ──────────────────────────────────────────────
class ArticleDeduplicator:
    """文章去重：URL精确匹配 + 标题相似度匹配"""

    def __init__(self, cache_file: Path, keep_days: int = 30,
                 logger: logging.Logger = None):
        self.cache_file = cache_file
        self.keep_days = keep_days
        self.logger = logger or logging.getLogger("ai_news_fetcher")
        self.seen: dict = self._load_cache()

    def _load_cache(self) -> dict:
        """加载去重缓存"""
        if not self.cache_file.exists():
            return {}

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            self.logger.warning(f"缓存文件损坏，重建空缓存: {e}")
            return {}

    def _save_cache(self):
        """保存去重缓存"""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.seen, f, ensure_ascii=False, indent=2)
        except IOError as e:
            self.logger.error(f"保存缓存失败: {e}")

    def _cleanup_expired(self):
        """清理过期缓存条目"""
        cutoff = datetime.now() - timedelta(days=self.keep_days)
        cutoff_str = cutoff.isoformat()

        before = len(self.seen)
        self.seen = {
            k: v for k, v in self.seen.items()
            if v > cutoff_str
        }
        removed = before - len(self.seen)
        if removed > 0:
            self.logger.info(f"清理过期缓存: 移除 {removed} 条")

    @staticmethod
    def _title_similarity(t1: str, t2: str) -> float:
        """计算两个标题的相似度"""
        return SequenceMatcher(None, t1.lower(), t2.lower()).ratio()

    def _is_similar_to_existing(self, article: Article, existing_articles: list) -> bool:
        """检查文章标题是否与已有文章过于相似"""
        for existing in existing_articles:
            if article.source == existing.source:
                continue  # 同一来源的不做标题相似度判断
            sim = self._title_similarity(article.title, existing.title)
            if sim > 0.75:
                self.logger.debug(f"标题相似度去重: '{article.title}' ~ '{existing.title}' ({sim:.2f})")
                return True
        return False

    def deduplicate(self, articles: list) -> tuple:
        """
        去重处理
        返回: (新文章列表, 统计信息)
        """
        self._cleanup_expired()

        new_articles = []
        seen_titles = []

        for article in articles:
            fp = article.fingerprint()

            # URL去重
            if fp in self.seen:
                continue

            # 标题相似度去重（跨源）
            if self._is_similar_to_existing(article, new_articles + seen_titles):
                # 标记为已见，避免重复检查
                self.seen[fp] = datetime.now().isoformat()
                continue

            # 是新文章
            self.seen[fp] = datetime.now().isoformat()
            new_articles.append(article)
            seen_titles.append(article)

        self._save_cache()

        stats = {
            "total_fetched": len(articles),
            "after_dedup": len(new_articles),
            "cache_size": len(self.seen),
        }

        self.logger.info(
            f"去重完成: 抓取 {stats['total_fetched']} 篇, "
            f"新增 {stats['after_dedup']} 篇, 缓存 {stats['cache_size']} 条"
        )

        return new_articles, stats


# ──────────────────────────────────────────────
# JSON 输出
# ──────────────────────────────────────────────
def save_articles_json(articles: list, output_path: Path, stats: dict):
    """保存文章列表为JSON，供WorkBuddy AI分析"""
    tz_shanghai = timezone(timedelta(hours=8))
    now = datetime.now(tz_shanghai)

    output = {
        "date": now.strftime("%Y-%m-%d"),
        "fetch_time": now.isoformat(),
        "stats": stats,
        "articles": [a.to_dict() for a in articles],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output_path


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────
def main():
    # 加载配置
    if not CONFIG_PATH.exists():
        print(f"错误: 配置文件不存在: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    logger = setup_logger(config)
    logger.info("=" * 60)
    logger.info("每日AI资讯 - RSS抓取开始")
    logger.info("=" * 60)

    # 初始化组件
    fetcher = RSSFetcher(
        feeds=config["feeds"],
        timeout=config.get("fetch", {}).get("timeout", 30),
        max_per_feed=config.get("fetch", {}).get("max_per_feed", 50),
        logger=logger,
    )

    deduplicator = ArticleDeduplicator(
        cache_file=BASE_DIR / config["output"]["cache_file"],
        keep_days=config.get("output", {}).get("keep_cache_days", 30),
        logger=logger,
    )

    # Step 1: 抓取RSS
    articles = fetcher.fetch_all()

    if not articles:
        logger.warning("未获取到任何文章，退出")
        # 仍然输出空结果，便于下游处理
        output_path = BASE_DIR / config["output"]["articles_file"]
        save_articles_json([], output_path, {
            "total_fetched": 0,
            "after_dedup": 0,
            "cache_size": len(deduplicator.seen),
            "new_articles": 0,
        })
        logger.info(f"空结果已保存: {output_path}")
        return

    # Step 2: 去重
    new_articles, dedup_stats = deduplicator.deduplicate(articles)

    # Step 3: 保存JSON
    output_path = BASE_DIR / config["output"]["articles_file"]
    stats = {
        "total_fetched": dedup_stats["total_fetched"],
        "after_dedup": dedup_stats["after_dedup"],
        "cache_size": dedup_stats["cache_size"],
        "new_articles": dedup_stats["after_dedup"],
    }

    save_articles_json(new_articles, output_path, stats)
    logger.info(f"文章数据已保存: {output_path}")
    logger.info(f"统计: {stats}")
    logger.info("=" * 60)
    logger.info("RSS抓取完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
