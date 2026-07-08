"""
Shared POI classification logic for brand_poi_scanner and brand_poi_analyzer.

Centralizes poi_kind (function type) and store_location_type (space type)
classification rules so both scanner and analyzer stay in sync.
"""


def safe_str(val) -> str:
    if isinstance(val, list):
        return " ".join(str(v) for v in val)
    return str(val) if val is not None else ""


# ── poi_kind (store function type) ──

ENERGY_TRIGGERS = ["换电", "充电", "超充", "能源", "power"]

SERVICE_KEYWORDS = ["服务中心", "售后", "维修", "施工中心", "精品施工", "官方精品施工中心"]

USER_KEYWORDS = [
    "用户中心", "授权用户中心", "问界用户中心", "AITO授权用户中心",
    "汽车中心", "4S店", "4S 店",
]

CAR_BRAND_CLUES = ["鸿蒙智行", "问界", "AITO", "HUAWEI", "华为AITO", "智己", "蔚来"]

MALL_CLUES = [
    "世博源", "晶耀前滩", "日月光中心", "荟聚", "正大乐城",
    "L1", "F1", "商场", "购物中心", "中心宝山店",
    "mall", "Mall", "广场", "百联", "万象城",
    "合生汇", "前滩太古里", "环球港",
]

EXPERIENCE_KEYWORDS = [
    "体验中心", "体验店", "蔚来空间", "蔚来中心", "智己汽车", "NIO House", "NIO Space",
]


def classify_poi_kind(
    name: str, poi_type: str, address: str,
    source_query: str = "",
    brand_id: str = "",
) -> str:
    text = safe_str(name) + " " + safe_str(poi_type) + " " + safe_str(address)
    sq = safe_str(source_query)
    combined = text + " " + sq

    if any(k in text for k in ENERGY_TRIGGERS):
        return "energy"
    if any(k in combined for k in SERVICE_KEYWORDS):
        return "service_center"
    if "交付" in text or "交付" in sq:
        return "delivery_center"
    if any(k in combined for k in USER_KEYWORDS):
        return "user_center"
    has_car_clue = any(k in combined for k in CAR_BRAND_CLUES)
    has_mall_clue = any(k in text for k in MALL_CLUES)
    if has_car_clue and has_mall_clue:
        return "mall_store"
    if any(k in combined for k in EXPERIENCE_KEYWORDS):
        return "experience_store"
    if any(k in text for k in MALL_CLUES):
        return "mall_store"
    if any(k in text for k in ("总部", "办公", "office")):
        return "office"
    return "other"


# ── store_location_type (space location type) ──

STORE_MALL_KEYWORDS = [
    "商场", "购物中心", "广场", "mall", "l1", "l2", "f1", "b1",
    "世博源", "晶耀前滩", "日月光中心", "荟聚", "正大乐城",
    "万象城", "百联", "龙湖", "合生汇", "环球港", "前滩太古里",
    "大悦城", "来福士", "iapm", "港汇", "美罗城", "印象城",
    "万达", "缤纷城", "宝乐汇", "上海中心大厦", "蓝鲸世界",
    "陆家嘴金融中心", "山姆会员超市", "山姆", "瑞虹新天地", "太阳宫",
    "虹桥国际机场", "久光中心", "兴业太古汇", "万象天地", "龙之梦",
    "虹桥天地", "BFC", "外滩金融中心", "TPY中心", "西岸中环",
    "中庭", "GF层", "LG", "LG2", "S101", "S104", "M114",
    "F1层", "1楼中庭", "地上一层", "出发禁区",
]

STORE_AUTO_PARK_KEYWORDS = [
    "汽车城", "汽车园", "汽车产业园", "汽车销售园区",
    "4s园区", "汽车市场", "车城", "嘉定汽车城", "安亭",
]

STORE_SERVICE_SITE_KEYWORDS = [
    "维修", "售后", "施工中心", "精品施工", "服务中心",
    "交付中心", "仓库", "厂房", "产业园", "物流园", "工场", "车间",
]

STORE_OFFICE_KEYWORDS = [
    "有限公司", "公司", "总部", "办公室", "办公楼", "写字楼", "商务楼",
]


def classify_store_location_type(name, address, poi_type):
    text = f"{name} {address} {poi_type}".lower()

    if any(k.lower() in text for k in STORE_OFFICE_KEYWORDS):
        return "office_or_entity"
    if any(k.lower() in text for k in STORE_AUTO_PARK_KEYWORDS):
        return "auto_park"
    if any(k.lower() in text for k in STORE_SERVICE_SITE_KEYWORDS):
        return "industrial_or_service_site"
    if any(k.lower() in text for k in STORE_MALL_KEYWORDS):
        return "mall"
    if "路" in address or "街" in address or "号" in address:
        return "road_address_store"

    return "unknown"