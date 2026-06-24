"""
AAGCP-Vector :: Natural-language command bridge.

This is the piece that makes AAGCP-Vector *the same product* as AAGCP
rather than a second demo. The existing control plane accepts commands
like:

    "mask ssn in HEALTH_RECORDS table for analyst roles"

and compiles them into Snowflake masking policies via the six-phase loop.
This bridge accepts the identical grammar — including the role-directive
negation keywords (for / not for / except) from
DYNAMIC_ROLE_BASED_MASKING.md — and compiles them into vector-space
governance actions instead:

    mask pii in health_records for analyst roles      → reveal-set policy
    unmask pii in health_records for compliance roles → reveal ALL
    erase Ramesh Iyer from health_records             → GDPR crypto-shred
    as ANALYST_ROLE: patients with diabetes           → governed query
    verify audit                                      → chain integrity
    stats                                             → plane metrics

One NL surface, two substrates: columns and vectors.
"""

from __future__ import annotations
import re
from typing import Optional

from .control_plane import VectorGovernanceControlPlane

# Mirrors the role-keyword table in DYNAMIC_ROLE_BASED_MASKING.md
_ROLE_ALIASES = {
    "analyst": "ANALYST_ROLE", "analysts": "ANALYST_ROLE",
    "hr": "HR_ROLE", "finance": "FINANCE_ROLE", "it": "IT_ROLE",
    "admin": "ADMIN", "admins": "ADMIN",
    "data_steward": "DATA_STEWARD", "data steward": "DATA_STEWARD",
    "compliance": "COMPLIANCE_OFFICER", "compliance officer": "COMPLIANCE_OFFICER",
    "public": "PUBLIC",
}

_ALL_PII = ["PERSON", "AADHAAR", "PAN", "IN_PHONE", "EMAIL", "MRN"]


def _canon_role(raw: str) -> Optional[str]:
    raw = raw.strip().lower().replace("roles", "").replace("role", "").strip(" _")
    return _ROLE_ALIASES.get(raw, raw.upper() if raw else None)


class NLGovernanceBridge:
    def __init__(self, plane: VectorGovernanceControlPlane):
        self.plane = plane

    def execute(self, command: str) -> dict:
        cmd = command.strip()

        # ── erase <Name> from <collection> ───────────────────────────
        m = re.match(r"erase\s+(.+?)\s+from\s+(\w+)", cmd, re.I)
        if m:
            subject, collection = m.group(1).strip(), m.group(2)
            cert = self.plane.erase_subject(subject, requester="nl_bridge")
            ok = bool(cert["tokens_shredded"])
            return {"intent": "GDPR_ERASURE", "subject": subject,
                    "collection": collection, "executed": ok,
                    "certificate_id": cert["certificate_id"],
                    "tokens_shredded": len(cert["tokens_shredded"]),
                    "vectors_touched": 0,
                    "message": (f"Crypto-shredded {len(cert['tokens_shredded'])} "
                                f"identifiers for '{subject}'. Zero vectors touched."
                                if ok else f"No vault entries found for '{subject}'.")}

        # ── mask/unmask pii in <collection> [not] for <role> roles ──
        m = re.match(
            r"(mask|unmask)\s+pii\s+in\s+(\w+)\s+(?:table\s+|collection\s+)?"
            r"(not\s+for|except|for)\s+([\w ]+?)\s*(?:roles?)?$", cmd, re.I)
        if m:
            action, collection, direction, role_raw = m.groups()
            role = _canon_role(role_raw)
            negated = direction.lower() in ("not for", "except")
            roles_cfg = self.plane.policy.policy.setdefault("roles", {})
            roles_cfg.setdefault(role, {})

            # Same truth table as the Snowflake CASE generator:
            # mask for X        → X sees tokens        (reveal = [])
            # mask not for X    → X sees values        (reveal = ALL)
            # unmask for X      → X sees values        (reveal = ALL)
            # unmask not for X  → X sees tokens        (reveal = [])
            sees_values = (action.lower() == "unmask") ^ negated
            roles_cfg[role]["reveal"] = ["ALL"] if sees_values else []

            self.plane.audit.record("POLICY_UPDATE_NL", command=cmd,
                                    role=role, reveal=roles_cfg[role]["reveal"],
                                    collection=collection)
            return {"intent": "POLICY_UPDATE", "role": role,
                    "collection": collection, "executed": True,
                    "reveal": roles_cfg[role]["reveal"],
                    "message": (f"{role} now sees "
                                f"{'UNMASKED values' if sees_values else 'masked tokens'} "
                                f"in {collection}. (Equivalent Snowflake policy: "
                                f"CASE WHEN CURRENT_ROLE() "
                                f"{'IN' if sees_values else 'NOT IN'} "
                                f"('{role}') THEN val ELSE token END)")}

        # ── as <ROLE>: <query> ───────────────────────────────────────
        m = re.match(r"(?:query\s+)?as\s+([\w ]+?)\s*[:,]\s*(.+)", cmd, re.I)
        if m:
            role = _canon_role(m.group(1)) or m.group(1).upper()
            res = self.plane.query(role, m.group(2).strip(), top_k=2)
            return {"intent": "GOVERNED_QUERY", "role": role, **res,
                    "message": (f"{len(res['results'])} results under {role} policy."
                                if res["permitted"] else
                                f"Denied: {res['reason']}")}

        # ── verify audit ─────────────────────────────────────────────
        if re.match(r"verify\s+audit", cmd, re.I):
            ok = self.plane.audit.verify()
            return {"intent": "AUDIT_VERIFY", "executed": True, "chain_valid": ok,
                    "message": "Audit hash-chain intact."
                               if ok else "TAMPERING DETECTED in audit chain."}

        # ── stats ────────────────────────────────────────────────────
        if re.match(r"stats|status|show\s+metrics", cmd, re.I):
            return {"intent": "STATS", "executed": True, **self.plane.stats,
                    "message": f"Plane stats: {self.plane.stats}"}

        return {"intent": "UNKNOWN", "executed": False,
                "message": f"Could not parse: '{cmd}'. Supported: mask/unmask pii, "
                           f"erase X from Y, as ROLE: query, verify audit, stats."}
