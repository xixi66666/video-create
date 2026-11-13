# 20 全部 49 节点与 Agent 迁移矩阵

N01 已退役，N02—N50 保留编号；本版所有活动节点均使用现有依赖和六个人工拍板校验。下表中“文字候选”仍需真实材料核验；“方案”不会生成媒体、发布回执或指标。当前只运行测试模型。

按节点受理与持久协作已实现；镜头、音轨、平台独立子实例执行尚未实现。接口和启动方式见 [运行说明](20-multi-agent-runtime.md)。

| 节点 | 专家 | 作用域 | 前置 | 交付模式 | 必填字段 | 人工职责 |
| --- | --- | --- | --- | --- | --- | --- |
| N02 盘点自身条件 | 定位与栏目 | ACCOUNT | 无 | GENERATE_TEXT 文字候选 | skills, experiences, resources, privacyBoundaries | 补充真实经历及隐私边界 |
| N03 确定目标观众 | 定位与栏目 | ACCOUNT | N02 | GENERATE_TEXT 文字候选 | segments, problems, evidenceRefs | 选择愿意长期服务的受众 |
| N04 确定账号定位 | 定位与栏目 | ACCOUNT | N03 | GENERATE_TEXT 文字候选 | audience, valuePromise, credibility, limitations | 决定对外身份和长期方向 |
| N05 设计内容栏目 | 定位与栏目 | ACCOUNT | N04 | GENERATE_TEXT 文字候选 | pillars, topicExamples, productionConstraints | 选择栏目与制作负担 |
| N06 建立账号主页 | 平台包装 | ACCOUNT | N04 | GENERATE_TEXT 文字候选 | platforms, profileDrafts, identityStatus | 身份操作及公开信息确认 |
| N07 建立制作规范 | 美术与连续性 | ACCOUNT | N05, N06 | GENERATE_TEXT 文字候选 | visualRules, audioRules, fileRules, qualityRules | 选择参考样片与规范 |
| N08 捕捉原始想法 | 选题研究 | IDEA | 无 | GENERATE_TEXT 文字候选 | rawContent, inputMode, capturedAt | 提供原始想法 |
| N09 解释想法的来源 | 选题研究 | IDEA | N08 | GENERATE_TEXT 文字候选 | trigger, realScenario, knownFacts, openQuestions | 补充真实触发场景 |
| N10 翻译成观众问题 | 选题研究 | IDEA | N09, N03 | GENERATE_TEXT 文字候选 | audience, scenario, problem, expectedBenefit | 确认表达意图 |
| N11 验证需求 | 选题研究 | IDEA | N10 | GENERATE_TEXT 文字候选 | sources, observations, sampleLimits, hypotheses | 判断证据是否足够 |
| N12 分析已有内容 | 选题研究 | IDEA | N11 | GENERATE_TEXT 文字候选 | references, comparison, unansweredQuestions | 判断有价值的差异 |
| N13 选择自己的切入点 | 选题研究 | IDEA | N12 | GENERATE_TEXT 文字候选 | options, evidence, productionEstimates, recommendation | 选择表达角度 |
| N14 判断是否值得做 | 制作统筹 | IDEA | N13 | GENERATE_TEXT 文字候选 | decision, rationale, budgetLimit, scope | 通过 G02 作立项决定 |
| N15 写选题卡 | 选题研究 | PROJECT | N14 | GENERATE_TEXT 文字候选 | audience, problem, angle, promise, scope | 通常无需逐条确认 |
| N16 收集资料与案例 | 资料与实测核验 | PROJECT | N15 | GENERATE_TEXT 文字候选 | sources, claims, cases, rightsNotes | 核查关键证据并提供真实案例 |
| N17 实际验证 | 资料与实测核验 | PROJECT | N16 | GENERATE_TEXT 文字候选 | method, inputs, results, limitations, evidenceRefs | 完成真实体验和关键验证 |
| N18 确定核心结论 | 编剧 | PROJECT | N17 | GENERATE_TEXT 文字候选 | conclusion, evidenceRefs, conditions, uncertainties | 确认立场和适用条件 |
| N19 选择呈现形式 | 导演与分镜 | PROJECT | N18, N07 | GENERATE_TEXT 文字候选 | contentMode, format, aspectRatio, targetDurationMs | 确认出镜、预算和形式 |
| N20 写内容大纲 | 编剧 | PROJECT | N19 | GENERATE_TEXT 文字候选 | sections, evidenceMapping, estimatedDurationMs | 确认重点和信息顺序 |
| N21 写开头 | 编剧 | PROJECT | N20 | GENERATE_TEXT 文字候选 | candidates, selectedCandidateId, promiseCheck | 选开场方向 |
| N22 写完整脚本 | 编剧 | PROJECT | N20, N21 | GENERATE_TEXT 文字候选 | segments, claims, sourceRefs, estimatedDurationMs | 确认观点、事实与个人表达 |
| N23 口语化与试读 | 编剧 | PROJECT | N22 | GENERATE_TEXT 文字候选 | spokenScript, pronunciationGuide, timingEstimate, previewRefs | 试读或试听并判断表达 |
| N24 写分镜与素材清单 | 导演与分镜 | PROJECT | N23, N19 | GENERATE_TEXT 文字候选 | shots, assetNeeds, styleGuideRef, animaticRef, hardShotTest | 通过 G03 确认脚本分镜和样片 |
| N25 准备拍摄环境 | 拍摄与录屏辅助 | PROJECT | N24 | PLAN_ONLY 制作/检查方案 | setupChecklist, testClipRefs, applicabilityReason | 布置机位、灯光、收音与道具 |
| N26 准备演示环境 | 拍摄与录屏辅助 | PROJECT | N24 | PLAN_ONLY 制作/检查方案 | scenario, dataRefs, privacyCheck, readiness | 确认账号、数据与演示范围 |
| N27 拍摄主体内容 | 拍摄与录屏辅助 | SHOT | N25, N26 | PLAN_ONLY 制作/检查方案 | shotId, candidates, method, captureNotes | 实拍由人执行；纯 AI 转 B 选择候选 |
| N28 录制旁白 | 声音制作 | TRACK | N23, N24 | PLAN_ONLY 制作/检查方案 | trackId, audioRef, transcript, alignment | 真人录音或确认合成声音 |
| N29 补充辅助画面 | 视频素材制作 | SHOT | N24, N27 | PLAN_ONLY 制作/检查方案 | shotId, candidates, sourceRecords, continuityChecks | 补拍或选用候选 |
| N30 整理与备份 | 资产管理 | PROJECT | N27, N28, N29 | PLAN_ONLY 制作/检查方案 | files, checksums, backupStatus, shotLinks | 仅异常处理；删除原件另行确认 |
| N31 粗剪 | 剪辑与后期 | PROJECT | N30, N24 | PLAN_ONLY 制作/检查方案 | timelineRef, previewRef, missingAssets | 叙事重构或采访纪录转 B |
| N32 精剪 | 剪辑与后期 | PROJECT | N31 | PLAN_ONLY 制作/检查方案 | timelineRef, previewRef, changeNotes | 判断情绪、重点和节奏 |
| N33 制作字幕 | 剪辑与后期 | PROJECT | N32, N28 | PLAN_ONLY 制作/检查方案 | subtitleRef, transcript, audioRevision, checks | 核查专名、数字和歧义 |
| N34 制作说明画面 | 图像制作 | SHOT | N32, N24 | PLAN_ONLY 制作/检查方案 | graphicsRefs, textSourceRefs, timing | 新设计或新解释内容转 B |
| N35 处理声音 | 声音制作 | PROJECT | N32, N28 | PLAN_ONLY 制作/检查方案 | audioRef, mixSettings, measurements, rightsRefs | 复杂修复或音乐情绪选择转 B |
| N36 调整画面 | 剪辑与后期 | PROJECT | N32 | PLAN_ONLY 制作/检查方案 | pictureRef, colorNotes, frameChecks | 确认视觉风格 |
| N37 导出母版 | 剪辑与后期 | PROJECT | N33, N34, N35, N36 | PLAN_ONLY 制作/检查方案 | fileRef, checksum, exportPreset, technicalReport | 仅异常时处理 |
| N38 写标题 | 平台包装 | PLATFORM | N37, N15 | GENERATE_TEXT 文字候选 | platform, candidates, selectedTitle, consistencyCheck | 选择对外标题 |
| N39 做封面 | 平台包装 | PLATFORM | N37, N07 | GENERATE_TEXT 文字候选 | platform, imageRef, textLayout, cropChecks | 选择封面 |
| N40 写配文 | 平台包装 | PLATFORM | N38, N39 | GENERATE_TEXT 文字候选 | platform, text, topics, sourceRefs, declarations | 确认对外表述 |
| N41 完成发布检查 | 质量检查 | PLATFORM | N37, N38, N39, N40 | PLAN_ONLY 制作/检查方案 | technicalChecks, contentChecks, rightsChecks, releaseManifestHash | 确认事实、隐私、授权范围和整体成片 |
| N42 上传与设置 | 发布执行 | PLATFORM | N41 | PLAN_ONLY 制作/检查方案 | platform, accountId, uploadStatus, draftId, manualInstructions | 授权/设置异常时处理 |
| N43 预览与确认发布 | 发布执行 | PLATFORM | N42 | PLAN_ONLY 制作/检查方案 | platform, accountId, manifestHash, submissionStatus, remoteId | 通过 G05 明确授权；手工发布可导入凭证 |
| N44 检查发布结果 | 发布执行 | PLATFORM | N43 | PLAN_ONLY 制作/检查方案 | platform, visibility, status, workUrl, checkedAt | 申诉或重新判断时介入 |
| N45 回复与收集反馈 | 互动反馈 | PLATFORM | N44 | PLAN_ONLY 制作/检查方案 | comments, questions, replyDrafts, sentReceipts | 确认回复及合作、争议与承诺 |
| N46 记录数据 | 数据复盘 | PLATFORM | N44 | PLAN_ONLY 制作/检查方案 | platform, observedAt, window, metrics, source | 异常口径时介入 |
| N47 分析内容表现 | 数据复盘 | PROJECT | N45, N46 | GENERATE_TEXT 文字候选 | comparisons, hypotheses, confounders, evidenceRefs | 结合内容与背景判断 |
| N48 选择下一次改进 | 数据复盘 | PROJECT | N47 | GENERATE_TEXT 文字候选 | chosenChange, reason, measurementPlan, nextIterationRef | 选择优先改进方向；纳入 G06 |
| N49 沉淀可复用资产 | 资产管理 | PROJECT | N47, N48 | PLAN_ONLY 制作/检查方案 | assetRefs, tags, sourceLinks, reuseConstraints | 新增主观优秀标准时确认 |
| N50 检查副业价值 | 经营分析 | ACCOUNT | N49 | GENERATE_TEXT 文字候选 | period, costs, revenue, outcomes, decision | 通过 G06 决定下一周期投入 |
