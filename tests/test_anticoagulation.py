import pytest
from core import triage_submission
from preop.medication import anticoagulants


def add_plan(submission, text, day="2030-06-22"):
    submission["documents"].append({"type": "Perioperative Medication Plan", "date": day, "text": text})


def categories(submission):
    return {i.category for i in triage_submission(submission, model="unused").issues}


@pytest.mark.parametrize("name,expected", [("Eliquis 5 mg", "apixaban"), ("Xarelto", "rivaroxaban"), ("Coumadin", "warfarin"), ("Pradaxa", "dabigatran"), ("Savaysa", "edoxaban")])
def test_aliases(name, expected):
    assert anticoagulants(name) == {expected}


@pytest.mark.parametrize("name", ["aspirin", "ASA", "clopidogrel"])
def test_antiplatelets_are_not_anticoagulants(submission, name):
    submission["medications"] = [{"name": name, "active": True}]
    assert triage_submission(submission, model="unused").decision == "READY"


def test_text_only_active_medication_needs_plan(submission):
    add_plan(submission, "Patient reports taking Xarelto 20 mg daily.")
    assert "ANTICOAGULATION_MANAGEMENT" in categories(submission)


def test_unknown_activity_is_missing_data(submission):
    submission["medications"] = [{"name": "Coumadin", "active": None}]
    assert categories(submission) == {"MISSING_REQUIRED_DATA"}


def test_inactive_anticoagulant_has_no_plan_requirement(submission):
    submission["medications"] = [{"name": "warfarin", "active": False}]
    assert triage_submission(submission, model="unused").decision == "READY"


@pytest.mark.parametrize("text", ["Hold Eliquis 2 days before surgery.", "Resume Eliquis after surgery.", "Patient takes Eliquis. Follow up with cardiology.", "Recommend discussing interruption of Eliquis; specific recommendations will follow."])
def test_incomplete_plan(submission, text):
    submission["medications"] = [{"name": "apixaban", "active": True}]
    add_plan(submission, text)
    assert "ANTICOAGULATION_MANAGEMENT" in categories(submission)


def test_complete_brand_name_plan(submission):
    submission["medications"] = [{"name": "apixaban", "active": True}]
    add_plan(submission, "Hold Eliquis 2 days before surgery. Resume Eliquis 24 hours after surgery once hemostasis is secure.")
    assert triage_submission(submission, model="unused").decision == "READY"


def test_current_switch_invalidates_old_plan(submission):
    submission["medications"] = [{"name": "warfarin", "active": True}]
    add_plan(submission, "Hold warfarin 5 days before surgery. Resume warfarin after surgery.")
    add_plan(submission, "MEDICATION RECONCILIATION:\nPatient switched from warfarin to apixaban.", "2030-06-28")
    assert categories(submission) == {"ANTICOAGULATION_MANAGEMENT"}


def test_unknown_text_status_supersedes_structured_active(submission):
    submission["medications"] = [{"name": "warfarin", "active": True}]
    add_plan(submission, "Coumadin: patient unable to confirm whether still taking.", "2030-06-28")
    assert categories(submission) == {"MISSING_REQUIRED_DATA"}


def test_newer_incomplete_plan_supersedes_old_complete(submission):
    submission["medications"] = [{"name": "apixaban", "active": True}]
    add_plan(submission, "Hold Eliquis before surgery. Resume Eliquis after surgery.")
    add_plan(submission, "Planned procedure: Example repair\nHold Eliquis before surgery. Postoperative management will be addressed after surgery.", "2030-06-27")
    assert categories(submission) == {"ANTICOAGULATION_MANAGEMENT"}
