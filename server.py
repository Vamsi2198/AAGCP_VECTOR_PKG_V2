#!/usr/bin/env python3
"""
AAGCP-Vector :: demo server (Python standard library only — no FastAPI).

Why stdlib: zero dependencies to break in deploy, and the vault is held
in-memory and rebuilt on /reset, which removes the disk-persistence bug
that made the live Erase button fail (an erased subject was tombstoned on
disk and could never be re-seeded).

Every endpoint computes its response from the live control plane. The only
fixed data is the seed corpus (six single-patient records); all outputs —
masking, query results, erasure, audit — are computed at request time.

Run locally:  python server.py        (serves http://localhost:8000)
Render:       binds 0.0.0.0:$PORT
"""

from __future__ import annotations
import json, os, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aagcp_vector.store import HashingEmbedder, InMemoryVectorStore
from aagcp_vector.vault import PseudonymVault
from aagcp_vector.policy import PolicyEngine, AuditChain
from aagcp_vector.control_plane import VectorGovernanceControlPlane
from aagcp_vector.nl_bridge import NLGovernanceBridge

ROOT = Path(__file__).parent
POLICY = str(ROOT / "policies" / "default_policy.yaml")
# Fixed secret → tokens reproducible within a session. In production this
# comes from an env var / KMS, never hard-coded.
SECRET = b"aagcp-vector-demo-secret-32bytes!"

# ── Seed corpus: one patient per record (so erasure is unambiguous) ───
LEXICON = ["Ramesh Iyer", "Priya Sharma", "Arjun Mehta", "Kavya Nair",
           "Vikram Reddy", "Ananya Das", "Anil Kumar", "Sunita Rao"]
SEED = {
    "rec_001": "Patient Ramesh Iyer, Aadhaar 4521 8834 9912, phone +91 9845012345, "
               "MRN-100234, diagnosed with Type 2 Diabetes. Treating physician "
               "Dr. Anil Kumar. Follow-up: metformin titration, HbA1c review in 12 weeks.",
    "rec_002": "Patient Priya Sharma, PAN ABCDE1234F, email priya.sharma@gmail.com, "
               "MRN-100871, diagnosed with Type 2 Diabetes with early nephropathy. "
               "Dr. Anil Kumar recommends SGLT2 inhibitor and renal panel.",
    "rec_003": "Patient Arjun Mehta, Aadhaar 7733 1029 5566, phone 9867554321, "
               "MRN-101422, presented with atrial fibrillation. Dr. Sunita Rao "
               "initiated anticoagulation, cardiology follow-up in 4 weeks.",
    "rec_004": "Patient Kavya Nair, email kavya.n@yahoo.in, MRN-102001, "
               "hypertension well controlled. Dr. Sunita Rao continued amlodipine.",
    "rec_005": "Patient Vikram Reddy, Aadhaar 9911 2233 4455, phone +91 9123456780, "
               "MRN-102388, Type 2 Diabetes with peripheral neuropathy. "
               "Dr. Anil Kumar adjusted insulin regimen, podiatry referral made.",
    "rec_006": "Patient Ananya Das, PAN FGHIJ5678K, MRN-102990, migraine with aura. "
               "Dr. Sunita Rao prescribed prophylaxis, neurology review scheduled.",
}


class Plane:
    """Holds the live control plane; rebuilt fresh on reset()."""
    def __init__(self):
        self._tmp = Path(tempfile.mkdtemp(prefix="aagcp_"))
        self.reset()

    def reset(self) -> dict:
        for f in ("vault.json", "audit.jsonl"):
            p = self._tmp / f
            if p.exists():
                p.unlink()
        self.cp = VectorGovernanceControlPlane(
            embedder=HashingEmbedder(512),
            store=InMemoryVectorStore(),
            vault=PseudonymVault(str(self._tmp / "vault.json"), secret=SECRET),
            policy=PolicyEngine(POLICY),
            audit=AuditChain(str(self._tmp / "audit.jsonl")),
            collection="health_records")
        self.bridge = NLGovernanceBridge(self.cp)
        for doc_id, text in SEED.items():
            self.cp.ingest(doc_id, text, person_lexicon=LEXICON)
        return {"success": True, "seeded": len(SEED),
                "message": f"Fresh database seeded with {len(SEED)} patient records.",
                "records": list(SEED.keys())}


STATE = Plane()


def _report_to_dict(r) -> dict:
    return {
        "success": True, "doc_id": r.doc_id, "executed": r.executed,
        "pii_detected": len(r.findings),
        "entities": [{"type": f.entity_type, "value": f.value,
                      "confidence": f.confidence} for f in r.findings],
        "risk_score": round(r.risk_score, 2),
        "data_subject": r.subject,
        "identities": r.identities,
        "conflicts": r.conflicts,
        "masked_text": r.masked_text,
        "simulate": {"leaks_raw": r.sim_leaks_raw,
                     "leaks_masked": r.sim_leaks_masked,
                     "raw_vs_masked_cosine": round(r.sim_rank_overlap, 3)},
        "phases": r.phase_trace,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, payload, ctype="application/json"):
        body = (payload if isinstance(payload, bytes)
                else json.dumps(payload, default=str).encode())
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ── GET ──────────────────────────────────────────────────────────
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (ROOT / "index.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")
        if self.path == "/health":
            return self._send(200, {"ok": True, "service": "aagcp-vector",
                                    "seeded_records": len(SEED)})
        if self.path == "/audit":
            return self._send(200, {
                "success": True,
                "audit_valid": STATE.cp.audit.verify(),
                "stats": STATE.cp.stats,
                "policy_version": STATE.cp.policy.version})
        return self._send(404, {"error": "not found", "path": self.path})

    # ── POST ─────────────────────────────────────────────────────────
    def do_POST(self):
        b = self._body()
        try:
            if self.path == "/reset":
                return self._send(200, STATE.reset())

            if self.path == "/ingest":
                doc_id = (b.get("doc_id") or "user_doc").strip()
                text = b.get("text") or ""
                if not text.strip():
                    return self._send(400, {"success": False,
                        "message": "Provide document text to ingest."})
                lex = b.get("lexicon")
                if isinstance(lex, str):
                    lex = [s.strip() for s in lex.split(",") if s.strip()]
                lex = lex or LEXICON
                r = STATE.cp.ingest(doc_id, text, person_lexicon=lex)
                return self._send(200, _report_to_dict(r))

            if self.path == "/query":
                role = (b.get("role") or "ANALYST_ROLE").strip()
                q = b.get("query") or ""
                if not q.strip():
                    return self._send(400, {"permitted": False,
                        "reason": "Provide query text."})
                top_k = int(b.get("top_k") or 3)
                return self._send(200, STATE.cp.query(role, q, top_k=top_k))

            if self.path == "/erase":
                subject = (b.get("subject") or "").strip()
                if not subject:
                    return self._send(400, {"executed": False,
                        "message": "Provide a subject name to erase."})
                return self._send(200, STATE.cp.erase_subject(
                    subject, requester=b.get("requester") or "dpo@demo"))

            if self.path == "/nl":
                cmd = (b.get("command") or "").strip()
                if not cmd:
                    return self._send(400, {"executed": False,
                        "message": "Provide a natural-language command."})
                return self._send(200, STATE.bridge.execute(cmd))

            return self._send(404, {"error": "not found", "path": self.path})
        except Exception as e:  # surface, never crash silently
            return self._send(500, {"error": type(e).__name__, "detail": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"AAGCP-Vector server on :{port}  (seeded {len(SEED)} records)")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
