# mealflow-ai

#### 介绍
面向政府机关食堂的运营决策 Agent：根据人数、库存、饮食限制、成本和公共自助终端反馈，编排工具生成可解释的菜单与采购方案；底层保留个人工作区的扩展能力。

V1 的国庆后演示以 Agent 决策为主，管理页面只提供数据与执行能力。核心证据是自然语言约束理解、真实工具编排、三方案取舍、What-if 重规划、人工确认、反馈闭环和模型故障降级。

#### 项目档案

当前产品定义以 [产品定稿方案](docs/产品定稿方案.md)、[Agent 设计](docs/Agent设计.md)、[技术开发文档](docs/技术开发文档.md) 和 [国庆 3–4 天开发计划](docs/三天开发计划.md) 为准；[原始家庭版项目档案](docs/项目档案.md) 仅作历史参考。

产品范围、用户、业务闭环、政务场景要求和阶段路线见 [产品定稿方案](docs/产品定稿方案.md)。


#### 开发状态

项目已完成 V1 底层框架：FastAPI/SQLite 后端、LangGraph 状态骨架、云端模型 Provider 边界、确定性规则工具、Vue 3 管理端、Agent 轨迹与三方案页面、What-if 接口和公共 PC Kiosk。当前 Agent API 使用可运行的规则基线；填入模型配置后应将约束解析节点替换为真实千问调用。

V1 模型策略已冻结：通过 API 调用千问主模型，DeepSeek 作为备用，智谱作为验证后可替换候选；V1 不进行本地模型部署，V2/V3 再逐步完善模型工程化与私有化评估。

#### 文档入口

- [V1 Agent 价值与演示口径（答辩必读）](docs/V1-Agent价值与演示口径.md)
- [MVP 验收标准](docs/mvp.md)
- [接口契约](docs/api.md)
- [数据字典与种子数据规范](docs/数据字典.md)
- [部署与运行手册](docs/部署与运行.md)
- [演示脚本](docs/demo-script.md)
- [安全与隐私说明](docs/安全与隐私.md)
- [贡献与协作指南](docs/贡献指南.md)
- [B/C 双端与多租户设计](docs/多租户产品设计.md)
- [V1 之后的迭代路线](docs/国庆后演示扩展计划.md)
- [Agent 设计](docs/Agent设计.md)
- [公共 PC 自助评分终端设计](docs/评分终端设计.md)
- [模型选型与部署策略](docs/模型选型与部署策略.md)
- [产品定稿方案](docs/产品定稿方案.md)

#### 安装与使用

要求 Python 3.12/3.13 与 Node.js 20+。从仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\apps\api[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir apps/api
```

另开终端启动前端：

```powershell
Set-Location apps/web
npm install
npm run dev
```

入口：管理员 Agent `http://localhost:5173/admin/agent`，公共终端 `http://localhost:5173/kiosk`，API 文档 `http://localhost:8000/docs`。

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest apps/api -q
Set-Location apps/web
npm run typecheck
npm run build
```
#### 参与贡献

1.  Fork 本仓库
2.  新建 Feat_xxx 分支
3.  提交代码
4.  新建 Pull Request
