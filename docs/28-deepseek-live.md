# DeepSeek 真实模型试用

此入口面向 Windows 本机试验。默认的 `scripts/start-local.ps1` 仍然关闭 LIVE；本文的独立启动脚本只有显式传入开关才启用。LIVE 运行可能产生请求和费用；服务启动时也可能恢复已有的排队任务或投递待处理任务，启动前应检查这些任务及其授权状态。

## 前提与模型登记

- 当前 Windows 用户的通用凭据已配置：目标名称 `creator-workbench-deepseek`，凭据内容为 UTF-16LE。脚本从凭据管理器读取，并把密钥作为 `DEEPSEEK_API_KEY` 仅传给 Python 运行时子进程；不把密钥写进项目配置或命令行。脚本必须在可读取该凭据的用户会话下执行。
- 按现有安装文档准备 Java、前端和 Python 运行时。先用默认启动脚本打开工作台，在「模型中心」登记以下档案：

| 字段 | 值 |
| --- | --- |
| 显示名称、服务商 | 自行填写便于识别的名称，例如 `DeepSeek Flash`、`DeepSeek` |
| 协议 | `CHAT_COMPLETIONS_COMPATIBLE` |
| 真实模型 ID | `deepseek-flash` |
| 服务地址 | `https://api.deepseek.com` |
| 认证环境变量名称 | `DEEPSEEK_API_KEY`，只填写变量名 |
| 模型能力 | `TEXT_REASONING`（文本推理） |
| 参数预设 | 推荐试用 `{"reasoning_effort":"none"}`；也可使用 `{}`。LIVE 适配器还允许 `temperature`、`top_p`；`reasoning_effort` 目前仅支持该协议下的 `none` |

服务地址和模型名称以 [DeepSeek 官方接入文档](https://api-docs.deepseek.com/quick_start/) 为准。当前工作台 Agent 适配器按文本能力调用；不要把该档案登记为工作台可执行的图像、音频或视频生成模型。保存档案并不验证模型能力。

在模型中心将该档案设为全局默认，或按工作台既有优先级分别绑定主管、主责专家、会诊专家和评审模型。最终解析到的每个档案 ID 都必须出现在启动脚本的授权列表；已有节点、项目或角色覆盖可能影响选择结果。

界面展示的「真实模型 ID」是供应商名称，**不是**启动参数需要的工作台档案 ID。登记后，在服务运行时可从本机 API 查询档案 ID（只输出名称、档案 ID 和远程模型 ID）：

```powershell
(Invoke-RestMethod 'http://127.0.0.1:8088/api/v1/workspace').data.models |
    Where-Object { $_.remoteModelId -eq 'deepseek-flash' } |
    Select-Object name, id, remoteModelId
```

如果有多个同名档案，按名称选择需要授权的 `id`。该查询读取服务端工作区；浏览器离线存储中的档案不会出现在查询结果中。

## 启动与停用

如需启用研究搜索，启动前在当前 PowerShell 进程设置以下变量（运行时仍只允许读取明确列出的页面主机）：

```powershell
$env:CREATOR_RESEARCH_ENABLED = 'true'
$env:CREATOR_RESEARCH_PROVIDER = 'deepseek'
$env:CREATOR_RESEARCH_ALLOWED_HOSTS = 'api-docs.deepseek.com'
```

DeepSeek Search 使用固定的官方 HTTPS 端点，复用上述凭据；搜索可能产生费用，具体以[官方说明](https://api-docs.deepseek.com/zh-cn/guides/search/)为准。搜索结果仅为线索，页面主机不会自动加入允许列表；需要读取其他官方页面时，由管理员按需添加精确域名。上述页面读取由本机研究工具执行，不调用 DeepSeek Fetch API。

在项目根目录先停止默认实例，再启动 LIVE 实例，将命令中的占位文字替换为上一步得到的工作台档案 ID：

```powershell
.\scripts\stop-local.ps1
.\scripts\start-local-deepseek.ps1 -EnableLive -ApprovedModelId '<工作台模型档案ID>'
```

如需授权多个已配置档案，可传入 `-ApprovedModelId '档案ID一','档案ID二'`。此脚本只读取 DeepSeek 凭据；其他供应商需要单独提供各自的认证环境变量和安全配置。

脚本监听的端口与默认入口相同：前端 5178、Java 8088、Python 8090。访问 `http://127.0.0.1:5178/` 后，在协作运行页选择 LIVE 并提交符合节点依赖条件的运行。默认启动和 LIVE 启动不能同时占用相同端口。

试验结束后停止实例；若需要关闭 LIVE 并继续使用工作台，重新运行默认入口：

```powershell
.\scripts\stop-local.ps1
.\scripts\start-local.ps1
```

停止进程不会删除 Windows 凭据；如不再使用，需要通过 Windows 凭据管理器删除或轮换。API 密钥若曾暴露在聊天或其他不受控位置，应在供应商控制台撤销并更换，并更新 Windows 凭据。

## 边界

LIVE 调用会将任务输入和模型请求发送到模型档案指定的服务地址，并将密钥用于该地址的认证。此独立启动入口为 `DEEPSEEK_API_KEY` 设置目的地约束：只允许 HTTPS 的 `api.deepseek.com`，端口省略或为 443，不允许 URL 用户信息、查询参数或片段，且受限请求不跟随重定向。该限制针对这一凭据引用，仅在使用此入口启动的运行时生效，不自动保护其他凭据或其他启动方式。请仅使用已授权、不含敏感信息的试验材料。环境变量可被有足够权限的本机进程访问，并非独立的密钥隔离系统。

请求可能计费。项目保留调用次数和运行时间限制，记录供应商返回的 usage，不再设置项目侧 token 阈值；供应商自己的上下文和输出限制仍然适用。先以小范围场景试验，核对供应商用量与费用。真实响应、工具调用或一次成功运行都不能证明领域专业能力；需要保留样本并由独立领域专家按场景评审，所有专家的 `domainVerified` 仍保持原状。会诊最多六名专家，串行执行且共享预算；新运行可按角色绑定独立模型并分别校验白名单，旧快照沿用主责 worker 配置。主责专家给出的意见对照只校验引文出处，须由人判断是否存在分歧；媒体执行与真实搜索能力仍受各自的接入和开关限制。
