"""Compatibility facade for the supplied runner, evaluator, and report viewer."""

from preop.engine import triage_submission
from preop.models import (
    BloodPressureVital,
    Condition,
    Decision,
    Document,
    Evidence,
    GenericVital,
    IssueCategory,
    LabResult,
    Medication,
    PatientInfo,
    PatientName,
    PatientSubmission,
    ProcedureInfo,
    ProcedureRisk,
    SubmissionMetadata,
    TemperatureVital,
    TriageIssue,
    TriageOutput,
    Vital,
)

__all__ = [
    "Decision",
    "ProcedureRisk",
    "IssueCategory",
    "PatientName",
    "PatientInfo",
    "ProcedureInfo",
    "BloodPressureVital",
    "TemperatureVital",
    "GenericVital",
    "Vital",
    "LabResult",
    "Medication",
    "Condition",
    "Document",
    "SubmissionMetadata",
    "PatientSubmission",
    "Evidence",
    "TriageIssue",
    "TriageOutput",
    "triage_submission",
    "triage_output_json_schema",
]


def triage_output_json_schema() -> dict[str, object]:
    return TriageOutput.model_json_schema()
