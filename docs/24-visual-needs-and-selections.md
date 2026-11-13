> 历史实现说明：任意节点绑定已由[视频制作抽卡与远程接口](26-production-lottery-and-media-api.md)替代，当前以新说明为准。

# 画面抽卡：需求、候选与区间采用

2026-10-27。本说明替代旧版「镜头候选工作台」的业务约束。入口仍为 `/candidates`，侧栏名称改为「画面抽卡」。

## 抽卡围绕画面需求

一个画面需求可以是「开场氛围参考」「某个人物的首帧」或「成片 12～15 秒的表情」。需求属于作品，可以独立创建；来源制作步骤可选，允许全部 49 个活动步骤，不再用 SHOT / VIDEO_GENERATION 目录标签限制入口。

当前流程是：描述需求 → 建立图片/视频候选批次 → 从外部工具生成后导入 → 对比与筛选 → 采用为参考或成片区间 → 导出画面采用方案。真实生成、换 seed 自动重抽和渲染连接器仍未接入；本页不会创建供应商任务或产生模型费用。

## 采用的两种用途

- **参考图 / 参考片段**：一般、首帧、尾帧、人物、风格参考。图片不需要时间；视频参考可只取素材的一小段。
- **成片画面**：填写目标起点、终点和画面轨道。视频同时指定素材入点/出点；图片按目标时长作为静态画面使用。

所有时间以整数毫秒保存，界面用秒输入，支持小于一秒的区间。当前视频按原速采用，源片段与目标区间时长必须一致。素材出点不得超过已登记时长；同一轨道不得重叠，不同轨道可叠加。需求有预定时间范围时，采用位置必须在范围内。

例如成片 12～15 秒可以由两条决定组成：

| 候选 | 取素材区间 | 放入成片 |
| --- | --- | --- |
| A | 2.4～3.6 秒 | 12～13.2 秒 |
| B | 4.0～5.8 秒 | 13.2～15 秒 |

同一个候选也可以多处使用，并非一个需求只能选一个完整文件。每条采用有独立编号和原因，可以调整、替换、撤销；旧记录和原件保留。重复提交同一采用编号和相同内容不会增加记录，复用编号提交不同内容会被拒绝。替换针对整条采用记录，不自动拆分旧区间；需要只替换中间一段时，应先将采用方案拆为多条区间。

图片支持 PNG/JPEG/WebP，视频支持 MP4/WebM，单文件不超过 50MB。批次类型必须与素材类型一致。浏览器读取视频时长；旧素材或无法读取时可以在核对原件后填写。服务端校验数值边界及文件 SHA-256，但未部署媒体解码器验证时长、帧率、画质和连续性。预览由浏览器执行，毫秒记录不等于帧率对齐或成片渲染。

## 与制作步骤的关系

「来源制作步骤」仅提供上下文，不决定抽卡资格，也不作为自动采用门禁。「使用此画面的制作步骤」是显式输入依赖：只有勾选的步骤及其既有实际下游，会在采用方案变化时需复查。

采用不会覆盖任何节点的 draft / output，不增加节点产物 revision，也不会自动将节点标记完成。关联步骤增加 visualInputRevision；已完成的关联步骤及实际下游变为 NEEDS_REVALIDATION。拍板指纹纳入这一输入修订号，相关旧批准会失效。未关联的独立参考和候选整理不会改动流程状态。

节点草稿、手工交付和正常完成检查恢复原有流程，G03 等拍板仍约束后续正式制作执行。记录采用方案不代表已执行生成、剪辑、渲染或发布，也不会替代节点验收。Agent 运行快照携带关联需求及其采用方案，输入变化后旧候选不能误采纳。

## 数据和旧版兼容

本轮在项目中增加 `visualWorkbench`，继续由原有工作区事务与 expectedVersion/CAS 持久化：

| 集合 | 关键内容 |
| --- | --- |
| needs | 画面名称、描述、可选来源、显式使用节点、可选目标范围、修订号 |
| batches | 需求 ID、图片/视频类型、提示词、模型快照、参数、费用上限、来源批次 |
| candidates | 不可变原件引用与 SHA-256、图片/视频类型、可选时长、seed、费用、筛选状态 |
| placements | 候选、采用用途、源区间、目标区间/轨道或参考用途、原因、有效状态及替换/撤销信息 |
| legacyAdoptions | 旧版完整采用归档 |

已有 `videoWorkbench` 原样保留。首次读取旧项目时，镜头转换为画面需求，节点号仅作为来源；候选、批次和完整采用历史复制到新模型。旧版只记录了整个文件，系统不会猜测它的目标位置或源区间，因此不自动转为有效时间线采用。原节点输出、状态及审批不因迁移被重置，界面提示重新指定所需区间。

迁移幂等，服务端在事务中仅保存一次并更新工作区版本；本地模式遵循相同数据转换。新项目没有旧数据时不额外创建空集合。原件与工作区 JSON 分开备份。

## API

统一为 `POST /api/v1/commands`，请求 `{type,payload,expectedVersion}`，payload 包含 projectId。返回原有 `{code,message,data,requestId}`。字段/范围/预算/归属错误返回 400，文件缺失 404，工作区版本冲突、采用编号冲突或原件变化返回 409。

| type | 主要字段 |
| --- | --- |
| CREATE_VISUAL_NEED | id、title，可选 description、sourceNodeId、consumerNodeIds、desiredStartMs/desiredEndMs |
| UPDATE_VISUAL_NEED | needId 及上述需求字段 |
| REMOVE_EMPTY_VISUAL_NEED | needId，仅允许无批次和采用历史的需求 |
| CREATE_VISUAL_BATCH | id、needId、mediaKind、prompt、parameters、budgetCents，modelId 或 externalModel，可选 sourceBatchId |
| IMPORT_VISUAL_CANDIDATE | id、batchId、assetId、costCents，可选 durationMs、seed、note |
| SET_VISUAL_CANDIDATE_STATUS | candidateId、status：PENDING / KEPT / REJECTED |
| ADOPT_VISUAL_CANDIDATE | id、candidateId、purpose、reason；按用途填写下面的范围字段 |
| REMOVE_VISUAL_PLACEMENT | placementId、reason |

采用用途为 REFERENCE 时填写 referenceRole；为 TIMELINE 时填写 targetStartMs、targetEndMs、trackId。视频两种用途均须填写 sourceInMs、sourceOutMs，未知时长的旧候选还须填写 sourceDurationMs。替换已有有效采用时提供 replacesId。

旧的 CREATE_VIDEO_SHOT / ADOPT_VIDEO_CANDIDATE 等写命令不再提供旧语义，返回不支持操作；客户端应使用新接口，历史数据迁移不依赖重放这些命令。

原件沿用文件上传与范围播放接口。导出「画面采用方案」得到版本化 JSON，包含有效采用及所引用候选的文件标识和校验值，便于之后交接剪辑/渲染器；导出不生成新的视频文件。

金额仍用整数分、人民币元展示，费用是人工登记；登记限额不代表供应商扣费上限。前后端继续拒绝生成参数中的认证字段和常见密钥值。每作品上限：300 个需求、600 个批次、2,000 个候选、2,000 条采用记录；达到上限拒绝新增，不清除旧历史。

## 验证

运行 `frontend` 的 `npm test`、`npm run build`，后端 `mvn clean test package`，以及 `frontend` 的 `npm run test:e2e:backend`。联合脚本使用独立端口、内存库与临时文件，禁止把测试指向日常工作区。

回归覆盖：任意来源或独立需求、毫秒区间、同候选多处使用、图片参考/静态画面、同轨重叠与跨轨叠加、替换/撤销/幂等、预算与原件校验、无损旧数据迁移、显式关联复查、原稿/输出保持、正常节点流程、方案导出、视频播放及手机布局。

本轮验收：前端领域测试 26 项、后端测试 21 项、联合浏览器测试 19 项通过，前端构建、后端打包及文档检查通过。普通浏览器测试 13 项通过且不会连接日常后端；旧 Agent 输入过期校验已覆盖画面需求变化。P0/P1/P2 的补充修复见 [ds 分支审查修复](25-branch-review-fixes.md)。

测试画面：[桌面](screenshots/visual-workbench-desktop.png)、[手机](screenshots/visual-workbench-mobile.png)。
