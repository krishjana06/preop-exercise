from core import triage_submission
from preop.extraction import document_day
from preop.models import Document
from preop.normalize import calendar_date


def test_procedure_date_in_note_does_not_become_service_date():
    document = Document(
        date="2030-06-20",
        text="PREOPERATIVE HISTORY AND PHYSICAL\nProcedure date: 2030-06-30\nPlanned procedure: Example repair",
    )
    assert str(document_day(document)) == "2030-06-20"


def test_invalid_date_suffix_is_not_accepted():
    assert calendar_date("2030-06-20nonsense") is None


def test_unknown_risk_is_not_inferred_from_name(submission):
    submission["procedure"].update(
        procedure_type="Elective major operation", procedure_risk="UNKNOWN"
    )
    output = triage_submission(submission, model="unused")
    assert output.decision == "NEEDS_FOLLOW_UP"
    assert any(i.evidence.source == "procedure.procedure_risk" for i in output.issues)
    assert not any(i.category == "REQUIRED_TESTING" for i in output.issues)


def test_equal_timestamp_conflicting_vitals_remain_ambiguous(submission):
    submission["vitals"].append(
        {
            "type": "blood_pressure",
            "systolic": 190,
            "diastolic": 120,
            "date": "2030-06-28T10:00:00Z",
        }
    )
    output = triage_submission(submission, model="unused")
    assert output.decision == "NEEDS_FOLLOW_UP"
    assert {i.category for i in output.issues} == {"MISSING_REQUIRED_DATA"}


def test_failed_newer_vital_semantics_does_not_use_old_bp_as_latest(submission):
    submission["vitals"][0]["systolic"] = 190
    submission["documents"].append(
        {
            "type": "Nursing intake",
            "date": "2030-06-29",
            "text": "Blood pressure measured 130 over 80.",
        }
    )
    output = triage_submission(submission, model="unused")
    assert output.decision == "NEEDS_FOLLOW_UP"
    assert {i.category for i in output.issues} == {"MISSING_REQUIRED_DATA"}


def test_unknown_temperature_units_never_clear_using_older_value(submission):
    submission["documents"].append(
        {
            "type": "Nursing intake",
            "date": "2030-06-29",
            "text": "Temperature 38.4 degrees Celsius.",
        }
    )
    output = triage_submission(submission, model="unused")
    assert output.decision == "NEEDS_FOLLOW_UP"
    assert any(i.category == "MISSING_REQUIRED_DATA" for i in output.issues)


def test_specialist_plan_without_physical_exam_is_not_an_hp_candidate(submission):
    submission["documents"].pop(0)
    submission["documents"].append(
        {
            "type": "Hematology Consultation",
            "date": "2030-06-25",
            "text": "Reason: perioperative medication management for planned Example repair.\nHPI: No history of major bleeding.\nASSESSMENT: acceptable risk for the procedure.",
        }
    )
    output = triage_submission(submission, model="unused")
    assert {i.category for i in output.issues} == {"REQUIRED_DOCUMENTATION"}
