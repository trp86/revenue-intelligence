"""The AI brief Gemini must return (spec 05 section 4, story #137)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Action(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    suggested_owner_role: str = Field(min_length=1, max_length=60)
    evidence_ids: list[str] = Field(default_factory=list)


class AiBrief(BaseModel):
    headline: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=600)
    recommendation: str = Field(min_length=1, max_length=600)
    actions: list[Action] = Field(min_length=1, max_length=5)
    risks: list[str] = Field(default_factory=list, max_length=4)
    confidence_label: Literal["High", "Medium", "Low"]
    evidence_ids_used: list[str] = Field(default_factory=list)
