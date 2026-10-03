# API 契约（MVP）

基础路径为 `/api/v1`，JSON 使用 UTF-8。成功响应直接返回对象或 `{ "items": [], "meta": {} }`；错误统一为 `{ "code": "VALIDATION_ERROR", "message": "输入不合法", "details": [] }`。

| 方法 | 路径 | 请求重点 | 响应重点 |
| --- | --- | --- | --- |
| GET/PUT | `/workspaces/{id}/profile` | 食堂档案、用餐限制、厨房条件 | 完整食堂档案 |
| GET/POST | `/workspaces/{id}/inventory` | `ingredient_id, quantity, unit, expires_on` | 库存项，含 `freshness_status` |
| PATCH/DELETE | `/inventory/{id}` | 可改数量、购买/到期日 | 更新后的库存项 / 204 |
| GET | `/recipes` | `q, max_minutes, tags` | 菜谱摘要列表 |
| GET | `/recipes/{id}` | — | 食材、步骤、时长、来源 |
| POST | `/agent/runs` | 自然语言需求与餐次 | 创建 Agent 运行，返回结构化约束与运行 ID |
| GET | `/agent/runs/{id}` | — | 当前状态、结构化约束、工具轨迹、警告、三种菜单方案与审批状态 |
| POST | `/agent/runs/{id}/revise` | 人数、预算、替代食材等变更 | 基于当前状态 What-if 重规划 |
| POST | `/meal-plans/preview` | 餐次、预计人数，见下例 | 多种菜单、约束、热量、分数、采购缺口 |
| POST | `/meal-plans` | preview 的确认结果 | 已保存菜单 |
| POST | `/meal-plans/{id}/publish` | — | 已发布菜单 |
| GET | `/kiosk/current-menu` | 公共 PC 设备令牌 | 当前绑定站点与餐次的已发布菜单 |
| POST | `/kiosk/feedback` | 设备令牌、评分、标签、可选备注、幂等键 | 匿名反馈记录与重置等待时间 |
| GET | `/feedback/summary` | 工作区、餐次 | 聚合评分、标签、备注摘要与剩余等级 |

菜单预览请求：

```json
{"workspace_id":"uuid","site_id":"uuid","meal_service_id":"uuid","date":"2026-10-04","expected_diners":120,"budget_limit_cents":90000,"time_limit_minutes":90,"preference_text":"清淡，优先临期番茄，不能含花生"}
```

关键响应字段：

```json
{"constraints_applied":["花生过敏","清淡"],"options":[{"strategy":"expiring_first","items":[{"recipe_id":"uuid","name":"番茄鸡蛋汤","estimated_kcal_per_serving":118,"score":0.86,"score_breakdown":{"expiring":0.4,"time":0.2}}],"estimated_cost_cents":83600,"warnings":[]}],"procurement_list":[{"ingredient":"小葱","required_quantity":"2.4kg","available_quantity":"0g","missing_quantity":"2.4kg"}]}
```

Agent Run 必须具有明确状态：`PARSING`、`RUNNING_TOOLS`、`BUILDING_OPTIONS`、`WAITING_APPROVAL`、`PUBLISHED`、`FALLBACK`、`FAILED`。`tool_trace` 每项至少返回 `tool_name`、`status`、`duration_ms`、`input_summary`、`output_summary` 和 `error_code`；摘要不得包含密钥、完整提示词或原始敏感备注。What-if 请求必须引用原 `agent_run_id`，并返回重新执行的节点和前后差异，不能伪装成无状态的新对话。

管理员写操作须校验资源所属工作区与角色。公共 PC 自助终端使用独立、受限的设备令牌，只能读取当前已发布菜单并提交匿名反馈，不能调用管理端或 Agent 接口。发布接口要求 Agent run、选中方案和管理员确认状态，并使用 `Idempotency-Key`。V1 不提供干部职工手机端和员工账号接口。
