# 帧序 Creator Workbench · 0.2

已增加 LangGraph + Deep Agents 真实主管委派、19 个独立专家包、独立评审与返工、持久检查点、运行轨迹和人工采纳。文字 Agent 默认只开放明确标记的测试模型，不调用付费模型。N27 已增加独立的本机 ComfyUI 视频候选连接器，使用与限制见 [本机 ComfyUI 连接器](docs/22-comfyui-local-connector.md)；其他外部工具仍仅有接入文档。

首次运行请按 [0.2 安装与运行说明](docs/20-multi-agent-runtime.md) 安装 Python 运行服务，然后使用 `scripts/start-local.ps1`。入口：`http://127.0.0.1:5178/runs`。

- [19 个专家包与专业验收](docs/19-agent-specialist-blueprints.md)
- [49 节点执行矩阵](docs/20-node-agent-migration-matrix.md)
- [实施方案及后续生产目标](docs/18-multi-agent-implementation-plan.md)

以下保留原有工作台说明。

# 创作操作台 Creator Workbench

> 首个可运行版本 0.1 · 2026-10-26 · 面向独立内容创作者的智能制作与发布管理工作台。

以下为 0.1 历史说明；当前实现与边界以 0.2 和本机 ComfyUI 连接器说明为准。原设计文档与历史实现范围分开记录，详见 [运行与实现状态](docs/14-running-and-implementation.md)。

## 立即运行

需要 Node.js 22.6+、Java 21+。依赖安装与后端构建后，在项目根目录执行：

```powershell
.\scripts\start-local.ps1
```

访问 http://127.0.0.1:5178/。后端默认 H2 文件数据库，MySQL 配置可选；本次未联调 MySQL。停止使用 `.\scripts\stop-local.ps1`。首次构建、手工启动、存储位置和能力边界见 [运行说明](docs/14-running-and-implementation.md)。

## 产品目标

把想法、定位、选题、证据、脚本、分镜、素材制作、剪辑、包装、发布、反馈、复盘、资产与经营连接成完整工作流。覆盖原始 **49 个活动业务节点**，允许 Agent 自动推进，并在关键节点由人拍板。用户拥有多个模型，模型和供应商都可选、可配、可替换；远端执行工具以协议接入。

本轮改动：顶部全局模型与局部继承、N01 退役归档、任务删除/恢复、流程作品上下文。详见 [交互与兼容调整](docs/17-workflow-update.md)。Agent 团队目前是角色配置，不是真正多 Agent 执行，详见 [实际实现与协作设计](docs/16-agent-implementation.md)。

## 阅读顺序

| 文档 | 用途 |
| --- | --- |
| [产品与范围](docs/01-product-and-scope.md) | 需求、边界、模式、默认假设、交付阶段 |
| [49 个活动节点目录](docs/02-node-catalog.md) | 逐节点输入、输出、分工、依赖、验收与返工 |
| [工作流与 Agent](docs/03-workflow-and-agents.md) | DAG、人工拍板、状态机、自动化、局部返工 |
| [模型选择与配置](docs/04-model-configuration.md) | 多供应商、多协议、能力、参数、路由、回退 |
| [系统架构](docs/05-system-architecture.md) | 前后端模块、任务执行、外部 Worker、工程结构 |
| [数据模型与接口](docs/06-data-model-and-api.md) | 实体、索引、事务、接口、异步事件和错误 |
| [界面与交互](docs/07-interface-and-interaction.md) | 全部页面、模型选择、工作区、审片与异常状态 |
| [外部工具接入流程](docs/08-external-integration.md) | 外部工具协议、步骤与验收；本机 ComfyUI 已有受限连接器 |
| [安全、成本和质量](docs/09-security-cost-and-quality.md) | 凭据、预算、来源、质检、评测和日志 |
| [开发计划与验收](docs/10-implementation-and-acceptance.md) | 分阶段开发、49 个活动节点覆盖、端到端验收 |
| [异机部署与交接](docs/11-deployment-and-handover.md) | 控制端/执行端分离、数据迁移和交接清单 |
| [来源与决策记录](docs/12-sources-and-decisions.md) | 官方资料、设计取舍、待实施时验证的事项 |
| [智能自动化机制](docs/13-intelligent-automation.md) | 自然语言计划、角色提示词、上下文、工具边界和解释 |
| [运行与实现状态](docs/14-running-and-implementation.md) | 当前实际功能、启动、数据库与尚未实现的能力 |
| [本次实现验收](docs/15-verification.md) | 已通过的测试、视觉检查与未验证范围 |
| [Agent 真实实现](docs/16-agent-implementation.md) | 当前规则与角色配置、真正多 Agent 协作还缺哪些执行能力 |
| [本轮交互与兼容调整](docs/17-workflow-update.md) | 全局模型、49 活动节点、任务删除/恢复、作品上下文与 27 项验收 |

## 配套规格

- `specs/nodes.json`：49 个活动节点的规范来源；节点说明由它生成。
- `specs/agents.json`：19 种逻辑职责，首版组合成 6 个工作单元。
- `specs/capabilities.json`：25 类能力标签；不等于必须部署 25 个模型。
- `specs/gates.json`：6 个拍板节点及其版本绑定。
- `specs/workflow-templates.json`：口播、录屏解说、AI 故事三类模板。
- `specs/schemas/`：节点、模型配置、产物信封的 JSON Schema。
- `examples/`：仅用于设计说明的配置与数据，外部地址使用 `.invalid`，不含密钥。

## 当前如何验证

用 Python 3 标准库执行文档检查，无需安装第三方依赖：

```powershell
python scripts/validate_docs.py
python scripts/render_node_catalog.py --check
```

上述是文档检查。应用检查为 `frontend` 内的 `npm test`、`npm run build`、`npx playwright test`，以及 `backend` 内的 `mvn test`。本机 ComfyUI 的使用与限制见 [连接器说明](docs/22-comfyui-local-connector.md)；真实供应商、MySQL 和真实发布尚未联调。

## 实施原则

1. 全流程覆盖，逐步自动化；未接入的节点保留人工交付入口。
2. 产物、状态、确认记录进入数据库；聊天记录只辅助沟通。
3. 模型选择可覆盖，运行配置不可变；同一任务的实际调用可追溯。
4. 生成成功不等于采用；技术检查、内容审阅、发布授权分别管理。
5. ComfyUI 在目标机器部署；本机视频候选已接入，其他外部工具仍只定义接入方法。
6. 未确认供应商、硬件、价格和账号权限时不假定可用。
