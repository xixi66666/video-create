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

默认未配置凭据时，启动脚本关闭 LIVE。用户明确选择 DeepSeek 后，若当前进程或 Windows 用户环境中有 `DEEPSEEK_API_KEY`，启动脚本启用 LIVE，并仅将 `model_deepseek_flash` 加入授权名单；启动本身不会调用模型。仍须在运行页主动提交 LIVE 任务，主管、专家和评审的模型都须在名单中。凭据只从环境变量读取，不保存到模型档案；没有静默回退。适配器支持 Chat Completions compatible / Responses，实际接入和领域质量仍需核验。其他协议只保留模型档案。

MiMo V2.5 TTS 登记为 TTS 能力；`scripts/mimo_tts.py` 可用 `MIMO_API_KEY` 调用官方接口生成 WAV，Windows 可通过 `scripts/invoke-mimo-tts.ps1` 读取用户环境变量后调用。当前该脚本尚未接入工作台 N28 按钮，登记模型不代表已实现界面内自动语音生成。

后续启用前需要完成工具调用能力、结构化输出、供应商计费与限额合同测试。白名单代表操作者授权，不会改写模型 verified 为真。标准启动脚本始终关闭付费，真实联调需按明确授权另行启动服务；不能以 token 数当作人民币费用硬上限。本轮没有开启这些开关，也没有进行真实供应商验收。

## 模型如何继承

专家语言模型：节点能力覆盖 → 节点默认 → 作品能力覆盖 → 作品默认 → 角色能力覆盖 → 角色默认 → 全局能力覆盖 → 全局默认。没有声明 `TEXT_REASONING` 的模型跳过，不把图像模型用于编剧。

主管使用 PRODUCER，评审使用 QUALITY，分别从作品、角色、全局解析，避免复用节点专家覆盖。每次运行记录三份配置快照；后续改全局默认只影响新运行。测试模式仍显示“测试模型”，不会把绑定的真实模型名称冒充为实际执行者。

## 专家包与专业边界

`agent-runtime/profiles/<ROLE>/` 每个角色都有独立 `profile.json`、`prompt.md`、`SKILL.md`、`knowledge.md`。19 个角色都是 CONFIGURED，domainVerified 为 false。它们包含各自的工作步骤、证据约束、验收和返工方法；专业方法配置不等于专业效果已经验证。

节点 requiredFields 在专家提交工具中确定性校验；独立评审判断语义质量。测试模型故意提交带有“测试材料”标记的候选，并触发一次返工，验证实际框架协作，不能证明脚本好看、事实正确或媒体可用。测试模型不访问网络、不读密钥、不调用供应商。

媒体、剪辑、上传、发布、素材归档、指标采集等节点的 Agent 协作仍使用 PLAN_ONLY，只交付方案或检查清单。另有独立的 [本机 ComfyUI N27 视频候选连接器](22-comfyui-local-connector.md)，不是 Agent 自动执行；FFmpeg、OBS、TTS、发布 API 等仍只有接入文档。镜头/音轨/平台子实例执行器尚未实现。

## 持久化、恢复与限制

Java H2/MySQL 业务库增加 `agent_run`，与旧聚合、素材表并存；Python `runs.sqlite` 保存运行、单调序号事件、不可变候选/评审版本，`checkpoints.sqlite` 保存 LangGraph 检查点。迁移只建表，不删除旧项目、素材、任务或 N01 归档。

运行状态包括排队、运行、等待采纳、通过、拒绝、取消、失败、返工耗尽、UNKNOWN。等待人工的 checkpoint 重启后可继续；进程中断时 RUNNING 变为 UNKNOWN，不自动重做可能已计费的调用。QUEUED 可重投。当前不提供从未知供应商结果自动恢复或盲目重试。

取消在模型调用、工具调用、候选提交之间检查；不会声称已经撤销供应商正在进行的请求。删除是软删除，不取消任务、不删除产物；排队或运行任务先取消，记录可恢复。

上限：两个本机 worker；每运行最多 30 次模型调用、每次最多 1,200 输出 token、180 秒、一次返工。默认不设累计 token 上限（`maxTotalTokens=0`）；操作者可在创建请求中显式设置 100 至 100,000 的累计上限。旧运行继续使用创建时保存的限制。调用次数在调用前检查；token 是已完成调用的统计边界，单次响应可能使显式设置的累计上限超出，不能冒充供应商强制费用预算。真实模型开关和白名单仍然生效；本机地址本身不证明服务不会转发至收费供应商，应由操作者确认服务实际数据与费用边界。运行时间在安全点检查，单次模型请求对 `http://127.0.0.1:<端口>` 为 90 秒、其他地址为 45 秒。超时或供应商异常不自动重试。

事件当前通过 2.5 秒轮询展示。尚未实现 SSE、生产队列/租约与多副本调度、跨服务 inbox、PostgreSQL checkpointer、多租户、真实费用预留、按 SHOT/TRACK/PLATFORM 拆分实例以及领域评测发布门禁。不要把本机运行版描述为上述生产能力已完成。

## 接口

Java 对浏览器提供 JSON envelope `{code,message,data,requestId}`，错误使用 400/404/409/413/503；内部 Python 令牌不返回浏览器。

| 方法与路径 | 参数 / 请求体 | 返回与用途 |
| --- | --- | --- |
| GET `/api/v1/agent-runs/readiness` | 无 | 服务就绪、真实调用开关、19 专家版本和配置校验和 |
| GET `/api/v1/agent-runs` | 无 | 最近 200 条运行、状态、删除标记、模型与限制快照 |
| POST `/api/v1/agent-runs` | `{id:"run_<UUID>",projectId,nodeId,mode:"FIXTURE"}`；可选填整数 `maxTotalTokens`，0 表示不设累计上限 | 幂等受理；依赖或拍板缺失返回 409 |
| GET `/api/v1/agent-runs/{id}` | 运行 ID | 运行、候选版本、评审和单调序号事件 |
| POST `/api/v1/agent-runs/{id}/decision` | `{decision:"ACCEPT"或"REJECT"}` | 采纳到草稿或拒绝；过期输入返回 409 |
| POST `/api/v1/agent-runs/{id}/control` | `{action:"CANCEL"或"DELETE"或"RESTORE"}` | 安全点取消、软删除与恢复 |

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

浏览器联调测试需要三个服务，建议使用隔离测试数据库和独立端口，不在用户工作区创建验收作品。实现计划及未交付项见 [实施方案](18-multi-agent-implementation-plan.md)；完整节点映射见 [49 节点矩阵](20-node-agent-migration-matrix.md)。
