# -*- coding: utf-8 -*-
"""
微信提醒脚本（云端版）
======================
通过 Server酱 或 PushPlus 把简报更新提醒、运行失败通知推送到微信。

免费额度：Server酱普通用户每天约 5 条，PushPlus 每天约 200 条，
本任务每天 1-2 条，绰绰有余。

注意：**content 请使用 Markdown 格式**（Server酱与 PushPlus 均按
Markdown 渲染），这样链接可点击、加粗生效。

环境变量:
  WECHAT_NOTIFY_TYPE   serverchan（默认）| pushplus
  WECHAT_NOTIFY_KEY    Server酱 SENDKEY：sct.ftqq.com 用微信扫码登录后获取
                       或 PushPlus token：pushplus.plus 用微信扫码登录后获取

用法:
  python wechat_notify.py --title "标题" --content "内容"   # 真实发送
  python wechat_notify.py --dry-run --title "标题"          # 仅打印请求，不发送
"""

import argparse
import json
import os
import sys

import requests


def send_wechat(title, content, notify_type=None, key=None, dry_run=False):
    """发送微信提醒（content 为 Markdown 格式）。返回 True 表示已发送。"""
    notify_type = (notify_type or os.environ.get(
        "WECHAT_NOTIFY_TYPE", "serverchan")).lower()
    key = (key or os.environ.get("WECHAT_NOTIFY_KEY", "")).strip()
    if not key:
        print("[警告] 未配置 WECHAT_NOTIFY_KEY，已跳过微信提醒")
        return False

    if notify_type == "pushplus":
        url = "https://www.pushplus.plus/send"
        payload = {"token": key, "title": title,
                   "content": content, "template": "markdown"}
        if dry_run:
            print(f"[dry-run] pushplus: {url}\n  "
                  f"payload: {json.dumps(payload, ensure_ascii=False)[:200]}")
            return True
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        ok = resp.json().get("code") == 200
        print(f"pushplus 推送{'成功' if ok else '失败'}: {resp.text[:200]}")
        return ok

    # 默认 serverchan
    url = f"https://sctapi.ftqq.com/{key}.send"
    params = {"title": title, "desp": content}
    if dry_run:
        print(f"[dry-run] serverchan: {url}\n  title={title[:50]}")
        return True
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    ok = resp.json().get("code") == 0
    print(f"serverchan 推送{'成功' if ok else '失败'}: {resp.text[:200]}")
    return ok


def main():
    parser = argparse.ArgumentParser(description="微信提醒（Server酱/PushPlus）")
    parser.add_argument("--title", required=True, help="消息标题")
    parser.add_argument("--content", default="", help="消息内容（Markdown 格式）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅打印请求，不真实发送")
    args = parser.parse_args()
    send_wechat(args.title, args.content, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
