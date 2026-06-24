"""
AAGCP-Vector :: Policy engine (declarative YAML) + hash-chained audit log.

Policy is data, not code — versioned, diffable, auditable (EU AI Act
Art. 11 technical documentation requirement). Role semantics intentionally
mirror the existing AAGCP Snowflake role model (ADMIN, DATA_STEWARD,
ANALYST_ROLE, HR_ROLE...) so one policy language can eventually drive
both enforcement points: column masking AND retrieval-time rehydration.

Audit log is an append-only JSONL hash chain (each record carries the
SHA256 of its predecessor) — the lightweight version of the WORM /
tamper-evident store already specified in AAGCP's architecture.
"""

from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Optional

import yaml


class PolicyEngine:
    def __init__(self, policy_path: str):
        self.path = Path(policy_path)
        self.policy = yaml.safe_load(self.path.read_text())

    @property
    def version(self) -> str:
        return str(self.policy.get("version", "unversioned"))

    def role_exists(self, role: str) -> bool:
        return role in self.policy.get("roles", {})

    def collection_allows_query(self, role: str, collection: str) -> bool:
        coll = self.policy.get("collections", {}).get(collection, {})
        return role not in set(coll.get("block_query_roles", []))

    def reveal_set(self, role: str) -> set:
        return set(self.policy.get("roles", {}).get(role, {}).get("reveal", []))

    def partial_rules(self, role: str) -> Dict[str, str]:
        return dict(self.policy.get("roles", {}).get(role, {}).get("partial", {}))

    def raw_pii_embedding_allowed(self, collection: str) -> bool:
        coll = self.policy.get("collections", {}).get(collection, {})
        return coll.get("pii_embedding", "deny_raw") != "deny_raw"


class AuditChain:
    GENESIS = "0" * 64

    def __init__(self, log_path: str):
        self.path = Path(log_path)
        self._prev = self.GENESIS
        if self.path.exists():
            lines = self.path.read_text().strip().splitlines()
            if lines:
                self._prev = json.loads(lines[-1])["record_hash"]

    def record(self, event: str, **fields) -> dict:
        entry = {
            "ts": time.time(),
            "event": event,
            **fields,
            "prev_hash": self._prev,
        }
        entry["record_hash"] = hashlib.sha256(
            json.dumps(entry, sort_keys=True, default=str).encode()
        ).hexdigest()
        self._prev = entry["record_hash"]
        with self.path.open("a") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
        return entry

    def verify(self) -> bool:
        """Recompute the chain; any tampering breaks linkage."""
        prev = self.GENESIS
        for line in self.path.read_text().strip().splitlines():
            rec = json.loads(line)
            claimed = rec.pop("record_hash")
            if rec.get("prev_hash") != prev:
                return False
            recomputed = hashlib.sha256(
                json.dumps(rec, sort_keys=True, default=str).encode()
            ).hexdigest()
            if recomputed != claimed:
                return False
            prev = claimed
        return True
