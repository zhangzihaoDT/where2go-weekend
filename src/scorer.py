import csv
import os
from collections import Counter, defaultdict
from datetime import date
from typing import Optional


def load_poi_data(csv_path: str) -> list[dict]:
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def load_district_config(yaml_path: str) -> dict[str, dict]:
    import yaml
    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {d["district_id"]: d for d in data["districts"]}


def score_districts(
    poi_rows: list[dict],
    district_config: dict[str, dict],
) -> list[dict]:
    districts = defaultdict(list)
    for row in poi_rows:
        districts[row["district_id"]].append(row)

    category_keys = {"coffee", "food_light", "art_space", "lifestyle"}
    results = []

    for district_id, pois in districts.items():
        config = district_config.get(district_id)
        if not config:
            continue

        district_name = pois[0]["district_name"]
        poi_count = len(pois)

        category_counter = Counter(p["category_id"] for p in pois)
        categories_present = [c for c in category_keys if category_counter.get(c, 0) > 0]
        category_diversity = len(categories_present)

        max_poi = max(len(v) for v in districts.values()) or 1
        density_score = min(100, (poi_count / max_poi) * 100)

        max_diversity = len(category_keys)
        freshness_score = min(100, (category_diversity / max_diversity) * 100)

        coffee_art_lifestyle_count = sum(
            category_counter.get(c, 0) for c in ["coffee", "art_space", "lifestyle"]
        )
        content_productivity_score = min(
            100, (coffee_art_lifestyle_count / max(poi_count, 1)) * 100
        )

        low_cost_cats = {"coffee", "food_light", "lifestyle"}
        low_cost_count = sum(category_counter.get(c, 0) for c in low_cost_cats)
        low_cost_score = min(100, (low_cost_count / max(poi_count, 1)) * 100)

        accessibility_score = config["default_accessibility_score"]
        crowding_risk = config["default_crowding_risk"]

        weekend_score = (
            density_score * 0.25
            + freshness_score * 0.20
            + low_cost_score * 0.20
            + accessibility_score * 0.15
            + content_productivity_score * 0.20
            - crowding_risk * 0.15
        )
        weekend_score = max(0, min(100, weekend_score))

        strengths = []
        if density_score >= 70:
            strengths.append("业态密集")
        if freshness_score >= 70:
            strengths.append("品类丰富")
        if low_cost_score >= 60:
            strengths.append("低成本友好")
        if accessibility_score >= 70:
            strengths.append("交通便利")
        if content_productivity_score >= 70:
            strengths.append("内容生产素材多")
        if crowding_risk < 50:
            strengths.append("人少清静")
        recommendation_reason = "、".join(strengths) if strengths else "值得一探"

        results.append({
            "district_id": district_id,
            "district_name": district_name,
            "poi_count": poi_count,
            "category_diversity": category_diversity,
            "density_score": round(density_score),
            "freshness_score": round(freshness_score),
            "low_cost_score": round(low_cost_score),
            "accessibility_score": accessibility_score,
            "crowding_risk": crowding_risk,
            "content_productivity_score": round(content_productivity_score),
            "weekend_score": round(weekend_score),
            "recommendation_reason": recommendation_reason,
        })

    return results


def write_scores_csv(results: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = [
        "district_id", "district_name", "poi_count", "category_diversity",
        "density_score", "freshness_score", "low_cost_score",
        "accessibility_score", "crowding_risk", "content_productivity_score",
        "weekend_score", "recommendation_reason",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def compute_change_scores(
    current_rows: list[dict],
    previous_rows: Optional[list[dict]],
    change_events: list[dict],
    district_config: dict[str, dict],
    score_date: date,
    target_weekend_date: Optional[date] = None,
) -> list[dict]:
    """Compute change-oriented scores for each district."""
    has_previous_snapshot = previous_rows is not None
    if previous_rows is None:
        previous_rows = []

    district_ids = set(r["district_id"] for r in current_rows)
    results = []

    for did in district_ids:
        config = district_config.get(did)
        if not config:
            continue

        dname = ""
        for r in current_rows:
            if r.get("district_id") == did:
                dname = r.get("district_name", "")
                break

        cur_pois = [r for r in current_rows if r["district_id"] == did]
        prev_pois = [r for r in previous_rows if r["district_id"] == did]

        cur_cats = set(r.get("category_id", "") for r in cur_pois)
        prev_cats = set(r.get("category_id", "") for r in prev_pois)

        new_poi_count = sum(
            1 for e in change_events
            if e["district_id"] == did and e["event_type"] == "new_poi"
        )
        disappeared_poi_count = sum(
            1 for e in change_events
            if e["district_id"] == did and e["event_type"] == "disappeared_poi"
        )
        category_growth_count = sum(
            1 for e in change_events
            if e["district_id"] == did and e["event_type"] == "category_growth"
        )
        category_decline_count = sum(
            1 for e in change_events
            if e["district_id"] == did and e["event_type"] == "category_decline"
        )

        freshness_score = 0
        if previous_rows:
            new_cats = cur_cats - prev_cats
            total_cats = len(set(list(cur_cats) + list(prev_cats))) or 1
            freshness_score = min(100, (len(new_cats) / total_cats) * 100)
            had_change = new_poi_count > 0 or category_growth_count > 0
            if not had_change:
                if disappeared_poi_count > 0:
                    freshness_score = max(freshness_score, 20)
            if new_poi_count > 0:
                freshness_score = max(freshness_score, min(100, new_poi_count * 15))
        else:
            freshness_score = 50

        total_category_changes = category_growth_count + category_decline_count
        max_category_change = 5
        category_change_score = min(100, (total_category_changes / max_category_change) * 100)

        tags = config.get("tags", [])
        tag_str = " ".join(tags)
        if any(t in tag_str for t in ["网红", "安福路", "武康路", "热门"]):
            low_crowding_potential = 30
        elif "社区商业" in tag_str or "老城" in tag_str:
            low_crowding_potential = 70
        elif "滨江" in tag_str or "岸线" in tag_str:
            low_crowding_potential = 65
        elif "创意园区" in tag_str:
            low_crowding_potential = 75
        else:
            low_crowding_potential = 60

        route_potential_score = min(
            100, (len(cur_cats) * 20) + (new_poi_count * 5)
        )

        change_score = (
            freshness_score * 0.35
            + category_change_score * 0.25
            + low_crowding_potential * 0.20
            + route_potential_score * 0.20
        )
        change_score = max(0, min(100, change_score))

        score_explanation = _build_score_explanation(
            did, dname, new_poi_count, category_growth_count,
            category_decline_count, cur_cats, prev_cats,
            has_previous_snapshot,
        )

        result = {
            "score_date": score_date.isoformat(),
            "district_id": did,
            "district_name": dname,
            "new_poi_count": new_poi_count,
            "disappeared_poi_count": disappeared_poi_count,
            "category_growth_count": category_growth_count,
            "category_decline_count": category_decline_count,
            "freshness_score": round(freshness_score),
            "category_change_score": round(category_change_score),
            "low_crowding_potential": low_crowding_potential,
            "route_potential_score": round(route_potential_score),
            "change_score": round(change_score),
            "score_explanation": score_explanation,
        }
        if target_weekend_date:
            result["target_weekend_date"] = target_weekend_date.isoformat()
        results.append(result)

    return results


def _build_score_explanation(
    did: str, dname: str,
    new_poi_count: int,
    cat_growth: int,
    cat_decline: int,
    cur_cats: set,
    prev_cats: set,
    has_history: bool,
) -> str:
    if not has_history:
        return f"{dname} 为首期基准快照，暂无历史数据。当前覆盖 {len(cur_cats)} 个品类。"

    parts = []
    if new_poi_count > 0:
        parts.append(f"新增 {new_poi_count} 个 POI")
    if cat_growth > 0:
        parts.append(f"{cat_growth} 个类目增长")
    if cat_decline > 0:
        parts.append(f"{cat_decline} 个类目减少")
    new_cats = cur_cats - prev_cats
    if new_cats:
        cat_names = {"coffee": "咖啡", "food_light": "轻食", "art_space": "艺术空间", "lifestyle": "生活方式"}
        names = [cat_names.get(c, c) for c in new_cats]
        parts.append(f"新增品类：{'、'.join(names)}")

    if parts:
        return f"{dname} 变化：{'，'.join(parts)}。"
    return f"{dname} 本期无明显变化。"


CHANGE_SCORE_FIELDS = [
    "score_date",
    "target_weekend_date",
    "district_id",
    "district_name",
    "new_poi_count",
    "disappeared_poi_count",
    "category_growth_count",
    "category_decline_count",
    "freshness_score",
    "category_change_score",
    "low_crowding_potential",
    "route_potential_score",
    "change_score",
    "score_explanation",
]


def write_change_scores_csv(results: list[dict], output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    # Build fieldnames from data, not static list, to handle optional target_weekend_date
    fieldnames = [
        "score_date", "target_weekend_date", "district_id", "district_name",
        "new_poi_count", "disappeared_poi_count", "category_growth_count",
        "category_decline_count", "freshness_score", "category_change_score",
        "low_crowding_potential", "route_potential_score", "change_score",
        "score_explanation",
    ]
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
