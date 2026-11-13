"""按同一场景比较人工评分；不调用模型，不推断统计显著性。"""
import argparse
import json
from pathlib import Path

from score_review import evaluate


def compare(cases, baseline, treatment):
    """每组记录包含 caseId、candidate、review；检查配对、评分标准与评审身份。"""
    by_id = {case["id"]: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("场景 ID 重复")

    def index(records):
        result = {}
        for record in records:
            case_id = record.get("caseId")
            if case_id not in by_id or case_id in result:
                raise ValueError("场景不存在或重复")
            report = evaluate(by_id[case_id], record["candidate"], record["review"])
            result[case_id] = (report, record["review"])
        return result

    left, right = index(baseline), index(treatment)
    if not left or left.keys() != right.keys():
        raise ValueError("基线和改进组必须包含相同且非空的场景集合")
    pairs = []
    for case_id in sorted(left):
        before, before_review = left[case_id]
        after, after_review = right[case_id]
        if before_review["reviewer"].strip() != after_review["reviewer"].strip():
            raise ValueError("同一场景的两组评分应由同一评审配对；多评审请分别生成报告")
        pairs.append({"caseId": case_id, "baselineScore": before["score"],
                      "candidateScore": after["score"], "maximum": before["maximum"],
                      "delta": after["score"] - before["score"],
                      "baselineViolations": before["violations"], "candidateViolations": after["violations"],
                      "reviewer": before_review["reviewer"]})
    return {"pairs": pairs, "totalDelta": sum(p["delta"] for p in pairs),
            "notice": "仅汇总配对人工判断，不能证明统计显著性或领域能力；须独立复核禁用行为和失败案例。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="基线记录 JSON 数组")
    parser.add_argument("--candidate", type=Path, required=True, help="改进组记录 JSON 数组")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    result = compare(read(args.scenarios)["cases"], read(args.baseline), read(args.candidate))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
