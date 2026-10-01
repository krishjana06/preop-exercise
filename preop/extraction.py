"""Deterministic text parsing. The optional semantic adapter is added separately."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time
import re
from typing import Literal

from .facts import DocumentFact, Measurement, MedicationFact, PlanFact, missing
from .medication import anticoagulants, medication_mentions
from .models import Document, PatientSubmission
from .normalize import calendar_date, fahrenheit, normalize_text, timestamp
from .provenance import ResolvedFact, SourceRef

BP_PATTERN = re.compile(r"(?:\b(?:NIBP|BP|Blood\s+pressure)\s*:?\s*|(?=\d{2,3}\s*/\s*\d{2,3}\s*mmHg))(\d{2,3})\s*/\s*(\d{2,3})\b(?:\s*mmHg)?", re.I)
TEMP_PATTERN = re.compile(r"(?:(?:\bTemperature|\bTemp|\bT)\s*:?\s*)?\b(\d{2,3}(?:\.\d+)?)\s*°?\s*([FC])\b", re.I)
DATE_PATTERN = r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}"
SERVICE_DATE_PATTERN = re.compile(rf"\b(?:Date of service|Visit date|Observation date|Date)\s*:\s*({DATE_PATTERN})", re.I)
HP_PATTERN = re.compile(r"history\s*(?:and|&)\s*(?:physical|pyhsical)|\bH\s*(?:&|and)\s*P\b", re.I)
PREOP_PATTERN = re.compile(r"\bpre[- ]?(?:op(?:erative)?)\b", re.I)
SIGNATURE_PATTERN = re.compile(r"patient signature\s*:\s*/s/\s*\S[^\n]*|patient signature on file[^\n]*|(?:e-?signed|signed|electronically signed) by (?:the )?patient[^\n]*|(?:electronic )?consent (?:obtained and )?signed by (?:the )?patient[^\n]*", re.I)
UNSIGNED_PATTERN = re.compile(r"patient signature\s*:\s*(?:pending|_+|blank|not completed)|patient signature (?:pending|not completed)|unsigned|NOT COMPLETED|took (?:the )?form home|printed for patient review", re.I)


@dataclass(frozen=True)
class Query:
    document_index: int
    kind: Literal["HP", "CONSENT", "MEDICATION", "PLAN", "VITAL"]


@dataclass
class DocumentExtraction:
    measurements: list[Measurement] = field(default_factory=list)
    hp: list[DocumentFact] = field(default_factory=list)
    consents: list[DocumentFact] = field(default_factory=list)
    medications: list[MedicationFact] = field(default_factory=list)
    plans: list[PlanFact] = field(default_factory=list)
    queries: list[Query] = field(default_factory=list)
    negative_hp: list[SourceRef] = field(default_factory=list)
    negative_consents: list[SourceRef] = field(default_factory=list)


def document_day(document: Document):
    """Explicit service/visit date is preferable to a scan/upload date."""
    match = SERVICE_DATE_PATTERN.search(document.text or "")
    return calendar_date(match.group(1)) if match else calendar_date(document.date)


def document_timestamp(document: Document):
    match = SERVICE_DATE_PATTERN.search(document.text or "")
    if match:
        day = calendar_date(match.group(1))
        return datetime.combine(day, time(), UTC) if day else None
    return timestamp(document.date)


def measurement_timestamp(document: Document, position: int):
    observed = document_timestamp(document)
    if observed is None:
        return None
    prefix = (document.text or "")[:position]
    clocks = list(re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", prefix))
    if clocks:
        match = clocks[-1]
        observed = observed.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    return observed


def extract_vitals(document: Document, index: int) -> list[Measurement]:
    text = document.text or ""
    measurements = []
    for kind, pattern in (("blood_pressure", BP_PATTERN), ("temperature", TEMP_PATTERN)):
        for match in pattern.finditer(text):
            # Numbers in conditional instructions or historical recollections are not observations.
            line_start = max(text.rfind("\n", 0, match.start()), text.rfind(". ", 0, match.start())) + 1
            context = text[line_start:match.start()].lower()
            if re.search(r"\b(?:if|target|threshold|call (?:if|for)|prior|previous|historical|home log)\b", context):
                continue
            source = SourceRef(path=f"documents[{index}]", quote=match.group(), details=f"Measurement on {document_day(document)}; document.date={document.date!r}")
            values = {"systolic": float(match.group(1)), "diastolic": float(match.group(2))} if kind == "blood_pressure" else {"temperature_f": fahrenheit(float(match.group(1)), match.group(2))}
            measurements.append(Measurement(kind=kind, observed_at=measurement_timestamp(document, match.start()), position=match.start(), source=source, **values))
    return measurements


def applies_to_procedure(text: str, procedure_type: str | None) -> bool | None:
    """Compare explicit procedure fields; uncertain synonyms go to semantic extraction."""
    listed = re.search(r"^(?:(?:planned|proposed|scheduled|intended)\s+)?procedure\s*:\s*([^\n]+)", text, re.I | re.M)
    if listed:
        actual = re.split(r"\s*\(|\s*scheduled for", listed.group(1), flags=re.I)[0]
        expected = normalize_text(procedure_type)
        if not expected:
            return None
        def words(value):
            return set(re.findall(r"[a-z0-9]+", normalize_text(value))) - {"elective", "planned", "procedure", "surgery", "scheduled", "the"}
        actual_words, expected_words = words(actual), words(expected)
        if actual_words and actual_words == expected_words:
            return True
        if actual_words and expected_words and not actual_words.intersection(expected_words) and len(actual_words | expected_words) >= 3 and not re.fullmatch(r"[A-Z]{2,6}", actual.strip()):
            return False
        # A definite mismatch is resolved semantically, avoiding substring/laterality mistakes.
        return None
    if re.search(r"\b(?:for (?:the )?(?:planned|scheduled) procedure|for procedure|for planned surgery)\b", text, re.I):
        return True
    if procedure_type and normalize_text(procedure_type) in normalize_text(text):
        return True
    return None


def source_for(document: Document, index: int, quote: str | None = None) -> SourceRef:
    return SourceRef(path=f"documents[{index}]", quote=quote if quote is not None else document.text, details=f"document.date={document.date!r}; service_date={document_day(document)}; type={document.type!r}")


def plan_instructions(text: str, medication: str) -> tuple[str | None, str | None]:
    preop, postop = None, None
    for segment in re.split(r"\n|(?<=[.!?])\s+", text):
        names = anticoagulants(segment)
        if medication not in names:
            continue
        if re.search(r"recommendations will follow|will (?:be )?addressed|to be determined|follow up|discuss interruption|specific recommendations", segment, re.I):
            continue
        if re.search(r"\b(?:hold|stop|withhold|discontinue|continue|last dose)\b", segment, re.I) and re.search(r"\b(?:before|prior|pre[- ]?op|preoperative|morning of|day of)\b", segment, re.I):
            preop = segment
        if re.search(r"\b(?:resume|restart|continue|reinitiate)\b", segment, re.I) and re.search(r"\b(?:after|post[- ]?op|postoperative|following (?:the )?(?:surgery|procedure)|evening of (?:the )?surgery|once hemostasis)\b", segment, re.I):
            postop = segment
    return preop, postop


def extract_documents(submission: PatientSubmission) -> DocumentExtraction:
    extraction = DocumentExtraction()
    procedure_type = submission.procedure.procedure_type if submission.procedure else None
    for index, document in enumerate(submission.documents):
        text = document.text or ""
        title = (document.type or "").replace("_", " ")
        source = source_for(document, index)
        extraction.measurements.extend(extract_vitals(document, index))
        extraction.medications.extend(medication_mentions(document, index, document_timestamp(document)))
        applicability = applies_to_procedure(text, procedure_type)
        hp_candidate = bool(HP_PATTERN.search(title) or HP_PATTERN.search(text))
        if hp_candidate:
            actual_hp = bool(HP_PATTERN.search(text[:250]) and PREOP_PATTERN.search(text) and not re.search(r"annual wellness|establish care|retained for .*context|H&P reviewed|H&P: not yet on file", text, re.I))
            if actual_hp and applicability is True:
                extraction.hp.append(DocumentFact(day=document_day(document), source=source))
            elif re.search(r"annual wellness|establish care|retained for .*context|H&P reviewed|H&P: not yet on file", text, re.I):
                extraction.negative_hp.append(source)
            else:
                extraction.queries.append(Query(index, "HP"))
        consent_candidate = bool(re.search(r"consent", title, re.I) or re.search(r"(?:surgical|informed|electronic) consent|patient signature", text, re.I))
        if consent_candidate:
            unsigned, signed = UNSIGNED_PATTERN.search(text), SIGNATURE_PATTERN.search(text)
            if signed and not unsigned and applicability is True:
                # Keep both the procedure field and signature in provenance.
                extraction.consents.append(DocumentFact(day=document_day(document), source=source))
            elif (unsigned and not signed) or applicability is False:
                extraction.negative_consents.append(source)
            elif hp_candidate and not re.search("consent", title, re.I) and not signed:
                pass
            elif re.search(r"formal consent per surgical team|risks and benefits .*discussed", text, re.I) and not re.search("consent", title, re.I):
                pass
            else:
                extraction.queries.append(Query(index, "CONSENT"))
        names = anticoagulants(text)
        plan_candidate = bool(names and (
            re.search(r"anticoagulation|perioperative medication plan|perioperative management", title + "\n" + text, re.I)
            or any(anticoagulants(segment) and re.search(r"\b(?:hold|stop|resume|restart|continue)\b", segment, re.I) and re.search(r"before|after|pre[- ]?op|post[- ]?op", segment, re.I) for segment in re.split(r"\n|(?<=[.!?])\s+", text))
        ))
        if plan_candidate:
            # Presence of a perioperative consultation does not itself establish current use.
            for name in sorted(names):
                preop, postop = plan_instructions(text, name)
                plan_applies = applicability
                if plan_applies is None and re.search(r"\b(?:before|after) (?:the )?(?:surgery|procedure)\b", text, re.I) and not re.search(r"^Procedure:", text, re.I | re.M):
                    plan_applies = True
                extraction.plans.append(PlanFact(medication=name, applies=plan_applies, preop=preop is not None, postop=postop is not None, observed_at=document_timestamp(document), source=source, preop_quote=preop, postop_quote=postop))
            if applicability is None or (not any(plan_instructions(text, name)[0] or plan_instructions(text, name)[1] for name in names) and not re.search(r"follow up|specific recommendations|discuss interruption|will (?:be )?addressed|per surgical team|to be determined", text, re.I)):
                extraction.queries.append(Query(index, "PLAN"))
        # Broaden candidates for unfamiliar document titles when substantive clinical text exists.
        if not hp_candidate and re.search(r"^\s*(?:history(?: of present illness)?|physical exam)\s*:", text, re.I | re.M) and PREOP_PATTERN.search(text) and not re.search(r"anesthesia|nursing", title, re.I):
            extraction.queries.append(Query(index, "HP"))
        if names and not any(m.source.path == f"documents[{index}]" for m in extraction.medications) and re.search(r"medication reconciliation|currently|taking|discontinued|switched|could not confirm", text, re.I):
            extraction.queries.append(Query(index, "MEDICATION"))
    extraction.queries = sorted(set(extraction.queries), key=lambda q: (q.document_index, q.kind))
    return extraction


def resolve_document(candidates: list[DocumentFact], ambiguous: list[SourceRef], negative: list[SourceRef], kind: str) -> ResolvedFact[DocumentFact]:
    dated = [c for c in candidates if c.day is not None]
    if kind == "HP" and any(c.day is None for c in candidates):
        undated = next(c for c in candidates if c.day is None)
        return ResolvedFact(state="AMBIGUOUS", source=undated.source)
    if candidates:
        selected = max(dated, key=lambda c: (c.day, c.source.quote or "")) if dated else min(candidates, key=lambda c: c.source.quote or "")
        return ResolvedFact(value=selected, state="KNOWN", source=selected.source)
    if ambiguous:
        return ResolvedFact(state="AMBIGUOUS", source=min(ambiguous, key=lambda s: (s.quote or "", s.path)))
    if negative:
        source = min(negative, key=lambda s: (s.quote or "", s.path))
        return ResolvedFact(source=source)
    return missing("documents", f"No applicable {kind} document found")
