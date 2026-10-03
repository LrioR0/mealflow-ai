# API 契约（MVP）

基础路径为 `/api/v1`，JSON 使用 UTF-8。成功响应直接返回对象或 `{ "items": [], "meta": {} }`；错误统一为 `{ "code": "VALIDATION_ERROR", "message": "输入不合法", "details": [] }`。

| 方法 | 路径 | 请求重点 | 响应重点 |
| --- | --- | --- | --- |
| GET/PUT | `/workspaces/{id}/profile` | 食堂档案、用餐限制、厨房条件 | 完整食堂档案 |
| GET/POST | `/workspaces/{id}/inventory` | `ingredient_id, quantity, unit, expires_on` | 库存项，含 `freshness_status` |
| PATCH/DELETE | `/inventory/{id}` | 可改数量、购买/到期日 | 更新后的库存项 / 204 |
| GET | `/recipes` | `q, max_minutes, tags` | 菜谱摘要列表 |
| GET | `/recipes/{id}` | — | 食材、步骤、时长、来源 |
| POST | `/meal-plans/preview` | 餐次、预计人数，见下例 | 菜单、约束、分数、采购缺口 |
| POST | `/meal-plans` | preview 的确认结果 | 已保存菜单 |
| POST | `/meal-plans/{id}/publish` | — | 已发布菜单 |
| POST | `/meal-plans/{item_id}/feedback` | `status, rating?, actual_minutes?` | 反馈记录 |
| POST | `/agent/chat` | `workspace_id, message` | 规则结果上的解释；可流式 |

菜单预览请求：

```json
{"workspace_id":"uuid","site_id":"uuid","meal_service_id":"uuid","date":"2026-10-01","expected_diners":120,"time_limit_minutes":90,"preference_text":"清淡，优先临期番茄"}
```

关键响应字段：

```json
{"constraints_applied":["花生过敏","清淡"],"items":[{"recipe_id":"uuid","name":"番茄鸡蛋汤","score":0.86,"score_breakdown":{"expiring":0.4,"time":0.2},"uses_expiring_ingredients":["番茄"]}],"shopping_list":[{"ingredient":"小葱","required_quantity":"2.4kg","available_quantity":"0g","missing_quantity":"2.4kg"}]}
```

写操作须校验资源所属工作区与身份角色。MVP 暂不实现登录时，开发环境仅允许切换预置 `manager`、`member` 身份；上线前不得把此临时行为保留为权限方案。
