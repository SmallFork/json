#!/usr/bin/env python3
"""
抓取 Steam 锁区游戏数据
数据源: steam-tracker.com
  1) API: https://steam-tracker.com/api?action=GetAppListV3
     返回 JSON，过滤 category_id 为 3 (Purchase disabled) 或 20 (Banned) 的条目
  2) HTML: https://steam-tracker.com/user/76561198027066612/apps/10
     解析 table tbody tr，category_id=10 (Regional variant)
输出: steam_blocked_apps.json（供油猴脚本静态加载，避免网络不稳定时在线抓取失败）
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

API_URL = "https://steam-tracker.com/api?action=GetAppListV3"
HTML_URL = "https://steam-tracker.com/user/76561198027066612/apps/10"

OUTPUT_DIR = Path(__file__).parent / "steam_blocked_apps_data"
OUTPUT_NAME = "steam_blocked_apps.json"

API_TIMEOUT = 20
HTML_TIMEOUT = 15

# API 数据源过滤的 category_id: 3=Purchase disabled, 20=Banned
BLOCKED_CATEGORY_IDS = {3, 20}

HEADERS_API = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh;q=0.8",
}

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh;q=0.8",
}


def fetch_api_apps() -> list[dict]:
    """从 steam-tracker.com API 获取 Banned + Purchase disabled 应用"""
    print(f"[{datetime.now().isoformat()}] 正在拉取 API: {API_URL}")
    session = requests.Session()
    resp = session.get(API_URL, headers=HEADERS_API, timeout=API_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    if not data or not data.get("success") or not isinstance(data.get("removed_apps"), list):
        raise ValueError("Invalid API response: success/removed_apps 字段缺失")

    raw_apps = data["removed_apps"]
    print(f"  API 返回总条目: {len(raw_apps):,}")

    apps: list[dict] = []
    for a in raw_apps:
        category_id = a.get("category_id")
        if category_id not in BLOCKED_CATEGORY_IDS:
            continue
        appid = a.get("appid")
        if not appid:
            continue
        apps.append({
            "appid": int(appid),
            "name": (a.get("name") or "").strip(),
            "category": (a.get("category") or "").strip(),
            "categoryId": int(category_id),
            "type": a.get("type") or "game",
            "source": "api",
            "changedAt": a.get("changed_at") or "",
        })

    print(f"  过滤后 (category_id in {sorted(BLOCKED_CATEGORY_IDS)}): {len(apps):,} 条")
    return apps


def fetch_html_apps() -> list[dict]:
    """从 steam-tracker.com HTML 页面抓取 Regional variant (category_id=10) 应用"""
    print(f"[{datetime.now().isoformat()}] 正在抓取 HTML: {HTML_URL}")
    session = requests.Session()
    resp = session.get(HTML_URL, headers=HEADERS_HTML, timeout=HTML_TIMEOUT)
    resp.raise_for_status()

    print(f"  下载完成: {len(resp.text):,} 字符")

    soup = BeautifulSoup(resp.text, "html.parser")
    apps: list[dict] = []
    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        # 列结构: Owners% | AppID(link to steamdb) | Name(link) | Type | Changed | ...
        appid_text = cells[1].get_text(strip=True)
        if not appid_text or not appid_text.isdigit():
            continue
        appid = int(appid_text)

        apps.append({
            "appid": appid,
            "name": cells[2].get_text(strip=True),
            "category": "Regional variant",
            "categoryId": 10,
            "type": "game",
            "source": "html",
            "changedAt": cells[4].get_text(strip=True) if len(cells) > 4 else "",
        })

    print(f"  HTML 解析结果: {len(apps):,} 条")
    return apps


def merge_apps(api_apps: list[dict], html_apps: list[dict]) -> list[dict]:
    """按 appid 去重合并，API 数据优先（已存在则不覆盖）"""
    merged: dict[int, dict] = {}
    for app in api_apps:
        merged[app["appid"]] = app
    api_count = len(merged)

    for app in html_apps:
        if app["appid"] not in merged:
            merged[app["appid"]] = app

    print(f"  合并去重后: {len(merged):,} 条 (API {api_count:,} + HTML 新增 {len(merged) - api_count:,})")
    return list(merged.values())


def main():
    api_apps: list[dict] = []
    html_apps: list[dict] = []

    # 数据源 1: API (Banned + Purchase disabled) — 失败不影响 HTML 抓取
    try:
        api_apps = fetch_api_apps()
    except Exception as e:
        print(f"  [warn] API 抓取失败: {e}", file=sys.stderr)

    # 数据源 2: HTML (Regional variant) — 失败不影响 API 数据
    try:
        html_apps = fetch_html_apps()
    except Exception as e:
        print(f"  [warn] HTML 抓取失败: {e}", file=sys.stderr)

    if not api_apps and not html_apps:
        print("[错误] 两个数据源均失败，无法生成数据文件", file=sys.stderr)
        sys.exit(1)

    merged = merge_apps(api_apps, html_apps)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    result = {
        "version": "1.0.0",
        "source": "steam-tracker.com",
        "fetchedAt": fetched_at,
        "totalCount": len(merged),
        "data": merged,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / OUTPUT_NAME
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n[完成] 已写入 {output_path}")
    print(f"  - 文件大小: {size_kb:.1f} KB")
    print(f"  - 锁区游戏: {len(merged):,} 款")
    print(f"  - 抓取时间: {fetched_at}")


if __name__ == "__main__":
    main()
