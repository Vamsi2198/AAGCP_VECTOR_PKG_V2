"""
AAGCP-Vector :: Pseudonym Vault (identity-aware, reference-counted).

You don't mask the vector — you make sure PII never enters it.

  1. Deterministic tokenization: HMAC(secret, type|value) → stable token.
     Same value ⇒ same token across every document, so cross-document
     linkage (and retrieval quality) survives.
  2. Vault holds token → {value, owning identities}. Corpus holds tokens only.
  3. Role-gated rehydration at query time = AAGCP's Snowflake masking CASE,
     applied at retrieval.
  4. GDPR erasure = crypto-shred by IDENTITY, reference-counted: a token is
     destroyed only when NO surviving identity still references it. This is
     what makes erasure surgical when records share identifiers (e.g. a name
     two real people share, or a wrongly-shared MRN) — erasing one subject
     never collaterally erases another.

Secret persistence: pass `secret` (from env/file) so tokens stay stable
across process restarts. Without it a fresh secret is minted per process
(fine for a single demo, wrong for a running service).
"""

from __future__ import annotations
import hmac, hashlib, json, secrets, re
from pathlib import Path
from typing import Dict, List, Optional, Set

from .pii import PIIFinding


class PseudonymVault:
    def __init__(self, vault_path: str, secret: Optional[bytes] = None):
        self.path = Path(vault_path)
        self.secret = secret or secrets.token_bytes(32)
        # token -> {"type":..., "value":..., "identities": set[str]}
        self._store: Dict[str, dict] = {}
        # identity_id -> set[token]
        self._identities: Dict[str, Set[str]] = {}
        # identity_id -> set[display name]  (for erase-by-name resolution)
        self._idnames: Dict[str, Set[str]] = {}
        self._shredded: List[str] = []
        if self.path.exists():
            self._load()

    # ── Tokenization ────────────────────────────────────────────────

    def token_for(self, finding: PIIFinding,
                  identity_id: Optional[str] = None,
                  display_name: Optional[str] = None) -> str:
        digest = hmac.new(
            self.secret,
            f"{finding.entity_type}|{finding.value.strip().lower()}".encode(),
            hashlib.sha256,
        ).hexdigest()[:16]  # 64-bit: collision-safe at 10M+ tokens (was 32-bit)
        token = f"<{finding.entity_type}_{digest}>"

        if token in self._shredded:
            return token  # already erased; never resurrect

        entry = self._store.setdefault(
            token, {"type": finding.entity_type, "value": finding.value,
                    "identities": set()})
        if identity_id:
            entry["identities"].add(identity_id)
            self._identities.setdefault(identity_id, set()).add(token)
            if display_name:
                self._idnames.setdefault(identity_id, set()).add(display_name)
        return token

    # ── Rehydration (query-time, policy-gated) ──────────────────────

    def resolve(self, token: str) -> Optional[dict]:
        return self._store.get(token)

    def rehydrate(self, text: str, permitted_types: set,
                  partial_rules: Dict[str, str]) -> str:
        def _sub(m):
            token = m.group(0)
            if token in self._shredded:
                return "[ERASED-GDPR]"
            entry = self._store.get(token)
            if not entry:
                return token
            etype, value = entry["type"], entry["value"]
            if "ALL" in permitted_types or etype in permitted_types:
                return value
            if partial_rules.get(etype) == "last4":
                return "*" * max(len(value) - 4, 2) + value[-4:]
            return token
        return re.sub(r"<[A-Z_]+_[0-9a-f]+>", _sub, text)  # width-agnostic

    # ── Crypto-shred (GDPR Art. 17), reference-counted ──────────────

    def resolve_identities_by_name(self, name: str) -> List[str]:
        n = name.strip().lower()
        return [iid for iid, names in self._idnames.items()
                if any(n == dn.strip().lower() for dn in names)]

    def crypto_shred_identity(self, identity_id: str) -> dict:
        """
        Erase ONE identity. For each of its tokens, drop this identity from
        the token's owner set; destroy the token only if no identity remains.
        Returns which tokens were destroyed vs retained (still referenced).
        """
        tokens = self._identities.pop(identity_id, set())
        self._idnames.pop(identity_id, None)
        destroyed, retained = [], []
        for t in tokens:
            entry = self._store.get(t)
            if not entry:
                continue
            entry["identities"].discard(identity_id)
            if entry["identities"]:
                retained.append(t)            # another subject still owns it
            else:
                del self._store[t]
                self._shredded.append(t)
                destroyed.append(t)
        self.save()
        return {"identity_id": identity_id,
                "tokens_destroyed": destroyed,
                "tokens_retained_shared": retained,
                "vectors_reembedded": 0, "vectors_deleted": 0,
                "method": "reference_counted_crypto_shred"}

    # ── Persistence ─────────────────────────────────────────────────

    def save(self):
        self.path.write_text(json.dumps({
            "store": {k: {**v, "identities": sorted(v["identities"])}
                      for k, v in self._store.items()},
            "identities": {k: sorted(v) for k, v in self._identities.items()},
            "idnames": {k: sorted(v) for k, v in self._idnames.items()},
            "shredded": self._shredded}, indent=2))

    def _load(self):
        d = json.loads(self.path.read_text())
        self._store = {k: {**v, "identities": set(v.get("identities", []))}
                       for k, v in d.get("store", {}).items()}
        self._identities = {k: set(v) for k, v in d.get("identities", {}).items()}
        self._idnames = {k: set(v) for k, v in d.get("idnames", {}).items()}
        self._shredded = d.get("shredded", [])
