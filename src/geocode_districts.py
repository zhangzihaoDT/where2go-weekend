#!/usr/bin/env python3
"""
Geocode calibration for districts.

Reads config/districts.yaml, calls AMAP geocode API for districts that
have an `address` field, writes suggested coordinates to
data/geocode_results.csv without modifying the original config.
"""

import csv
import os
import sys
from typing import Optional

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.amap_client import get_api_key, get_api_secret, _sign_params, _amap_get


GEOCODE_RESULT_FIELDS = [
    "district_id",
    "name",
    "address",
    "original_lng",
    "original_lat",
    "suggested_lng",
    "suggested_lat",
    "geocode_status",
    "level",
    "confidence",
]


def geocode_address(address: str, city: str = "上海") -> Optional[dict]:
    api_key = get_api_key()
    if not api_key:
        return None

    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": api_key,
        "address": address,
        "city": city,
        "output": "JSON",
    }
    try:
        data = _amap_get(url, params)
        if data.get("status") != "1":
            return None
        geocodes = data.get("geocodes", [])
        if not geocodes:
            return None
        g = geocodes[0]
        location = g.get("location", "")
        if not location:
            return None
        parts = location.split(",")
        if len(parts) != 2:
            return None
        return {
            "suggested_lng": float(parts[0]),
            "suggested_lat": float(parts[1]),
            "level": g.get("level", ""),
            "confidence": g.get("confidence", ""),
        }
    except Exception:
        return None


def main():
    print("=== where2go-weekend 街区坐标校准 ===\n")

    api_key = get_api_key()
    if not api_key:
        print("⚠  未设置 AMAP_API_KEY，跳过地理编码调用。")
        print("   请在 .env 中配置 AMAP_API_KEY 后重试。")
        print("   无 API key 时：")
        print("     - 不会调用高德地理编码 API")
        print("     - geocode_results.csv 不会被生成")
        print("     - 坐标建议将基于手动校准")
        return

    districts_path = os.path.join(PROJECT_ROOT, "config", "districts.yaml")
    output_path = os.path.join(PROJECT_ROOT, "data", "geocode_results.csv")

    with open(districts_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    results = []
    for d in config.get("districts", []):
        address = d.get("address", "").strip()
        if not address:
            print(f"  [跳过] {d['name']} — 未配置 address 字段")
            continue

        print(f"  正在校准 {d['name']}...")
        print(f"    地址: {address}")

        geo = geocode_address(address, d.get("city", "上海"))
        if geo is None:
            print(f"    → 地理编码失败，跳过")
            results.append({
                "district_id": d["district_id"],
                "name": d["name"],
                "address": address,
                "original_lng": d.get("center_lng", ""),
                "original_lat": d.get("center_lat", ""),
                "suggested_lng": "",
                "suggested_lat": "",
                "geocode_status": "failed",
                "level": "",
                "confidence": "",
            })
            continue

        suggested_lng = geo["suggested_lng"]
        suggested_lat = geo["suggested_lat"]
        original_lng = d.get("center_lng", "")
        original_lat = d.get("center_lat", "")

        print(f"    原始坐标: ({original_lng}, {original_lat})")
        print(f"    建议坐标: ({suggested_lng}, {suggested_lat})")
        print(f"    精度等级: {geo['level']}, confidence: {geo['confidence']}")

        results.append({
            "district_id": d["district_id"],
            "name": d["name"],
            "address": address,
            "original_lng": original_lng,
            "original_lat": original_lat,
            "suggested_lng": suggested_lng,
            "suggested_lat": suggested_lat,
            "geocode_status": "success",
            "level": geo["level"],
            "confidence": geo["confidence"],
        })

    if not results:
        print("\n没有可校准的街区。请确保 districts.yaml 中配置了 address 字段。")
        return

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=GEOCODE_RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(results)

    print(f"\n✅ 已写入 {output_path}，共 {len(results)} 条校准记录。")
    print("   注意：geocode_results.csv 不会自动覆盖 districts.yaml。")
    print("   如需更新坐标，请手动将建议值复制到 districts.yaml。")


if __name__ == "__main__":
    main()
