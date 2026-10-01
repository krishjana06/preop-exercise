from datetime import date, timedelta

import pytest

from core import triage_submission


def categories(submission):
    return {i.category for i in triage_submission(submission, model="unused").issues}


@pytest.mark.parametrize(
    "age,blocked", [(0, False), (30, False), (31, True), (-1, True)]
)
def test_hp_window(submission, age, blocked):
    submission["documents"][0]["date"] = str(date(2030, 6, 30) - timedelta(days=age))
    assert ("REQUIRED_DOCUMENTATION" in categories(submission)) is blocked


@pytest.mark.parametrize(
    "title",
    ["History and Pyhsical", "H&P Note", "Admission H&P", "Clinic H&P (external)"],
)
def test_hp_titles_are_not_authoritative(submission, title):
    submission["documents"][0]["type"] = title
    assert triage_submission(submission, model="unused").decision == "READY"


def test_wellness_hp_does_not_count(submission):
    submission["documents"][0]["text"] = (
        "HISTORY AND PHYSICAL\nEncounter: annual wellness / establish care. No acute complaints."
    )
    assert "REQUIRED_DOCUMENTATION" in categories(submission)


def test_service_date_wins_over_upload_date(submission):
    submission["documents"][0].update(
        date="2030-06-29",
        text="PREOPERATIVE HISTORY AND PHYSICAL\nDate of service: 05/01/2030\nPlanned procedure: Example repair\nHistory and exam completed.",
    )
    assert "REQUIRED_DOCUMENTATION" in categories(submission)


@pytest.mark.parametrize(
    "signature",
    [
        "Patient signature: pending",
        "Patient signature: NOT COMPLETED",
        "Patient signature: __________",
        "Printed for patient review; unsigned",
    ],
)
def test_unsigned_consent(submission, signature):
    submission["documents"][1]["text"] = (
        f"Procedure: Example repair\n{signature}\nElectronically signed by Surgeon Smith."
    )
    assert "REQUIRED_DOCUMENTATION" in categories(submission)


@pytest.mark.parametrize(
    "signature",
    [
        "Patient signature: /s/ Person",
        "Patient signature on file - signed in clinic",
        "Consent obtained and signed by patient",
        "e-signed by patient",
    ],
)
def test_signed_consent(submission, signature):
    submission["documents"][1]["text"] = f"Procedure: Example repair\n{signature}"
    assert triage_submission(submission, model="unused").decision == "READY"


def test_new_signed_consent_supersedes_old_unsigned(submission):
    submission["documents"].append(
        {
            "type": "Surgical Consent",
            "date": "2030-06-19",
            "text": "Procedure: Example repair\nPatient signature: pending",
        }
    )
    assert triage_submission(submission, model="unused").decision == "READY"


def test_wrong_procedure_consent(submission):
    submission["documents"][1]["text"] = (
        "Procedure: Other operation\nPatient signature: /s/ Person"
    )
    assert "REQUIRED_DOCUMENTATION" in categories(submission)


def test_narrative_date_does_not_backfill_missing_procedure_date(submission):
    submission["procedure"]["procedure_date"] = None
    submission["documents"][0]["text"] += "\nTarget procedure date: 2030-06-30"
    assert categories(submission) == {"MISSING_REQUIRED_DATA"}
