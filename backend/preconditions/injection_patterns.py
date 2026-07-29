"""Regex catalogue + escalation thresholds (PRD Section 5, step 1).

Cascading design: this regex pass runs first (no network call, <20ms per
Section 16); scores in [ESCALATE_LOW, ESCALATE_HIGH) escalate to a Haiku
classification; >=ESCALATE_HIGH blocks outright without needing escalation.
"""
from __future__ import annotations

import re

ESCALATE_LOW = 0.4
ESCALATE_HIGH = 0.8

# Each pattern contributes the paired score if it matches anywhere in the
# text. Deliberately simple substring/regex heuristics -- completeness is
# not the goal here, only cheaply catching the obvious cases and routing
# genuine ambiguity (the 0.4-0.8 band) to Haiku, per Section 5's design.
PATTERNS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"ignore (all |any )?(previous|prior|above|earlier) instructions", re.IGNORECASE), 0.9),
    (re.compile(r"disregard (all |any )?(previous|prior|above|earlier)", re.IGNORECASE), 0.9),
    (re.compile(r"reveal (your |the )?(system prompt|instructions)", re.IGNORECASE), 0.85),
    (re.compile(r"</?(system|instructions|admin)>", re.IGNORECASE), 0.7),
    (re.compile(r"new instructions\s*:", re.IGNORECASE), 0.6),
    (re.compile(r"you are now\b", re.IGNORECASE), 0.55),
    (re.compile(r"\bdo anything now\b|\bDAN\b", re.IGNORECASE), 0.6),
    (re.compile(r"\bsystem prompt\b", re.IGNORECASE), 0.45),
    (re.compile(r"\bact as (an?|the)\b", re.IGNORECASE), 0.4),
]


def regex_score(text: str) -> float:
    """Highest single-pattern score across all matches, 0.0 if none match."""
    scores = [weight for pattern, weight in PATTERNS if pattern.search(text)]
    return max(scores, default=0.0)
