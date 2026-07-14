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

你的任务不是逐家搜索所有门店的开业新闻，也不是把地图新增 POI 直接写成"新店开业"。你的任务是：

1. 用品牌官网或地图 POI 快照维护门店主表；
2. 比较前后两期快照，识别少量变化候选；
3. 只对变化候选检索外部开业证据；
4. 区分"首次观测""疑似新增"和"确认开业"；
5. 输出可追溯、可复核、可持续更新的结构化结果。

---

## 1. Skill 说明

### 适用任务

- 比较两期品牌门店或 POI 数据
- 识别新增门店、疑似关店、迁址、改名或楼层变化
- 监控数百家零售门店的开业信息
- 建立或更新门店 registry
- 从地图 POI 中筛选值得进一步搜索的开业候选
- 为周报、月报生成门店变化事件

### 不适用任务

- 仅绘制门店地图（使用 `brand-map-pipeline`）
- 仅统计某一时点的门店数量
- 仅查询一家指定门店的营业时间
- 没有任何基准快照、门店主表或历史记录，却要求判断"本期新增"
- 在缺少历史快照时，只能建立 baseline，不得声称识别出新增或关闭事件

### 与 brand-map-pipeline 的关系

`brand-map-pipeline` 负责品牌 POI 的原始采集和地图可视化。`store-opening-watch` 负责基于已采集快照的门店变化分析。前者产生原始观测，后者在此基础上形成变化判断。

---

## 2. 必须遵守的原则

### 2.1 判断链路

始终遵守以下顺序：

```text
全量门店快照 → 标准化 → 门店实体去重 → 前后快照比对
→ 生成变化候选 → 仅搜索候选门店 → 证据分级 → 确认开业或保留未知
```

禁止采用：`400+ 家门店 × 每日逐家搜索开业新闻`。

### 2.2 变化候选优先

只对变化候选执行高成本步骤（联网搜索、证据判断）。不得对全部存量门店进行无差别搜索。

### 2.3 POI 不等于门店

- POI 新增不等同于真实新开业
- POI 消失不等同于门店关闭
- 名称修改、地址修正、楼层变化、坐标漂移和数据源更新需要与真实开闭店区分
- 未达到确认标准的事件必须标记为疑似或待验证

详见 `references/store-matching.md`。

### 2.4 原始数据保护

原始快照只读。不修改、不覆盖、不删除原始输入。标准化结果、门店实体和事件结果写入独立目录。每次运行必须保存输入文件名、日期和处理版本。

### 2.5 结果可追溯

建议必须能够回溯到推断，推断必须能够回溯到观测和证据。对外结论应尽量解释"发生了什么、为什么重要、用户可以做什么"。

### 2.6 项目级共同原则

项目根目录 `AGENTS.md` 中的采集与使用分离、事实推断建议分离、成本与工具原则同样适用于本 Skill。

---

## 3. 主执行流程

### 阶段一：输入与对齐

**Step 1：确认输入和比较范围**

检查两期数据的品牌、城市、日期范围是否一致。排查分页不完整、查询范围变化和数据源字段变化。未通过完整性检查时不得输出大规模关店结论。

详见 `references/workflow.md`。

**Step 2：读取快照和本地数据**

读取 baseline 和 current 快照，或门店主表和当前快照。确认最低字段齐全（name, brand_name, city, address, lon, lat）。

### 阶段二：变化识别

**Step 3：生成变化候选**

比较前后快照，识别 `new_store_candidate`、`possible_closed_store`、`renamed_store`、`relocated_store`、`possible_floor_change`、`function_changed`。

详见 `references/workflow.md`。

**Step 4：门店实体去重**

执行名称标准化、地址标准化、电话标准化，按匹配优先级判断是否属于同一门店实体。

详见 `references/store-matching.md`。

### 阶段三：证据判断

**Step 5：搜索外部证据**

只对 P0/P1 候选（`new_store_candidate`、`possible_closed_store`、`relocated_store`、`reopened_store`）启动外部证据搜索。对每个候选生成 3–6 个精确查询，不做无边界泛搜。

详见 `references/source-strategy.md`。

**Step 6：证据分级与事件判断**

按证据分级标准判断事件状态：高置信度 → `confirmed_opening`；中置信度 → 交叉验证；低置信度 → 不能确认开业。同时维护日期口径。

详见 `references/evidence-levels.md`。

### 阶段四：输出

**Step 7：输出结构化结果和审计信息**

输出 `compare.json`、`candidates.csv`、`compare.md`。报告中必须明确区分已确认开业、本期首次观测、疑似新增、疑似关店和纯数据变化。

详见 `references/output-contract.md`。

**Step 8：验收**

执行验收检查：所有候选都有处理状态；确认事件有足够证据；疑似事件没有被写成确认事实；输出满足约定结构；报告可以追溯至数据和证据。

---

## 4. 决策入口

| 场景 | 读取 |
|---|---|
| 确认门店是否是同一实体 | `references/store-matching.md` |
| 判断证据是否足以确认开业 | `references/evidence-levels.md` |
| 规划搜索查询和来源策略 | `references/source-strategy.md` |
| 写入结构化输出结果 | `references/output-contract.md` |
| 遇到改名、迁址、楼层变化、快闪店、POI 残留等边界情况 | `references/edge-cases.md` |
| 查看完整的执行顺序和输入输出 | `references/workflow.md` |

---

## 5. 完成定义

每次运行完成前，必须确认：

- [ ] 所有变化候选都有处理状态（确认、疑似、否定或待复核）
- [ ] 确认事件有足够证据（满足 high 或 multiple medium 标准）
- [ ] 疑似事件没有被写成确认事实
- [ ] 输出满足 `references/output-contract.md` 约定的结构
- [ ] 报告中的结论可以追溯至快照数据和外部证据
- [ ] 没有对全部存量门店执行无差别搜索
- [ ] 数据质量状态已判定（`usable` / `usable_with_warnings` / `unusable`）

---

## 6. 输出汇报格式

以简洁清单汇报：

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

- 明确说明哪些结论来自结构化比对
- 明确说明哪些结论有外部证据
- 明确说明哪些仍是待确认候选
```
