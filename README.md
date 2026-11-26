# 商品价格监控采集平台

面向多区域站点的商品价格抓取、规格归一、比价计算与变价告警的采集治理平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/routers/review_workbench.py  复核认领工作台专用接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/review_workbench.py 候选证据版本/认领单/结论回填闭环
│   ├── app/services/base.py     共享服务骨架
│   ├── app/scenario_seed.py     认领闭环剧本数据（6 条候选与证据版本）
│   ├── app/store.py          内存数据仓库与示例数据
│   └── tests_scenario_e2e.py 认领闭环端到端剧本复做（.venv/bin/python -I 运行）
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8020/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5200/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8020`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集站点目录 | `shop_site` | 站点配置 | 站点名称、站点域名、采集区域 |
| 价格爬取任务 | `price_crawler` | 爬取任务 | 任务名称、目标站点、商品关键词 |
| 页面解析模板 | `page_parser` | 解析模板 | 模板名称、适用站点、选择器路径 |
| 规格归一器 | `spec_normalizer` | 规格归一规则 | 规则名称、源规格文本、归一规格 |
| 货币换算器 | `currency_conv` | 汇率快照 | 快照日期、源货币、目标货币 |
| 价格基线库 | `price_baseline` | 价格基线 | 商品标识、归一规格、基线价格 |
| 比价计算器 | `price_compare` | 比价结果 | 比价批次、商品标识、最低价站点 |
| 变价告警规则 | `price_alert` | 告警规则 | 规则名称、监控商品、价差阈值 |
| 商品登记中心 | `goods_registry` | 商品档案 | 商品标识、商品名称、品牌 |
| 规格匹配器 | `sku_match` | 匹配记录 | 匹配批次、商品档案、候选规格 |
| 页面样本库 | `sample_store` | 页面样本 | 样本批次、站点名称、原始HTML摘要 |
| 解析质量审计 | `parse_audit` | 审计明细 | 审计时间、解析模板、样本总数 |
| 采集调度计划 | `crawl_schedule` | 调度计划 | 计划名称、关联任务、调度周期 |
| 抓取频控 | `rate_limit` | 频控规则 | 规则名称、目标站点、每分钟上限 |
| 代理线路池 | `proxy_route` | 代理线路 | 线路标识、线路区域、可用性评分 |
| 失败隔离区 | `failure_quarantine` | 隔离记录 | 样本指纹、失败阶段、失败原因 |
| 比价导出通道 | `price_export` | 导出任务 | 任务名称、商品范围、导出格式 |
| 变价历史流水 | `change_history` | 变价记录 | 商品标识、旧价格、新价格 |
| 人工复核队列 | `match_review` | 复核记录 | 记录编号、匹配记录、复核结论 |
| 采集量指标 | `collect_metrics` | 指标记录 | 统计时间、站点名称、抓取量 |

## 人工复核认领工作台

入口：前端导航「复核认领工作台」（路由 `/review-workbench`），后端前缀 `/api/review-workbench`。

闭环：候选证据版本（`candidate_evidence`）→ 复核队列匹配清单（`match_review`，每条带
证据版本与归一规格）→ 批量认领生成认领单（`claim_order`，逐条判定资格）→ 取得有效资格的
条目提交结论 → 规格匹配器（`sku_match`）按「匹配记录 id + 证据版本」只回填这条可对账结果。

关键规则：

- 候选结果按证据版本、候选归一规格筛选并分页；重新获取只返回仍待复核、证据有效且仍满足
  规格的条目，已确认或证据撤回的条目不进入交付范围。
- 同一待复核匹配只能由一个复核员取得有效资格；证据版本被撤回的条目进入「等待重确认」，
  重确认不通过则转「未取得资格」，均不能写回；无复核资格角色直接未取得资格。
- 旧证据版本撤回时记录失效原因与替换去向；通用资源路由的通过/驳回动作同样受认领资格闸门约束。

剧本复做（6 条候选、每页 4 条，第二页为 R1/R3；R1 随后被更正为两瓶组合装 R2）：

```bash
cd backend
.venv/bin/python -I tests_scenario_e2e.py
```

也可在页面点「模拟上游更正 R1」「批量认领」「重新确认」「提交通过/驳回」逐步复做，
点「复位剧本」回到初始快照。

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

领域：数据工程
子方向：数据采集、爬虫与RPA
