"""Medication terminology and current-use reconciliation, separate from policy."""
from __future__ import annotations

import re
from .facts import MedicationFact
from .models import Document, PatientSubmission
from .normalize import timestamp
from .provenance import SourceRef

ANTICOAGULANT_ALIASES = {
    "warfarin": ("warfarin", "coumadin"),
    "apixaban": ("apixaban", "eliquis"),
    "rivaroxaban": ("rivaroxaban", "xarelto"),
    "dabigatran": ("dabigatran", "pradaxa"),
    "edoxaban": ("edoxaban", "savaysa"),
}
ANTIPLATELETS = ("aspirin", "asa", "clopidogrel")


def anticoagulants(text: str | None) -> set[str]:
    return {name for name, aliases in ANTICOAGULANT_ALIASES.items() if any(re.search(rf"\b{re.escape(alias)}\b", text or "", re.I) for alias in aliases)}


def canonical_medication(text: str | None) -> str | None:
    names = anticoagulants(text)
    return next(iter(names)) if len(names) == 1 else None


def medication_mentions(document: Document, index: int, observed_at) -> list[MedicationFact]:
    """Use explicit current-use/reconciliation assertions, never a hold command."""
    text = document.text or ""
    mentions = []
    for segment in re.split(r"\n|(?<=[.!?])\s+", text):
        for name in sorted(anticoagulants(segment)):
            aliases = "|".join(re.escape(a) for a in ANTICOAGULANT_ALIASES[name])
            mention = re.search(rf"\b(?:{aliases})\b", segment, re.I)
            before, after = segment[:mention.start()].lower(), segment[mention.end():].lower()
            status = None
            if re.search(r"(?:could not|cannot|can't|unable to) confirm|unsure|unclear|unknown|not sure", segment, re.I):
                status = "UNKNOWN"
            elif re.search(rf"switched\s+from\s+(?:{aliases})\b", segment, re.I):
                status = "INACTIVE"
            elif re.search(rf"switched\s+from\s+\w+\s+to\s+(?:{aliases})\b", segment, re.I):
                status = "ACTIVE"
            elif re.search(r"(?:no longer (?:taking|on)|not taking|stopped|discontinued|off)\s*:?\s*$", before) or re.search(r"^.{0,50}\b(?:was |has been |is )?(?:discontinued|stopped|inactive|no longer taken)\b", after):
                status = "INACTIVE"
            elif re.search(r"(?:reports? taking|takes?|taking|currently on|now on|now taking|replaced with)\s*$", before) or re.search(r"\btaking as prescribed\b", after):
                status = "ACTIVE"
            # An explicit medication list in an H&P or reconciliation note supports use.
            elif segment.lstrip().startswith("-") and re.search(r"MEDICATION(?:S| RECONCILIATION)\s*(?:\([^\n]*\))?:", text, re.I):
                status = "ACTIVE"
            if status:
                mentions.append(MedicationFact(name=name, status=status, observed_at=observed_at, source=SourceRef(path=f"documents[{index}]", quote=segment, details=f"Medication assertion observed_at={observed_at}")))
    return mentions


def reconcile_medications(submission: PatientSubmission, mentions: list[MedicationFact]) -> dict[str, MedicationFact]:
    baseline: dict[str, list[MedicationFact]] = {}
    for index, medication in enumerate(submission.medications):
        for name in sorted(anticoagulants(medication.name)):
            status = "UNKNOWN" if medication.active is None else ("ACTIVE" if medication.active else "INACTIVE")
            baseline.setdefault(name, []).append(MedicationFact(name=name, status=status, observed_at=None, source=SourceRef(path=f"medications[{index}]", details=f"name={medication.name!r}; active={medication.active!r}")))
    resolved = {}
    for name in sorted(set(baseline) | {m.name for m in mentions}):
        narrative = [m for m in mentions if m.name == name]
        # Reconciliation/current-use assertions supersede the undated medication snapshot.
        candidates = narrative if narrative else baseline[name]
        if narrative and any(m.observed_at is None for m in narrative):
            current = [m for m in narrative if m.observed_at is None]
            selected = min(current, key=lambda m: (m.source.quote or "", m.source.details, m.source.path))
            resolved[name] = selected.model_copy(update={"status": "UNKNOWN"})
            continue
        latest = max((m.observed_at for m in candidates if m.observed_at is not None), default=None)
        current = [m for m in candidates if m.observed_at == latest]
        selected = min(current, key=lambda m: (m.source.quote or "", m.source.details, m.source.path))
        if len({m.status for m in current}) > 1:
            selected = selected.model_copy(update={"status": "UNKNOWN", "source": selected.source.model_copy(update={"details": "Conflicting current-use assertions; " + selected.source.details})})
        resolved[name] = selected
    return resolved
