"""Pure normalization; calendar-day windows preserve each supplied date."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
import math
import re

LAB_CODE_ALIASES = {"CBC": "CBC", "LAB-CBC": "CBC", "CMP": "CMP", "LAB-CMP": "CMP"}


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().replace("_", " ")).strip()


def calendar_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip()[:10], fmt).date()
        except ValueError:
            pass
    return None


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        day = calendar_date(value)
        return datetime.combine(day, time(), UTC) if day else None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def lab_code(code: str | None, display: str | None = None) -> str | None:
    canonical = LAB_CODE_ALIASES.get((code or "").strip().upper())
    if code:
        return canonical
    # Display fallback only if the authoritative code is absent.
    return {"complete blood count": "CBC", "comprehensive metabolic panel": "CMP"}.get(normalize_text(display))


def fahrenheit(value: float, unit: str) -> float:
    return round(value * 9 / 5 + 32, 6) if unit.upper() == "C" else value


def finite_number(value: float | None) -> bool:
    return value is not None and math.isfinite(value)
