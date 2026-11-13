# 镜头候选工作台：导入、对比与正式采用

> 历史实现记录：以下节点限制和自动完成规则已被替换。当前使用 [画面需求与区间采用](24-visual-needs-and-selections.md)。

2026-10-27，第一阶段交付。入口为侧栏「镜头候选」(`/candidates`)，也可从支持视频生成能力的节点进入「管理镜头候选」。

## 当前可以使用的流程

1. 选择作品、制作节点，新建有稳定编号的镜头。当前目录支持 N27、N29，判断依据为节点的 SHOT 作用域和 VIDEO_GENERATION 能力，不在业务代码里固定节点号。
2. 为镜头新建导入批次，登记提示词、外部模型名称与版本（或已登记的视频模型）、生成参数及费用上限。批次配置保存快照，后续模型改名或删除不会改写历史批次。
3. 在外部工具完成视频生成，批量导入 MP4/WebM，也可从本作品素材库登记。单文件不超过 50MB；保存 SHA-256、seed、备注和人工登记费用。不同 seed 可分别登记，不伪造未知参数。
4. 预览播放视频，最多同时对比两条候选，保留、淘汰或恢复。保留和淘汰不会更新节点产物、不会使下游失效；当前采用的候选不能直接淘汰。
5. 点击「正式采用」，说明采用原因并确认。服务端重新检查工作区版本、前置依赖、G03 等拍板以及原文件校验值，再记录采用关系并发布节点采用清单。
6. 使用「沿用设置建立下一批」复用已冻结的提示词和参数，再到外部工具生成并导入。新批次记录来源批次，旧候选、文件和采用记录继续保留。

本期真实生成、批量派发、换 seed 自动重抽、供应商取消/重试和费用预留仍待连接器实现。本页不会调用供应商；导入批次并非远端生成任务，登记费用并非供应商实际账单。ComfyUI 等工具仍按 [接入合同](08-external-integration.md) 保持 DOCUMENTED。

## 数据与采用语义

业务实体保存于现有 `workspace_document` 的 `project.videoWorkbench`，通过原有 Spring 事务、MyBatis 参数绑定和 expectedVersion/CAS 一起提交。本期不拆独立 SQL 表，避免引入与现有工作区并列的双写数据源。浏览器本地模式使用相同实体与规则，原文件存在 IndexedDB；后端模式原文件沿用 `media_file`。旧项目无此字段时按空集合读取，首次创建才写入，不清空任何旧产物。

| 实体 | 关键字段 |
| --- | --- |
| shots | id、nodeId、title、selectedCandidateId、selectionRevision |
| batches | id、shotId、prompt、modelSnapshot、parameters、budgetCents、sourceBatchId |
| candidates | id、shotId、batchId、assetId、fileRef、sha256、seed、costCents、note、status |
| adoptions | id、shotId、candidateId、previousCandidateId、revision、previousOutput、previousDraft、reason、at |

金额用整数分，界面以人民币元展示；费用上限对该批次全部候选累计生效，淘汰不会退回已登记费用。生成参数允许供应商选项存档，但前后端递归拒绝认证字段和常见密钥值。模型快照只取模型标识、名称、供应商和协议，不包含认证信息。

正式采用会保存采用前的节点产物和草稿，更新该镜头的采用指针与版本，把文件引用、校验值、候选/批次编号写入节点输出清单，并增加节点 revision。一个节点包含多个镜头时，必须全部选定才为 COMPLETED，否则为 DRAFT。换片始终保留旧候选和采用记录；重复采用同一候选不重复增加镜头/节点版本或采用记录。

节点失效沿用现有「实际依赖」传播：引用旧节点版本的已完成下游变为 NEEDS_REVALIDATION，相关拍板因版本或状态变化失效，未引用的节点保持原状。当前精度为节点，尚未建立剪辑时间线中每个素材片段的依赖。为已完成节点增加镜头会使该节点及下游需复查；误建且尚无批次的空镜头可以删除，删除后按当前节点情况重新确认。

管理了镜头的节点，其采用清单由工作台维护，不能靠任意文本伪造完成。上游变更后若候选仍适用，可回到节点页面重新标记完成；业务依赖和拍板仍会再次校验。普通人工节点保留原有文本编辑流程。

## 命令接口

统一为 `POST /api/v1/commands`，请求体 `{type,payload,expectedVersion}`；payload 均包含 projectId。成功返回 `{code,message,data,requestId}`，data 是新工作区；字段/归属/费用错误为 400，文件缺失为 404，版本冲突、前提未满足或文件变化为 409。文件上传沿用 `POST /api/v1/files`；GET 文件支持浏览器范围请求播放。

| type | payload 其他字段 |
| --- | --- |
| CREATE_VIDEO_SHOT | id、nodeId、title |
| REMOVE_EMPTY_VIDEO_SHOT | shotId，仅允许无批次且无采用记录的镜头 |
| CREATE_VIDEO_BATCH | id、shotId、prompt、parameters、budgetCents、modelId 或 externalModel，可选 sourceBatchId |
| IMPORT_VIDEO_CANDIDATE | id、batchId、assetId、costCents，可选 seed、note |
| SET_VIDEO_CANDIDATE_STATUS | candidateId、status（PENDING / KEPT / REJECTED） |
| ADOPT_VIDEO_CANDIDATE | id（采用记录编号）、candidateId、reason |

采用前对本地文件或服务端原件重新计算校验值；文件缺失或被更改会拒绝采用。批量导入逐条登记，失败会逐条显示；已上传但未登记成功的文件保留在素材库，可重新登记，不会被误报为导入成功。旧的本地素材没有校验值时需重新上传。

单个作品当前最多 100 个镜头、300 个批次、1,000 条候选、500 条采用记录。记录达到上限时拒绝新增，不自动清除历史。工作区 JSON 与原文件需分别备份；大规模镜头和长期运行时应迁移到独立候选表及对象存储。

## 验证

```powershell
cd frontend
npm test
npm run build
npm run test:e2e
cd ../backend
mvn clean test package
cd ../frontend
npm run test:e2e:backend
```

使用隔离测试脚本，不向日常工作区导入验收作品。测试素材为随源码保存的 VP8/WebM 色块片段，不使用真实模型或用户视频。覆盖前后端业务规则、原件变化拦截、范围播放、批量导入、视频解码、对比、正式采用、换片、刷新恢复、依赖失效、移动端布局及旧版流程回归。

本轮验收：前端领域测试 20/20、后端测试 15/15、联合浏览器测试 18/18，前端构建、后端打包与文档检查通过。联合服务使用随机端口和临时数据库，成功后已清理。

测试作品截图：[桌面工作台](screenshots/video-candidates-desktop.png)、[手机工作台](screenshots/video-candidates-mobile.png)。
