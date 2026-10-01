"""Pure policy evaluators. Every issue is supported by a resolved source."""
from __future__ import annotations

from .facts import FactBundle
from .models import Decision, IssueCategory, TriageIssue
from .policy import H_AND_P_MAX_AGE_DAYS, LAB_REQUIREMENTS, MAX_DIASTOLIC_BP, MAX_SYSTOLIC_BP, MAX_TEMPERATURE_F
from .provenance import SourceRef


def issue(category: IssueCategory, description: str, source: SourceRef, details: str) -> TriageIssue:
    return TriageIssue(category=category, description=description, evidence=source.evidence(details))


def evaluate_missing_required_data(facts: FactBundle) -> list[TriageIssue]:
    issues = []
    for name, fact in (("procedure date", facts.procedure_date), ("procedure risk", facts.risk), ("blood pressure", facts.blood_pressure), ("temperature", facts.temperature)):
        if fact.state != "KNOWN":
            issues.append(issue("MISSING_REQUIRED_DATA", f"Missing or unresolved {name}", fact.source, f"Required {name} is {fact.state.lower()}"))
    if facts.blood_pressure.state == "KNOWN":
        measurement = facts.blood_pressure.value
        if measurement.systolic is None or measurement.diastolic is None:
            issues.append(issue("MISSING_REQUIRED_DATA", "Incomplete latest blood pressure", measurement.source, "Both systolic and diastolic values are required"))
    for medication in facts.medications.values():
        if medication.status == "UNKNOWN":
            issues.append(issue("MISSING_REQUIRED_DATA", f"Unknown active status for {medication.name}", medication.source, "Current anticoagulant use cannot be established"))
    for source in facts.unresolved:
        issues.append(issue("MISSING_REQUIRED_DATA", "Unresolved required document fact", source, "Semantic extraction could not establish a grounded required fact"))
    for name, fact in (("H&P", facts.hp), ("consent", facts.consent)):
        if fact.state == "AMBIGUOUS":
            issues.append(issue("MISSING_REQUIRED_DATA", f"Unresolved {name} evidence", fact.source, "Required document meaning or date is ambiguous"))
    if facts.procedure_date.state == "KNOWN" and facts.risk.state == "KNOWN":
        for code in LAB_REQUIREMENTS[facts.risk.value]:
            lab = facts.labs[code]
            if lab.state == "AMBIGUOUS":
                issues.append(issue("MISSING_REQUIRED_DATA", f"Unresolved {code} result date", lab.source, "Cannot determine the newest finalized result"))
    return issues


def evaluate_documentation(facts: FactBundle) -> list[TriageIssue]:
    issues = []
    if facts.hp.state == "MISSING":
        issues.append(issue("REQUIRED_DOCUMENTATION", "Missing applicable preoperative H&P", facts.hp.source, "No completed preoperative history and physical for the scheduled procedure"))
    elif facts.hp.state == "KNOWN" and facts.procedure_date.state == "KNOWN":
        age = (facts.procedure_date.value - facts.hp.value.day).days
        if not 0 <= age <= H_AND_P_MAX_AGE_DAYS:
            issues.append(issue("REQUIRED_DOCUMENTATION", "Preoperative H&P outside required window", facts.hp.source, f"H&P date {facts.hp.value.day} is {age} days before procedure date {facts.procedure_date.value}; allowed interval is 0 to {H_AND_P_MAX_AGE_DAYS} days"))
    if facts.consent.state == "MISSING":
        issues.append(issue("REQUIRED_DOCUMENTATION", "Missing patient-signed surgical consent", facts.consent.source, "No applicable consent explicitly signed by the patient"))
    return issues


def evaluate_testing(facts: FactBundle) -> list[TriageIssue]:
    if facts.procedure_date.state != "KNOWN" or facts.risk.state != "KNOWN":
        return []
    issues = []
    for code, window in LAB_REQUIREMENTS[facts.risk.value].items():
        fact = facts.labs[code]
        if fact.state == "MISSING":
            issues.append(issue("REQUIRED_TESTING", f"Missing required {code}", fact.source, f"{facts.risk.value} risk requires finalized {code} within {window} days before procedure date {facts.procedure_date.value}"))
        elif fact.state == "KNOWN":
            age = (facts.procedure_date.value - fact.value.day).days
            if not 0 <= age <= window:
                issues.append(issue("REQUIRED_TESTING", f"{code} outside required window", fact.source, f"Most recent valid {code} dated {fact.value.day} is {age} days before procedure date {facts.procedure_date.value}; {facts.risk.value} risk requires 0 to {window} days"))
    return issues


def evaluate_anticoagulation(facts: FactBundle) -> list[TriageIssue]:
    issues = []
    for medication in facts.medications.values():
        if medication.status != "ACTIVE":
            continue
        matching = [p for p in facts.plans if p.medication == medication.name and p.applies is True]
        # A newer documented incomplete plan supersedes an older complete plan.
        dated = [p for p in matching if p.observed_at is not None]
        latest = max((p.observed_at for p in dated), default=None)
        current = [p for p in matching if p.observed_at == latest]
        complete = current and all(p.preop and p.postop for p in current)
        if not complete:
            plan = min(current, key=lambda p: (p.source.quote or "", p.source.path)) if current else None
            source = plan.source if plan else medication.source
            details = f"Active {medication.name}: {medication.source.path}"
            if medication.source.quote:
                details += f'; active-use excerpt: "{medication.source.quote}"'
            if plan:
                details += f"; plan preoperative instructions={plan.preop}, postoperative instructions={plan.postop}"
            else:
                details += "; no applicable plan for the current anticoagulant found"
            issues.append(issue("ANTICOAGULATION_MANAGEMENT", f"Missing or incomplete perioperative plan for {medication.name}", source, details))
    return issues


def evaluate_acute_safety(facts: FactBundle) -> list[TriageIssue]:
    issues = []
    if facts.blood_pressure.state == "KNOWN":
        bp = facts.blood_pressure.value
        if (bp.systolic is not None and bp.systolic >= MAX_SYSTOLIC_BP) or (bp.diastolic is not None and bp.diastolic >= MAX_DIASTOLIC_BP):
            issues.append(issue("ACUTE_SAFETY_EXCLUSION", "Latest blood pressure meets safety exclusion", bp.source, f"Latest BP {bp.systolic:g}/{bp.diastolic:g} mmHg at {bp.observed_at}; exclusion is systolic >= {MAX_SYSTOLIC_BP} or diastolic >= {MAX_DIASTOLIC_BP}" if bp.systolic is not None and bp.diastolic is not None else f"Latest BP systolic={bp.systolic}, diastolic={bp.diastolic}; exclusion is systolic >= {MAX_SYSTOLIC_BP} or diastolic >= {MAX_DIASTOLIC_BP}"))
    if facts.temperature.state == "KNOWN":
        temp = facts.temperature.value
        if temp.temperature_f > MAX_TEMPERATURE_F:
            issues.append(issue("ACUTE_SAFETY_EXCLUSION", "Latest temperature meets safety exclusion", temp.source, f"Latest temperature {temp.temperature_f:g} F at {temp.observed_at}; exclusion is temperature > {MAX_TEMPERATURE_F} F"))
    return issues


def determine_decision(issues: list[TriageIssue]) -> Decision:
    if any(item.category == "ACUTE_SAFETY_EXCLUSION" for item in issues):
        return "NOT_CLEARED"
    return "NEEDS_FOLLOW_UP" if issues else "READY"
