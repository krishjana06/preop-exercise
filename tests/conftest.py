from copy import deepcopy
import pytest


@pytest.fixture(autouse=True)
def no_live_api_in_unit_tests(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PREOP_FALLBACK_MODEL", raising=False)


@pytest.fixture
def submission():
    return deepcopy({
        "procedure": {"procedure_type": "Example repair", "procedure_date": "2030-06-30", "procedure_risk": "LOW"},
        "vitals": [
            {"type": "blood_pressure", "systolic": 120, "diastolic": 80, "date": "2030-06-28T10:00:00Z"},
            {"type": "temperature", "value_f": 98.6, "date": "2030-06-28T10:00:00Z"},
        ],
        "labs": [{"code": "CBC", "effective_at": "2030-06-20T08:00:00Z", "status": "final"}],
        "medications": [],
        "documents": [
            {"type": "Pre-op H&P", "date": "2030-06-20", "text": "PREOPERATIVE HISTORY AND PHYSICAL\nPlanned procedure: Example repair\nHistory and exam completed for planned procedure."},
            {"type": "Surgical Consent", "date": "2030-06-21", "text": "Procedure: Example repair\nPatient signature: /s/ Example Person (electronically signed)."},
        ],
    })
