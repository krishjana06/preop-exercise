from datetime import date

import pytest

from preop.models import PatientSubmission, TriageOutput
from preop.normalize import calendar_date, fahrenheit, lab_code, timestamp


@pytest.mark.parametrize(
    "raw", ["2030-04-01", "2030-04-01T23:59:00-07:00", "04/01/2030"]
)
def test_calendar_date_preserves_local_day(raw):
    assert calendar_date(raw) == date(2030, 4, 1)


@pytest.mark.parametrize("raw", [None, "", "nonsense", "2030-02-30"])
def test_invalid_dates_are_unknown(raw):
    assert calendar_date(raw) is None


def test_utc_order_and_conversion():
    assert timestamp("2030-04-01T10:00:00-04:00") == timestamp("2030-04-01T14:00:00Z")
    assert fahrenheit(38, "C") == 100.4


def test_lab_aliases_do_not_promote_bmp():
    assert lab_code("LAB-CBC") == "CBC"
    assert lab_code("LAB-CMP") == "CMP"
    assert lab_code("BMP", "Comprehensive metabolic panel") is None


def test_vital_validation_preserves_temperature():
    record = PatientSubmission(
        vitals=[{"type": "temperature", "value_f": 99, "date": "2030-04-01"}]
    )
    assert record.vitals[0].value_f == 99


def test_rich_evidence_schema():
    output = TriageOutput(
        decision="NEEDS_FOLLOW_UP",
        issues=[
            {
                "category": "MISSING_REQUIRED_DATA",
                "description": "Missing date",
                "evidence": {"source": "procedure.procedure_date", "details": "null"},
            }
        ],
        explanation="Missing date",
    )
    assert output.issues[0].evidence.source == "procedure.procedure_date"
