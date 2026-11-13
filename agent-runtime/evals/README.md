# 专家人工评测场景

`expert_scenarios.py` 为 19 个专家各准备三条虚构场景：证据边界或缺失材料、角色专业判断，以及冲突或失败边界。生成时从节点目录读取必填字段并校验角色映射；该检查不调用模型、不评判专家回答，也不改变 `domainVerified`。

在项目根目录运行：

```powershell
python -X utf8 agent-runtime/evals/expert_scenarios.py --root . --output expert-scenarios.json
```

将受授权运行的完整候选输出保存为 JSON 后，可为任一场景生成评分表，并填写后汇总：

```powershell
python -X utf8 agent-runtime/evals/score_review.py template --scenarios expert-scenarios.json --case offline-analyst-specialist --candidate candidate.json --output review.json
python -X utf8 agent-runtime/evals/score_review.py score --scenarios expert-scenarios.json --case offline-analyst-specialist --candidate candidate.json --review review.json --output result.json
```

已有 DeepSeek 密钥且明确授权调用时，也可使用 `deepseek_runtime_smoke.py` 对任一虚构场景生成真实候选和事件；此操作会向供应商发送场景文本并产生费用，不能替代领域专家评分。默认运行 `offline-analyst-specialist`；先查看上一步生成的场景 ID，再例如执行：

```powershell
agent-runtime/.venv/Scripts/python.exe -X utf8 agent-runtime/evals/deepseek_runtime_smoke.py --case offline-quality-adversarial --output quality-smoke.json
```

脚本使用环境变量 `DEEPSEEK_API_KEY`、隔离临时数据库，禁用研究和本地媒体工具，不自动采纳。结果包含场景、配置、角色版本、候选和事件；失败与未完成也会记录。模拟场景缺少真实节点依赖和媒体，不表示生产任务已验证；项目不再限制 token，仍限制调用次数和时间，供应商自身限制及计费继续适用。

逐条人工判断 `criteria`：0 为不满足或错误，1 为部分满足或依据不足，2 为满足且有充分依据；`evidence` 写明输出中对应的内容或检查理由。逐条判断 `forbidden` 是否出现，填写 `observed` 和依据。填写评审人、模型及配置、专家版本和 SHA-256、限制与未解决问题；模型配置只记录非敏感参数，不记录密钥、账号或私密输入。评分器只验证这些记录完整、标准未被改写、候选哈希一致，并汇总分数与禁用行为，不自动认定通过、也不验证评审人的专业性。相同场景可对基线和新版本分别使用相同标准盲评，保留完整候选、评审和限制，勿把简单总分视作统计显著性。

人工评审还须检查输出是否符合节点字段与实际工具权限。真实节点仍受依赖和人工审批约束；这些场景不代表可以绕过工作流直接执行所有节点。

这些场景只是起点，每角色三例仍不足以衡量专业水平；需要补充真实授权数据、更多失败和对抗情形、多个独立领域评审与基线对照。结构合同测试和上述人工评分记录均不能替代真实供应商、媒体工具及领域能力验收。真实模型调用需遵守现有授权、费用与数据边界；在取得充分领域评测证据前不要将角色标记为已验证。

## 基线对照

完成同一评审人对基线和改进组的评分后，分别准备 JSON 数组，每项包含 `caseId`、原始 `candidate` 和填写完整的 `review`。同一场景使用同一评审人，其他评审分别成组；避免看到版本信息影响评价，可在评分前由组织者随机化并盲化候选。汇总命令：

```powershell
python -X utf8 agent-runtime/evals/compare_reviews.py --scenarios expert-scenarios.json --baseline baseline.json --candidate candidate-reviews.json --output comparison.json
```

程序复核评分依据、评分标准、候选哈希和场景配对，展示逐例差值和禁用行为；不会计算统计显著性，也不自动授予领域认证。保留原始候选、评分与失败案例；多评审的分歧仍须人工讨论。
