import pytest

from preop.facts import resolve_structured
from preop.models import PatientSubmission
from preop.rules import evaluate_acute_safety, evaluate_missing_required_data


@pytest.mark.parametrize(
    "systolic,diastolic,temp,excluded",
    [
        (179, 109, 100.4, False),
        (180, 109, 100.4, True),
        (179, 110, 100.4, True),
        (120, 80, 100.5, True),
    ],
)
def test_exact_safety_boundaries(submission, systolic, diastolic, temp, excluded):
    submission["vitals"][0].update(systolic=systolic, diastolic=diastolic)
    submission["vitals"][1]["value_f"] = temp
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert bool(evaluate_acute_safety(facts)) is excluded


def test_later_safe_bp_overrides_abnormal(submission):
    submission["vitals"].append(
        {
            "type": "blood_pressure",
            "systolic": 190,
            "diastolic": 115,
            "date": "2030-06-27",
        }
    )
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert not evaluate_acute_safety(facts)


def test_incomplete_latest_bp_preserves_known_exclusion(submission):
    submission["vitals"][0].update(systolic=190, diastolic=None)
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert evaluate_acute_safety(facts)
    assert evaluate_missing_required_data(facts)


def test_missing_temperature_is_required_data(submission):
    submission["vitals"].pop()
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert evaluate_missing_required_data(facts)[0].category == "MISSING_REQUIRED_DATA"


def test_undated_measurement_cannot_be_declared_latest(submission):
    submission["vitals"][0]["date"] = None
    facts, _ = resolve_structured(PatientSubmission.model_validate(submission))
    assert facts.blood_pressure.state == "AMBIGUOUS"


@pytest.mark.parametrize(
    "text,excluded",
    [
        ("08:06 BP 189/112. 08:30 repeat BP 137/78. T 37.0 C", False),
        ("08:06 BP 137/78. 08:30 repeat BP 189/112. T 37.0 C", True),
        ("08:30 Blood pressure 120/80, Temperature 38.6 °C", True),
        ("08:30 NIBP 120/80, 38.0 °C temporal", False),
    ],
)
def test_newer_document_measurements(submission, text, excluded):
    from core import triage_submission

    submission["documents"].append(
        {"type": "Nursing Intake", "date": "2030-06-29", "text": text}
    )
    assert (
        triage_submission(submission, model="unused").decision == "NOT_CLEARED"
    ) is excluded


def test_later_flowsheet_reference_does_not_replace_measurement(submission):
    from core import triage_submission

    submission["vitals"][0]["systolic"] = 190
    submission["documents"].append(
        {"date": "2030-06-29", "text": "Vital signs: see flowsheet."}
    )
    assert triage_submission(submission, model="unused").decision == "NOT_CLEARED"


def test_conditional_threshold_is_not_an_observation(submission):
    from core import triage_submission

    submission["documents"].append(
        {"date": "2030-06-29", "text": "Call if BP 180/110 or Temperature 101.0 F."}
    )
    assert triage_submission(submission, model="unused").decision == "READY"


def test_unlabelled_mmhg_recheck_in_addendum(submission):
    from core import triage_submission

    submission["documents"].append(
        {
            "date": "2030-06-29",
            "text": "08:00 NIBP 190/115.\nADDENDUM 08:30: Re-measured 130/75 mmHg following rest. Temperature 98.6 F.",
        }
    )
    assert triage_submission(submission, model="unused").decision == "READY"
