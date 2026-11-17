# Maven Revenue Intelligence — Dashboard 审计与数据契约

> **REVIEWED AND APPROVED FOR MILESTONE 1.** 本文档最初于 2026-11-15 编写，2026-11-16 改写为中文学习版；
> 用户在逐表、逐字段、逐指标阅读和 Dashboard 视觉评审后，于 2026-11-16 确认完成 review 并要求进入下一 milestone。
> 该批准关闭数据审计 gate，但不等于 gold values 已冻结；gold calculations 仍须在 Milestone 3 单独计算和审核。

## 0. 建议阅读顺序

如果目标是彻底搞懂这个 dashboard，建议按下面的顺序阅读：

```text
第 5–6 节：六张源表分别记录什么
    ↓
第 7–8 节：这些表如何 join，以及业务维度如何从原始字段得到
    ↓
第 9–10 节：每个 metric 的公式、分母、grain 和 date basis
    ↓
第 4 节：四个 dashboard 页面分别展示什么、数字从哪里来
    ↓
第 11–13 节：数据能回答什么、不能回答什么，以及第一条 agent path
```

最核心的数据流是：

```text
CSV source data
→ SQLite 六张业务表
→ dashboard/metrics.py 中的确定性计算
→ dashboard/ui.py 中的四个页面
→ 未来 agent 只能调用经过验证的 metric tools
```

## 1. 本文档的目的

这是 Milestone 1 的唯一正式参考文档，用来说明：

- 当前 dashboard 能怎样展示 month-over-month revenue change（月环比收入变化）；
- 每一张源表、每一个字段、每条 logical join 和重要 cardinality；
- dashboard metric 的公式、分母、grain（计算粒度）和 date ownership（时间归属）；
- 哪些关系只能算 descriptive evidence，哪些 causal explanation 数据无法支持；
- 未来 investigation agent 可以安全接收哪些 dashboard context；
- 推荐的第一条 midpoint investigation path，等待用户批准。

本文档不是 gold-case fixture，不是 agent prompt，也不代表 agent 已经存在。

## 2. 核验依据

以下内容已于 2026-11-15 使用实际项目核验：

- 当前工作目录中真实运行的 Streamlit application；
- `dashboard/ui.py`、`dashboard/metrics.py`、`dashboard/filters.py`、`dashboard/options.py` 和
  `dashboard/models.py`；
- 只读 SQLite database：`tmp/maven-analysis/maven_fuzzy.db`；
- `tmp/maven-fuzzy-source/Data/` 下的六个 CSV 文件；
- source-data repository revision：`e9a5f12296021570172de75cc98fd22e4c3a705c`；
- 自动测试结果：写本文档前为 `49 passed in 9.08s`；
- 对 schema、cardinality、orphan rows、timestamp 和 reconciliation 的直接 SQL 检查；
- 使用 `scripts/build_database.py` 从六个 CSV 临时重建的对照数据库。

临时重建库只用于比较，没有替换应用当前使用的数据库。

## 3. 先给结论

### 3.1 哪一页应该作为月环比调查入口？

**Executive Overview 应该作为 midpoint revenue investigation 的主入口。** 它是当前唯一能在一页中同时展示
以下信息的页面：

- gross revenue 或 net revenue；
- orders；
- sessions；
- conversion rate；
- average order value（AOV）；
- gross margin；
- refund rate；
- 与 comparison period 的 delta；
- `gross revenue = sessions × conversion rate × average order value` 这一分解关系；
- 当前期间按 traffic source 排列的 revenue。

实际运行时已经手动设置：

```text
Reporting window: Custom
Start month: Jun 2014
End month: Jun 2014
Compare with: Previous period
```

页面正确显示为 `Jun 1–Jun 30, 2014 (Previous period)`，其他三页也保留了同一个时间窗口。Executive Overview
显示 June 相对 May 的 revenue decline，并指出 conversion 是相对变化最大的分量。这只是 capability smoke check，
不是已经冻结的 gold result。

### 3.2 Dashboard 现在能做什么？

当前 dashboard 可以：

1. 验证某个月环比变化确实发生；
2. 把 gross revenue 的变化拆成 traffic volume、conversion 和 order value；
3. 展示当前期间的 acquisition、funnel、product、basket、margin 和 refund evidence；
4. 将 funnel stage 与 previous period 进行比较；
5. 让四个页面共享同一个 date window 和 session filters。

### 3.3 Dashboard 现在还不能做什么？

它还不能独立完成严谨的“原因解释”。原因是大部分 segment charts 展示的是**当前期间排名**，而不是每个 segment
对月环比变化的 contribution。

```text
当前收入最大的 segment
≠
造成两个月收入差异最大的 segment
```

因此，后续 agent 必须调用 deterministic delta/contribution tools，不能直接把当前排名当成 revenue decline 的解释。

### 3.4 2026-11-16 新增的 Data Guide

Dashboard 现在增加了一页英文 `Data Guide`，把本文档中已经核验的内容直接放进应用，帮助第一次接触该数据的
读者理解页面。它不是第五个 analysis page，也不会改变任何 metric calculation。它包含：

1. `Raw Data Dictionary`：六张源表的 grain、field definitions、实际前五行和 16 个 URL；
2. `Derived Dimensions`：Traffic Source、Campaign、landing page、funnel stage 等自定义规则；
3. `Metrics & Charts`：四个分析页面的 formula、aggregation grain 和 interpretation caveat。

本轮确认的展示规则是：

- Traffic Source 只显示 active dataset 中实际存在的 Paid Search、Paid Social、Organic Search 和 Direct，不显示
  count 为零的 Other；
- Campaign 对 Brand、Nonbrand、Pilot、Desktop targeted 和 Untracked 给出简短英文解释；
- `utm_content` 和 landing-page URL 使用 readable display label，同时明确标注 source value 已被 masked，数据中
  没有原始 ad creative 或 landing-page content；
- Data Guide 不加入 free-form Q&A；未来自然语言问题由 investigation agent 处理；
- Dashboard 中所有 table cells 统一左对齐；money columns 保持 numeric 类型并显示 `$`；
- Data Guide 使用居中的阅读版式（最大宽度 1440px，左右留白随 viewport 调整），table `Fields` 区域用
  浅紫色，`First five rows` 区域用浅蓝色。2026-11-16 最初实现的分层 relationship cards，以及随后短暂使用的
  四列关系表，均在用户视觉评审后于同日 supersede；当前版本使用标准 logical ERD：六张表各出现一次，schema box
  显示主要 PK/FK 字段，五条核心 analysis joins 使用连线和实际 cardinality 标记。ERD 与第一个 source-table
  expander 之间保留明确间距。

实现证据：`dashboard/guide.py`、`dashboard/display.py`、`dashboard/labels.py` 和 `dashboard/ui.py`。2026-11-16
最新完整测试结果为 `69 passed in 10.15s`，并已在运行中的 Streamlit 页面完成视觉检查。

## 4. 四个 Dashboard 页面到底在做什么？

### 4.1 四页共用的 Global filters

| Control | 可选值或行为 | 在 investigation 中的含义 |
| --- | --- | --- |
| Reporting window | Latest 12/6/3 months、All history、Custom | Custom 可通过设置相同的 start/end month 选择一个完整自然月 |
| Compare with | Previous period、Previous year、None | 单月窗口选择 Previous period 时，会自动使用前一个自然月 |
| Traffic source | Paid Search、Paid Social、Organic Search、Direct | 共用 session attribution filter；active dataset 没有 Other，因此 UI 和 Data Guide 均不显示空类别 |
| Campaign | Brand、Nonbrand、Desktop targeted、Pilot、Untracked | 带业务标签的 raw campaign filter |
| Device | desktop、mobile | Session 使用的 device |
| Session type | New、Repeat | 新访或回访 session |

所有日期范围在代码中均为 half-open interval：

```text
start <= timestamp < 所选结束月份之后的第一天
```

### 4.2 四页 capability map

| 页面 | 页面上看得到什么 | 页面专属 controls | 调用的 metric functions | 在调查中的作用 | 当前限制 |
| --- | --- | --- | --- | --- | --- |
| Executive Overview | Revenue、orders、sessions、conversion、AOV、margin、refund rate、net revenue、KPI deltas、trend、traffic/conversion/AOV index | Time grain、Gross/Net basis、Primary KPI | `overview_kpis`、`overview_trend`、`overview_drivers` | 确认变化，并决定先查 traffic、conversion 还是 AOV | Traffic-source chart 只显示当前 gross revenue，不是各 source 的 change contribution；即使页面选 Net，该 chart 仍为 Gross |
| Acquisition | Sessions、orders、conversion、revenue/session 的整体 delta；当前 source、campaign、device、landing page 排名 | Ad content、referrer type、landing page、metric | `acquisition_performance` | 定位不同 acquisition dimensions 的 traffic quality 与 conversion pattern | Segment charts 只有当前值，没有 previous-period delta/contribution；没有 ad spend，所以 revenue/session 不是 ROAS |
| Website Funnel | Sessions、observed thank-you events、total conversion delta、当前 stage reach/drop-off、detail table 中的 prior total conversion | Landing page、product page、funnel version、compare dimension | `funnel_summary`、`funnel_breakdown` | 当 conversion 发生变化时，沿 ordered funnel 查找变化出现在哪个 stage | 这是基于 pageview order 的 session cohort，不是 causal experiment；最后事件是 thank-you pageview |
| Products & Refunds | Revenue、units、margin、refund-rate delta，当前 product、basket、add-on 与 refund evidence，aggregate monthly trend | Product、item role、order size、purchase/refund date basis、metric | `product_performance`、`product_trend`、`aggregate_product_trend`、`basket_mix` | 当 AOV、mix、basket、margin 或 refund 变化时继续调查 | Product ranking 是当前值，不是 product 对 MoM change 的 contribution；refund 解读取决于 date basis |

### 4.3 已经算出来、但没有直接作为 change factor 展示的内容

| 已有计算 | 代码位置 | 当前 UI 缺口 |
| --- | --- | --- |
| 按 ad content 或 referrer type 的 acquisition | `DIMENSION_EXPRESSIONS`、`acquisition_performance` | 两者目前是 filters，没有对应 breakdown chart |
| 按 session type 的 acquisition | `acquisition_performance` | Session type 是 global filter，没有 comparison chart |
| Campaign、device、session type、referrer type overview drivers | `overview_drivers` | Executive Overview 目前只调用 Traffic source |
| 按 session type 比较 funnel | `funnel_breakdown` | UI 的 Compare by 没有 Session type |
| Product net revenue | `product_performance` | 已计算，但不是可选 chart metric |
| Basket revenue 与 AOV | `basket_mix` | 当前 basket chart 只展示 order count |
| Executive Overview 的 refund amount | `overview_kpis`、`overview_trend` | 页面显示 refund rate 和 net revenue，没有 refund dollars KPI card |
| Segment change contribution | 尚未实现 | 后续必须补；不能把 current-period ranking 当作 change contribution |

### 4.4 未来 Agent 需要从 Dashboard 接收什么 Context？

这些值目前分别存在于 Streamlit state 中，但还没有组成 typed context packet。后续 context object 应只包含：

```text
page
current_period_start
current_period_end_exclusive
comparison_mode
comparison_period_start
comparison_period_end_exclusive
global_filters
page_controls
primary_metric
revenue_basis
data_through
is_partial_period
```

各页 page-specific controls：

- Executive Overview：time grain、revenue basis、primary KPI；
- Acquisition：ad content、referrer type、landing page、selected metric；
- Website Funnel：landing page、product page、funnel version、comparison dimension；
- Products & Refunds：product、item role、order size、date basis、selected metric。

不能把整个 Streamlit session state 交给 agent。当前还没有 chart-mark selection、evidence ID 或 typed resolved
comparison period，这些是后续 implementation gaps，不是当前已经存在的能力。

## 5. 六张源表分别是什么？

### 5.1 表的 grain、行数与时间范围

| 表 | 一行代表什么（grain） | 行数 | 时间范围 | Primary key |
| --- | --- | ---:| --- | --- |
| `website_sessions` | 一次网站访问/session | 472,871 | 2012-03-19 08:04:16 至 2015-03-19 07:59:08 | `website_session_id` |
| `website_pageviews` | 一次 pageview event | 1,188,124 | 2012-03-19 08:04:16 至 2015-03-19 07:59:32 | `website_pageview_id` |
| `orders` | 一笔完成的订单 | 32,313 | 2012-03-19 10:42:46 至 2015-03-19 05:38:31 | `order_id` |
| `order_items` | 一笔订单中的一个商品 line item | 40,025 | 2012-03-19 10:42:46 至 2015-03-19 05:38:31 | `order_item_id` |
| `order_item_refunds` | 一个商品的一次退款事件 | 1,731 | 2012-04-06 11:32:43 至 2015-04-01 18:11:08 | `order_item_refund_id` |
| `products` | 一个 catalog product | 4 | 商品上线时间：2012-03-19 至 2014-02-05 | `product_id` |

最后一个 session month（March 2015）不是完整月份。Refund data 延伸到 2015-04-01，比 session coverage 更晚。

### 5.2 Schema 层面的限制

- SQLite 声明了六个 primary keys，但**没有声明 foreign-key constraints，也没有声明 `NOT NULL` constraints**。
- 对实际数据的 logical relationship 检查未发现 orphan rows 或 key consistency failure。
- Timestamp 使用可排序的 `YYYY-MM-DD HH:MM:SS` text，不带 timezone。数据集没有说明 timezone，因此所有
  calendar grouping 只能按原始 timestamp 处理。
- Source CSV 在四个 session attributes 中用文本 `NULL` 表示缺失。当前运行库也存为文本 `NULL`，当前 builder
  则会将其转换为 SQL `NULL`。查询层通过 `NULLIF(column, 'NULL')` 同时兼容两种表示。

## 6. 完整字段字典

当前运行库中所有字段的 SQL-null count 都是 0。下列四个 session fields 使用文本 sentinel 表示缺失。

为了让 schema 与真实数据可以直接对照，每个小节都附上当前运行库按 primary key 升序排列的前五行；
`products` 只有四行，因此展示全部四行。下列 values 未做格式转换。样例于 2026-11-16 从
`tmp/maven-analysis/maven_fuzzy.db` 读取，复现规则为：

```sql
SELECT * FROM <table> ORDER BY <primary_key> LIMIT 5;
```

### 6.1 `website_sessions`

**Grain：** 一行是一条 website session。共有 394,318 个 distinct users、394,318 条 new sessions 和 78,553
条 repeat sessions。一个 user 在数据中有 1–4 条 sessions。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `website_session_id` | INTEGER PK | 无缺失 | Session 唯一键；连接 pageviews 和 orders |
| `created_at` | TEXT | 无缺失 | Session start time；决定 session count、global filter options 和 funnel cohort |
| `user_id` | INTEGER | 无缺失；394,318 distinct | Logical customer identifier；没有单独的 customer table |
| `is_repeat_session` | INTEGER | 无缺失；0 或 1 | 直接生成 New/Repeat label |
| `utm_source` | TEXT | 83,328 个文本 `NULL`；其余为 `gsearch`、`bsearch`、`socialbook` | Raw paid-source tag；与 referrer 一起推导 traffic source |
| `utm_campaign` | TEXT | 83,328 个文本 `NULL`；其余为 `nonbrand`、`brand`、`desktop_targeted`、`pilot` | Raw campaign tag |
| `utm_content` | TEXT | 83,328 个文本 `NULL`；含 sentinel 共七种状态 | Raw ad-content tag |
| `device_type` | TEXT | 无缺失；`desktop` 或 `mobile` | Session device |
| `http_referer` | TEXT | 39,917 个文本 `NULL`；其余为 gsearch、bsearch 或 socialbook URL | 与 UTM source 一起区分 paid、organic、direct traffic |

实际 raw source/campaign/content 组合具有固定关系：gsearch 与 bsearch 使用 brand/nonbrand；socialbook 使用
desktop-targeted/pilot；未追踪 sessions 的三个字段均使用 sentinel。

**实际前五行：**

| `website_session_id` | `created_at` | `user_id` | `is_repeat_session` | `utm_source` | `utm_campaign` | `utm_content` | `device_type` | `http_referer` |
| ---: | --- | ---: | ---: | --- | --- | --- | --- | --- |
| 1 | 2012-03-19 08:04:16 | 1 | 0 | gsearch | nonbrand | g_ad_1 | mobile | https://www.gsearch.com |
| 2 | 2012-03-19 08:16:49 | 2 | 0 | gsearch | nonbrand | g_ad_1 | desktop | https://www.gsearch.com |
| 3 | 2012-03-19 08:26:55 | 3 | 0 | gsearch | nonbrand | g_ad_1 | desktop | https://www.gsearch.com |
| 4 | 2012-03-19 08:37:33 | 4 | 0 | gsearch | nonbrand | g_ad_1 | desktop | https://www.gsearch.com |
| 5 | 2012-03-19 09:00:55 | 5 | 0 | gsearch | nonbrand | g_ad_1 | mobile | https://www.gsearch.com |

### 6.2 `website_pageviews`

**Grain：** 一行是一次 pageview event。每个 session 至少有一条 pageview。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `website_pageview_id` | INTEGER PK | 无缺失；1–1,188,124 | Event key；递增 ID 用于判断 funnel 顺序 |
| `created_at` | TEXT | 无缺失 | Pageview time；当前不用于定义 funnel cohort window |
| `website_session_id` | INTEGER | 无缺失 | Logical many-to-one join 到 `website_sessions` |
| `pageview_url` | TEXT | 无缺失；16 个 distinct URLs | 访问页面；session 中最小 ID 定义 landing page；指定 URL 定义 funnel stages |

Funnel URL 包括 `/products`、四个 product-detail paths、`/cart`、`/shipping`、`/billing`、`/billing-2`
和 `/thank-you-for-your-order`。`/billing` 标为 Original，`/billing-2` 标为 Optimized。

**实际前五行：**

| `website_pageview_id` | `created_at` | `website_session_id` | `pageview_url` |
| ---: | --- | ---: | --- |
| 1 | 2012-03-19 08:04:16 | 1 | /home |
| 2 | 2012-03-19 08:16:49 | 2 | /home |
| 3 | 2012-03-19 08:26:55 | 3 | /home |
| 4 | 2012-03-19 08:37:33 | 4 | /home |
| 5 | 2012-03-19 09:00:55 | 5 | /home |

**全部 16 个 unique URLs：** 下表同时给出 pageview event 数和至少访问过该 URL 的 session 数。当前数据中，
每个 URL 在同一 session 内至多出现一次，所以两列恰好相等；代码不应把这一观察当作永久规则。

| `pageview_url` | Pageview events | Distinct sessions |
| --- | ---: | ---: |
| `/billing` | 3,617 | 3,617 |
| `/billing-2` | 48,441 | 48,441 |
| `/cart` | 94,953 | 94,953 |
| `/home` | 137,576 | 137,576 |
| `/lander-1` | 47,574 | 47,574 |
| `/lander-2` | 131,170 | 131,170 |
| `/lander-3` | 79,000 | 79,000 |
| `/lander-4` | 9,385 | 9,385 |
| `/lander-5` | 68,166 | 68,166 |
| `/products` | 261,231 | 261,231 |
| `/shipping` | 64,484 | 64,484 |
| `/thank-you-for-your-order` | 32,313 | 32,313 |
| `/the-birthday-sugar-panda` | 19,046 | 19,046 |
| `/the-forever-love-bear` | 26,033 | 26,033 |
| `/the-hudson-river-mini-bear` | 2,610 | 2,610 |
| `/the-original-mr-fuzzy` | 162,525 | 162,525 |

URL count 的复现查询：

```sql
SELECT pageview_url,
       COUNT(*) AS pageview_count,
       COUNT(DISTINCT website_session_id) AS session_count
FROM website_pageviews
GROUP BY pageview_url
ORDER BY pageview_url;
```

### 6.3 `orders`

**Grain：** 一行是一笔完成订单。当前数据中，每个 purchasing session 最多只有一笔 order。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `order_id` | INTEGER PK | 无缺失 | Order key；连接 items 和 refunds |
| `created_at` | TEXT | 无缺失 | Order event time；决定 order count、gross revenue、order COGS 和 AOV 的期间 |
| `website_session_id` | INTEGER | 无缺失；32,313 distinct | Logical one-to-zero/one join 到 attributed session |
| `user_id` | INTEGER | 无缺失；31,696 buyers | Buyer identifier；已验证与 joined session user 一致 |
| `primary_product_id` | INTEGER | 无缺失；1–4 | 订单的 primary product |
| `items_purchased` | INTEGER | 无缺失；1 或 2 | 订单中的 item 数；已验证与实际 line-item count 相等 |
| `price_usd` | REAL | 无缺失；29.99–109.98 | 退款前的整笔 order revenue |
| `cogs_usd` | REAL | 无缺失；9.49–41.98 | 整笔订单的 cost of goods sold |

**实际前五行：**

| `order_id` | `created_at` | `website_session_id` | `user_id` | `primary_product_id` | `items_purchased` | `price_usd` | `cogs_usd` |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2012-03-19 10:42:46 | 20 | 20 | 1 | 1 | 49.99 | 19.49 |
| 2 | 2012-03-19 19:27:37 | 104 | 104 | 1 | 1 | 49.99 | 19.49 |
| 3 | 2012-03-20 06:44:45 | 147 | 147 | 1 | 1 | 49.99 | 19.49 |
| 4 | 2012-03-20 09:41:45 | 160 | 160 | 1 | 1 | 49.99 | 19.49 |
| 5 | 2012-03-20 11:28:15 | 177 | 177 | 1 | 1 | 49.99 | 19.49 |

### 6.4 `order_items`

**Grain：** 一行是一笔订单中的一个 product line item。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `order_item_id` | INTEGER PK | 无缺失 | Item key；连接 refund events |
| `created_at` | TEXT | 无缺失 | Item purchase time；当前所有记录均与 order timestamp 相同 |
| `order_id` | INTEGER | 无缺失 | Logical many-to-one join 到 `orders` |
| `product_id` | INTEGER | 无缺失；1–4 | Logical many-to-one join 到 `products` |
| `is_primary_item` | INTEGER | 无缺失；0 或 1 | Primary 或 add-on role；每笔订单恰好有一个 primary item |
| `price_usd` | REAL | 无缺失；29.99–59.99 | 退款前的 item revenue |
| `cogs_usd` | REAL | 无缺失；9.49–22.49 | Item COGS |

**实际前五行：**

| `order_item_id` | `created_at` | `order_id` | `product_id` | `is_primary_item` | `price_usd` | `cogs_usd` |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2012-03-19 10:42:46 | 1 | 1 | 1 | 49.99 | 19.49 |
| 2 | 2012-03-19 19:27:37 | 2 | 1 | 1 | 49.99 | 19.49 |
| 3 | 2012-03-20 06:44:45 | 3 | 1 | 1 | 49.99 | 19.49 |
| 4 | 2012-03-20 09:41:45 | 4 | 1 | 1 | 49.99 | 19.49 |
| 5 | 2012-03-20 11:28:15 | 5 | 1 | 1 | 49.99 | 19.49 |

### 6.5 `order_item_refunds`

**Grain：** 一行是一个 item 的一次 refund event。当前数据中，一个 refunded item 最多有一次 refund event。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `order_item_refund_id` | INTEGER PK | 无缺失 | Refund-event key |
| `created_at` | TEXT | 无缺失 | Refund event time；决定 Refund-date metrics |
| `order_item_id` | INTEGER | 无缺失；1,731 distinct | Logical one-to-zero/one join 到 `order_items` |
| `order_id` | INTEGER | 无缺失；1,723 distinct | Denormalized order key；已验证与 item 所属 order 一致 |
| `refund_amount_usd` | REAL | 无缺失；29.99–59.99 | Item 的 refund dollars |

**实际前五行：**

| `order_item_refund_id` | `created_at` | `order_item_id` | `order_id` | `refund_amount_usd` |
| ---: | --- | ---: | ---: | ---: |
| 1 | 2012-04-06 11:32:43 | 57 | 57 | 49.99 |
| 2 | 2012-04-13 01:09:43 | 74 | 74 | 49.99 |
| 3 | 2012-04-15 07:03:48 | 71 | 71 | 49.99 |
| 4 | 2012-04-17 20:00:37 | 118 | 118 | 49.99 |
| 5 | 2012-04-22 20:53:49 | 116 | 116 | 49.99 |

### 6.6 `products`

**Grain：** 一行是一个 catalog product。

| Field | Type | 缺失情况 / domain | 业务含义与用途 |
| --- | --- | --- | --- |
| `product_id` | INTEGER PK | 无缺失；1–4 | Product key |
| `created_at` | TEXT | 无缺失 | Product launch timestamp；当前不作为 dashboard filter |
| `product_name` | TEXT | 无缺失；四个名称 | Product reporting 中使用的 display name |

四个商品为 The Original Mr. Fuzzy、The Forever Love Bear、The Birthday Sugar Panda 和
The Hudson River Mini bear。

**实际全部四行：**

| `product_id` | `created_at` | `product_name` |
| ---: | --- | --- |
| 1 | 2012-03-19 08:00:00 | The Original Mr. Fuzzy |
| 2 | 2013-01-06 13:00:00 | The Forever Love Bear |
| 3 | 2013-12-12 09:00:00 | The Birthday Sugar Panda |
| 4 | 2014-02-05 10:00:00 | The Hudson River Mini bear |

## 7. 表之间如何连接？哪里容易重复计算？

```text
website_sessions（一条 session）
  ├──< website_pageviews（每条 session 有 1–7 条 pageviews）
  └──0..1 orders（当前数据中每条 session 最多一笔订单）
          └──< order_items（每笔订单有 1–2 个 items）
                  ├──> products（每个 item 对应一个 product）
                  └──0..1 order_item_refunds（每个 item 最多一次 refund）
```

`user_id` 在 sessions 与 orders 中重复出现，是 logical identifier，但没有 customer dimension table。

| Relationship | 实际 cardinality | Integrity check | 最重要的 duplication risk |
| --- | --- | --- | --- |
| Session → pageviews | 1 对 1–7；平均 2.513 | 每条 session 都有 pageview；0 orphan pageviews | 如果将 order amount 直接 join 到 pageviews，revenue 会被重复多次 |
| Session → orders | 1 对 0–1 | 0 orphan orders；session/order user ID 一致 | 当前数据最多一单，但代码不应把它当作所有电商数据的永久规则 |
| Order → items | 1 对 1–2；平均 1.239 | Item count、revenue、COGS 与 order totals 完全 reconcile | 如果将 order totals join 到 items，多商品订单会重复 order revenue |
| Product → items | 1 对多 | 0 orphan product IDs | Product metrics 必须在 item grain 聚合 |
| Item → refunds | 当前为 1 对 0–1 | 0 orphan refunds；refund order ID 与 item order ID 一致 | 如果先 join refund 再算 sold-item denominator，可能改变分母 |

以下检查均为 0 failures：

- pageview timestamp 早于 session；
- order timestamp 早于 session；
- refund timestamp 早于 purchase；
- item timestamp 与 order timestamp 不同；
- 订单没有且仅有一个 primary item；
- `primary_product_id` 与 primary item 不一致；
- item count、order/item revenue、order/item COGS 无法 reconcile。

全部 32,313 个 order sessions 都有且仅有一个 `/thank-you-for-your-order` pageview；每个 thank-you session
也都有 order。这是当前 dataset property，但正式 order metric 仍以 `orders` table 为准。

## 8. 原始字段如何变成业务维度？

### 8.1 Traffic source

| Business label | 推导规则 |
| --- | --- |
| Paid Search | normalized `utm_source` 为 `gsearch` 或 `bsearch` |
| Paid Social | normalized `utm_source` 为 `socialbook` |
| Organic Search | normalized source 缺失、normalized referrer 存在 |
| Direct | normalized source 和 referrer 都缺失 |
| Other | 其他状态 |

Normalization 会将 SQL `NULL` 和文本 `"NULL"` 都当作缺失。

### 8.2 Referrer type

| Label | 推导规则 |
| --- | --- |
| Paid | normalized UTM source 存在 |
| Organic | normalized UTM source 缺失、referrer 存在 |
| Direct | 两者都缺失 |

### 8.3 Landing page 与 Session type

- Landing page = 一条 session 中 `website_pageview_id` 最小的 pageview。
- New/Repeat 直接使用 `is_repeat_session`，不是根据 user 的 session 顺序重新计算。

## 9. 每个 Metric 到底怎么算？

### 9.1 Executive 与 Acquisition metrics

| Metric | 公式 | 聚合前 grain | Date owner | 页面 / function | 注意事项 |
| --- | --- | --- | --- | --- | --- |
| Sessions | count session rows | Session | `website_sessions.created_at` | 所有页面 / `overview_kpis` | 计算 visits，不是 users |
| Orders | count order rows | Order | `orders.created_at` | Executive、Acquisition / `overview_kpis`、`acquisition_performance` | Acquisition attributes 来自原始 session |
| Gross revenue | sum `orders.price_usd` | Order | `orders.created_at` | Executive / `overview_kpis`、`overview_trend` | 不能在 pageview/item fan-out 后直接相加 |
| Conversion rate | Orders / Sessions | Order 与 session 分别先聚合 | Orders 使用 order time；Sessions 使用 session time | Executive、Acquisition | 属于 event-period rate，不是 experiment，也不是严格 session cohort；全数据仅六笔 order 跨月 |
| AOV | Gross revenue / Orders | Order | `orders.created_at` | Executive | 基于 gross order revenue |
| Order COGS | sum `orders.cogs_usd` | Order | `orders.created_at` | Executive | Product reporting 改用 item COGS |
| Gross margin | Gross revenue − order COGS | Order | `orders.created_at` | Executive、Acquisition | Executive 选 Net 时还会减去该期间的 refund dollars |
| Revenue/session | Gross revenue / Sessions | Orders、sessions 分别聚合 | 混合上述两个时间口径 | Acquisition | 不是 ROAS，因为没有 ad spend |
| Margin/session | Gross margin / Sessions | Orders、sessions 分别聚合 | 同上 | Acquisition | 数据不含 COGS 之外的 product/refund costs |

同一 period/filter 下的精确 algebraic decomposition：

```text
Gross revenue
= Sessions × (Orders / Sessions) × (Gross revenue / Orders)
= Sessions × Conversion rate × AOV
```

这是 accounting identity，不代表其中一个 factor 的变化因果上导致了另一个 factor。

### 9.2 Refund 与 Net metrics

| Metric | 公式 | Date owner / basis | 注意事项 |
| --- | --- | --- | --- |
| Refund amount | sum `refund_amount_usd` | Executive 和 Refund-date view 使用 refund-event time | Refund 可能对应更早销售；source/device attribution 来自原 order session |
| Net revenue | 期间内 gross order revenue − 期间内记录的 refund events | 混合 order-event 与 refund-event periods | 不是 same-purchase cohort metric |
| Executive refund rate | 期间内 refund events / 期间内 sold items | 混合 refund-event 与 item-purchase periods | 分子分母不一定来自同一批商品 |
| Product refund rate，Purchase date | Purchase-period cohort 中后来退款的 items / 该期间 sold items | Item purchase time | 可以包含 displayed period 之后发生的 refund |
| Product refund rate，Refund date | 期间内 refund events / 同一 displayed period 内购买的 items | 混合 event periods | UI 会明确提示 denominator |

因为 date basis 回答的是不同问题，每个 agent tool 和 report 都必须明确写出所选 basis。

### 9.3 Funnel metrics

Funnel 先选择在 period 内创建的 sessions，再查看这些 sessions 的全部 pageviews。每一个 stage 的第一条匹配
pageview ID 必须大于上一 stage 的 ID：

```text
Landing → Products → Product detail → Cart → Shipping → Billing → Thank-you
```

| Metric | 公式 |
| --- | --- |
| Stage reach | 到达该 ordered stage 的 selected sessions 数量 |
| Step conversion | 当前 stage reach / 上一个 stage reach |
| Total conversion | 当前 stage reach / landing sessions |
| Drop-off | 上一个 stage reach − 当前 stage reach |
| Funnel final conversion | thank-you reach / landing sessions |

Funnel 描述 observed navigation，不能证明用户为什么流失，也不能证明某个 page version 导致 conversion change。

### 9.4 Product 与 Basket metrics

| Metric | 公式 | Grain / date owner | 注意事项 |
| --- | --- | --- | --- |
| Product units | count item rows | Item / `order_items.created_at` | Multi-item order 会贡献多个 units |
| Product revenue | sum `order_items.price_usd` | Item / item purchase time | 全部 items 合计后与 order revenue 完全 reconcile |
| Product COGS | sum `order_items.cogs_usd` | Item / item purchase time | 全部 items 合计后与 order COGS 完全 reconcile |
| Product gross margin | Item revenue − item COGS | Item / item purchase time | 退款前 margin |
| Product net revenue | Item revenue − 按所选 basis 匹配的 refund amount | Item + refund | 已计算，但目前不能作为 chart selector |
| Attachment rate | Add-on item units / selected product units | Item | 不是“包含 add-on 的 orders 占比” |
| Basket mix | 将 orders 分为 1 item 与 >1 item | Order / `orders.created_at` | 当前数据只有 1-item 或 2-item orders |

## 10. 四个跨表计算例子

这些例子说明有效的 computation path，不是已经冻结的 gold answers。

### Example A — Gross revenue movement

```text
website_sessions
  → 统计 selected month 和 session filters 下的 sessions

orders
  → 按 order timestamp 统计 orders
  → 加总 order-level price_usd

Gross revenue = Sessions × (Orders / Sessions) × (Gross revenue / Orders)
```

如果 revenue 下跌而 sessions 基本不变，剩余变化在代数上必须由 conversion 和/或 AOV 解释。但数据仍不能告诉我们
conversion 或 AOV 为什么变化。

### Example B — Acquisition localization

```text
website_sessions.utm_source / http_referer / campaign / device
  → normalized business segment
  → 通过 website_session_id join zero-or-one order
  → 按 segment 聚合 sessions、orders、gross revenue、margin
```

这条路径可以比较不同 segment 的 measured values。未来 contribution tool 必须比较 current 与 prior segment
values；仅按 current revenue 排名是不够的。

### Example C — Conversion branch through the Funnel

```text
selected month 中的 website_sessions
  → 按 pageview ID 排序 website_pageviews
  → 找到每个 ordered stage 的第一次有效到达
  → 计算 stage reach、step conversion、total conversion、drop-off
```

较低的 thank-you rate 可以定位到某个 stage transition，但不能直接说是 page design、latency、inventory、price
或其他 operational factor 导致。

### Example D — AOV 与 Product-mix branch

```text
orders
  → order revenue 与 items_purchased
  → order_items 中的 product 和 primary/add-on role
  → products 中的 display name
  → 按 purchase/refund date basis 连接 order_item_refunds
```

当前数据中的 order totals 与 item totals 完全 reconcile。因此可以把 order-level AOV change 描述性地定位到
product price、unit mix 或 multi-item basket mix，但不能解释顾客为什么选择了这种组合。

## 11. 数据能回答什么？不能回答什么？

### 11.1 数据支持回答

- Gross/net revenue、orders、sessions、conversion、AOV、margin 或 refunds 是否发生变化？
- 哪个 measured traffic source、campaign、device、session type、ad content、referrer type 或 landing page 与
  segment difference 相关？
- 最大的 measured funnel drop-off 出现在哪个 transition？
- 哪些 products、item roles 和 basket sizes 与 measured revenue、margin、units、refund differences 相关？
- Purchase-date 与 Refund-date views 有什么不同？

### 11.2 数据不能支持为 causal conclusion

- 用户为什么放弃某个页面；
- campaign 是否盈利，因为没有 spend；
- A/B test 是否导致变化、是否 statistically significant，因为没有 assignment/exposure；
- 商品为什么被退款；
- Inventory、fulfillment、shipping delay、site latency、technical outage 或 support quality；
- Competitor、market、seasonality cause、customer demographics 或 geography；
- 完整 profit、CAC 或 ROAS；
- 六张表中不存在的任何 external 或 operational cause。

这些内容只能标记为 hypothesis 或 missing-evidence question，不能写成 established fact。

## 12. 已确认的 Gaps 与 Risks

### 12.1 当前数据库与重建库的 Missing-value 表示不同

当前数据库在每个 UTM field 中保存 83,328 个文本 `"NULL"`，在 `http_referer` 中保存 39,917 个文本
`"NULL"`。使用当前 builder 临时重建后，这些值变成 SQL `NULL`。

两份数据库的六张表行数相同，May/June 2014 Executive KPI 结果也完全一致，因此当前 query layer 能兼容两种表示。
但两份 database 并非 byte-identical；Milestone 2 必须选择并记录 canonical representation，才能声称 clean-build
完全可复现。

### 12.2 还没有 Typed Dashboard Context

各项 state 已存在，但还没有小型、versioned context schema。Agent 不能读取 arbitrary Streamlit state。

### 12.3 还没有真正的 Change-contribution Calculation

当前 charts 主要排序 current-period values。Milestone 4 必须增加 deterministic prior/current deltas 和
contribution ranking，agent 才能将一个 segment 称为 measured driver of change。

### 12.4 Date-basis 容易混淆

Session、order、item、refund metrics 分别由不同 timestamps 决定。除非明确选择 purchase cohort，net 和 refund-rate
metrics 会混合不同 event periods。

### 12.5 最后一个月份不完整

March 2015 的 sessions/orders 不完整，refund events 则延伸到 April。Agent 必须显示 data-through 和
partial-period status，不能把不完整月份当作完整月份比较。

## 13. 获批的第一条 Midpoint Investigation Path

用户于 2026-11-16 完成数据与 Dashboard review 后批准以下 midpoint 流程：

```text
1. Executive Overview 验证 selected gross-revenue change。
2. Deterministic code 将其拆成 sessions、conversion rate 和 AOV。
3. Deterministic segment deltas 按 measured business impact 排名。
4. 如果 conversion 的变化重要，继续检查 ordered funnel 与 acquisition segments。
5. 如果 AOV 的变化重要，继续检查 product mix、item role 与 basket size。
6. 如果 Net 与 Gross 差异明显，先说明 refund date basis，再检查 refund exposure。
7. 验证 reconciliation，列出 unknowns，然后停止。
```

这条 path 对 midpoint 足够窄，同时保留了以后扩展 refund investigation、experiment analysis 和更广问题类型的接口。

## 14. 用户确认的九项

下列内容已在逐表和逐指标 walkthrough 后由用户于 2026-11-16 确认；这项批准允许进入 ground-truth
calculation，但 exact gold values 仍需在 Milestone 3 审核：

- [x] Executive Overview 是 month-over-month investigation 的主入口。
- [x] Gross revenue 使用 order event time 和 order-level `price_usd`。
- [x] Conversion rate 使用当前展示的 event-period `orders / sessions`，并接受上述 timestamp caveat。
- [x] AOV = gross order revenue / orders。
- [x] Executive Net revenue 减去 selected period 内记录的 refund events。
- [x] Refund rate 必须始终说明使用 Purchase-date 还是 Refund-date semantics。
- [x] Current-period segment ranking 不能当作 change contribution。
- [x] Funnel 只能作为 descriptive ordered-pageview evidence，不能声称 causality。
- [x] 第 13 节是获批的 midpoint 第一条 investigation path。

Milestone 1 review gate 已关闭。下一数据步骤是独立计算、呈现并审核 gold values 和 held-out cases。
