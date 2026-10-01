"""Resolve structured facts without guessing missing authoritative fields."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging
from typing import Literal, TypeVar

from pydantic import BaseModel
from .models import PatientSubmission
from .normalize import calendar_date, fahrenheit, finite_number, lab_code, normalize_text, timestamp
from .policy import LAB_REQUIREMENTS
from .provenance import ResolvedFact, SourceRef

logger = logging.getLogger(__name__)
T = TypeVar("T")


class LabFact(BaseModel):
    code: str
    day: date
    observed_at: datetime
    source: SourceRef


class Measurement(BaseModel):
    kind: Literal["blood_pressure", "temperature"]
    observed_at: datetime | None
    systolic: float | None = None
    diastolic: float | None = None
    temperature_f: float | None = None
    position: int = 0
    source: SourceRef

    def values(self) -> tuple[float | None, ...]:
        return (self.systolic, self.diastolic) if self.kind == "blood_pressure" else (self.temperature_f,)


class DocumentFact(BaseModel):
    day: date | None
    source: SourceRef


class MedicationFact(BaseModel):
    name: str
    status: Literal["ACTIVE", "INACTIVE", "UNKNOWN"]
    observed_at: datetime | None
    source: SourceRef


class PlanFact(BaseModel):
    medication: str | None
    applies: bool | None
    preop: bool
    postop: bool
    observed_at: datetime | None
    source: SourceRef
    preop_quote: str | None = None
    postop_quote: str | None = None


def missing(path: str, details: str = "") -> ResolvedFact:
    return ResolvedFact(source=SourceRef(path=path, details=details))


@dataclass
class FactBundle:
    procedure_date: ResolvedFact[date]
    risk: ResolvedFact[str]
    labs: dict[str, ResolvedFact[LabFact]] = field(default_factory=dict)
    blood_pressure: ResolvedFact[Measurement] = field(default_factory=lambda: missing("vitals", "No blood pressure measurement found"))
    temperature: ResolvedFact[Measurement] = field(default_factory=lambda: missing("vitals", "No temperature measurement found"))
    hp: ResolvedFact[DocumentFact] = field(default_factory=lambda: missing("documents", "No applicable preoperative H&P found"))
    consent: ResolvedFact[DocumentFact] = field(default_factory=lambda: missing("documents", "No patient-signed consent for this procedure found"))
    medications: dict[str, MedicationFact] = field(default_factory=dict)
    plans: list[PlanFact] = field(default_factory=list)
    unresolved: list[SourceRef] = field(default_factory=list)


def resolve_measurements(measurements: list[Measurement], kind: str) -> ResolvedFact[Measurement]:
    candidates = [m for m in measurements if m.kind == kind]
    if not candidates:
        return missing("vitals", f"No actual {kind} measurement found in vitals or documents")
    undated = [m for m in candidates if m.observed_at is None]
    if undated:
        source = min(undated, key=lambda m: (m.source.details, m.source.quote or "", m.source.path)).source
        return ResolvedFact(state="AMBIGUOUS", source=source.model_copy(update={"details": source.details + "; Measurement date is missing or invalid; latest cannot be established"}))
    latest_time = max(m.observed_at for m in candidates if m.observed_at is not None)
    latest = [m for m in candidates if m.observed_at == latest_time]
    # Text order resolves rechecks within the same note, never across different notes.
    by_source: dict[str, Measurement] = {}
    for measurement in latest:
        previous = by_source.get(measurement.source.path)
        if previous is None or measurement.position > previous.position:
            by_source[measurement.source.path] = measurement
    tied = list(by_source.values())
    if len({m.values() for m in tied}) > 1:
        source = min(tied, key=lambda m: (m.source.quote or "", m.source.details, m.source.path)).source
        return ResolvedFact(state="AMBIGUOUS", source=source.model_copy(update={"details": "Conflicting measurements at the same timestamp; " + source.details}))
    selected = min(tied, key=lambda m: (m.source.quote or "", m.source.details, m.source.path))
    logger.debug("Latest %s: source=%s observed_at=%s", kind, selected.source.path, selected.observed_at)
    return ResolvedFact(value=selected, state="KNOWN", source=selected.source)


def resolve_structured(submission: PatientSubmission) -> tuple[FactBundle, list[Measurement]]:
    procedure = submission.procedure
    raw_date = procedure.procedure_date if procedure else None
    day = calendar_date(raw_date)
    date_fact = ResolvedFact[date](value=day, state="KNOWN" if day else ("MISSING" if raw_date is None else "AMBIGUOUS"), source=SourceRef(path="procedure.procedure_date", details=f"procedure.procedure_date = {raw_date!r}"))
    raw_risk = procedure.procedure_risk if procedure else None
    risk = (raw_risk or "").strip().upper()
    risk_fact = ResolvedFact[str](value=risk if risk in LAB_REQUIREMENTS else None, state="KNOWN" if risk in LAB_REQUIREMENTS else ("MISSING" if raw_risk is None else "AMBIGUOUS"), source=SourceRef(path="procedure.procedure_risk", details=f"procedure.procedure_risk = {raw_risk!r}"))
    facts = FactBundle(procedure_date=date_fact, risk=risk_fact)
    logger.debug("Procedure date state=%s; risk state=%s", date_fact.state, risk_fact.state)
    for code in ("CBC", "CMP"):
        records: list[LabFact] = []
        undated: list[SourceRef] = []
        for index, lab in enumerate(submission.labs):
            if lab_code(lab.code, lab.display) != code or normalize_text(lab.status) != "final":
                continue
            source = SourceRef(path=f"labs[{index}]", details=f"code={lab.code!r}; status={lab.status!r}; effective_at={lab.effective_at!r}")
            lab_day, observed = calendar_date(lab.effective_at), timestamp(lab.effective_at)
            if lab_day is None or observed is None:
                undated.append(source)
            else:
                records.append(LabFact(code=code, day=lab_day, observed_at=observed, source=source))
        if undated:
            facts.labs[code] = ResolvedFact(state="AMBIGUOUS", source=min(undated, key=lambda s: (s.details, s.path)))
        elif records:
            record = max(records, key=lambda r: (r.observed_at, r.source.details))
            facts.labs[code] = ResolvedFact(value=record, state="KNOWN", source=record.source)
            logger.debug("Selected %s: %s effective_at=%s", code, record.source.path, record.observed_at)
        else:
            facts.labs[code] = missing("labs", f"No finalized {code} result found")
    measurements: list[Measurement] = []
    for index, vital in enumerate(submission.vitals):
        kind = normalize_text(vital.type)
        source = SourceRef(path=f"vitals[{index}]", details=f"date={vital.date!r}; systolic={vital.systolic!r}; diastolic={vital.diastolic!r}; value_f={vital.value_f!r}; value_c={vital.value_c!r}")
        if kind == "blood pressure" and (finite_number(vital.systolic) or finite_number(vital.diastolic)):
            measurements.append(Measurement(kind="blood_pressure", observed_at=timestamp(vital.date), systolic=vital.systolic if finite_number(vital.systolic) else None, diastolic=vital.diastolic if finite_number(vital.diastolic) else None, source=source))
        elif kind == "temperature" and (finite_number(vital.value_f) or finite_number(vital.value_c)):
            value = vital.value_f if finite_number(vital.value_f) else fahrenheit(vital.value_c, "C")
            measurements.append(Measurement(kind="temperature", observed_at=timestamp(vital.date), temperature_f=value, source=source))
    facts.blood_pressure = resolve_measurements(measurements, "blood_pressure")
    facts.temperature = resolve_measurements(measurements, "temperature")
    return facts, measurements
