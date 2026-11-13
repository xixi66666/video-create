"""校验模型提出的会诊意见对照；不判定谁正确，也不代替人工核实。"""


def validate_comparison(comparison, opinions):
    if not isinstance(comparison, dict) or set(comparison) != {"summary", "differences"}:
        raise ValueError("会诊对照须包含 summary 与 differences")
    summary, differences = comparison["summary"], comparison["differences"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise ValueError("会诊对照摘要为空或过长")
    if not isinstance(differences, list) or len(differences) > 20:
        raise ValueError("会诊分歧列表无效")
    by_role = {opinion["role"]: opinion for opinion in opinions}
    verified = []
    for item in differences:
        if not isinstance(item, dict) or set(item) != {"topic", "positions"}:
            raise ValueError("分歧须包含 topic 与 positions")
        topic, positions = item["topic"], item["positions"]
        if not isinstance(topic, str) or not topic.strip() or len(topic) > 200:
            raise ValueError("分歧议题为空或过长")
        if not isinstance(positions, list) or not 2 <= len(positions) <= len(by_role):
            raise ValueError("分歧须引用至少两位不同专家")
        cited, seen = [], set()
        for position in positions:
            if not isinstance(position, dict) or set(position) != {"role", "quote"}:
                raise ValueError("每条观点须包含 role 和 quote")
            role, quote = position["role"], position["quote"]
            if not isinstance(role, str) or role not in by_role or role in seen:
                raise ValueError("分歧引用角色不存在或重复")
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 1000:
                raise ValueError("会诊引用为空或过长")
            opinion = by_role[role]
            evidence = [opinion["analysis"], *opinion["sources"], *opinion["uncertainties"]]
            if not any(isinstance(value, str) and quote in value for value in evidence):
                raise ValueError("会诊引用不在对应专家原文中")
            seen.add(role)
            cited.append({"role": role, "quote": quote, "opinionHash": opinion["sha256"]})
        verified.append({"topic": topic, "positions": cited})
    return {"summary": summary, "differences": verified,
            "notice": "主责专家归纳，仅核对引文属于对应会诊意见；是否构成分歧、事实是否正确须由人判断。未列出分歧不代表意见完全一致。"}
