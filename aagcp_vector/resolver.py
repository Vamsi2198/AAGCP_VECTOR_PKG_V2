"""
AAGCP-Vector :: Entity Resolution.

The snake's-eye detail that makes the eagle's-eye claim ("surgical,
provable erasure") actually true.

The problem the demo's first version ignored
--------------------------------------------
A NAME is not an identity. In real records:

  * Same Aadhaar, different name spelling  → ONE person  (merge; Aadhaar wins)
  * Same name, different Aadhaar           → TWO people  (must NOT merge)
  * Same MRN, different Aadhaar            → DATA CONFLICT (flag, never guess)
  * Duplicate record (all IDs match)       → dedupe

So the data subject must be keyed on the *strongest stable identifier
present*, not on the display name. This module clusters PII findings into
SubjectIdentity objects under that precedence and surfaces conflicts to a
human instead of silently merging or splitting — the same
escalate-don't-guess principle as the multi-regulation conflict resolver.
"""

from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .pii import PIIFinding

# Strongest → weakest identity anchor. Aadhaar is a unique national ID;
# PAN is unique but tax-scoped; MRN is hospital-local (and, as the user's
# test proved, sometimes mis-keyed across patients); PERSON name is the
# weakest and only used when nothing stronger exists.
KEY_PRECEDENCE = ["AADHAAR", "PAN", "MRN", "PERSON"]
_STRENGTH = {t: i for i, t in enumerate(KEY_PRECEDENCE)}


@dataclass
class SubjectIdentity:
    identity_id: str                      # stable hash of canonical key
    canonical_type: str                   # AADHAAR | PAN | MRN | PERSON
    canonical_value: str
    display_names: Set[str] = field(default_factory=set)
    identifiers: Dict[str, Set[str]] = field(default_factory=dict)  # type -> values
    record_indices: List[int] = field(default_factory=list)
    confidence: float = 1.0               # <1.0 when name-only (ambiguous)

    def add_finding(self, f: PIIFinding):
        self.identifiers.setdefault(f.entity_type, set()).add(f.value)
        if f.entity_type == "PERSON":
            self.display_names.add(f.value)


@dataclass
class IdentityConflict:
    kind: str                             # e.g. "SHARED_MRN_DIFFERENT_AADHAAR"
    detail: str
    values: List[str]


class EntityResolver:
    """
    Segments a document into per-subject records and resolves each to a
    SubjectIdentity keyed on the strongest available identifier.
    """

    # A new record starts at "Patient <Name>" or at a line that begins
    # with a (possibly lower-cased) known person name.
    _RECORD_ANCHOR = re.compile(r"(?im)^\s*(?:patient\s+)?(?=[A-Z]|\b)")

    def __init__(self):
        self.conflicts: List[IdentityConflict] = []

    # ── Record segmentation ──────────────────────────────────────────

    def _segment_records(self, text: str,
                         findings: List[PIIFinding]) -> List[List[PIIFinding]]:
        """
        Split findings into records by line. Each non-empty line is treated
        as one record; findings are bucketed by the line their start offset
        falls in. Robust to the 'no headings' case because it's offset-based,
        not label-based.
        """
        # Build line spans
        spans: List[Tuple[int, int]] = []
        pos = 0
        for line in text.splitlines(keepends=True):
            spans.append((pos, pos + len(line)))
            pos += len(line)

        buckets: Dict[int, List[PIIFinding]] = {}
        for f in findings:
            for i, (s, e) in enumerate(spans):
                if s <= f.start < e:
                    buckets.setdefault(i, []).append(f)
                    break
        return [buckets[i] for i in sorted(buckets)]

    # ── Canonical key selection ──────────────────────────────────────

    @staticmethod
    def _canonical(record: List[PIIFinding]) -> Optional[Tuple[str, str]]:
        best = None
        for f in record:
            if f.entity_type not in _STRENGTH:
                continue
            if best is None or _STRENGTH[f.entity_type] < _STRENGTH[best[0]]:
                best = (f.entity_type, f.value)
        return best

    @staticmethod
    def _id(canon_type: str, canon_value: str) -> str:
        return hashlib.sha256(
            f"{canon_type}|{canon_value.strip().lower()}".encode()
        ).hexdigest()[:12]

    # ── Resolution ───────────────────────────────────────────────────

    def resolve(self, text: str,
                findings: List[PIIFinding]) -> Tuple[Dict[str, SubjectIdentity],
                                                     Dict[int, str]]:
        """
        Returns:
          identities: identity_id -> SubjectIdentity
          finding_owner: id(finding by position) -> identity_id

        Same Aadhaar across records ⇒ same identity (merge).
        Same name / different Aadhaar ⇒ distinct identities (no merge).
        Conflicting strong IDs ⇒ recorded in self.conflicts.
        """
        self.conflicts = []
        records = self._segment_records(text, findings)

        identities: Dict[str, SubjectIdentity] = {}
        finding_owner: Dict[int, str] = {}
        # secondary index: identifier value -> identity_id, to detect conflicts
        value_index: Dict[str, str] = {}

        for ridx, record in enumerate(records):
            canon = self._canonical(record)
            if canon is None:
                continue
            ctype, cvalue = canon
            iid = self._id(ctype, cvalue)

            # Conflict probe: does any *strong* identifier in this record
            # already belong to a DIFFERENT identity?
            for f in record:
                if f.entity_type in ("AADHAAR", "PAN"):
                    key = f"{f.entity_type}:{f.value}"
                    prior = value_index.get(key)
                    if prior and prior != iid:
                        self.conflicts.append(IdentityConflict(
                            kind=f"SHARED_{f.entity_type}_DIFFERENT_SUBJECT",
                            detail=(f"{f.entity_type} {f.value} appears under two "
                                    f"distinct subjects — likely data error."),
                            values=[f.value]))

            ident = identities.get(iid)
            if ident is None:
                ident = SubjectIdentity(
                    identity_id=iid, canonical_type=ctype, canonical_value=cvalue,
                    confidence=1.0 if ctype != "PERSON" else 0.6)
                identities[iid] = ident
            ident.record_indices.append(ridx)

            for f in record:
                ident.add_finding(f)
                finding_owner[id(f)] = iid
                # MRN conflict: same MRN, two identities ⇒ flag (user's test)
                key = f"{f.entity_type}:{f.value}"
                if f.entity_type == "MRN":
                    prior = value_index.get(key)
                    if prior and prior != iid:
                        self.conflicts.append(IdentityConflict(
                            kind="SHARED_MRN_DIFFERENT_AADHAAR",
                            detail=(f"MRN {f.value} is shared by two distinct "
                                    f"identities — MRN must be 1:1 with patient. "
                                    f"Flagged for steward review; not merged."),
                            values=[f.value]))
                value_index.setdefault(key, iid)

        # Dedup detection: identities with identical identifier sets
        self._flag_duplicates(identities)
        return identities, finding_owner

    def _flag_duplicates(self, identities: Dict[str, SubjectIdentity]):
        seen: Dict[str, str] = {}
        for iid, ident in identities.items():
            sig = "|".join(
                f"{t}={','.join(sorted(v))}"
                for t, v in sorted(ident.identifiers.items())
            )
            if sig in seen:
                self.conflicts.append(IdentityConflict(
                    kind="DUPLICATE_RECORD",
                    detail=f"Identity {iid} duplicates {seen[sig]} (identical IDs).",
                    values=[iid, seen[sig]]))
            seen[sig] = iid
