"""Validate, extract facts, resolve sources, apply all rules, render stable output."""

from __future__ import annotations

import logging
import re

from .extraction import (
    DocumentExtraction,
    document_timestamp,
    extract_documents,
    resolve_document,
    source_for,
)
from .facts import FactBundle, resolve_measurements, resolve_structured
from .medication import reconcile_medications
from .models import PatientSubmission, TriageOutput
from .policy import ISSUE_ORDER
from .provenance import ResolvedFact, SourceRef
from .rules import (
    determine_decision,
    evaluate_acute_safety,
    evaluate_anticoagulation,
    evaluate_documentation,
    evaluate_missing_required_data,
    evaluate_testing,
)

logger = logging.getLogger(__name__)


def resolve_facts(
    submission: PatientSubmission, extraction: DocumentExtraction
) -> FactBundle:
    facts, measurements = resolve_structured(submission)
    measurements.extend(extraction.measurements)
    facts.blood_pressure = resolve_measurements(measurements, "blood_pressure")
    facts.temperature = resolve_measurements(measurements, "temperature")
    ambiguous_hp = [
        source_for(submission.documents[q.document_index], q.document_index)
        for q in extraction.queries
        if q.kind == "HP"
    ]
    ambiguous_consent = [
        source_for(submission.documents[q.document_index], q.document_index)
        for q in extraction.queries
        if q.kind == "CONSENT"
    ]
    facts.hp = resolve_document(
        extraction.hp, ambiguous_hp, extraction.negative_hp, "HP"
    )
    facts.consent = resolve_document(
        extraction.consents, ambiguous_consent, extraction.negative_consents, "CONSENT"
    )
    facts.medications = reconcile_medications(submission, extraction.medications)
    facts.plans = extraction.plans
    for query in extraction.queries:
        if query.kind in ("MEDICATION", "VITAL"):
            source = source_for(
                submission.documents[query.document_index], query.document_index
            )
            if query.kind == "MEDICATION":
                facts.unresolved.append(source)
            if query.kind == "VITAL":
                document = submission.documents[query.document_index]
                observed = document_timestamp(document)
                unresolved_kinds = {
                    kind
                    for kind, _ in extraction.vital_gaps.get(query.document_index, [])
                }
                for attr, pattern in (
                    (
                        "blood_pressure",
                        r"blood pressure|\bBP\b|NIBP|recheck|re-measured",
                    ),
                    ("temperature", r"temperature|temp|Celsius|Fahrenheit"),
                ):
                    fact = getattr(facts, attr)
                    if (
                        attr in unresolved_kinds
                        or (
                            not unresolved_kinds
                            and re.search(pattern, document.text or "", re.I)
                        )
                    ) and (
                        observed is None
                        or fact.state != "KNOWN"
                        or observed.date() >= fact.value.observed_at.date()
                    ):
                        setattr(
                            facts, attr, ResolvedFact(state="AMBIGUOUS", source=source)
                        )
    for index, medication in enumerate(submission.medications):
        if medication.active is not False and not (medication.name or "").strip():
            facts.unresolved.append(
                SourceRef(
                    path=f"medications[{index}].name",
                    details=f"name={medication.name!r}; active={medication.active!r}; medication identity cannot be classified",
                )
            )
    logger.debug(
        "Selected H&P: %s state=%s; consent: %s state=%s",
        facts.hp.source.path,
        facts.hp.state,
        facts.consent.source.path,
        facts.consent.state,
    )
    logger.debug(
        "Active anticoagulants: %s",
        sorted(m.name for m in facts.medications.values() if m.status == "ACTIVE"),
    )
    logger.debug(
        "Plan facts: %s",
        [(p.source.path, p.medication, p.preop, p.postop) for p in facts.plans],
    )
    return facts


def evaluate_facts(facts: FactBundle) -> TriageOutput:
    issues = []
    for evaluator in (
        evaluate_missing_required_data,
        evaluate_documentation,
        evaluate_testing,
        evaluate_anticoagulation,
        evaluate_acute_safety,
    ):
        issues.extend(evaluator(facts))
    unique = {
        (i.category, i.description, i.evidence.source, i.evidence.details): i
        for i in issues
    }
    ordered = sorted(
        unique.values(),
        key=lambda i: (
            ISSUE_ORDER[i.category],
            i.description,
            i.evidence.source,
            i.evidence.details,
        ),
    )
    explanation = (
        " | ".join(f"{i.category}: {i.description}" for i in ordered)
        if ordered
        else "All required criteria are satisfied."
    )
    return TriageOutput(
        decision=determine_decision(ordered), issues=ordered, explanation=explanation
    )


def triage_submission(
    submission: dict[str, object] | PatientSubmission, *, model: str
) -> TriageOutput:
    from .semantic import resolve_semantics

    validated = (
        submission
        if isinstance(submission, PatientSubmission)
        else PatientSubmission.model_validate(submission)
    )
    extraction = extract_documents(validated)
    extraction = resolve_semantics(validated, extraction, model=model)
    return evaluate_facts(resolve_facts(validated, extraction))
