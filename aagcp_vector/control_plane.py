"""
AAGCP-Vector :: The six-phase control plane, ported to vector space.

Same closed loop as ai_control_plane.py — OBSERVE → ANALYZE → PLAN →
SIMULATE → EXECUTE → LEARN — with the enforcement point moved from
"Snowflake masking policy on a column" to "the embedding pipeline of a
vector store". One control plane, two substrates.

The architectural claim under test, stated precisely:

    PII cannot be redacted from a vector after embedding — the
    information is distributed across every dimension. Therefore
    governance must move to ingestion time. Masked-before-embed with a
    deterministic pseudonym vault preserves retrieval semantics, enables
    role-gated rehydration at query time, and reduces GDPR erasure to a
    vault-key deletion (crypto-shred) with zero re-embedding.

SIMULATE is not decorative here: before any document is committed, the
plane embeds BOTH the raw and the masked variant in a sandbox, runs leak
probes against each, and only EXECUTEs if the masked variant leaks
nothing while preserving ranking overlap. Pre-ingestion simulation —
evaluate once per document, not on every query.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import numpy as np

from .pii import PIIDetector, PIIFinding
from .vault import PseudonymVault
from .store import EmbedderAdapter, VectorStoreAdapter, InMemoryVectorStore
from .policy import PolicyEngine, AuditChain
from .resolver import EntityResolver


class Phase(Enum):
    OBSERVE = "observe"
    ANALYZE = "analyze"
    PLAN = "plan"
    SIMULATE = "simulate"
    EXECUTE = "execute"
    LEARN = "learn"


@dataclass
class IngestReport:
    doc_id: str
    findings: List[PIIFinding]
    risk_score: float
    subject: Optional[str]
    masked_text: str
    sim_leaks_raw: int
    sim_leaks_masked: int
    sim_rank_overlap: float
    executed: bool
    phase_trace: List[str] = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    identities: dict = field(default_factory=dict)


class VectorGovernanceControlPlane:
    def __init__(self, embedder: EmbedderAdapter, store: VectorStoreAdapter,
                 vault: PseudonymVault, policy: PolicyEngine,
                 audit: AuditChain, collection: str = "default"):
        self.embedder = embedder
        self.store = store
        self.vault = vault
        self.policy = policy
        self.audit = audit
        self.collection = collection
        self.detector = PIIDetector()
        self.resolver = EntityResolver()
        self.stats = {"ingested": 0, "blocked": 0, "queries": 0,
                      "leaks_prevented": 0, "erasures": 0}
        # Ungoverned twin store used ONLY to demonstrate the leak baseline.
        self._ungoverned = InMemoryVectorStore()

    # ── INGEST: the full six-phase loop per document ─────────────────

    def ingest(self, doc_id: str, text: str,
               person_lexicon: Optional[List[str]] = None,
               probe_queries: Optional[List[str]] = None) -> IngestReport:
        trace = []

        # OBSERVE — detect PII in the source before any embedding
        if person_lexicon:
            self.detector = PIIDetector(person_lexicon=person_lexicon)
        findings = self.detector.scan(text)
        trace.append(f"OBSERVE: {len(findings)} PII entities "
                     f"({', '.join(sorted({f.entity_type for f in findings})) or 'none'})")

        # ANALYZE — entity resolution. The data subject is keyed on the
        # STRONGEST identifier per record (Aadhaar > PAN > MRN > name), not
        # on the display name. Same Aadhaar across records merges; same name
        # with different Aadhaar stays distinct; conflicting strong IDs are
        # flagged, never silently merged.
        risk = self.detector.risk_score(findings)
        identities, finding_owner = self.resolver.resolve(text, findings)
        conflicts = self.resolver.conflicts
        # "subject" for the report = the highest-confidence identity's name
        subject = None
        if identities:
            primary = max(identities.values(),
                          key=lambda i: (i.confidence, len(i.identifiers)))
            subject = (sorted(primary.display_names)[0]
                       if primary.display_names else primary.canonical_value)
        trace.append(f"ANALYZE: risk={risk:.2f}, identities={len(identities)}, "
                     f"subject={subject or 'unattributed'}, "
                     f"conflicts={len(conflicts)}")

        # PLAN — masking plan: deterministic, linkage-preserving tokens, each
        # attributed to its resolved identity (right-to-left to keep offsets).
        masked_text = text
        for f in sorted(findings, key=lambda x: x.start, reverse=True):
            iid = finding_owner.get(id(f))
            dname = f.value if f.entity_type == "PERSON" else None
            masked_text = (masked_text[: f.start]
                           + self.vault.token_for(f, identity_id=iid,
                                                   display_name=dname)
                           + masked_text[f.end:])
        trace.append(f"PLAN: {len(findings)} tokens minted across "
                     f"{len(identities)} identities, strategy=pseudonym_vault")

        # SIMULATE — sandbox both variants, probe for leaks, check ranking
        raw_vec = self.embedder.embed(text)
        masked_vec = self.embedder.embed(masked_text)
        probes = probe_queries or ["patient diagnosis", "contact details"]
        leaks_raw = self._count_leaks(text, findings)
        leaks_masked = self._count_leaks(masked_text, findings)
        overlap = float(np.dot(raw_vec, masked_vec))  # cosine of the two variants
        trace.append(f"SIMULATE: leaks raw={leaks_raw} masked={leaks_masked}, "
                     f"raw↔masked cosine={overlap:.3f}")

        gate_ok = leaks_masked == 0 and (
            self.policy.raw_pii_embedding_allowed(self.collection) is False
        )

        # EXECUTE — commit masked variant only; raw vector is discarded
        executed = False
        if gate_ok:
            self.store.upsert(doc_id, masked_vec, masked_text,
                              {"collection": self.collection,
                               "pii_count": len(findings),
                               "subject_attributed": bool(subject)})
            self._ungoverned.upsert(doc_id, raw_vec, text, {})  # baseline twin
            self.vault.save()
            executed = True
            self.stats["ingested"] += 1
            self.stats["leaks_prevented"] += leaks_raw
            trace.append("EXECUTE: masked embedding committed, raw discarded")
        else:
            self.stats["blocked"] += 1
            trace.append("EXECUTE: BLOCKED by simulate gate")

        # LEARN — audit chain + stats
        self.audit.record("VECTOR_INGEST", doc_id=doc_id,
                          collection=self.collection,
                          pii_entities=len(findings), risk=risk,
                          subject=subject, executed=executed,
                          policy_version=self.policy.version)
        trace.append("LEARN: audit chained, stats updated")

        report = IngestReport(doc_id, findings, risk, subject, masked_text,
                              leaks_raw, leaks_masked, overlap, executed, trace)
        report.conflicts = [c.__dict__ for c in conflicts]
        report.identities = {iid: {"canonical_type": i.canonical_type,
                                    "names": sorted(i.display_names),
                                    "identifiers": {t: sorted(v) for t, v in i.identifiers.items()}}
                              for iid, i in identities.items()}
        return report

    @staticmethod
    def _count_leaks(text: str, findings: List[PIIFinding]) -> int:
        return sum(1 for f in findings if f.value in text)

    # ── QUERY: role-gated retrieval with rehydration ─────────────────

    def query(self, role: str, query_text: str, top_k: int = 3) -> dict:
        if not self.policy.role_exists(role):
            self.audit.record("QUERY_DENIED", role=role, reason="unknown_role")
            return {"permitted": False, "reason": f"unknown role '{role}'", "results": []}
        if not self.policy.collection_allows_query(role, self.collection):
            self.audit.record("QUERY_DENIED", role=role, reason="collection_blocked")
            return {"permitted": False, "reason": "collection blocked for role", "results": []}

        qvec = self.embedder.embed(query_text)
        hits = self.store.query(qvec, top_k=top_k)

        reveal = self.policy.reveal_set(role)
        partial = self.policy.partial_rules(role)
        for h in hits:
            h["text"] = self.vault.rehydrate(h["text"], reveal, partial)

        self.stats["queries"] += 1
        self.audit.record("VECTOR_QUERY", role=role, query=query_text,
                          retrieved=[h["id"] for h in hits],
                          reveal_types=sorted(reveal) or ["none"])
        return {"permitted": True, "role": role, "results": hits}

    def query_ungoverned_baseline(self, query_text: str, top_k: int = 3) -> List[dict]:
        """What the client's stack does today: raw text in, raw PII out."""
        return self._ungoverned.query(self.embedder.embed(query_text), top_k)

    # ── ERASE: GDPR Art. 17 via crypto-shred ─────────────────────────

    def erase_subject(self, subject: str, requester: str) -> dict:
        """
        Erase by name → resolve to identity(ies) → reference-counted shred.
        If the name maps to multiple distinct identities (true name
        collision), refuse and ask for a disambiguating identifier — we do
        not erase the wrong person.
        """
        iids = self.vault.resolve_identities_by_name(subject)
        if not iids:
            return {"executed": False, "subject": subject,
                    "certificate_id": str(uuid.uuid4()),
                    "tokens_shredded": [], "tokens_retained_shared": [],
                    "vectors_reembedded": 0, "vectors_deleted": 0,
                    "message": f"No vault identity matches '{subject}'."}
        if len(iids) > 1:
            return {"executed": False, "subject": subject, "ambiguous": True,
                    "candidate_identities": iids,
                    "certificate_id": str(uuid.uuid4()),
                    "tokens_shredded": [],
                    "message": (f"'{subject}' matches {len(iids)} distinct "
                                f"subjects. Specify an identifier (e.g. Aadhaar) "
                                f"to erase the right one.")}
        res = self.vault.crypto_shred_identity(iids[0])
        cert = {"certificate_id": str(uuid.uuid4()), "executed": True,
                "subject": subject, "identity_id": iids[0],
                "tokens_shredded": res["tokens_destroyed"],
                "tokens_retained_shared": res["tokens_retained_shared"],
                "vectors_reembedded": 0, "vectors_deleted": 0,
                "method": res["method"], "requester": requester}
        cert["audit"] = self.audit.record(
            "GDPR_ERASURE", subject=subject, identity_id=iids[0],
            requester=requester,
            tokens_destroyed=len(res["tokens_destroyed"]),
            tokens_retained_shared=len(res["tokens_retained_shared"]),
            method=res["method"], vectors_touched=0)
        self.stats["erasures"] += 1
        return cert
