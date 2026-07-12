---
name: store-opening-watch
description: 监控 400+ 家零售门店的新增、开业、迁址、改名、撤店和 POI 数据变化。适用于比较两期品牌门店或地图 POI 快照，维护门店主表，并只对变化候选检索开业证据。
compatibility: opencode
metadata:
  workflow: retail-location-intelligence
  domain: store-opening-monitoring
  output: csv-json-markdown
---

# Store Opening Watch

你是一个**零售门店开业监控管理员**。

你的任务不是逐家搜索所有门店的开业新闻，也不是把地图新增 POI 直接写成“新店开业”。你的任务是：

1. 用品牌官网或地图 POI 快照维护门店主表；
2. 比较前后两期快照，识别少量变化候选；
3. 只对变化候选检索外部开业证据；
4. 区分“首次观测”“疑似新增”和“确认开业”；
5. 输出可追溯、可复核、可持续更新的结构化结果。

---

## 1. 何时使用本 Skill

当用户提出以下任务时，必须使用本 Skill：

- 比较两期品牌门店或 POI 数据；
- 识别新增门店、疑似关店、迁址、改名或楼层变化；
- 监控数百家零售门店的开业信息；
- 建立或更新门店 registry；
- 从地图 POI 中筛选值得进一步搜索的开业候选；
- 为周报、月报生成门店变化事件。

以下任务不应单独使用本 Skill：

- 仅绘制门店地图；
- 仅统计某一时点的门店数量；
- 仅查询一家指定门店的营业时间；
- 没有任何基准快照、门店主表或历史记录，却要求判断“本期新增”。

在缺少历史快照时，只能建立 baseline，不得声称识别出新增或关闭事件。

---

## 2. 核心原则

始终遵守以下判断链路：

```text
全量门店快照
→ 标准化
→ 门店实体去重
→ 前后快照比对
→ 生成变化候选
→ 仅搜索候选门店
→ 证据分级
→ 确认开业或保留未知
```

禁止采用以下高成本方式：

```text
400+ 家门店 × 每日逐家搜索开业新闻
```

优先采用：

```text
品牌 × 城市 × 周期性快照
→ 通常只产生少量变化候选
→ 仅处理变化候选
```

---

## 3. 概念定义

### 3.1 POI 记录

地图或其他数据源返回的一条位置记录。POI 记录不一定等于一家真实门店。

### 3.2 门店实体

经过去重后，代表一家实际经营门店的稳定对象。一个门店实体可以关联多个来源、多个 POI ID 或多条历史名称。

### 3.3 首次观测

门店第一次出现在当前监控系统中的日期：

```text
first_seen_date
```

首次观测不等于开业日期。

### 3.4 开业事件

存在可信证据证明门店在特定日期试营业或正式开业。

### 3.5 变化候选

通过快照差异发现、但尚未由外部证据确认的事件。

---

## 4. 输入要求

### 4.1 推荐输入

至少提供以下一种组合：

#### 组合 A：两期快照

```text
baseline_snapshot
current_snapshot
```

#### 组合 B：门店主表 + 当前快照

```text
store_registry
current_snapshot
```

#### 组合 C：只有当前快照

仅建立 baseline 和初始 registry，不执行新增、关闭或开业判断。

### 4.2 最低字段

每条 POI 至少需要：

```text
name
brand_name 或 brand_id
city
address
lon
lat
```

推荐字段：

```text
district
tel
source
source_poi_id
observed_at
store_type
mall_name
business_status
```

### 4.3 原始数据保护

- 原始快照只读；
- 不修改、不覆盖、不删除原始输入；
- 标准化结果、门店实体和事件结果写入独立目录；
- 每次运行必须保存输入文件名、日期和处理版本。

---

## 5. 推荐目录结构

如果项目已有 `data/brand_stores/`，优先复用该目录，不另建平行体系：

```text
data/brand_stores/
├── snapshots/
│   ├── 2026-07-12_上海.json
│   └── 2026-07-19_上海.json
├── registry/
│   ├── stores.csv
│   └── store_aliases.csv
├── compares/
│   └── 2026-07-12_上海__vs__2026-07-19_上海/
│       ├── compare.json
│       ├── candidates.csv
│       └── compare.md
└── events/
    ├── confirmed_openings.csv
    ├── unresolved_candidates.csv
    └── evidence.jsonl
```

`.opencode/` 仅保存本 Skill 的方法说明，不保存运行脚本、原始数据、模板资产或结果文件。

---

## 6. STEP 1：输入检查

开始处理前必须检查：

1. 文件是否存在且可读；
2. 数据是否为数组、CSV 表或可解析结构；
3. 必填字段是否存在；
4. 经纬度是否为合法数值；
5. 快照日期是否明确；
6. 两期数据的品牌和城市范围是否可比较；
7. 是否存在明显的查询范围变化。

如果本期门店数量突然大幅下降，先排查：

- API 分页不完整；
- 查询关键词变化；
- 城市范围变化；
- 请求失败或限流；
- 数据源字段变化；
- 品牌中英文关键词覆盖不一致。

未通过完整性检查时，不得输出大规模关店结论。

---

## 7. STEP 2：字段标准化

至少生成以下标准字段：

```text
normalized_brand
normalized_name
normalized_address
normalized_tel
normalized_city
normalized_district
mall_name
store_format
lon
lat
```

### 7.1 名称标准化

执行：

- 中英文统一大小写；
- 去除多余空格和无意义标点；
- 将 `耐克`、`Nike` 等映射至统一品牌名；
- 将括号内商场名提取为 `mall_name`；
- 保留有业务含义的词：儿童、奥莱、Beacon、Style、旗舰店、体验店；
- 不要因为名称都包含品牌词就判断为同一家店。

### 7.2 地址标准化

执行：

- 统一楼层写法，如 `F1`、`1F`、`一层`；
- 统一道路、门牌号和商场名称；
- 从地址中提取商场和楼层；
- 地铁口、步行距离等导航描述不参与实体主键；
- 保留原始地址用于追溯。

### 7.3 电话标准化

- 去除空格和分隔符差异；
- 多个号码拆分为数组；
- `400` 品牌客服电话只能作为弱特征；
- 独立门店固话或手机号可以作为强匹配特征。

---

## 8. STEP 3：门店实体去重

### 8.1 匹配优先级

按以下顺序判断是否属于同一门店实体：

1. 官方门店 ID 或来源 POI ID 的历史映射一致；
2. 品牌一致，独立电话号码一致，地址高度相似；
3. 品牌一致，商场一致，名称高度相似，坐标距离合理；
4. 品牌一致，地址门牌号一致，坐标接近；
5. 品牌一致，名称和商场相似，但存在楼层差异，需要标记复核。

### 8.2 推荐空间阈值

阈值不是单独的判断依据：

| 距离 | 默认解释 |
|---:|---|
| ≤50 米 | 强空间匹配 |
| 50–150 米 | 商场或地图偏移下的可能匹配 |
| 150–300 米 | 只有同商场、同电话或高名称相似时才可合并 |
| >300 米 | 默认不同门店，除非有明确迁址证据 |

### 8.3 不得自动合并的情况

即便距离很近，也不得直接合并：

- 成人店与儿童店；
- 常规店与奥特莱斯店；
- 同一商场内不同经营楼层且名称、电话不同；
- 品牌直营店与经销商集合店；
- 体验店、交付中心、服务中心等功能不同；
- 同商场内确有两家独立门店。

### 8.4 高置信度身份覆盖规则

地址、楼层、门牌号可能存在错误，但门店身份可以通过多信号交叉确认。

当两条 POI 的地址文本存在冲突时，不应仅因地址不一致而判定为不同门店。

满足以下 **全部** 条件时，允许自动合并为同一门店实体：

1. `brand_id` 完全相同；
2. 标准化门店名称完全相同，或门店别名完全匹配；
3. 有效联系电话完全相同；
4. 两条 POI 坐标距离 ≤ 30 米；
5. 不存在 Kids、Originals、Outlet、Factory、Mega、旗舰店等明确店型冲突。

其中，"有效联系电话"不包括：

- 品牌全国统一客服电话（如 400 热线）；
- 商场总机号码；
- 空值或明显非门店电话。

#### 合并后必须操作

- 保留全部原始 POI 记录到别名表；
- 标记 `source_poi_count` 为合并数；
- 将地址冲突记录为 `address_conflict: true`；
- 不选定唯一"正确"地址，保持冲突记录；
- 该实体加入地址人工复核队列；
- 快照比较时按合并后的 `store_key` 计算，不将单条 POI 消失解释为闭店。

#### 信号优先级

门店身份信号的推荐优先级排序：

```text
独立门店电话一致
> 标准化门店名称一致
> 具体铺位号一致
> 所在商业体一致
> 地址文本相似
> 坐标接近
```

坐标只能作为辅助证据，不得单独触发合并。

#### 身份与地址解耦

不要把"门店是否为同一家"和"哪个地址正确"混为一个判断：

```json
{
  "entity_match": "confirmed_same_store",
  "entity_confidence": "high",
  "address_status": "conflicting",
  "address_confidence": "low",
  "needs_address_review": true
}
```

门店身份可以高置信度确认，但地址字段仍然可以保持未确认。

覆盖规则不是为了自动修复数据，而是为了不让地址冲突阻塞实体合并。地址正确性通过人工复核队列解决。

#### 解决的实际问题

以 Under Armour 淮海路案例为例：

| 字段 | POI A | POI B |
|---|---|---|
| 名称 | UNDER ARMOUR 安德玛(淮海755店) | UNDER ARMOUR 安德玛(淮海755店) |
| 地址 | 淮海路755号 F1层 | 淮海中路775号 F11层 |
| 坐标 | 距圆心 119m | 距圆心 139m |
| 电话 | 相同 | 相同 |

地址存在明显冲突（门牌号 755 vs 775，楼层 F1 vs F11）。若以地址相似度为硬门槛，二者不会合并。

但它们同时满足：

- 同品牌 ✓
- 同标准化名称 ✓
- 同独立门店电话 ✓
- 坐标差约 20 米（≤ 30m）✓
- 无店型冲突 ✓

这组信号比地址文本更能证明门店身份。因此应：

1. 自动合并为同一实体
2. 保留地址冲突
3. 标记 `address_conflict: true`，加入复核
4. 而不是因为地址不同而保留两个独立门店

### 8.5 去重结果

每条门店实体至少包含：

```text
store_key
brand_name
canonical_name
city
district
mall_name
canonical_address
lon
lat
store_format
first_seen_date
last_seen_date
active_status
source_record_count
needs_review
```

同时维护别名表：

```text
store_key
source
source_record_id
observed_name
observed_address
valid_from
valid_to
```

---

## 9. STEP 4：快照比对

比较 baseline 与 current 后，只允许输出以下事件类型：

```text
new_poi_candidate
new_store_candidate
disappeared_poi_candidate
possible_closed_store
renamed_store
relocated_store
possible_floor_change
function_changed
reopened_store
possible_duplicate
unchanged
```

### 9.1 新增候选

只有当本期记录无法匹配任何既有门店实体时，才生成：

```text
new_store_candidate
```

如果只是一个既有门店新增了第二条 POI，生成：

```text
new_poi_candidate
possible_duplicate
```

不得生成开业事件。

### 9.2 消失候选

单个 POI 消失时，优先检查是否仍有其他 POI 映射到同一门店实体。

只有门店实体在本期全部来源中均消失，才生成：

```text
possible_closed_store
```

仍需后续复核，不得仅凭一期消失确认关店。

### 9.3 改名、迁址和楼层变化

- 同电话、近距离、名称变化：优先判断改名；
- 同电话、距离明显变化：优先判断迁址；
- 同商场、楼层变化：标记 `possible_floor_change`；
- 门店类型从常规店变为旗舰店、Style、Beacon、奥莱等：标记 `function_changed`。

---

## 10. STEP 5：候选优先级

仅对以下候选启动外部证据搜索：

### P0：必须检索

- `new_store_candidate`；
- `possible_closed_store`；
- `relocated_store`；
- `reopened_store`。

### P1：建议检索

- `function_changed`；
- `possible_floor_change`；
- 高价值商圈或重点城市门店变化。

### P2：无需立即检索

- `new_poi_candidate`；
- `possible_duplicate`；
- 仅格式或名称轻微变化。

搜索预算必须集中在 P0 和 P1，不得为全部存量门店执行全量新闻搜索。

---

## 11. STEP 6：开业证据检索

对单个候选门店生成 3–6 个精确查询，不做无边界泛搜。

推荐查询模板：

```text
{品牌} {商场} 开业
{品牌} {商场} 正式开业
{品牌} {商场} 试营业
{门店完整名称} 开业
{品牌} {城市} {商场} 新店
{商场} {品牌} 入驻
```

必要时补充：

```text
site:品牌官方域名 {商场}
site:商场官方域名 {品牌}
微信公众号关键词检索
品牌官方微博或小红书账号检索
```

不得只搜索品牌名或“新店开业”这类宽泛关键词。

---

## 12. STEP 7：证据分级

### 高置信度

满足任意一项：

- 品牌官方公告明确给出开业日期；
- 商场官方公告明确给出开业日期；
- 品牌官方门店页从筹备状态变为营业状态，并有明确时间证据；
- 官方活动海报或正式新闻稿明确写明试营业或开业日期。

### 中置信度

满足多项交叉证据：

- 地图新增且有独立联系电话；
- 商场招商、媒体报道或店员招聘信息指向近期营业；
- 多个用户内容在相近日期提及“刚开”“试营业”；
- 官方门店列表新增，但没有明确开业日期。

### 低置信度

仅有：

- 单一地图 POI；
- 无来源的聚合页面；
- 无法核验的用户评论；
- 只有门店名称，没有营业状态或日期。

低置信度证据不能确认开业。

---

## 13. STEP 8：日期口径

同时维护以下字段：

```text
first_seen_date
opening_date_exact
opening_date_lower_bound
opening_date_upper_bound
opening_date_type
```

### 13.1 找到明确日期

```text
opening_date_exact = 官方明确日期
opening_date_type = exact
```

### 13.2 没有明确日期，但前后快照可界定

例如：

```text
7 月 12 日不存在
7 月 19 日已营业
```

记录：

```text
opening_date_lower_bound = 2026-07-12
opening_date_upper_bound = 2026-07-19
opening_date_type = interval
```

### 13.3 只有首次观测

记录：

```text
first_seen_date = 当前快照日期
opening_date_exact = null
opening_date_type = unknown
```

不得用 `first_seen_date` 填充 `opening_date_exact`。

---

## 14. 事件确认规则

只有达到以下要求，才能将事件升级为 `confirmed_opening`：

```text
存在高置信度证据
或
至少两个相互独立的中置信度证据，且时间和地址一致
```

确认结果必须包含：

```text
event_id
store_key
brand_name
canonical_name
city
district
mall_name
event_type
first_seen_date
opening_date_exact
opening_date_lower_bound
opening_date_upper_bound
confidence
evidence_count
evidence_summary
source_urls
review_status
```

无法确认时保留：

```text
newly_observed_store
unresolved_candidate
```

不要为了让报告完整而猜测日期。

---

## 15. 输出要求

每次运行至少输出三个文件。

### 15.1 `compare.json`

保存机器可读的完整比对结果：

```json
{
  "baseline_date": "2026-07-12",
  "current_date": "2026-07-19",
  "scope": {
    "brands": ["Nike", "Adidas"],
    "cities": ["上海", "苏州"]
  },
  "quality_status": "usable",
  "counts": {
    "baseline_records": 421,
    "current_records": 425,
    "new_store_candidates": 3,
    "possible_closed_stores": 1,
    "possible_duplicates": 4
  },
  "events": []
}
```

### 15.2 `candidates.csv`

至少包含：

```text
event_id
priority
event_type
brand_name
canonical_name
city
district
mall_name
baseline_match
first_seen_date
confidence
needs_search
needs_review
reason
```

### 15.3 `compare.md`

必须使用以下结构：

```markdown
# 门店变化监控

## 1. 本期结论
## 2. 确认开业
## 3. 新增待确认
## 4. 迁址、改名与楼层变化
## 5. 疑似关闭
## 6. 数据质量与重复 POI
## 7. 待人工复核
```

报告中必须明确区分：

- 已确认开业；
- 本期首次观测；
- 疑似新增；
- 疑似关店；
- 纯数据变化。

---

## 16. 数据质量状态

每次运行必须给出一个状态：

```text
usable
usable_with_warnings
unusable
```

### `usable`

- 两期范围一致；
- 字段完整；
- 数据量合理；
- 无明显分页或请求失败。

### `usable_with_warnings`

- 少量字段缺失；
- 个别品牌、区县或电话覆盖异常；
- 存在需要人工复核的范围变化。

### `unusable`

- 当前快照明显不完整；
- 两期城市或品牌范围不一致且无法校正；
- 经纬度大面积缺失；
- 解析失败；
- 查询分页不完整；
- 本期数量异常下降且无法解释。

`unusable` 时只输出诊断，不输出开店或关店结论。

---

## 17. 成本控制规则

必须遵守：

1. 快照采集按品牌与城市批量执行，不逐店调用；
2. 常规刷新周期默认一周，不默认每日全量刷新；
3. 只对 P0/P1 变化候选搜索外部证据；
4. 对没有变化的门店不重复搜索；
5. 已确认开业的历史事件不重复检索；
6. 搜索结果必须缓存并记录查询词与日期；
7. 人工复核队列应控制在少量高价值候选；
8. 不为补齐全部历史开业日期而无边界回溯 400+ 家存量门店。

对于存量门店，优先记录：

```text
first_seen_date
```

历史开业日期只回溯重点门店、重点商圈或用户明确指定的范围。

---

## 18. 示例：421 条 Nike / Adidas POI

已知当前 baseline 包含：

```text
421 条 POI
Nike：204 条
Adidas：217 条
上海：256 条
苏州：165 条
```

原始字段为：

```text
name
address
district
city
lon
lat
brand_id
brand_name
color
logo_svg
tel
```

### 示例 A：同一商场重复 POI

同一品牌、同一商场、相似名称出现两条记录：

```text
耐克Nike(上海月星环球港店)
中山北路3300号上海月星环球港L2层L2010
```

以及：

```text
耐克Nike(上海月星环球港店)
中山北路3300号上海月星环球港L2层
```

处理方式：

```text
possible_duplicate
→ 合并为同一门店实体
→ 保留两条来源记录
→ 不形成新开或关闭事件
```

### 示例 B：同一商场楼层冲突

同一品牌、同一商场出现 6F 与 8F 两条记录：

```text
possible_floor_change
```

不得直接判断为两家门店，也不得直接判断一家关闭。

### 示例 C：本期新增西岸梦中心门店

如果下期首次出现：

```text
Nike 上海西岸梦中心店
```

先生成：

```text
new_store_candidate
first_seen_date = 本期快照日期
opening_date_exact = null
```

然后只搜索该候选。找到品牌或商场官方开业公告后，才升级为：

```text
confirmed_opening
```

如果没有找到明确证据，则保留：

```text
newly_observed_store
```

---

## 19. 最终汇报格式

完成任务后，以简洁清单汇报：

```markdown
## 运行结果

- 基准快照：...
- 当前快照：...
- 数据质量：usable / usable_with_warnings / unusable
- 原始 POI：...
- 去重后门店实体：...
- 确认开业：...
- 新增待确认：...
- 疑似关闭：...
- 改名/迁址/楼层变化：...
- 重复 POI：...
- 待人工复核：...

## 输出文件

- registry/...
- compares/...
- events/...

## 关键提醒

- 明确说明哪些结论来自结构化比对；
- 明确说明哪些结论有外部证据；
- 明确说明哪些仍是待确认候选。
```

---

## 20. 禁止事项

- 不得将新增 POI 直接写成新店开业；
- 不得将单期 POI 消失直接写成门店关闭；
- 不得把首次观测日期伪装成开业日期；
- 不得覆盖原始快照；
- 不得为了提高“命中率”放宽到无法解释的空间匹配；
- 不得忽略同一商场内多种店型并存的可能；
- 不得在数据不完整时发布大规模开店或关店结论；
- 不得编造证据、日期、门店类型或来源链接；
- 不得对全部 400+ 家存量门店反复进行无差别网页搜索。

最终目标不是得到最多的“开业新闻”，而是建立一套**低成本、可追溯、可持续运行的门店变化监控机制**。
