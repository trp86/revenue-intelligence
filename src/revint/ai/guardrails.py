"""Checks on every AI brief before it is stored (spec 05 section 5, G2 to G6; story #137).

A brief that fails any check is rejected: it is never stored as valid, and never shown.
- G2: every number in the text must be a value of the package (formatted variants allowed:
  rounding, thousands separators, a percent of a share).
- G3: every evidence id the brief cites must be a fact id of the package.
- G5: the brief's confidence cannot be above the engine's confidence.
- G6: no banned term (price cuts, discounts, margin, blaming competitors or the economy).
"""

from __future__ import annotations

import re

from revint.ai.evidence import EvidencePackage
from revint.ai.schema import AiBrief

LEVELS = {"Low": 0, "Medium": 1, "High": 2}
BANNED = (
    "price cut",
    "cut the price",
    "lower the price",
    "reduce the price",
    "discount",
    "margin",
    "rebate",
    "because of competitor",
    "because of the competition",
    "because of the economy",
    "inflation",
)
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


class GuardrailError(Exception):
    """The brief broke a rule; the message names the rule."""


def _texts(brief: AiBrief) -> list[str]:
    return [
        brief.headline,
        brief.explanation,
        brief.recommendation,
        *(a.text for a in brief.actions),
        *brief.risks,
    ]


def _allowed_numbers(package: EvidencePackage) -> set[float]:
    values: list[float] = []
    for fact in package.facts:
        if isinstance(fact.value, int | float):
            values.append(float(fact.value))
            if fact.unit == "share":
                values.append(float(fact.value) * 100)
        else:
            values += [float(n) for n in re.findall(r"\d+", fact.value)]  # the parts of a date
    for amount in (package.estimate.value_low, package.estimate.value_high):
        if amount is not None:
            values.append(float(amount))
    allowed: set[float] = set()
    for value in values:
        allowed |= {value, round(value), round(value, 1), round(value, 2), abs(value)}
        allowed |= {round(abs(value)), round(abs(value), 1), round(abs(value), 2)}
    # small counting words a sentence may use ("2 actions", "the next 3 months") stay allowed
    allowed |= {float(n) for n in range(0, 13)}
    return allowed


def _close(number: float, allowed: set[float]) -> bool:
    if number in allowed:
        return True
    # a rounded variant: 12,115.46 may be written 12,115 or 12.1 thousand
    return any(abs(number - a) <= max(0.5, abs(a) * 0.005) for a in allowed)


def check(brief: AiBrief, package: EvidencePackage) -> None:
    """Raise GuardrailError naming the first rule the brief breaks."""
    ids = package.fact_ids()
    cited = set(brief.evidence_ids_used) | {i for a in brief.actions for i in a.evidence_ids}
    unknown = sorted(cited - ids)
    if unknown:
        raise GuardrailError(f"G3: unknown evidence ids {', '.join(unknown)}")
    if LEVELS[brief.confidence_label] > LEVELS.get(package.confidence, 0):
        raise GuardrailError(
            f"G5: confidence {brief.confidence_label} is above the engine's {package.confidence}"
        )
    text = " ".join(_texts(brief))
    lowered = text.lower()
    for term in BANNED:
        if term in lowered:
            raise GuardrailError(f"G6: banned term '{term}'")
    allowed = _allowed_numbers(package)
    for match in _NUMBER.findall(text):
        number = float(match.replace(",", ""))
        if not _close(number, allowed):
            raise GuardrailError(f"G2: the number {match} is not in the evidence")
