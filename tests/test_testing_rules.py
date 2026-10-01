from datetime import date, timedelta

import pytest

from preop.facts import resolve_structured
from preop.models import PatientSubmission
from preop.rules import evaluate_missing_required_data, evaluate_testing


def lab_issues(submission):
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    return evaluate_testing(facts)


@pytest.mark.parametrize(
    "risk,code,age,blocked",
    [
        ("LOW", "CBC", 30, False),
        ("LOW", "CBC", 31, True),
        ("MODERATE", "CBC", 30, False),
        ("MODERATE", "CBC", 31, True),
        ("HIGH", "CBC", 14, False),
        ("HIGH", "CBC", 15, True),
        ("HIGH", "CMP", 14, False),
        ("HIGH", "CMP", 15, True),
        ("LOW", "CBC", -1, True),
    ],
)
def test_lab_windows(submission, risk, code, age, blocked):
    submission["procedure"]["procedure_risk"] = risk
    submission["labs"] = [
        {"code": c, "effective_at": "2030-06-29", "status": "final"}
        for c in ("CBC", "CMP")
    ]
    target = next(lab for lab in submission["labs"] if lab["code"] == code)
    target["effective_at"] = str(date(2030, 6, 30) - timedelta(days=age))
    assert bool(lab_issues(submission)) is blocked


def test_filter_error_before_latest_and_alias(submission):
    submission["labs"] += [
        {"code": "LAB-CBC", "effective_at": "2030-06-29", "status": "entered-in-error"}
    ]
    assert not lab_issues(submission)
    submission["labs"][0]["code"] = "LAB-CBC"
    assert not lab_issues(submission)


def test_bmp_does_not_satisfy_high_risk_cmp(submission):
    submission["procedure"]["procedure_risk"] = "HIGH"
    submission["labs"].append(
        {"code": "LAB-BMP", "status": "final", "effective_at": "2030-06-29"}
    )
    assert any("CMP" in i.description for i in lab_issues(submission))


@pytest.mark.parametrize("field", ["procedure_date", "procedure_risk"])
def test_missing_dependency_suppresses_testing(submission, field):
    submission["procedure"][field] = None
    submission["labs"] = []
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert not evaluate_testing(facts)
    assert len(evaluate_missing_required_data(facts)) == 1


def test_latest_after_procedure_does_not_fall_back_to_older(submission):
    submission["labs"].append(
        {"code": "CBC", "effective_at": "2030-07-01", "status": "final"}
    )
    assert lab_issues(submission)
