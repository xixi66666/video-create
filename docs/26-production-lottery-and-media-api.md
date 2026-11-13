# 视频制作抽卡与远程媒体执行接口

2026-10-27。替代 24 号文档中的任意节点绑定设计。

## 本轮交付与实际边界

画面抽卡归属作品中的视频制作任务：N27 主体内容、N29 辅助画面。每个任务可以建立任意多个画面需求，时间范围与分镜编号均可选；不是一秒一个节点，也不要求先建立分镜实体。

已实现：限定归属、参考图快照、图片/视频候选、毫秒区间、多处采用、替换/撤销、剪辑实际引用、生成任务持久化、批量排队、查询、取消请求、未知受理恢复、远程 HTTP 客户端、原件回收与校验。生成成功不自动采用，不写节点 draft/output，不自动完成节点。

**远程媒体 Worker 尚未部署，未连接真实供应商或渲染器。** 远程 HTTP 协议是本项目的媒体 Worker 协议，不是 ComfyUI 原生地址；仅填写一个 ComfyUI URL 不能使远程 Worker 工作。项目另有独立的[本机 ComfyUI 候选连接器](22-comfyui-local-connector.md)和[声音采集与 MiMo 配音工具](../voicelib/README.md)，不代表已接通自动剪辑或渲染。远程 Worker 接口以本地模拟服务做合同验证，真实环境需另行部署联调。

## 制作与剪辑

入口位于作品 N27/N29；全局侧栏和其他业务节点不再提供通用抽卡按钮。`/candidates` 仍可按作品查看视频制作素材，以兼容原链接。

需求使用 `productionNodeId: N27 | N29` 和可选 `shotId`。新写入拒绝 `sourceNodeId`、`consumerNodeIds`。N31/N32 通过 `USE_VISUAL_PLAN` 提交真正使用的 `placementIds`，而不是任意勾选业务节点。替换/撤销画面使所属制作任务、明确引用该需求的剪辑步骤及其已有实际下游需复查。节点产物版本不增加，输入修订与拍板指纹变化；上游选题、脚本、经营不会因任意绑定被污染。

剪辑仍是手工交付和采用方案交接，未实现时间线编辑或视频渲染。导出方案 JSON 不是视频文件。

批次可冻结参考候选的 ID、角色、原件引用与 SHA-256，供视频生成使用；当前界面一次选择一张参考图，接口最多接受八张。直接文生视频可不选参考图。改变提示词、模型、参考图或参数时新建批次；继续抽取可复用原批次，旧结果保留。

## 工作台 API

机器可读定义见[工作台 OpenAPI](../specs/visual-jobs.openapi.json)。

原有 `POST /api/v1/commands`、上传和文件范围播放继续使用。工作区命令均携带 `expectedVersion`。

| 方法 | 地址 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/visual-jobs/readiness` | 已配置/在线、支持的类型与 seed 能力；不返回认证信息 |
| GET | `/api/v1/visual-jobs?projectId=...` | 该作品生成任务列表与错误 |
| GET | `/api/v1/visual-jobs/{id}` | 查看单条持久任务 |
| POST | `/api/v1/visual-jobs` | 一次创建 1～8 条持久任务；输入在受理时冻结 |
| POST | `/api/v1/visual-jobs/{id}/control` | `CANCEL` 或 `RECOVER` |

创建请求示例：

```json
{
  "id": "draw_example_20261027",
  "projectId": "your_project",
  "batchId": "your_batch",
  "count": 4,
  "maxCostCents": 25,
  "seedStart": 1000,
  "expectedVersion": 38
}
```

返回沿用 `{code,message,data,requestId}`；data 为任务数组。相同抽取 ID 与相同请求幂等返回，改变请求复用 ID 返回 409。版本冲突为 409，未配置执行端为 503，参数、范围或费用预留错误为 400。执行前检查项目状态、N27/N29 依赖和人工拍板；seed 不支持时明确拒绝，不伪造复现能力。

批次预算计算包含已登记费用和未结束任务的预留。未提交就取消/拒绝的任务释放预留；已提交后失败或取消的任务保守保留预留，不能假定供应商未收费，当前尚未提供费用对账释放界面。费用预留是工作台调度边界，不等于第三方供应商的账户扣费硬上限；Worker 必须执行自己的费用约束并报告真实费用。无法在预留内执行时应拒绝任务。

`USE_VISUAL_PLAN` 的 payload 为 `{projectId,nodeId:"N31"或"N32",placementIds:[...]}`。只能引用有效的 TIMELINE 采用，旧的失效采用引用保留用于提示复查。

## 部署分工与配置

```text
浏览器 → 工作台 Spring Boot → 远程媒体 Worker → ComfyUI / 已登记生成工具
               ↑            ↓
          本机/服务器原件库 ← 任务结果与原件
```

工作台通过服务器配置连接执行端，不在前端让用户填写任意 URL：

```powershell
$env:CREATOR_MEDIA_EXECUTOR_URL='https://media-worker.example.invalid'
$env:CREATOR_MEDIA_EXECUTOR_ENABLED='true'
# CREATOR_MEDIA_EXECUTOR_TOKEN 由部署环境注入；不要写入源码、工作区或日志。
```

也可使用 Spring 参数 `--workbench.media-executor-url=... --workbench.media-executor-enabled=true`。默认地址为空且关闭，不会自动访问用户另一台机器。HTTP 客户端不跟随重定向，只访问管理员配置的地址；内网地址可以用于服务器之间通信。工作台自身仍是原有单用户版本，上线时由部署环境提供受控访问入口。

Worker 需要维护：已发布模板及版本、真实 ComfyUI node/input 参数绑定、工具/模型版本、幂等任务表、客户端 job ID 与 ComfyUI prompt ID 的映射、输入输出文件、任务取消能力。工作台不下载模型、不安装节点、不把浏览器提交的任意图当作可信工作流执行。

## 媒体 Worker 协议 creator-media-v1

机器可读合同见 [OpenAPI](../specs/media-worker.openapi.json)。以下地址均相对配置的执行端。

| 方法 | 地址 | 必需行为 |
| --- | --- | --- |
| GET | `/v1/health` | 返回 protocol、mediaKinds、supportsSeed、referenceRoles |
| POST | `/v1/jobs/{id}/inputs/{inputId}` | 先传参考图二进制；同 ID/同内容幂等，不同内容拒绝 |
| POST | `/v1/jobs` | 按客户端 ID 持久受理，返回相同 id；相同 ID 不重复执行 |
| GET | `/v1/jobs/{id}` | 查询原任务；返回 QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED |
| POST | `/v1/jobs/{id}/cancel` | 幂等取消请求，不支持时明确返回；不能误中断其他任务 |
| GET | `/v1/jobs/{id}/outputs/{outputId}` | 回收归属原件二进制，不返回任意下载 URL |

配置了认证环境变量时，各请求携带 Bearer 认证。Worker 必须在受理前持久化幂等记录；同 ID 不同任务内容返回 409。`parameters.templateId` 可指向 Worker 已登记模板，具体参数 Schema 由该模板定义。`batch.modelSnapshot` 仅是制作记录，Worker 还需核对真实模板、模型和能力。

工作台先上传参考图，提交时将 references 中的 fileRef 替换为 inputId，避免远端磁盘路径与工作台相对 URL 混用。输出下载固定在受配置 Worker 的任务路径下，不接受生成结果提供的任意 URL。

成功结果示例：

```json
{
  "id": "draw_example_20261027_0",
  "state": "SUCCEEDED",
  "costCents": 20,
  "outputs": [{
    "id": "main",
    "fileName": "clip.webm",
    "mediaType": "video/webm",
    "durationMs": 5000,
    "sha256": "64位小写十六进制SHA256"
  }]
}
```

每条任务对应一个候选原件，多个候选通过多个任务表示。图片支持 PNG/JPEG/WebP，视频支持 MP4/WebM，单文件上限 50MB；视频必须报告有效时长。当前校验类型、数值、大小、SHA-256，没有使用媒体解码器实测时长和帧率。

## 状态、恢复与数据

任务列表返回最近200条，每作品最多4000条；单条详情可按ID查询。

工作台状态：QUEUED → SUBMITTING → SUBMITTED/RUNNING → SUCCEEDED/FAILED；另有 UNKNOWN、CANCEL_REQUESTED、CANCELLED、COLLECTION_FAILED。

- 提交超时或重启遗留 SUBMITTING：只查询原 ID，不自动重发生成。
- UNKNOWN/文件回收失败的 RECOVER：查询原任务并重新回收，不创建新生成。
- 排队或准备中、尚未发起生成请求时可以在本地停止；如部分参考素材已上传，执行端可能仍保留这些输入，不能声称已清理。进入 SUBMITTING 后即使在发送生成请求前取消，仍保守保留预算预留。生成请求已经开始后需等待远端确认，生成已完成时取消可能来不及，结果仍进入候选。
- 调度每 2.5 秒检查一次，单进程串行，持久记录保存在 `visual_generation_job`。尚未实现多副本租约调度；一套任务库只运行一个调度实例。
- 文件、素材目录、候选和完成状态在回收事务中保持一致；失败回滚清理本次新建原件。

`visualWorkbench` 升为 schemaVersion 3，增加 uses 和明确归属。v2 的来源/使用节点保存在各需求 legacyBinding；只有原来源 N27/N29 可自动归类，其他需求留待人工归类。候选、原件、采用和旧节点状态保留，不猜测时间线，不自动恢复历史需复查状态。迁移幂等并沿用 CAS。

## 验证

运行 `frontend/npm test`、`npm run build`，后端 `mvn test package`，联合测试 `frontend/npm run test:e2e:backend`，文档检查 `python scripts/validate_docs.py`。联合测试使用独立端口和临时数据。

新增合同测试覆盖：持久幂等、预算预留、非法归属、未连接执行端、受理未知只查询、原件回收不自动采用、取消等待确认、真实 HTTP 路径和二进制传输。它们不能替代远端 Worker/ComfyUI 实机验收。

本轮通过：前端领域测试29项、后端测试32项、普通浏览器测试17项、隔离联合浏览器测试24项，前端构建、后端打包与文档检查通过。界面检查：[桌面](screenshots/production-lottery-desktop.png)、[手机](screenshots/production-lottery-mobile.png)。
