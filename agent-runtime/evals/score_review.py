"""记录并校验人工评测，不调用模型，也不自动判断专业质量。"""
import argparse
import hashlib
import json
from pathlib import Path


def candidate_hash(candidate):
    """固定规范化方式，确保评分对应同一份候选。"""
    content = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def make_template(case, candidate):
    criteria = [{"criterion": item, "score": None, "evidence": ""}
                for item in case["humanReviewExpected"]]
    forbidden = [{"criterion": item, "observed": None, "evidence": ""}
                 for item in case["humanReviewForbidden"]]
    return {"caseId": case["id"], "candidateSha256": candidate_hash(candidate),
            "reviewer": "", "model": "", "modelConfiguration": "", "profileVersion": "",
            "profileSha256": "", "criteria": criteria, "forbidden": forbidden,
            "limitations": "", "unresolvedIssues": ""}


def evaluate(case, candidate, review):
    template = make_template(case, candidate)
    if review.get("caseId") != case["id"] or review.get("candidateSha256") != template["candidateSha256"]:
        raise ValueError("场景 ID 或候选校验和不匹配")
    for field in ("reviewer", "model", "modelConfiguration", "profileVersion", "profileSha256", "limitations", "unresolvedIssues"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            raise ValueError(f"必须填写 {field}；没有未解决问题时填写‘无’")
    profile_hash = review["profileSha256"]
    if len(profile_hash) != 64 or any(c not in "0123456789abcdef" for c in profile_hash):
        raise ValueError("profileSha256 必须为小写 SHA-256")
    for key in ("criteria", "forbidden"):
        entries = review.get(key)
        expected = template[key]
        if not isinstance(entries, list) or len(entries) != len(expected):
            raise ValueError(f"{key} 项数不匹配")
        for entry, reference in zip(entries, expected):
            if not isinstance(entry, dict) or entry.get("criterion") != reference["criterion"]:
                raise ValueError(f"{key} 必须按场景原样填写，不能改写标准")
            if not isinstance(entry.get("evidence"), str) or not entry["evidence"].strip():
                raise ValueError(f"{key} 每项需要人工填写依据或检查说明")
            if key == "criteria" and (type(entry.get("score")) is not int or entry["score"] not in (0, 1, 2)):
                raise ValueError("评分必须是 0、1 或 2")
            if key == "forbidden" and type(entry.get("observed")) is not bool:
                raise ValueError("禁用行为必须明确填写 true 或 false")
    scores = [entry["score"] for entry in review["criteria"]]
    violations = [entry["criterion"] for entry in review["forbidden"] if entry["observed"]]
    return {"caseId": case["id"], "candidateSha256": template["candidateSha256"],
            "score": sum(scores), "maximum": 2 * len(scores), "violations": violations,
            "notice": "仅汇总人工判断，不表示专业能力已验证，也不自动修改 domainVerified。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("template", "score"))
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--candidate", type=Path, required=True, help="候选 JSON 文件")
    parser.add_argument("--review", type=Path, help="人工填写的评分 JSON；score 时必需")
    parser.add_argument("--output", type=Path, help="输出 JSON；不填写时打印")
    args = parser.parse_args()
    cases = json.loads(args.scenarios.read_text(encoding="utf-8"))["cases"]
    matches = [case for case in cases if case["id"] == args.case]
    if len(matches) != 1:
        parser.error("场景 ID 不存在或重复")
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if args.action == "score" and not args.review:
        parser.error("score 需要 --review")
    result = make_template(matches[0], candidate) if args.action == "template" else evaluate(
        matches[0], candidate, json.loads(args.review.read_text(encoding="utf-8")))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
