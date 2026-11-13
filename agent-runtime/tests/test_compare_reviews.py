import importlib.util
import sys
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1] / "evals"
sys.path.insert(0, str(EVALS))
spec = importlib.util.spec_from_file_location("compare_reviews", EVALS / "compare_reviews.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from score_review import make_template


def record(case, score, body="answer", reviewer="expert"):
    candidate = {"body": body}
    review = make_template(case, candidate)
    review.update(reviewer=reviewer, model="test", modelConfiguration="{}", profileVersion="1.2.0",
                  profileSha256="a" * 64, limitations="测试", unresolvedIssues="无")
    review["criteria"][0].update(score=score, evidence="人工核对")
    review["forbidden"][0].update(observed=False, evidence="人工核对")
    return {"caseId": case["id"], "candidate": candidate, "review": review}


def test_compare_paired_reviews_and_reject_mismatches():
    case = {"id": "c1", "humanReviewExpected": ["方法"], "humanReviewForbidden": ["编造"]}
    before, after = record(case, 0), record(case, 2, "improved")
    report = module.compare([case], [before], [after])
    assert report["totalDelta"] == 2
    assert report["pairs"][0]["candidateViolations"] == []
    with pytest.raises(ValueError, match="相同"):
        module.compare([case], [before], [])
    with pytest.raises(ValueError, match="同一评审"):
        module.compare([case], [before], [record(case, 2, reviewer="other")])
    after["candidate"]["body"] = "tampered"
    with pytest.raises(ValueError, match="校验和"):
        module.compare([case], [before], [after])
