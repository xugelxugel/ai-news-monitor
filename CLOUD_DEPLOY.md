# 云端部署指南（全程免费方案：GitHub Pages + 微信提醒）

把每日AI资讯简报流水线迁移到 GitHub Actions 云端运行，**零成本**：

- **调度执行**：GitHub Actions（私有仓库每月 2000 分钟免费，每天约跑 5-15 分钟）
- **LLM 分析**：智谱 GLM-4-Flash（完全免费），Gemini 免费档备用
- **网页发布**：GitHub Pages（免费静态托管，每天一页，自动积累历史归档）
- **微信提醒**：Server酱 / PushPlus（免费，微信扫码绑定，每天 1-2 条）

**交付形态**：每天 6:50 简报生成后微信收到提醒（含网页链接），点开即看完整简报；
网页版有固定地址，可随时回看任意一天的历史。

## 一、代码已就绪

| 文件 | 作用 |
|---|---|
| `fetch_and_prepare.py` | 并发抓取 8 个美国媒体 RSS + 去重，生成 `today_articles.json` |
| `llm_analyze.py` | 调用 LLM API 生成中文分析与战略分析（智谱主用 + Gemini 备用自动切换） |
| `gen_briefing.py` | 生成 HTML 简报（与 WorkBuddy 版结构一致） |
| `publish_pages.py` | 发布步骤：复制简报 → `docs/briefings/` + 生成归档索引 `docs/index.html` + 微信提醒 |
| `wechat_notify.py` | 微信推送（Server酱/PushPlus），也用于失败通知 |
| `run_daily.py` | 编排：fetch → llm_analyze → gen_briefing → publish，失败自动微信通知 |
| `requirements.txt` | 依赖清单 |
| `.env.example` | 环境变量模板（含全部说明） |
| `.github/workflows/daily.yml` | 每日 22:50 UTC（北京 6:50）定时任务 + 发布 Pages + 保活 commit |

## 二、需要准备的 3 个免费账号

1. **GitHub 账号**：https://github.com （私有仓库免费）
2. **智谱 API Key**（LLM，必填）：
   - 打开 https://open.bigmodel.cn 注册 → 实名认证
   - 左侧菜单 **API Keys** → **创建新的 API Key**，复制保存（GLM-4-Flash 完全免费）
   - 可选备用：Gemini https://aistudio.google.com/apikey （免费档足够每日用量）
3. **微信提醒 Key**（必填，二选一）：
   - **Server酱**：https://sct.ftqq.com → 微信扫码登录 → 复制 **SENDKEY**（普通用户每天约 5 条，够用）
   - **PushPlus**：https://www.pushplus.plus → 微信扫码登录 → 复制 **token**（每天约 200 条）

## 三、推送代码到 GitHub

在项目根目录（`C:\Users\xugel\WorkBuddy\每日AI资讯`）执行：

```bash
# 1. GitHub 网页上新建私有仓库 ai-news-monitor（New repository → Private，不要勾选任何初始化选项）
# 2. 一键推送（脚本已内置用户名与仓库名）
bash push_to_github.sh
```

首次 push 会弹出 GitHub 登录/授权窗口，正常登录即可。

## 四、配置 Secrets（密钥）

仓库页面 → **Settings → Secrets and variables → Actions → New repository secret**，逐个添加：

| Secret 名 | 必填 | 值 |
|---|---|---|
| `LLM_API_KEY` | ✅ | 智谱 API Key |
| `LLM_FALLBACK_API_KEY` | 可选 | Gemini API Key（建议配置，双保险） |
| `WECHAT_NOTIFY_KEY` | ✅ | Server酱 SENDKEY 或 PushPlus token |
| `WECHAT_NOTIFY_TYPE` | 可选 | `serverchan`（默认）或 `pushplus` |

## 五、启用 GitHub Pages（一次性）

仓库页面 → **Settings → Pages** → Source 选 **GitHub Actions**（工作流会自动配置，无需手动设置）。

此后每次 workflow 运行，`docs/` 内容会自动发布，当日简报地址为：

```
https://xugelxugel.github.io/ai-news-monitor/briefings/YYYY-MM-DD.html
```

归档首页（列出所有历史简报）：`https://xugelxugel.github.io/ai-news-monitor/`

## 六、手动触发验证

1. 仓库 → **Actions** → 左侧 **AI News Daily Briefing** → **Run workflow** → 运行
2. 等 3-10 分钟，绿色对勾 = 成功
3. **微信**收到 `【每日AI资讯】简报已更新` 提醒（含网页链接）
4. 打开链接确认简报正常显示
5. 失败时微信会收到"运行失败"提醒，可在 Actions 日志中查看详细报错

## 七、验证稳定后停用本地自动化

确认连续 2-3 天正常后，停用本机 WorkBuddy 中的自动化任务
（ID: `automation-1785902903319`，名称：每日AI资讯简报），
避免本地与云端重复生成。

## 八、定时、发布与保活说明

- 定时：cron `50 22 * * *`（UTC）= 北京时间每天早上 6:50（有数分钟延迟，属正常）
- **双 cron 兜底**：GitHub 定时任务是 best-effort，高峰期可能延迟甚至跳过。额外配置了
  `20 1 * * *`（UTC）= 北京时间 9:20 的兜底触发；`run_daily.py` 会先检查当天简报是否已生成，
  已生成则直接跳过，不会重复运行
- **发布**：workflow 末尾用官方 deploy-pages 动作上传 `docs/`，无构建超时问题
- **保活**：每天自动 commit `.keepalive` + 去重缓存，防止 GitHub 因仓库 60 天无活动暂停定时任务，同时保证云端跨天去重

## 九、成本与限额

| 项目 | 免费额度 | 本任务用量 |
|---|---|---|
| GitHub Actions | 2000 分钟/月（私有仓库） | 约 150-450 分钟/月 |
| GitHub Pages | 无限流量（仓库 ≤1GB） | 每天几 KB |
| GLM-4-Flash | 完全免费 | 每天约 10-30 次 |
| Gemini Flash | 约 1500 次请求/天 | 备用 |
| Server酱 / PushPlus | 每天 5 条 / 200 条 | 每天 1-2 条 |

**总计：¥0/年。**

## 十、常见问题

- **configure-pages 报错 "Resource not accessible by integration / Get Pages site failed (Not Found)"**：
  这是 GitHub 的已知问题——`enablement: true` 自动启用 Pages 在部分仓库会因 token 权限被拒。
  **修复（一次性）**：仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions** → Save，
  然后回到 Actions 重新 Run workflow 即可。同时建议检查 Settings → Actions → General →
  Workflow permissions 是否选了 **Read and write permissions**。
- **429 限流**：智谱免费档并发高会限流，脚本已内置重试，并在连续失败后自动切到备用供应商
- **微信没收到**：先确认 Secrets 里 `WECHAT_NOTIFY_KEY` 已配置；Server酱/PushPlus 需先扫码绑定微信并关注服务号
- **Pages 页面 404**：确认 Settings → Pages 里 Source 是 "GitHub Actions"；推送后等 1-2 分钟再访问
- **想换模型**：不用改代码，改 Secrets 里的 `LLM_BASE_URL` / `LLM_MODEL` 即可（OpenAI 兼容接口任意模型都行）
- **GitHub Actions 不触发**：检查仓库 Settings → Actions → General 的权限设置是否允许工作流运行
