import os
from datetime import date
from typing import Optional


def generate_report(
    change_scores: list[dict],
    change_events: list[dict],
    snapshot_rows: list[dict],
    output_dir: str,
    snapshot_date: date,
    weekend_date: date,
    has_previous_snapshot: bool,
    collection_state: Optional[object] = None,
    map_path: Optional[str] = None,
    coord_mode: Optional[str] = None,
    map_provider: Optional[str] = None,
):
    scores_sorted = sorted(change_scores, key=lambda x: x["change_score"], reverse=True)
    top = scores_sorted[0] if scores_sorted else None

    lines = []
    lines.append(f"# 本周末去哪儿｜上海城市变化雷达")
    lines.append(f"**报告日期：{weekend_date.isoformat()}**")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 本周城市变化信号")
    lines.append("")
    if not has_previous_snapshot:
        lines.append("这是第一期基准快照。本周暂无可对比的历史数据，以下分析基于当前 POI 快照的首次观察。")
        lines.append("")
        lines.append(f"本期覆盖 {len(change_scores)} 个街区，共 "
                      f"{len(snapshot_rows)} 个 POI 节点。从下一期开始，将能够识别新增与消失的 POI。")
    else:
        _add_change_signal(lines, top, change_events, scores_sorted)
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 街区变化指数")
    lines.append("")
    lines.append("| 街区 | 变化指数 | 新增 POI | 类目变化 | 低拥挤潜力 | 变化解释 |")
    lines.append("|------|---------|---------|---------|-----------|---------|")
    for s in scores_sorted:
        cat_changes = s["category_growth_count"] + s["category_decline_count"]
        cat_change_text = f"+{s['category_growth_count']}/-{s['category_decline_count']}" if cat_changes > 0 else "无"
        lines.append(
            f"| {s['district_name']} "
            f"| {s['change_score']} "
            f"| {s['new_poi_count']} "
            f"| {cat_change_text} "
            f"| {s['low_crowding_potential']} "
            f"| {s['score_explanation']} |"
        )
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 新出现的空间 / 业态")
    lines.append("")
    new_events = [e for e in change_events if e["event_type"] == "new_poi"]
    growth_events = [e for e in change_events if e["event_type"] == "category_growth"]

    if new_events:
        lines.append("### 新增 POI")
        lines.append("")
        lines.append("| 街区 | 名称 | 类别 | 信号强度 | 说明 |")
        lines.append("|------|------|------|---------|------|")
        for e in new_events:
            lines.append(
                f"| {e['district_name']} | {e['name']} "
                f"| {e['category_id']} | {e['signal_strength']} | {e['why_interesting']} |"
            )
        lines.append("")
    else:
        if has_previous_snapshot:
            lines.append("本期未发现新增 POI。街区业态处于稳定期。")
        else:
            lines.append("首期快照暂无法识别新增 POI，下一期将开始追踪。")
        lines.append("")

    if growth_events:
        lines.append("### 类目增长")
        lines.append("")
        lines.append("| 街区 | 类目 | 信号强度 | 说明 |")
        lines.append("|------|------|---------|------|")
        for e in growth_events:
            lines.append(
                f"| {e['district_name']} | {e['category_id']} "
                f"| {e['signal_strength']} | {e['why_interesting']} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 为什么这个变化值得去看")
    lines.append("")
    _add_change_observation(lines, change_scores, change_events, snapshot_rows, has_previous_snapshot)
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 三条周末观察路线")
    lines.append("")

    _add_observation_route_1(lines, scores_sorted)
    lines.append("")
    _add_observation_route_2(lines, scores_sorted)
    lines.append("")
    _add_observation_route_3(lines, scores_sorted, change_events)
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 一个城市观察选题")
    lines.append("")
    _add_topic(lines, change_scores, change_events)
    lines.append("")

    if map_path:
        lines.append("---")
        lines.append("")
        lines.append("## 地图预览")
        lines.append("")
        lines.append(f"本次 POI 点位和街区采样范围已生成静态地图：")
        lines.append("")
        lines.append(f"> `reports/maps/{os.path.basename(map_path)}`")
        lines.append("")
        if map_provider == "amap_js":
            lines.append(
                "地图 provider：**amap_js**。"
                "本地图使用高德 JS API 底图，POI 坐标来自高德 Web Service，"
                "坐标体系为 GCJ-02，不执行坐标转换。"
                "该地图用于 POI 点位 QA，不作为精确导航工具。"
            )
        elif coord_mode == "raw_gcj02":
            lines.append(
                "地图 provider：**leaflet_osm**。"
                "坐标模式为 **raw_gcj02**，GCJ-02 坐标直接叠加到 OSM 底图，可能存在偏移。"
            )
        else:
            lines.append(
                "地图使用 Leaflet + OpenStreetMap 生成。高德 POI 原始坐标为 GCJ-02，"
                "本地图默认使用近似转换后的 WGS84 坐标进行可视化，仅用于数据 QA 和空间预览，"
                "不用于导航或精确测绘。"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 数据采集说明")
    lines.append("")
    if collection_state:
        source_label = "高德地图 POI API" if not _is_sample_only(snapshot_rows) else "sample POI 数据集"
        lines.append(
            f"本报告生成于 **{date.today().isoformat()}**，"
            f"使用 **{snapshot_date.isoformat()}** 的 POI 快照，"
            f"为 **{weekend_date.isoformat()}** 周末出行提供城市变化观察。"
        )
        lines.append("")
        lines.append(f"- **数据来源**：{source_label}")
        lines.append(f"- **API 请求数**：{collection_state.api_requests_used}")
        lines.append(f"- **缓存命中数**：{collection_state.cache_hits}")
        lines.append(f"- **跳过查询数**：{collection_state.skipped_queries}")
        lines.append(f"- **是否使用 sample fallback**：{'是' if collection_state.fallback_used else '否'}")
        lines.append("")
        if map_path:
            lines.append(f"- **地图已生成**：是")
            lines.append(f"- **地图路径**：`reports/maps/{os.path.basename(map_path)}`")
            lines.append(f"- **地图 provider**：{map_provider or 'amap_js'}")
            if map_provider == "amap_js":
                lines.append(f"- **地图坐标模式**：none (直接使用 GCJ-02)")
                lines.append(f"- **map_crs**：GCJ-02")
                lines.append(f"- **coord_transform_method**：none")
                lines.append(
                    "- **坐标说明**：本地图使用高德 JS API 底图，POI 坐标来自高德 Web Service，"
                    "坐标体系为 GCJ-02，不执行坐标转换。"
                    "该模式用于验证高德 POI 点位，减少坐标转换偏差。"
                )
            else:
                lines.append(f"- **地图坐标模式**：{coord_mode or 'approx_wgs84'}")
                lines.append(
                    "- **坐标转换说明**：高德 POI 原始坐标为 GCJ-02，"
                    "地图默认使用近似转换后的 WGS84 坐标进行可视化，"
                    "仅用于数据 QA 和空间预览，不用于导航或精确测绘。"
                )
        else:
            lines.append("- **地图已生成**：否")
        lines.append("")
        lines.append(
            "这是城市变化雷达的采样观察，并非全面数据扫描。"
            "POI 数据受限于高德 API 覆盖范围、关键词匹配率和日调用配额。"
            "未识别到变化不代表该街区没有变化，只能说明在本期采样中没有发现新增或消失的节点。"
        )
    else:
        lines.append(
            "未记录采集状态。这是城市变化雷达的采样观察，并非全面数据扫描。"
        )
    lines.append("")

    lines.append("---")
    lines.append("")
    source_info = "数据来源：高德地图 POI API" if not _is_sample_only(snapshot_rows) else "数据来源：sample POI 数据集"
    lines.append(f"*报告由 where2go-weekend v0.3.2 自动生成。{source_info}。*")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"{weekend_date.isoformat()}_shanghai_weekend.md"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filepath


def _is_sample_only(rows: list[dict]) -> bool:
    for r in rows:
        if r.get("source") == "amap":
            return False
    return True


def _add_change_signal(lines: list[str], top: dict, events: list[dict], scores: list[dict]):
    new_count = sum(1 for e in events if e["event_type"] == "new_poi")
    growth_count = sum(1 for e in events if e["event_type"] == "category_growth")
    decline_count = sum(1 for e in events if e["event_type"] == "category_decline")

    if new_count > 0:
        lines.append(f"本周识别到 **{new_count} 个新出现 POI**")
        new_by_district = {}
        for e in events:
            if e["event_type"] == "new_poi":
                dn = e["district_name"]
                if dn not in new_by_district:
                    new_by_district[dn] = 0
                new_by_district[dn] += 1
        parts = [f"{dn}（{cnt} 个）" for dn, cnt in sorted(new_by_district.items(), key=lambda x: -x[1])]
        lines.append("，其中 " + "、".join(parts) + "。")

    if growth_count > 0:
        lines.append(f"识别到 {growth_count} 个类目增长信号")
        growth_districts = set(e["district_name"] for e in events if e["event_type"] == "category_growth")
        lines.append("，涉及 " + "、".join(growth_districts) + "。")

    if decline_count > 0:
        decline_districts = set(e["district_name"] for e in events if e["event_type"] == "category_decline")
        if decline_districts:
            lines.append(f"同时注意到 " + "、".join(decline_districts) + " 出现类目减少，需持续观察。")

    if new_count == 0 and growth_count == 0:
        lines.append("本期无明显新增信号，各街区业态趋于稳定。")

    if top and top["change_score"] >= 50:
        lines.append(
            f"变化指数最高的街区是 **{top['district_name']}**（{top['change_score']} 分），"
            f"重点关注：{top['score_explanation']}"
        )
    lines.append("")


def _add_change_observation(lines: list[str], scores: list[dict], events: list[dict],
                            snapshot_rows: list[dict], has_history: bool):
    if not has_history:
        lines.append("本期是第一期基准快照，无法进行历史对比。但从当前数据可以看到各街区的基础业态格局。")
        lines.append("")
        for s in scores:
            if s["change_score"] >= 50:
                lines.append(
                    f"- **{s['district_name']}**（变化指数 {s['change_score']}）："
                    f"{s['score_explanation']}"
                )
        lines.append("")
        lines.append(
            "从下一期开始，我们将能够对比 POI 快照，识别新增与消失的节点，"
            "从而判断哪些街区正在发生变化。"
        )
        return

    new_events = [e for e in events if e["event_type"] == "new_poi"]
    growth_events = [e for e in events if e["event_type"] == "category_growth"]

    if new_events:
        by_district = {}
        for e in new_events:
            dn = e["district_name"]
            if dn not in by_district:
                by_district[dn] = []
            by_district[dn].append(e)
        for dn, evts in sorted(by_district.items(), key=lambda x: -len(x[1])):
            names = [e["name"] for e in evts if e.get("name")]
            cats = set(e["category_id"] for e in evts)
            cat_names = {"coffee": "咖啡", "food_light": "轻食", "art_space": "艺术空间", "lifestyle": "生活方式"}
            cat_text = "、".join(cat_names.get(c, c) for c in cats)
            lines.append(
                f"**{dn}** 新增 {'、'.join(names[:3])} 等 {len(evts)} 个节点，"
                f"主要集中在 {cat_text} 品类。"
            )
            if "coffee" in cats or "food_light" in cats:
                lines.append(f"  → 咖啡/轻食节点增加，可能增强周末停留属性。")
            if "art_space" in cats:
                lines.append(f"  → 艺术空间增加，内容生产潜力提升。")
            if "lifestyle" in cats:
                lines.append(f"  → 复合空间/买手店增加，街区生活方式属性增强。")
        lines.append("")

    top = max(scores, key=lambda x: x["change_score"]) if scores else None
    if top and top["change_score"] >= 50:
        lines.append(
            f"变化最明显的是 **{top['district_name']}**（变化指数 {top['change_score']}）。"
        )
        if top["new_poi_count"] > 0:
            lines.append(
                f"如果 {top['district_name']} 持续出现咖啡、轻食和复合空间节点，"
                "它就不只是办公园区或路过的街道，而可能开始具备周末生活目的地属性。"
            )
        lines.append("")


def _add_observation_route_1(lines: list[str], scores: list[dict]):
    lines.append("### 路线一：独处低成本观察路线")
    lines.append("")
    lines.append("**适合人群**：一个人，想安静观察城市变化")
    lines.append("")
    lines.append("**观察问题**：")
    lines.append("- 这个街区的咖啡店是独立运营还是连锁？")
    lines.append("- 轻食/烘焙店的密度能否支撑半日停留？")
    lines.append('- 空间设计是\u201c为打卡\u201d还是\u201c为日常\u201d？')
    lines.append("")
    low_crowd = min(scores, key=lambda x: x["low_crowding_potential"], default=None)
    target = max(scores, key=lambda x: x["change_score"]) if scores else None

    if target:
        lines.append("**建议路线**：")
        lines.append(f"- {target['district_name']} → 找一家独立咖啡馆 → 观察街区业态 → 记录空间变化")
        lines.append("")
        lines.append("**为什么现在值得去**：")
        lines.append(
            f"{target['district_name']} 当前变化指数 {target['change_score']}，"
            "正处于业态变动期，适合作为独立观察样本。"
        )
    else:
        lines.append("**建议路线**：选择一个 POI 密度适中的街区，沿主街步行观察")
        lines.append("")


def _add_observation_route_2(lines: list[dict], scores: list[dict]):
    lines.append("### 路线二：朋友 / 约会半日观察路线")
    lines.append("")
    lines.append("**适合人群**：两人同行，愿意边走边聊城市话题")
    lines.append("")
    lines.append("**观察问题**：")
    lines.append("- 这个街区给不同类型的人提供了哪些停留理由？")
    lines.append("- 咖啡馆、书店、买手店之间有没有形成动线？")
    lines.append('- 整体氛围是\u201c消费导向\u201d还是\u201c停留导向\u201d？')
    lines.append("")
    target = max(scores, key=lambda x: x["route_potential_score"]) if scores else None

    if target:
        lines.append("**建议路线**：")
        lines.append(
            f"- {target['district_name']} → 特色咖啡馆（观察空间类型）→ "
            "展览/画廊 → 复合空间/买手店 → 讨论观察笔记"
        )
        lines.append("")
        lines.append("**为什么现在值得去**：")
        lines.append(
            f"{target['district_name']} 路线潜力分 {target['route_potential_score']}，"
            "业态组合适合边走边聊，适合半日城市观察体验。"
        )
    else:
        lines.append("**建议路线**：选择业态最丰富的街区，边走边聊")
        lines.append("")


def _add_observation_route_3(lines: list[dict], scores: list[dict], events: list[dict]):
    lines.append("### 路线三：内容创作者城市观察路线")
    lines.append("")
    lines.append("**适合人群**：摄影师 / 写作者 / 城市研究者 / 自媒体")
    lines.append("")
    lines.append("**观察问题**：")
    lines.append("- 哪些空间正在变化（装修、新开、关闭）？")
    lines.append("- 这些变化反映了什么样的消费趋势？")
    lines.append('- 能否拍到\u201c变化中\u201d的城市画面？')
    lines.append("")
    target = max(scores, key=lambda x: x["freshness_score"]) if scores else None
    top_changes = [e for e in events if e["event_type"] in ("new_poi", "category_growth")]

    if target:
        lines.append("**建议路线**：")
        lines.append(f"- 上午：{target['district_name']} → 拍摄城市空间与街景")
        lines.append(f"- 下午：探访 {min(3, len(top_changes)) if top_changes else 2}-3 个变化节点，记录对比观察")
        lines.append(f"- 傍晚：撰写观察笔记 / 整理素材")
        lines.append("")
        lines.append("**为什么现在值得去**：")
        lines.append(
            f"{target['district_name']} 新鲜度评分 {target['freshness_score']}，"
            "正处于变化活跃期，适合捕捉正在发生的城市更新。"
        )
    else:
        lines.append("**建议路线**：选择一个正在变化的街区，前后对比拍摄")
        lines.append("")


def _add_topic(lines: list[dict], scores: list[dict], events: list[dict]):
    top = max(scores, key=lambda x: x["change_score"]) if scores else None
    new_count = sum(1 for e in events if e["event_type"] == "new_poi")
    growth_count = sum(1 for e in events if e["event_type"] == "category_growth")

    if new_count > 0 or growth_count > 0:
        lines.append('### 选题：街区正在\u201c长\u201d出什么？')
        lines.append("")
        lines.append("**观察角度**")
        lines.append("")
        lines.append(
            '不写\u201c好店推荐\u201d，而是写街区正在发生的业态变化。'
            "新增了哪些节点？什么品类在增长？这些变化说明了什么趋势？"
        )
        lines.append("")
        lines.append("**为什么现在值得写**")
        lines.append("")
        lines.append(
            '上海的城市更新正在从\u201c大拆大建\u201d转向\u201c毛细血管级\u201d的业态替换。'
            "一个街区的变化往往不是轰动的，而是通过一家新咖啡、一间新画廊、"
            "一个复合空间逐步完成的。记录这些变化，比推荐一家好店更有长期阅读价值。"
        )
    else:
        lines.append('### 选题：那些\u201c没有变化\u201d的街区，也在告诉我们什么？')
        lines.append("")
        lines.append("**观察角度**")
        lines.append("")
        lines.append(
            "不是所有街区都在快速变化。稳定的商业生态同样值得记录——"
            "它们可能意味着成熟、平衡，也可能意味着停滞。"
        )
        lines.append("")
        lines.append("**为什么现在值得写**")
        lines.append("")
        lines.append(
            '在关注\u201c变化\u201d的热潮中，\u201c不变化\u201d也是一种信号。'
            "稳定的街区可能在等一个触发点，也可能是城市空间自我调节的结果。"
        )
