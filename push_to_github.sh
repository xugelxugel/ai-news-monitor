#!/usr/bin/env bash
# ============================================================
# 每日AI资讯简报 · 一键推送到 GitHub
#
# 用法：
#   1. 在 GitHub 网页新建同名【私有】仓库
#      （New repository → Private，不要勾选任何初始化选项）
#   2. 在本项目根目录执行:  bash push_to_github.sh
#
# 首次 push 会弹出 GitHub 登录/授权窗口，正常登录即可。
# ============================================================

USERNAME="xugelxugel"
REPO_NAME="ai-news-monitor"

set -e
cd "$(dirname "$0")"

if [ "$USERNAME" = "你的GitHub用户名" ] || [ "$REPO_NAME" = "你的仓库名" ]; then
  echo "请先编辑 push_to_github.sh，填入你的 USERNAME 和 REPO_NAME"
  exit 1
fi

REMOTE="https://github.com/$USERNAME/$REPO_NAME.git"

if git remote get-url origin >/dev/null 2>&1; then
  echo "origin 已存在: $(git remote get-url origin)"
else
  echo "添加远程仓库: $REMOTE"
  git remote add origin "$REMOTE"
fi

echo "推送 main 分支..."
git push -u origin main

echo ""
echo "推送完成！接下来请完成 3 步（详见 CLOUD_DEPLOY.md）："
echo "  1. 配置 Secrets: 仓库 Settings → Secrets and variables → Actions"
echo "     必填: LLM_API_KEY（智谱 Key）、WECHAT_NOTIFY_KEY（Server酱 SENDKEY 或 PushPlus token）"
echo "     可选: LLM_FALLBACK_API_KEY（Gemini 备用）、WECHAT_NOTIFY_TYPE（serverchan/pushplus）"
echo "  2. 启用 Pages: Settings → Pages → Source 选 \"GitHub Actions\"（工作流会自动配置）"
echo "  3. 手动测试: Actions → AI News Daily Briefing → Run workflow"
