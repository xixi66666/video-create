> 更新：专家离线计算工具、主管与评审独立配置及未完成项见 项目中的 `docs/27-expert-capability-gaps.md`。

# 0.2 多 Agent 运行实现与使用

本版在原有 Vue / Spring Boot 工作台上增加 Python 运行服务。**主管确实通过 Deep Agents 的 `task` 工具调用独立专家，评审由另一个 Agent 执行；LangGraph 管理返工和人工暂停。默认仅开放测试模型，未调用付费模型。**

## 一次协作如何运行

1. 在作品中选择节点，点“启动 Agent 协作”，进入带作品和节点上下文的“协作运行”。
2. Java 重新检查依赖和人工拍板，固定创作档案、作品简报、依赖产物、当前草稿、审批及三方模型配置。任务与投递意图一起写入 `agent_run`。
3. 定时 outbox 向内部 FastAPI 投递相同运行 ID。网络失败保留意图，不创建新 ID。Python 持久检查幂等键与请求，固定当时的 Skill、知识、Prompt 和校验和。
4. 外层 LangGraph 的 delegate 节点创建 Deep Agents 主管。主管只能通过 `task` 委派当前节点专家；不能代写候选或批准发布。
5. 专家有独立消息上下文和内存文件系统，强制读取自己的 Skill、知识、任务输入，再调用 `submit_candidate` 提交结构化候选。没有主机文件、Shell、网络搜索、发布等权限。
6. 独立评审根据输入、节点标准和候选调用 `submit_review`。REVISE 回到专家，最多返工一次；PASS 进入 LangGraph `interrupt` 等待人工采纳。
7. 你采纳时，Java 重新计算输入指纹、检查业务依赖和审批。草稿或输入变化会拒绝过期候选。采纳事务只写草稿，不标记完成；采纳决定通过 outbox 同步给检查点。重复点击不会重复写入。
8. 核对真实材料后，在作品节点中标记完成；六个人工拍板仍由人完成。当前按节点执行，不跨审批自动连续推进。

可选邀请最多六名会诊专家，按选择顺序串行运行并共享调用次数和时间预算；角色可继承各自的模型配置。多人会诊的新运行提供带原意见引文的模型对照，系统只核对引文出处，分歧和事实仍由人工判断。详情见 [会诊与能力边界](27-expert-capability-gaps.md)。

## 运行与停止

需要 Java 21+、Node 22.6+、Python 3.12。保留现有技术栈，没有换掉原有页面、数据或人工制作功能。

```powershell
# 在项目根目录，首次安装
cd frontend
npm ci
cd ..
./scripts/install-agent-runtime.ps1 -PythonExecutable '你的 Python 3.12/python.exe'
cd backend
mvn test package
cd ..
./scripts/start-local.ps1
# 访问 http://127.0.0.1:5178/runs
./scripts/stop-local.ps1
```

三个服务仅监听 127.0.0.1：前端 5178、Java 8088、Python 8090。启动脚本为 Java 和 Python 生成同一临时内部认证令牌，只通过子进程环境传递；不保存在源码或日志。直接启动两个后端时必须自行设置同一 `CREATOR_RUNTIME_TOKEN`。默认关闭 LangSmith 外部追踪。环境变量不是团队版的凭据管理系统。

### 数据位置

从项目源码、IDEA 或 `backend/target` 中的 JAR 启动时，默认都使用 `backend/data/workbench.mv.db` 和 `backend/data/files`，与进程工作目录无关。可通过环境变量 `CREATOR_DATA_DIR` 指定统一数据目录；它应使用绝对路径。已有的 `spring.datasource.url`、`workbench.files-dir` 显式配置和 MySQL profile 仍可分别覆盖对应设置。将 JAR 单独复制到项目以外时，默认使用 JAR 所在目录的 `data`，也可显式指定数据目录。

旧版本可能因工作目录不同，在项目根目录产生另一份 `data`。这些数据不会自动合并、删除或覆盖。切换前请备份数据库和对应素材目录；若两份工作区都包含需要保留的内容，需先核对并单独迁移，不能简单覆盖数据库文件。浏览器本地工作区也独立保存，不会自动合并到数据库。

本轮遵循“不调用付费模型”。启动脚本强制 `CREATOR_ENABLE_LIVE_MODELS=false`，Java 与 Python 均拒绝 LIVE 请求。未来启用必须同时设置该开关和 `CREATOR_APPROVED_AGENT_MODELS`（操作者明确授权的模型 ID，以逗号分隔），并在运行页主动选择真实模型。三个角色的模型都必须在白名单中，凭据从对应环境变量读取；没有静默回退。 适配器代码支持 Chat Completions compatible / Responses，但还没有通过真实服务验收，不标记模型 verified/enabled。其他协议只保留模型档案。

后续启用前需要完成工具调用能力、结构化输出、供应商计费与限额合同测试。白名单代表操作者授权，不会改写模型 verified 为真。标准启动脚本始终关闭付费，真实联调需按明确授权另行启动服务；不能以 token 数当作人民币费用硬上限。本轮没有开启这些开关，也没有进行真实供应商验收。

## 模型如何继承

专家语言模型：节点能力覆盖 → 节点默认 → 作品能力覆盖 → 作品默认 → 角色能力覆盖 → 角色默认 → 全局能力覆盖 → 全局默认。没有声明 `TEXT_REASONING` 的模型跳过，不把图像模型用于编剧。

主管使用 PRODUCER，评审使用 QUALITY，分别从作品、角色、全局解析，避免复用节点专家覆盖。每次运行记录三份配置快照；后续改全局默认只影响新运行。测试模式仍显示“测试模型”，不会把绑定的真实模型名称冒充为实际执行者。

## 专家包与专业边界

`agent-runtime/profiles/<小写连字符角色名>/` 每个角色都有独立 `profile.json`、`prompt.md`、`SKILL.md`、`knowledge.md`；Skill 的 name 与目录一致，角色 ID 保持原样。19 个角色都是 CONFIGURED，domainVerified 为 false。它们包含各自的工作步骤、证据约束、验收和返工方法；专业方法配置不等于专业效果已经验证。

节点 requiredFields 在专家提交工具中只检查存在和非空；独立模型评审不等于确定性的事实验证。采纳的新候选会保存来源和待核对事项；完成前需要人工明确复核当前内容，测试候选须替换为人工提供的内容。人工确认只记录复核行为，不证明事实、文件或授权真实。旧版本已采纳且没有来源记录的草稿不会自动获得此保护。测试模型故意提交带有“测试材料”标记的候选，并触发一次返工，验证实际框架协作，不能证明脚本好看、事实正确或媒体可用。测试模型不访问网络、不读密钥、不调用供应商。

19 个角色的虚构评测场景及使用方式见 [专家人工评测场景](../agent-runtime/evals/README.md)。场景与目录匹配不代表已完成领域评测。

媒体、剪辑、上传、发布、素材归档、指标采集等节点使用 PLAN_ONLY。49 个活动节点均可按依赖进入协作，但这些节点只交付方案或检查清单。ComfyUI、FFmpeg、OBS、TTS、视频生成、发布 API 等依然为 DOCUMENTED，接入合同见 [外部接入说明](08-external-integration.md)。镜头/音轨/平台子实例执行器尚未实现。

## 持久化、恢复与限制

Java H2/MySQL 业务库增加 `agent_run`，与旧聚合、素材表并存；Python `runs.sqlite` 保存运行、单调序号事件、不可变候选/评审版本，`checkpoints.sqlite` 保存 LangGraph 检查点。迁移只建表，不删除旧项目、素材、任务或 N01 归档。

运行状态包括排队、运行、等待采纳、通过、拒绝、取消、失败、返工耗尽、UNKNOWN；投递层另有投递失败、采纳同步失败、拒绝同步失败。等待人工的 checkpoint 重启后可继续；进程中断时 RUNNING 变为 UNKNOWN，不自动重做可能已计费的调用。QUEUED 可重投。400/404/409/413 等永久投递错误停止重投并展示最后原因，可由操作者重试；503 等临时错误保留意图。当前不提供从未知供应商结果自动恢复或盲目重试。

取消在模型调用、工具调用、候选提交之间检查；不会声称已经撤销供应商正在进行的请求。曾投递失败或已投递的运行先持久记录取消意图，再同步远端取消，期间不再重投原任务；若远端返回 404 等永久错误，显示取消未确认并由操作者核对后重试，不把未知状态当成已取消。删除是软删除，不取消任务、不删除产物；排队、运行或取消未确认的任务先确认取消，记录可恢复。

上限：两个本机 worker；普通运行最多 30 次模型调用、180 秒、一次返工。输入超过 400,000 字节在 Java 受理前拒绝。按操作者要求项目不再限制累计 token 或单次输出 token，仍记录供应商返回的 usage；供应商自己的模型限制仍然生效。调用次数和时间限制不是费用上限。运行时间在安全点检查，单次模型请求另有超时。超时或供应商异常不自动重试。LIVE 模式在受理前校验模型参数，当前 Agent 适配器接受 `temperature/top_p`；Chat Completions 还可显式设置 `reasoning_effort: "none"`，是否支持取决于供应商，不设置时保持原有默认行为。不满足时返回明确错误，不进入 outbox。

事件当前通过 2.5 秒轮询展示。尚未实现 SSE、生产队列/租约与多副本调度、跨服务 inbox、PostgreSQL checkpointer、多租户、真实费用预留、按 SHOT/TRACK/PLATFORM 拆分业务节点实例以及领域评测发布门禁。画面需求与采用已独立于节点产物；PLATFORM 拍板已按平台记录，但发布节点仍是项目级。不要把本机运行版描述为上述生产能力已完成。P0/P1/P2 修复及剩余作用域边界见 [ds 分支审查修复](25-branch-review-fixes.md)。

## 接口

Java 对浏览器提供 JSON envelope `{code,message,data,requestId}`，错误使用 400/404/409/413/503；内部 Python 令牌不返回浏览器。

| 方法与路径 | 参数 / 请求体 | 返回与用途 |
| --- | --- | --- |
| GET `/api/v1/agent-runs/readiness` | 无 | 服务就绪、真实调用开关、19 专家版本和配置校验和 |
| GET `/api/v1/agent-runs` | 无 | 最近 200 条运行、状态、删除标记、模型与限制快照 |
| POST `/api/v1/agent-runs` | `{id:"run_<UUID>",projectId,nodeId,mode:"FIXTURE"}` | 幂等受理；依赖或拍板缺失返回 409 |
| GET `/api/v1/agent-runs/{id}` | 运行 ID | 运行、候选版本、评审和单调序号事件 |
| POST `/api/v1/agent-runs/{id}/decision` | `{decision:"ACCEPT"或"REJECT"}` | 采纳到草稿或拒绝；过期输入返回 409 |
| POST `/api/v1/agent-runs/{id}/control` | `{action:"CANCEL"、"DELETE"、"RESTORE"或"RETRY"}` | 安全点取消、软删除、恢复与重试投递 |

## 验证

```powershell
cd agent-runtime
./.venv/Scripts/python.exe -m pytest -q
cd ../backend
mvn test package
cd ../frontend
npm test
npm run build
npx playwright test
cd ..
python scripts/validate_docs.py
python scripts/render_node_catalog.py --check
```

普通 `npx playwright test` 只运行浏览器本地模式，跳过后端/Agent 用例。完整联调请在 frontend 执行 `npm run test:e2e:backend`，脚本自动启动三个隔离服务，使用内存业务库与临时文件/运行库，写入前核对实例标记；不需要手工配置服务地址。详见 [测试隔离与修复说明](22-audit-fixes.md)。实现计划及未交付项见 [实施方案](18-multi-agent-implementation-plan.md)；完整节点映射见 [49 节点矩阵](20-node-agent-migration-matrix.md)。
