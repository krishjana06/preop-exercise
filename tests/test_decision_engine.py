from copy import deepcopy

import pytest

from core import PatientSubmission, triage_submission


@pytest.mark.parametrize(
    "blocks,decision,expected",
    [
        ([], "READY", set()),
        (["documentation"], "NEEDS_FOLLOW_UP", {"REQUIRED_DOCUMENTATION"}),
        (["testing"], "NEEDS_FOLLOW_UP", {"REQUIRED_TESTING"}),
        (["anticoagulation"], "NEEDS_FOLLOW_UP", {"ANTICOAGULATION_MANAGEMENT"}),
        (["safety"], "NOT_CLEARED", {"ACUTE_SAFETY_EXCLUSION"}),
        (
            ["safety", "documentation"],
            "NOT_CLEARED",
            {"ACUTE_SAFETY_EXCLUSION", "REQUIRED_DOCUMENTATION"},
        ),
        (
            ["safety", "testing"],
            "NOT_CLEARED",
            {"ACUTE_SAFETY_EXCLUSION", "REQUIRED_TESTING"},
        ),
        (
            ["testing", "anticoagulation"],
            "NEEDS_FOLLOW_UP",
            {"REQUIRED_TESTING", "ANTICOAGULATION_MANAGEMENT"},
        ),
        (
            ["safety", "documentation", "testing", "anticoagulation"],
            "NOT_CLEARED",
            {
                "ACUTE_SAFETY_EXCLUSION",
                "REQUIRED_DOCUMENTATION",
                "REQUIRED_TESTING",
                "ANTICOAGULATION_MANAGEMENT",
            },
        ),
    ],
)
def test_all_independent_issues_retained(submission, blocks, decision, expected):
    for block in blocks:
        if block == "documentation":
            submission["documents"] = []
        elif block == "testing":
            submission["labs"] = []
        elif block == "anticoagulation":
            submission["medications"] = [{"name": "Eliquis", "active": True}]
        else:
            submission["vitals"][0]["systolic"] = 180
    output = triage_submission(submission, model="unused")
    assert output.decision == decision
    assert {i.category for i in output.issues} == expected


def test_output_and_explanation_are_exactly_repeatable(submission):
    submission["vitals"][0]["systolic"] = 180
    submission["labs"] = []
    outputs = [
        triage_submission(submission, model="unused").model_dump_json()
        for _ in range(5)
    ]
    assert len(set(outputs)) == 1
    result = triage_submission(submission, model="unused")
    assert result.explanation == " | ".join(
        f"{i.category}: {i.description}" for i in result.issues
    )
    assert [i.category for i in result.issues] == [
        "REQUIRED_TESTING",
        "ACUTE_SAFETY_EXCLUSION",
    ]


def test_input_dict_and_model_are_not_mutated(submission):
    snapshot = deepcopy(submission)
    triage_submission(submission, model="unused")
    assert submission == snapshot
    validated = PatientSubmission.model_validate(submission)
    model_snapshot = validated.model_dump()
    triage_submission(validated, model="unused")
    assert validated.model_dump() == model_snapshot


@pytest.mark.parametrize("array", ["labs", "vitals", "documents"])
def test_array_order_does_not_change_policy_result(submission, array):
    submission["labs"].append(
        {"code": "CBC", "status": "final", "effective_at": "2030-04-01"}
    )
    submission["vitals"].append(
        {
            "type": "blood_pressure",
            "systolic": 190,
            "diastolic": 120,
            "date": "2030-06-10",
        }
    )
    submission["documents"].append(
        {
            "type": "Radiology report",
            "date": "2030-06-29",
            "text": "Routine imaging without pertinent findings.",
        }
    )
    before = triage_submission(submission, model="unused")
    submission[array].reverse()
    after = triage_submission(submission, model="unused")
    assert before.decision == after.decision
    assert [(i.category, i.description) for i in before.issues] == [
        (i.category, i.description) for i in after.issues
    ]


def test_irrelevant_documents_do_not_change_exact_output(submission):
    submission["documents"].extend(
        [
            {
                "type": "Social Work Note",
                "date": "2030-06-29",
                "text": "Ride home arranged.",
            },
            {
                "type": "Nutrition Consult",
                "date": "2030-06-29",
                "text": "Protein intake reviewed.",
            },
        ]
    )
    first = triage_submission(submission, model="unused")
    submission["documents"][-2:] = reversed(submission["documents"][-2:])
    second = triage_submission(submission, model="unused")
    assert first == second


def test_missing_procedure_type_with_explicit_documents_is_uncertain(submission):
    submission["procedure"]["procedure_type"] = None
    assert triage_submission(submission, model="unused").decision == "NEEDS_FOLLOW_UP"
