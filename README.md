# 每日AI资讯简报

每日自动监测美国主流媒体的 AI 产业动态，分析美方战略方向及对中国 AI 产业的影响，生成精美 HTML 简报。

## 监测来源（7 个）

| 来源 | 类型 | RSS 地址 |
|------|------|----------|
| **TechCrunch** | 硅谷科技/创投 | `https://techcrunch.com/feed/` |
| **The Verge** | 综合科技 | `https://www.theverge.com/rss/index.xml` |
| **CNBC Technology** | 财经商业 | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115` |
| **Bloomberg Technology** | 财经商业 | `https://feeds.bloomberg.com/technology/news.rss` |
| **VentureBeat** | AI 产业分析 | `https://venturebeat.com/feed/` |
| **Reuters Technology** | 全球通讯社 | Google News 代理（`site:reuters.com`） |
| **NYT Technology** | 政策/调查报道 | `https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml` |

## 关注方向

1. **基础模型** — GPT、Claude、Gemini、Llama 等大模型进展
2. **新框架** — AI 开发框架、安全框架、行业联盟与标准
3. **算力基础设施** — GPU、TPU、芯片、算力云服务
4. **AI 投资并购** — 大额融资、收购、IPO
5. **数据中心项目** — 数据中心建设、选址、电力供应

## 运行方式

### 云端自动运行（GitHub Actions，推荐）

代码已配置 GitHub 云端流水线（详见 `CLOUD_DEPLOY.md`）：

```
fetch_and_prepare.py → llm_analyze.py（智谱 GLM 分析）→ gen_briefing.py → publish_pages.py
→ GitHub Pages 发布 + 微信提醒
```

每天 **6:50 AM 北京时间** 由 GitHub Actions 自动执行，网页版简报：
`https://xugelxugel.github.io/ai-news-monitor/briefings/YYYY-MM-DD.html`

### 本地手动运行

```bash
cd C:\Users\xugel\WorkBuddy\每日AI资讯
C:\Users\xugel\.workbuddy\binaries\python\envs\default\Scripts\python.exe fetch_and_prepare.py
```

运行后会生成 `data/today_articles.json`，随后可通过 WorkBuddy 对话请求生成简报。

## 文件结构

```
每日AI资讯/
├── README.md                       # 本文件
├── CLOUD_DEPLOY.md                 # GitHub 云端部署指南
├── config.yaml                     # RSS 源与运行配置
├── fetch_and_prepare.py            # RSS 抓取与去重脚本
├── llm_analyze.py                  # LLM 分析脚本（智谱 GLM 主用 + Gemini 备用）
├── gen_briefing.py                 # HTML 简报生成脚本
├── publish_pages.py                # GitHub Pages 发布 + 微信提醒
├── wechat_notify.py                # 微信推送（Server酱/PushPlus）
├── run_daily.py                    # 云端流水线编排（四步串联）
├── push_to_github.sh               # 一键推送到 GitHub
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量模板
├── .github/workflows/daily.yml     # GitHub Actions 每日定时任务
├── data/
│   ├── today_articles.json         # 当日待分析文章（Python 产出）
│   ├── analysis.json               # LLM 分析结果（中文标题/摘要/评分/战略分析）
│   ├── briefings/
│   │   └── YYYY-MM-DD/
│   │       └── ai_briefing.html    # 每日简报
│   └── cache/
│       └── seen_articles.json      # 去重缓存（30天自动清理）
├── docs/                           # GitHub Pages 发布目录（云端生成）
│   ├── index.html                  # 归档索引
│   └── briefings/YYYY-MM-DD.html   # 每日简报网页版
└── logs/
    └── fetch.log                   # 抓取日志
```

## 技术架构

```
RSS 源 (7个) → fetch_and_prepare.py（抓取+去重）→ today_articles.json
             → llm_analyze.py（LLM 分析，免费 API）→ analysis.json
             → gen_briefing.py（生成 HTML）→ publish_pages.py（发布+微信提醒）
```

- 云端运行无需外部 API Key 之外的任何成本（智谱 GLM-4-Flash 免费 + GitHub Pages 免费）
- 本地调试可用 `python llm_analyze.py --dry-run` 验证链路

## Python 环境

- 解释器：`C:\Users\xugel\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
- 依赖：`feedparser`, `beautifulsoup4`, `requests`, `pyyaml`
