"""
Brand POI Snapshot — dir, manifest, schema, read/write.

Snapshots live under data/brand_poi/snapshots/{date}_{city}/.

Structure:
  snapshots/{date}_{city}/
    manifest.json
    brand_poi.csv
    brand_poi.json
    enriched.csv       (from analyze)
    summary.json       (from analyze)
    analysis.md        (from analyze)

Compare results live under data/brand_poi/compares/:
  compares/{base_id}__vs__{target_id}/
    compare.json
    compare.md
"""

import csv
import json
import os
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SNAPSHOT_BASE = os.path.join(PROJECT_ROOT, "data", "brand_poi", "snapshots")
COMPARE_BASE = os.path.join(PROJECT_ROOT, "data", "brand_poi", "compares")

REQUIRED_CSV_COLUMNS = [
    "brand_id", "brand_name", "name", "district",
    "lng_gcj02", "lat_gcj02", "poi_kind", "source_query", "address",
]


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def make_snapshot_id(date_str: str, city: str) -> str:
    return f"{date_str}_{city}"


def parse_snapshot_id(snapshot_id: str) -> tuple[str, str]:
    parts = snapshot_id.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return snapshot_id, "上海"


class BrandPoiSnapshot:

    def __init__(self, snapshot_id: str, base_dir: str = SNAPSHOT_BASE):
        self.snapshot_id = snapshot_id
        self.date_str, self.city = parse_snapshot_id(snapshot_id)
        self.dir = os.path.join(base_dir, snapshot_id)

    @classmethod
    def from_date_city(cls, date_str: str, city: str, base_dir: str = SNAPSHOT_BASE):
        return cls(make_snapshot_id(date_str, city), base_dir)

    # ── File paths ──

    @property
    def csv_path(self) -> str:
        return os.path.join(self.dir, "brand_poi.csv")

    @property
    def json_path(self) -> str:
        return os.path.join(self.dir, "brand_poi.json")

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.dir, "manifest.json")

    @property
    def enriched_csv_path(self) -> str:
        return os.path.join(self.dir, "enriched.csv")

    @property
    def summary_json_path(self) -> str:
        return os.path.join(self.dir, "summary.json")

    @property
    def analysis_report_path(self) -> str:
        return os.path.join(self.dir, "analysis.md")

    # ── Existence ──

    def exists(self) -> bool:
        return os.path.isdir(self.dir)

    def has_enriched(self) -> bool:
        return os.path.isfile(self.enriched_csv_path)

    # ── Manifest ──

    def create_manifest(self, stats: dict, brands: list[str]) -> dict:
        _ensure_dir(self.dir)
        manifest = {
            "version": 1,
            "date": self.date_str,
            "city": self.city,
            "brands": brands,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "stats": stats,
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return manifest

    def read_manifest(self) -> dict | None:
        if not os.path.isfile(self.manifest_path):
            return None
        with open(self.manifest_path, encoding="utf-8") as f:
            return json.load(f)

    # ── Read / write CSV ──

    def write_csv(self, rows: list[dict], fieldnames: list[str] | None = None):
        _ensure_dir(self.dir)
        if not fieldnames and rows:
            fieldnames = list(rows[0].keys())
        elif not fieldnames:
            fieldnames = REQUIRED_CSV_COLUMNS
        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fieldnames})

    def read_csv(self) -> list[dict]:
        if not os.path.isfile(self.csv_path):
            return []
        with open(self.csv_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    # ── Read / write JSON ──

    def write_json(self, rows: list[dict]):
        _ensure_dir(self.dir)
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)

    def read_json(self) -> list[dict]:
        if not os.path.isfile(self.json_path):
            return []
        with open(self.json_path, encoding="utf-8") as f:
            return json.load(f)

    # ── Enriched artifacts ──

    def write_enriched_csv(self, rows: list[dict]):
        _ensure_dir(self.dir)
        if not rows:
            with open(self.enriched_csv_path, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=REQUIRED_CSV_COLUMNS)
                w.writeheader()
            return
        fieldnames = list(rows[0].keys())
        with open(self.enriched_csv_path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)

    def read_enriched_csv(self) -> list[dict]:
        if not os.path.isfile(self.enriched_csv_path):
            return []
        with open(self.enriched_csv_path, encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def write_summary_json(self, summary: dict):
        _ensure_dir(self.dir)
        with open(self.summary_json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def read_summary_json(self) -> dict | None:
        if not os.path.isfile(self.summary_json_path):
            return None
        with open(self.summary_json_path, encoding="utf-8") as f:
            return json.load(f)

    def write_analysis_report(self, md: str):
        _ensure_dir(self.dir)
        with open(self.analysis_report_path, "w", encoding="utf-8") as f:
            f.write(md)

    # ── Schema validation ──

    @staticmethod
    def validate_schema(rows: list[dict]) -> list[str]:
        if not rows:
            return []
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in rows[0]]
        return missing

    # ── List snapshots ──

    @classmethod
    def list_snapshots(cls, base_dir: str = SNAPSHOT_BASE) -> list[tuple[str, str, int]]:
        if not os.path.isdir(base_dir):
            return []
        results = []
        for name in sorted(os.listdir(base_dir), reverse=True):
            snap_dir = os.path.join(base_dir, name)
            if not os.path.isdir(snap_dir):
                continue
            manifest_path = os.path.join(snap_dir, "manifest.json")
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    m = json.load(f)
                results.append((name, m.get("city", "?"), m.get("stats", {}).get("total_poi", 0)))
            except Exception:
                continue
        return results


# ── Compare helpers (separate from snapshot) ──


def compare_dir_id(base_id: str, target_id: str) -> str:
    return f"{base_id}__vs__{target_id}"


def write_compare_result(base_id: str, target_id: str, result: dict,
                         base_dir: str = COMPARE_BASE):
    cid = compare_dir_id(base_id, target_id)
    out_dir = os.path.join(base_dir, cid)
    _ensure_dir(out_dir)
    json_path = os.path.join(out_dir, "compare.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    if "markdown" in result:
        md_path = os.path.join(out_dir, "compare.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(result["markdown"])
    return out_dir
