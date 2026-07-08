import csv
import os
from collections import Counter, defaultdict
from datetime import date
from typing import Optional


CHANGE_EVENT_FIELDS = [
    "snapshot_date",
    "previous_snapshot_date",
    "district_id",
    "district_name",
    "category_id",
    "event_type",
    "poi_id",
    "name",
    "address",
    "signal_strength",
    "why_interesting",
]


def load_snapshot(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _make_poi_key(row: dict) -> str:
    return f"{row.get('poi_id', '')}|{row.get('name', '')}|{row.get('address', '')}"


def _build_poi_index(rows: list[dict]) -> dict[str, dict]:
    index = {}
    for r in rows:
        key = _make_poi_key(r)
        if key not in index:
            index[key] = r
    return index


def find_previous_snapshot(snapshot_dir: str, current_date: date) -> tuple[Optional[str], Optional[date]]:
    if not os.path.isdir(snapshot_dir):
        return None, None
    candidates = []
    for fname in os.listdir(snapshot_dir):
        if fname.endswith("_poi_snapshot.csv"):
            date_str = fname.replace("_poi_snapshot.csv", "")
            try:
                d = date.fromisoformat(date_str)
                if d < current_date:
                    candidates.append((d, os.path.join(snapshot_dir, fname)))
            except ValueError:
                continue
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][0]


def _generate_category_change_events(
    current_rows: list[dict],
    previous_rows: list[dict],
    current_date: date,
    previous_date: date,
) -> list[dict]:
    events = []

    def count_by_district_category(rows: list[dict]) -> dict:
        cc = defaultdict(Counter)
        for r in rows:
            cc[r.get("district_id", "")][r.get("category_id", "")] += 1
        return cc

    current_counts = count_by_district_category(current_rows)
    previous_counts = count_by_district_category(previous_rows)

    all_districts = set(list(current_counts.keys()) + list(previous_counts.keys()))
    all_categories = {"coffee", "food_light", "art_space", "lifestyle"}

    for did in all_districts:
        dname = ""
        for r in current_rows:
            if r.get("district_id") == did:
                dname = r.get("district_name", "")
                break
        if not dname:
            for r in previous_rows:
                if r.get("district_id") == did:
                    dname = r.get("district_name", "")
                    break

        for cat in all_categories:
            cur = current_counts.get(did, {}).get(cat, 0)
            prev = previous_counts.get(did, {}).get(cat, 0)
            if cur > prev and (cur - prev) >= 1:
                diff = cur - prev
                events.append({
                    "snapshot_date": current_date.isoformat(),
                    "previous_snapshot_date": previous_date.isoformat(),
                    "district_id": did,
                    "district_name": dname,
                    "category_id": cat,
                    "event_type": "category_growth",
                    "poi_id": "",
                    "name": "",
                    "address": "",
                    "signal_strength": min(100, 50 + diff * 10),
                    "why_interesting": _category_change_reason(cat, "growth"),
                })
            elif prev > cur and (prev - cur) >= 1:
                diff = prev - cur
                events.append({
                    "snapshot_date": current_date.isoformat(),
                    "previous_snapshot_date": previous_date.isoformat(),
                    "district_id": did,
                    "district_name": dname,
                    "category_id": cat,
                    "event_type": "category_decline",
                    "poi_id": "",
                    "name": "",
                    "address": "",
                    "signal_strength": min(100, 40 + diff * 10),
                    "why_interesting": _category_change_reason(cat, "decline"),
                })

    return events


def _category_change_reason(category_id: str, direction: str) -> str:
    reasons = {
        "coffee": {
            "growth": "该街区新增咖啡节点，可能增强周末停留属性。",
            "decline": "该街区咖啡节点减少，可能影响周末停留吸引力。",
        },
        "food_light": {
            "growth": "轻食/烘焙类节点增加，街区日常可达性提升。",
            "decline": "轻食类节点减少，可能降低日常消费便利性。",
        },
        "art_space": {
            "growth": "艺术空间类节点增加，说明内容生产力正在增强。",
            "decline": "艺术空间类节点减少，内容生产潜力可能减弱。",
        },
        "lifestyle": {
            "growth": "复合空间/买手店增加，可能意味着街区从单一消费转向生活方式目的地。",
            "decline": "生活方式类节点减少，街区业态多样性可能下降。",
        },
    }
    return reasons.get(category_id, {}).get(
        direction, f"{category_id} 类目出现{direction}趋势。"
    )


def detect_changes(
    current_rows: list[dict],
    previous_rows: list[dict],
    current_date: date,
    previous_date: date,
) -> list[dict]:
    events = []

    current_index = _build_poi_index(current_rows)
    previous_index = _build_poi_index(previous_rows)

    current_keys = set(current_index.keys())
    previous_keys = set(previous_index.keys())

    new_keys = current_keys - previous_keys
    disappeared_keys = previous_keys - current_keys

    for key in new_keys:
        poi = current_index[key]
        events.append({
            "snapshot_date": current_date.isoformat(),
            "previous_snapshot_date": previous_date.isoformat(),
            "district_id": poi.get("district_id", ""),
            "district_name": poi.get("district_name", ""),
            "category_id": poi.get("category_id", ""),
            "event_type": "new_poi",
            "poi_id": poi.get("poi_id", ""),
            "name": poi.get("name", ""),
            "address": poi.get("address", ""),
            "signal_strength": 70,
            "why_interesting": _new_poi_reason(poi),
        })

    for key in disappeared_keys:
        poi = previous_index[key]
        events.append({
            "snapshot_date": current_date.isoformat(),
            "previous_snapshot_date": previous_date.isoformat(),
            "district_id": poi.get("district_id", ""),
            "district_name": poi.get("district_name", ""),
            "category_id": poi.get("category_id", ""),
            "event_type": "disappeared_poi",
            "poi_id": poi.get("poi_id", ""),
            "name": poi.get("name", ""),
            "address": poi.get("address", ""),
            "signal_strength": 50,
            "why_interesting": _disappeared_poi_reason(poi),
        })

    category_events = _generate_category_change_events(
        current_rows, previous_rows, current_date, previous_date
    )
    events.extend(category_events)

    return events


def _new_poi_reason(poi: dict) -> str:
    cat = poi.get("category_id", "")
    name = poi.get("name", "新节点")
    if cat == "coffee":
        return f"「{name}」新增咖啡节点，可能提升街区周末停留吸引力。"
    elif cat == "food_light":
        return f"「{name}」新增轻食/烘焙节点，日常可达性增强。"
    elif cat == "art_space":
        return f"「{name}」新增艺术空间，街区内容生产力提升。"
    elif cat == "lifestyle":
        return f"「{name}」新增复合空间，街区生活方式属性增强。"
    return f"「{name}」新出现，值得关注其业态类型。"


def _disappeared_poi_reason(poi: dict) -> str:
    name = poi.get("name", "某节点")
    return f"「{name}」已消失，需关注是否为临时闭店或业态调整。"


def generate_baseline_events(
    current_rows: list[dict],
    current_date: date,
) -> list[dict]:
    events = []
    for row in current_rows:
        events.append({
            "snapshot_date": current_date.isoformat(),
            "previous_snapshot_date": "",
            "district_id": row.get("district_id", ""),
            "district_name": row.get("district_name", ""),
            "category_id": row.get("category_id", ""),
            "event_type": "no_previous_snapshot",
            "poi_id": row.get("poi_id", ""),
            "name": row.get("name", ""),
            "address": row.get("address", ""),
            "signal_strength": 0,
            "why_interesting": "这是第一期基准快照，后续将基于此识别变化。",
        })
    return events


def write_change_events_csv(events: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CHANGE_EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)
