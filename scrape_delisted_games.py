#!/usr/bin/env python3
"""
抓取 Steam 绝版游戏数据
数据源: https://steam-tracker.com/apps/delisted
输出: steam_delisted_apps.json（与 steam-delisted-apps-old.json 格式一致）
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://steam-tracker.com/apps/delisted"
OUTPUT_DIR = Path(__file__).parent / "steam_delisted_apps_data"
OUTPUT_NAME = "steam_delisted_apps.json"
TIMEOUT = 60

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh;q=0.8",
}

DELIST_TYPE_MAP = {
    "delisted": "delisted",
    "purchase disabled": "purchase_disabled",
    "purchase_disabled": "purchase_disabled",
    "retail only": "retail_only",
    "retail_only": "retail_only",
    "f2p (unavailable)": "f2p_unavailable",
    "f2p_unavailable": "f2p_unavailable",
    "test app": "test_app",
    "test_app": "test_app",
}

SCARCITY_ORDER = {
    "delisted": 5,
    "test_app": 4,
    "purchase_disabled": 3,
    "retail_only": 2,
    "f2p_unavailable": 1,
}


def fetch_page() -> str:
    """下载完整 HTML 页面（站点一次性返回全部记录，无需分页）"""
    print(f"[{datetime.now().isoformat()}] 开始下载 {SOURCE_URL}")
    session = requests.Session()
    resp = session.get(SOURCE_URL, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    print(f"  下载完成: {len(resp.text):,} 字符")
    return resp.text


def parse_table(soup: BeautifulSoup, table_id: str, category: str) -> list[dict]:
    """解析指定表格，返回原始行数据"""
    table = soup.find("table", id=table_id)
    if not table:
        print(f"  [warn] 未找到表格 #{table_id}", file=sys.stderr)
        return []

    tbody = table.find("tbody") or table
    rows: list[dict] = []
    for tr in tbody.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 7:
            continue

        appid_text = cells[1].get_text(strip=True)
        if not appid_text or not appid_text.isdigit():
            continue

        rows.append({
            "appid": int(appid_text),
            "name": cells[2].get_text(strip=True),
            "owners": cells[0].get_text(strip=True),
            "type": cells[3].get_text(strip=True),
            "changed": cells[4].get_text(strip=True),
            "keyshops": cells[5].get_text(strip=True),
            "achievements": cells[6].get_text(strip=True),
            "category": category,
        })

    return rows


def map_delist_type(type_text: str) -> str:
    """将原始类型文本映射为 DelistType"""
    normalized = type_text.lower().strip()
    for key, value in DELIST_TYPE_MAP.items():
        if key in normalized:
            return value
    return "purchase_disabled"


def convert_date(date_str: str) -> str:
    """MM/YYYY -> YYYY-MM"""
    trimmed = date_str.strip()
    parts = trimmed.split("/")
    if len(parts) == 2:
        return f"{parts[1]}-{parts[0].zfill(2)}"
    return trimmed


def parse_owner_percentage(owners_str: str) -> float:
    """解析拥有率百分比字符串"""
    cleaned = owners_str.replace("%", "").replace("✔", "").strip()
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return 0.0


def parse_keyshop_price(keyshops_str: str) -> Optional[float]:
    """解析 keyshop 价格"""
    cleaned = keyshops_str.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        val = float(cleaned)
        return round(val, 2) if val > 0 else None
    except ValueError:
        return None


def parse_achievements(achievements_str: str) -> int:
    """解析成就数量"""
    cleaned = achievements_str.replace("?", "").strip()
    if not cleaned:
        return -1
    try:
        return int(cleaned)
    except ValueError:
        return -1


def to_delisted_game_data(raw: dict, fetched_at: str) -> Optional[dict]:
    """将原始行数据转换为 DelistedGameData 格式"""
    name = raw.get("name", "").strip()
    if not name:
        return None

    return {
        "appId": raw["appid"],
        "name": name,
        "delistType": map_delist_type(raw.get("type", "")),
        "delistedAt": convert_date(raw.get("changed", "")),
        "ownerPercentage": parse_owner_percentage(raw.get("owners", "0%")),
        "achievementCount": parse_achievements(raw.get("achievements", "")),
        "keyshopPrice": parse_keyshop_price(raw.get("keyshops", "")),
        "source": "steam-tracker",
        "fetchedAt": fetched_at,
    }


def merge_records(raw_records: list[dict]) -> dict[int, dict]:
    """按 appid 去重，若出现冲突优先保留稀缺度更高的类型"""
    seen: dict[int, dict] = {}
    for raw in raw_records:
        appid = raw["appid"]
        if appid in seen:
            existing = seen[appid]
            existing_type = map_delist_type(existing.get("type", ""))
            current_type = map_delist_type(raw.get("type", ""))
            if SCARCITY_ORDER.get(current_type, 0) > SCARCITY_ORDER.get(existing_type, 0):
                seen[appid] = raw
        else:
            seen[appid] = raw
    return seen


def main():
    html = fetch_page()
    soup = BeautifulSoup(html, "html.parser")

    delisted_raw = parse_table(soup, "delisted-apps", "Delisted")
    unscannable_raw = parse_table(soup, "unscannable-apps", "Unscannable")
    print(f"  delisted-apps: {len(delisted_raw)} 条")
    print(f"  unscannable-apps: {len(unscannable_raw)} 条")

    all_raw = delisted_raw + unscannable_raw
    merged = merge_records(all_raw)
    print(f"  合并去重后: {len(merged)} 条")

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    games = []
    for raw in merged.values():
        game = to_delisted_game_data(raw, fetched_at)
        if game:
            games.append(game)

    result = {
        "version": "1.0.0",
        "source": "steam-tracker.com",
        "fetchedAt": fetched_at,
        "totalCount": len(games),
        "data": games,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / OUTPUT_NAME
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    size_kb = output_path.stat().st_size / 1024
    print(f"\n[完成] 已写入 {output_path}")
    print(f"  - 文件大小: {size_kb:.1f} KB")
    print(f"  - 绝版游戏: {len(games)} 款")
    print(f"  - 抓取时间: {fetched_at}")


if __name__ == "__main__":
    main()
