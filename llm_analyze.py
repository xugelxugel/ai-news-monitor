# -*- coding: utf-8 -*-
"""
LLM 分析脚本（GitHub 云端版）
==============================
读取 data/today_articles.json（fetch_and_prepare.py 产出），调用 LLM API：
  1. 逐篇生成中文分析（title_cn / summary_cn / importance_score / category / score_reason）
  2. 整体生成三块战略分析（us_strategy 美方战略 / china_impact 中国影响 / weekly_watch 本周关注）
输出 data/analysis.json，供 gen_briefing.py 生成 HTML 简报。

免费供应商设计（均走 OpenAI 兼容接口）：
  主供应商 : 智谱 GLM-4-Flash（默认 glm-4-flash，免费）
  备用供应商: Google Gemini 免费档（默认 gemini-3.6-flash）
主供应商连续失败达阈值后自动切换备用，保证每日任务不中断。

环境变量:
  LLM_API_KEY               主供应商 API Key（智谱，必填）
  LLM_BASE_URL              主供应商 OpenAI 兼容端点（可选，有默认值）
  LLM_MODEL                 主模型名（可选，有默认值）
  LLM_FALLBACK_API_KEY      备用供应商 API Key（Gemini，可选）
  LLM_FALLBACK_BASE_URL     备用供应商端点（可选，有默认值）
  LLM_FALLBACK_MODEL        备用模型名（可选，有默认值）
  LLM_CONCURRENCY           逐篇分析并发数（默认 1，免费档限流稳妥）
  LLM_TIMEOUT               单请求超时秒数（默认 90）

用法:
  python llm_analyze.py                # 正常分析
  python llm_analyze.py --dry-run      # 不调用 API，生成占位分析（本地验证用）
  python llm_analyze.py --max-items 5  # 只分析前 N 篇（调试用）
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTICLES_JSON = os.path.join(BASE_DIR, "data", "today_articles.json")
ANALYSIS_JSON = os.path.join(BASE_DIR, "data", "analysis.json")

FAILOVER_THRESHOLD = 3   # 主供应商连续失败 N 次后切换到备用
MAX_RETRIES = 2          # 单条内容在单个供应商上的额外重试次数

TRACKING_TOPICS = ["基础模型", "新框架", "算力基础设施", "AI投资并购", "数据中心项目"]

SYSTEM_PROMPT = (
    "你是中美AI竞争情报分析师，擅长从美国科技媒体报道中提炼关键情报，"
    "并用简体中文输出。你关注美国在基础模型、新框架、算力建设、AI投融资并购、"
    "数据中心项目方面的动态，并擅长分析这些动态对中国AI产业的影响。"
)

# 逐篇分析 prompt
ITEM_PROMPT_TEMPLATE = """请分析以下英文新闻，只输出一个 JSON 对象（不要输出任何其他文字、注释或 markdown 代码块标记）。

【标题】{title}
【摘要】{summary}
【来源】{source}
【链接】{link}

JSON 字段定义：
- title_cn: 中文标题（保留 AI/LLM/GPT/GPU 等英文缩写不展开，其余翻译成自然流畅的中文）
- summary_cn: 2-3 句深度中文摘要（不是简单翻译，要包含分析视角，点出该事件与美国AI产业格局或中美AI竞争的关系）
- importance_score: 重要程度评分，1-10 的整数（10=基础模型重大发布/算力核心突破/大额并购或中美直接博弈；7-9=头部公司战略动向、AI安全事件、数据中心大项目；4-6=产业链上下游、融资、常规产品发布；1-3=与AI产业关系较远的边缘新闻）
- category: 内容分类，从以下方向中选择 1-2 个，用" · "连接：{topics}
- score_reason: 一句话中文说明为什么给这个分数

示例输出：
{{"title_cn": "…", "summary_cn": "…", "importance_score": 8, "category": "算力基础设施", "score_reason": "…"}}"""

# 整体战略分析 prompt（一次性输入全部文章标题）
OVERALL_PROMPT_TEMPLATE = """以下是今天监测到的美国AI产业新闻（{count} 条），已按重要性排序：
{article_list}

请基于这些新闻，输出一个 JSON 对象（不要输出任何其他文字），包含三个字段：

1. "us_strategy": 美方战略方向分析 —— 提炼 3-5 条核心战略动向，每条格式为
   {{"point": "加粗小标题", "detail": "2-3 句深度分析，结合具体新闻展开"}}
   从技术路线、算力布局、资本动向、监管政策、人才组织、全球竞争等维度综合判断。

2. "china_impact": 对中国AI产业的影响分析 —— 提炼 3-5 条影响，每条格式为
   {{"point": "加粗小标题（格式：领域：要点）", "detail": "2-3 句分析，说明影响机制与应对建议"}}
   覆盖技术竞争、供应链、人才、资本、安全治理等维度。

3. "weekly_watch": 本周重点关注 —— 3-5 条后续跟踪线索，每条格式为
   {{"point": "加粗小标题", "detail": "1-2 句说明跟踪什么、关注什么信号"}}

输出 JSON 示例：
{{"us_strategy": [{{"point": "…", "detail": "…"}}], "china_impact": [{{"point": "…", "detail": "…"}}], "weekly_watch": [{{"point": "…", "detail": "…"}}]}}"""


# ============================================================
# 供应商管理（含失败切换）
# ============================================================

class RateLimitError(RuntimeError):
    """供应商限流（HTTP 429），应等待更长时间后重试。"""


class ProviderPool:
    """管理多个 LLM 供应商，主供应商连续失败后自动切换到备用。"""

    def __init__(self, providers):
        self.providers = [p for p in providers if p.get("api_key")]
        if not self.providers:
            raise SystemExit("[错误] 未配置任何 LLM API Key（LLM_API_KEY 必填）")
        self.index = 0
        self.consecutive_failures = 0
        self.lock = threading.Lock()
        self.usage = {p["name"]: 0 for p in self.providers}

    def current(self):
        return self.providers[self.index]

    def on_success(self):
        with self.lock:
            self.consecutive_failures = 0
            self.usage[self.providers[self.index]["name"]] += 1

    def on_failure(self):
        with self.lock:
            self.consecutive_failures += 1
            if (self.consecutive_failures >= FAILOVER_THRESHOLD
                    and self.index < len(self.providers) - 1):
                self.index += 1
                self.consecutive_failures = 0
                print(f"  [切换] 主供应商连续失败，切换到备用供应商: "
                      f"{self.providers[self.index]['name']}")


def call_chat(provider, messages, timeout):
    """调用单个供应商的 OpenAI 兼容 chat/completions 接口，返回 content 文本。"""
    url = provider["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 3000,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code == 429:
        raise RateLimitError(
            f"429 限流（{provider['name']}）: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise RuntimeError(
            f"HTTP {resp.status_code}（{provider['name']}）: {resp.text[:300]}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"响应格式异常（{provider['name']}）: {data}") from e
    return content


def extract_json(text):
    """从模型输出中提取 JSON 对象。支持修复被 max_tokens 截断的输出。"""
    start = text.find("{")
    if start == -1:
        raise ValueError(f"输出中未找到 JSON: {text[:200]}")
    end = text.rfind("}")
    if end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass  # 完整 } 存在但 JSON 仍有语法错误，继续尝试修复
    snippet = text[start:]
    last_comma = snippet.rfind(",")
    if last_comma > 0:
        candidate = snippet[:last_comma].rstrip() + "}"
        try:
            result = json.loads(candidate)
            print(f"  [修复] JSON 被截断，已提取已完成字段: {list(result.keys())}")
            return result
        except json.JSONDecodeError:
            pass
    raise ValueError(f"输出中未找到有效 JSON（可能被截断）: {text[:200]}")


def normalize_item_analysis(parsed, fallback_title):
    """校验并归一化逐篇分析字段，缺失时给默认值。"""
    score = parsed.get("importance_score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 3
    score = max(1, min(10, score))
    category = str(parsed.get("category") or "").strip()
    if not category:
        category = "AI产业动态"
    return {
        "title_cn": str(parsed.get("title_cn") or fallback_title),
        "summary_cn": str(parsed.get("summary_cn") or ""),
        "importance_score": score,
        "category": category,
        "score_reason": str(parsed.get("score_reason") or ""),
    }


def analyze_item(item, pool, timeout):
    """分析单篇新闻，返回 {url: analysis}。内部处理重试与供应商切换。"""
    summary = item.get("summary") or "（无摘要）"
    user_prompt = ITEM_PROMPT_TEMPLATE.format(
        title=item["title"],
        summary=summary[:1200],
        source=item["source"],
        link=item["url"],
        topics="、".join(TRACKING_TOPICS),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        provider = pool.current()
        try:
            content = call_chat(provider, messages, timeout)
            parsed = extract_json(content)
            analysis = normalize_item_analysis(parsed, item["title"])
            pool.on_success()
            return {item["url"]: analysis}
        except RateLimitError as e:
            last_err = e
            pool.on_failure()
            wait = 5 * (attempt + 1)
            print(f"  [限流] {str(e)[:80]} 等待 {wait}s 后重试")
            time.sleep(wait)
        except Exception as e:
            last_err = e
            pool.on_failure()
            if attempt < MAX_RETRIES:
                time.sleep(2 * (attempt + 1))
    print(f"  [失败] 分析失败: {item['title'][:60]}... 原因: {last_err}")
    return {}


def analyze_overall(items, pool, timeout):
    """整体生成三块战略分析。失败时返回空结构，由简报以默认文案兜底。"""
    article_list = "\n".join(
        f"{i+1}. {it['title'][:100]}" for i, it in enumerate(items[:30]))
    user_prompt = OVERALL_PROMPT_TEMPLATE.format(
        count=len(items), article_list=article_list)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    last_err = "未知错误"
    for attempt in range(MAX_RETRIES + 1):
        provider = pool.current()
        try:
            content = call_chat(provider, messages, timeout)
            parsed = extract_json(content)
            pool.on_success()
            return {
                "us_strategy": normalize_blocks(parsed.get("us_strategy")),
                "china_impact": normalize_blocks(parsed.get("china_impact")),
                "weekly_watch": normalize_blocks(parsed.get("weekly_watch")),
            }
        except RateLimitError as e:
            last_err = str(e)
            pool.on_failure()
            wait = 8 * (attempt + 1)
            print(f"  [限流] 整体分析 {str(e)[:80]} 等待 {wait}s 后重试")
            time.sleep(wait)
        except Exception as e:
            last_err = str(e)
            pool.on_failure()
            if attempt < MAX_RETRIES:
                time.sleep(3 * (attempt + 1))
    print(f"  [失败] 整体战略分析失败，将使用兜底文案: {last_err}")
    return {"us_strategy": [], "china_impact": [], "weekly_watch": []}


def normalize_blocks(blocks):
    """校验战略分析块结构，返回 [{point, detail}] 列表。"""
    if not isinstance(blocks, list):
        return []
    result = []
    for b in blocks[:5]:
        if isinstance(b, dict) and b.get("point"):
            result.append({
                "point": str(b["point"]).strip(),
                "detail": str(b.get("detail") or "").strip(),
            })
    return result


def dry_run_item(item):
    """不调用 API 的占位分析，用于本地验证 JSON 结构与下游链路。"""
    return {
        item["url"]: {
            "title_cn": item["title"],
            "summary_cn": "（dry-run 占位摘要，未调用真实 LLM）",
            "importance_score": 5,
            "category": "AI产业动态",
            "score_reason": "（dry-run 占位）",
        }
    }


def dry_run_overall():
    """占位整体分析。"""
    return {
        "us_strategy": [{"point": "（dry-run 占位）", "detail": "未调用真实 LLM，此为占位内容。"}],
        "china_impact": [{"point": "（dry-run 占位）", "detail": "未调用真实 LLM，此为占位内容。"}],
        "weekly_watch": [{"point": "（dry-run 占位）", "detail": "未调用真实 LLM，此为占位内容。"}],
    }


# ============================================================
# 主流程
# ============================================================

def build_providers():
    """从环境变量构建供应商列表（智谱主用 + Gemini 备用）。"""
    providers = [
        {
            "name": "bigmodel",
            "base_url": os.environ.get(
                "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
            "api_key": os.environ.get("LLM_API_KEY", ""),
            "model": os.environ.get("LLM_MODEL", "glm-4-flash"),
        },
        {
            "name": "gemini",
            "base_url": os.environ.get(
                "LLM_FALLBACK_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/"),
            "api_key": os.environ.get("LLM_FALLBACK_API_KEY", ""),
            "model": os.environ.get("LLM_FALLBACK_MODEL", "gemini-3.6-flash"),
        },
    ]
    active = [p for p in providers if p.get("api_key")]
    if not active:
        raise SystemExit(
            "[错误] 未配置任何 LLM API Key。\n"
            "  主供应商: 设置环境变量 LLM_API_KEY（智谱 Key，见 open.bigmodel.cn）\n"
            "  备用供应商: 可选设置 LLM_FALLBACK_API_KEY（Gemini，见 aistudio.google.com/apikey）")
    return providers


def main():
    parser = argparse.ArgumentParser(description="LLM 深度分析（生成 data/analysis.json）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不调用 API，生成占位分析（本地验证用）")
    parser.add_argument("--max-items", type=int, default=0,
                        help="只分析前 N 篇（默认全部）")
    args = parser.parse_args()

    if not os.path.exists(ARTICLES_JSON):
        raise SystemExit(f"[错误] 未找到 {ARTICLES_JSON}，请先运行 fetch_and_prepare.py")
    with open(ARTICLES_JSON, "r", encoding="utf-8") as f:
        payload = json.load(f)
    items = payload.get("articles", [])
    if args.max_items > 0:
        items = items[:args.max_items]
    print(f"待分析文章: {len(items)} 篇（日期 {payload.get('date', '?')}）")

    os.makedirs(os.path.dirname(ANALYSIS_JSON), exist_ok=True)
    concurrency = int(os.environ.get("LLM_CONCURRENCY", "1"))
    timeout = int(os.environ.get("LLM_TIMEOUT", "90"))

    item_results = {}
    overall = {}

    if args.dry_run:
        print("[dry-run] 不调用 API，生成占位分析...")
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(dry_run_item, item) for item in items]
            for fut in as_completed(futs):
                item_results.update(fut.result())
        overall = dry_run_overall()
    else:
        providers = build_providers()
        pool_state = ProviderPool(providers)
        print(f"启用供应商: {[p['name'] for p in pool_state.providers]} | 并发: {concurrency}")

        # 先做整体战略分析（一次调用），再逐篇分析
        print("\n[整体分析] 生成美方战略 / 中国影响 / 本周关注...")
        overall = analyze_overall(items, pool_state, timeout)
        if not overall.get("us_strategy"):
            print("[警告] 整体分析为空，简报将使用兜底文案")

        print(f"\n[逐篇分析] 共 {len(items)} 篇...")
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futs = [pool.submit(analyze_item, item, pool_state, timeout)
                    for item in items]
            done = 0
            for fut in as_completed(futs):
                item_results.update(fut.result())
                done += 1
                if done % 5 == 0 or done == len(items):
                    print(f"  进度: {done}/{len(items)}")
        print("供应商用量: " + ", ".join(
            f"{k}={v}" for k, v in pool_state.usage.items()))

    output = {
        "date": payload.get("date", ""),
        "overall": overall,
        "articles": item_results,
    }
    with open(ANALYSIS_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    covered = len(item_results)
    print(f"分析完成: 成功 {covered}/{len(items)}")
    if covered == 0 and not args.dry_run:
        print("[严重] LLM 分析全部失败，简报将使用英文原文兜底（请检查 API Key / 限流）")
        print(f"输出: {ANALYSIS_JSON}")
        return 2
    if covered < len(items):
        print(f"[警告] {len(items) - covered} 篇分析失败，简报中将以原文标题兜底")
    print(f"输出: {ANALYSIS_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
