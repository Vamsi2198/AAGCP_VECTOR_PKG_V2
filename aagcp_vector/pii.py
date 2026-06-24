"""
AAGCP-Vector :: OBSERVE-phase PII detection.

Pattern-based detector with first-class Indian PII support
(Aadhaar, PAN, +91 mobile) alongside global identifiers.

Production path: swap in Presidio via PresidioAdapter — same interface
as the existing AAGCP PIIAnalyzer (control_pannel.py), which already
falls back to regex when Presidio is unavailable. This module IS that
fallback, hardened and extended for unstructured text.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class PIIFinding:
    entity_type: str      # AADHAAR | PAN | IN_PHONE | EMAIL | MRN | PERSON
    value: str            # raw matched text
    start: int
    end: int
    confidence: float


# Detection order matters: longer/stricter patterns first so a 12-digit
# Aadhaar is never partially consumed as a 10-digit phone number.
_PATTERNS: list[tuple[str, re.Pattern, float]] = [
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), 0.95),
    ("PAN",     re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.97),
    ("IN_PHONE", re.compile(r"(?:\+91[ -]?)?\b[6-9]\d{9}\b"), 0.90),
    ("EMAIL",   re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), 0.98),
    ("MRN",     re.compile(r"\bMRN[-: ]?\d{5,8}\b"), 0.95),
]

# Person names: honorific-anchored Title Case, plus an optional lexicon
# for demo determinism. Production: Presidio/NER replaces this.
_HONORIFIC = re.compile(
    r"\b(?:Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)


class PIIDetector:
    def __init__(self, person_lexicon: Optional[List[str]] = None):
        self.person_lexicon = sorted(person_lexicon or [], key=len, reverse=True)

    def scan(self, text: str) -> List[PIIFinding]:
        findings: List[PIIFinding] = []

        for etype, pattern, conf in _PATTERNS:
            for m in pattern.finditer(text):
                findings.append(PIIFinding(etype, m.group(0), m.start(), m.end(), conf))

        for m in _HONORIFIC.finditer(text):
            findings.append(
                PIIFinding("PERSON", m.group(1), m.start(1), m.end(1), 0.85)
            )

        for name in self.person_lexicon:
            # Case-insensitive: "Dinesh iyer" in the lexicon still catches
            # "Dinesh Iyer" in text. Store the matched casing, not the lexicon
            # casing, so tokenization keys on what actually appears.
            for m in re.finditer(re.escape(name), text, re.IGNORECASE):
                findings.append(PIIFinding("PERSON", m.group(0),
                                           m.start(), m.end(), 0.99))

        return self._resolve_overlaps(findings)

    @staticmethod
    def _resolve_overlaps(findings: List[PIIFinding]) -> List[PIIFinding]:
        """Keep the longest/highest-confidence span when matches overlap."""
        kept: List[PIIFinding] = []
        for f in sorted(findings, key=lambda x: (x.start, -(x.end - x.start), -x.confidence)):
            if not kept or f.start >= kept[-1].end:
                kept.append(f)
        return kept

    @staticmethod
    def risk_score(findings: List[PIIFinding]) -> float:
        """ANALYZE-phase risk weighting (mirrors AAGCP impact assessment)."""
        weights = {"AADHAAR": 1.0, "PAN": 0.9, "MRN": 0.8,
                   "PERSON": 0.6, "IN_PHONE": 0.5, "EMAIL": 0.4}
        if not findings:
            return 0.0
        return min(1.0, sum(weights.get(f.entity_type, 0.3) for f in findings) / 3.0)
