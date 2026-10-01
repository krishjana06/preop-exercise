"""Facts retain their original source through normalization and policy evaluation."""
from __future__ import annotations

from typing import Generic, Literal, TypeVar
from pydantic import BaseModel, model_validator
from .models import Evidence

T = TypeVar("T")


class SourceRef(BaseModel):
    path: str
    quote: str | None = None
    details: str = ""

    def evidence(self, explanation: str) -> Evidence:
        parts = [explanation]
        if self.details:
            parts.append(self.details)
        if self.quote:
            parts.append(f'Exact excerpt: "{self.quote}"')
        return Evidence(source=self.path, details="; ".join(parts))


class ResolvedFact(BaseModel, Generic[T]):
    value: T | None = None
    state: Literal["KNOWN", "MISSING", "AMBIGUOUS"] = "MISSING"
    source: SourceRef

    @model_validator(mode="after")
    def known_requires_value(self) -> ResolvedFact[T]:
        if self.state == "KNOWN" and self.value is None:
            raise ValueError("A known fact must have a value")
        return self
