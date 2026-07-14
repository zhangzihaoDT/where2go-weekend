# Workflow：完整执行流程

> 何时读取：需要查看完整端到端 SOP、各阶段输入输出、失败降级处理和验收细节时。

---

## 1. 输入要求

### 1.1 推荐输入

至少提供以下一种组合：

**组合 A：两期快照**

```text
baseline_snapshot
current_snapshot
```

**组合 B：门店主表 + 当前快照**

```text
store_registry
current_snapshot
```

**组合 C：只有当前快照**

仅建立 baseline 和初始 registry，不执行新增、关闭或开业判断。

### 1.2 最低字段

每条 POI 至少需要：

```text
name, brand_name 或 brand_id, city, address, lon, lat
```

推荐字段：

```text
district, tel, source, source_poi_id, observed_at, store_type, mall_name, business_status
```

### 1.3 原始数据保护

- 原始快照只读
- 不修改、不覆盖、不删除原始输入
- 标准化结果、门店实体和事件结果写入独立目录
- 每次运行必须保存输入文件名、日期和处理版本

---

## 2. 推荐目录结构

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

## 3. STEP 1：输入检查

开始处理前必须检查：

1. 文件是否存在且可读
2. 数据是否为数组、CSV 表或可解析结构
3. 必填字段是否存在
4. 经纬度是否为合法数值
5. 快照日期是否明确
6. 两期数据的品牌和城市范围是否可比较
7. 是否存在明显的查询范围变化

如果本期门店数量突然大幅下降，先排查：

- API 分页不完整
- 查询关键词变化
- 城市范围变化
- 请求失败或限流
- 数据源字段变化
- 品牌中英文关键词覆盖不一致

未通过完整性检查时，不得输出大规模关店结论。

---

## 4. STEP 4：快照比对（详细）

比较 baseline 与 current 后，只允许输出以下事件类型：

```text
new_poi_candidate        # 既有门店新增了 POI
new_store_candidate      # 无法匹配任何既有门店实体
disappeared_poi_candidate # POI 消失，但门店仍有其他 POI
possible_closed_store    # 门店本期在所有来源中均消失
renamed_store            # 同电话、近距离、名称变化
relocated_store          # 同电话、距离明显变化
possible_floor_change    # 同商场、楼层变化
function_changed         # 门店类型变化（常规→旗舰/奥莱等）
reopened_store           # 之前消失的门店重新出现
possible_duplicate       # 同一门店新增了重复 POI
unchanged                # 无变化
```

### 4.1 新增候选

只有当本期记录无法匹配任何既有门店实体时，才生成 `new_store_candidate`。如果只是一个既有门店新增了第二条 POI，生成 `new_poi_candidate` / `possible_duplicate`。不得生成开业事件。

### 4.2 消失候选

单个 POI 消失时，优先检查是否仍有其他 POI 映射到同一门店实体。只有门店实体在本期全部来源中均消失，才生成 `possible_closed_store`。仍需后续复核，不得仅凭一期消失确认关店。

### 4.3 改名、迁址和楼层变化

- 同电话、近距离、名称变化：优先判断改名
- 同电话、距离明显变化：优先判断迁址
- 同商场、楼层变化：标记 `possible_floor_change`
- 门店类型从常规店变为旗舰店、Style、Beacon、奥莱等：标记 `function_changed`

---

## 5. STEP 5：候选优先级

仅对以下候选启动外部证据搜索：

### P0：必须检索

- `new_store_candidate`
- `possible_closed_store`
- `relocated_store`
- `reopened_store`

### P1：建议检索

- `function_changed`
- `possible_floor_change`
- 高价值商圈或重点城市门店变化

### P2：无需立即检索

- `new_poi_candidate`
- `possible_duplicate`
- 仅格式或名称轻微变化

搜索预算必须集中在 P0 和 P1，不得为全部存量门店执行全量新闻搜索。

---

## 6. 数据质量状态

每次运行必须给出一个状态。

### `usable`

- 两期范围一致
- 字段完整
- 数据量合理
- 无明显分页或请求失败

### `usable_with_warnings`

- 少量字段缺失
- 个别品牌、区县或电话覆盖异常
- 存在需要人工复核的范围变化

### `unusable`

- 当前快照明显不完整
- 两期城市或品牌范围不一致且无法校正
- 经纬度大面积缺失
- 解析失败
- 查询分页不完整
- 本期数量异常下降且无法解释

`unusable` 时只输出诊断，不输出开店或关店结论。

---

## 7. 成本控制规则

1. 快照采集按品牌与城市批量执行，不逐店调用
2. 常规刷新周期默认一周，不默认每日全量刷新
3. 只对 P0/P1 变化候选搜索外部证据
4. 对没有变化的门店不重复搜索
5. 已确认开业的历史事件不重复检索
6. 搜索结果必须缓存并记录查询词与日期
7. 人工复核队列应控制在少量高价值候选
8. 不为补齐全部历史开业日期而无边界回溯 400+ 家存量门店

对于存量门店，优先记录 `first_seen_date`。历史开业日期只回溯重点门店、重点商圈或用户明确指定的范围。

---

## 8. 验收流程

每次运行完成后，执行以下检查：

1. 所有候选都有处理状态
2. 确认事件有足够证据
3. 疑似事件没有被写成确认事实
4. 输出满足 `output-contract.md` 约定的结构
5. 报告可以追溯至数据和证据
6. 没有对全部存量执行无差别搜索
7. 数据质量状态已判定
