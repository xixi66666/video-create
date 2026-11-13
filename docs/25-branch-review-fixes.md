# ds 分支审查修复记录

日期：2026-10-27。范围：P0/P1/P2 审查问题。当前分支还包含已存在的“画面抽卡”实现，本轮修复与其兼容。

## P0

- 浏览器测试只允许隔离脚本运行后端/Agent 用例。`frontend/playwright.config.ts` 在非隔离环境忽略 `agents.spec.ts`、`backend.spec.ts`、`visual-backend.spec.ts`；三个文件各自调用 `useIsolatedBackend()`，不再依赖共享模块顶层副作用。普通 `npm run test:e2e` 只运行本地模式。
- 画面抽卡采用不会覆盖节点 `draft/output`，也不会自动完成节点；Agent 输入固定携带关联画面需求与采用方案。旧版镜头草稿冲突语义已由新模型消除。仍保留 `visualInputRevision` 使关联节点和拍板失效。

## P1

- Outbox 增加 `agent_run_dispatch` 记录投递次数与最后错误。400/401/403/404/409/413/422 等永久错误停止重投，进入 `SUBMISSION_FAILED`、`ADOPTED_SYNC_FAILED` 或 `REJECTED_SYNC_FAILED`；运行页显示原因并支持 `RETRY`。503 等临时错误保留意图并展示最后错误。
- Agent 输入超过 400,000 字节在 Java 受理前拒绝，避免进入 Python 后永久失败。
- LIVE 运行在业务受理前按 `temperature/top_p` 白名单校验模型参数；模型页默认参数不再写入 `maxOutputTokens`。协议、白名单和参数错误不会静默卡在“等待投递”。
- 工作流模板 `overrides` 已消费：`CONDITIONAL` 才显示跳过入口，前后端共同校验；N25/N26 等节点按模板显示责任与推荐能力。
- 项目状态支持 `ACTIVE/PAUSED/ABANDONED`。暂停/放弃后不能完成节点、跳过、拍板或启动 Agent；可在项目设置或 G02 恢复。项目标题、简报、预算和平台可在设置中修改，变平台会使相关确认失效。
- G04/G05 等 PLATFORM 拍板改为逐平台记录和校验；所有当前平台都确认后才放行下游。旧的不分平台批准需要重新确认。发布节点仍按项目保存，尚未拆分平台实例。
- 结构化 JSON 产物在手工完成时检查 `requiredFields`；普通自由文本仍可手工交付。画面抽卡作为独立输入模型，不伪造节点产物。
- 画面抽卡沿用文件 SHA-256、批次预算、素材归属和范围播放校验；旧视频候选只做无损迁移。

## P2

- `SAVE_MODEL` 对模型档案字段做明确白名单，未知字段（包括顶层凭据字段）返回 400。
- `ADD_LEDGER` 缺少/非法金额返回 400；服务端异常信封覆盖空指针、类型不支持、算术异常等输入错误，不再直接 500。
- 初始化完成前不渲染工作区，避免用户先写本地状态后被服务端快照覆盖。
- `dispatch()` 不再持有 `create/decide/control` 的同步锁；HTTP 投递只由独立调度标记串行。
- `planOnly` 改为根据节点 `executorKind` 判断，不再硬编码角色与节点编号。
- 素材库上传可选择关联作品；只有关联作品的素材可被画面抽卡登记。
- Agent 候选面板显示结构化字段、来源和不确定性；Runs 页显示投递错误与重试入口。
- 测试与文档更新：普通 Playwright 13 项，本地领域测试 26 项，后端测试 21 项，隔离联合测试 19 项。

## 未完成的作用域

以下仍按项目级保存，不能宣称为完整的多实例能力：

- ACCOUNT 的 N02—N07 与 G01/G06 尚未跨作品共享或复用；G01 界面已提示该限制。
- IDEA 的 N08—N14 仍作为项目内的选题流程，不与灵感对象建立独立实例。
- PLATFORM 的 N38—N46 仍共用项目节点；G04/G05 已按平台独立确认，但发布节点尚未按平台拆分。
- TRACK 子实例和真实发布/指标连接器仍未接入。

这些是后续架构迁移，不应在界面或文档中描述为已完成。

## 验证

```powershell
cd frontend
npm test
npm run build
npm run test:e2e
npm run test:e2e:backend
cd ../backend
mvn clean test package
cd ..
python scripts/validate_docs.py
python scripts/render_node_catalog.py --check
```

本轮已通过：前端领域测试 26、后端测试 21、隔离联合测试 19、普通浏览器测试 13、前端构建、文档检查。未调用付费模型，未做真实发布或 MySQL 联调。
