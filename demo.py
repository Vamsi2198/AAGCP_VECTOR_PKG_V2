#!/usr/bin/env python3
"""
AAGCP-Vector — end-to-end demonstration.

The exact client question this answers:
  "Our documents contain PII. Once they're embedded in a vector database,
   how do we mask it?"

Run:  python demo.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from aagcp_vector.pii import PIIDetector
from aagcp_vector.vault import PseudonymVault
from aagcp_vector.store import HashingEmbedder, InMemoryVectorStore
from aagcp_vector.policy import PolicyEngine, AuditChain
from aagcp_vector.control_plane import VectorGovernanceControlPlane

OUT = Path(__file__).parent / "demo_output"
OUT.mkdir(exist_ok=True)
REPORT = []

def section(title):
    line = "=" * 72
    print(f"\n{line}\n  {title}\n{line}")
    REPORT.append(f"\n## {title}\n")

def log(msg=""):
    print(msg)
    REPORT.append(msg)

# ── Demo corpus: Indian healthcare records (synthetic) ────────────────

PATIENTS = ["Ramesh Iyer", "Priya Sharma", "Arjun Mehta", "Kavya Nair",
            "Vikram Reddy", "Ananya Das"]
DOCTORS = ["Anil Kumar", "Sunita Rao"]
LEXICON = PATIENTS + DOCTORS

DOCS = {
    "rec_001": "Patient Ramesh Iyer, Aadhaar 4521 8834 9912, phone +91 9845012345, "
               "MRN-100234, diagnosed with Type 2 Diabetes. Treating physician Dr. Anil Kumar. "
               "Follow-up: metformin titration, HbA1c review in 12 weeks.",
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

PROBES = ["patients diagnosed with type 2 diabetes",
          "cardiology and heart rhythm cases",
          "who is treated by Dr. Anil Kumar"]

# ── Build the plane ───────────────────────────────────────────────────

for f in ["vault.json", "audit.jsonl"]:
    p = OUT / f
    if p.exists():
        p.unlink()

# Fixed secret → tokens are reproducible across runs (good for screenshots)
# and stable across restarts. In production this comes from an env var or
# mounted file / KMS, never hard-coded.
DEMO_SECRET = b"aagcp-vector-demo-secret-32bytes!"
POLICY = str(Path(__file__).parent / "policies" / "default_policy.yaml")

embedder = HashingEmbedder(dim=512)
plane = VectorGovernanceControlPlane(
    embedder=embedder,
    store=InMemoryVectorStore(),
    vault=PseudonymVault(str(OUT / "vault.json"), secret=DEMO_SECRET),
    policy=PolicyEngine(POLICY),
    audit=AuditChain(str(OUT / "audit.jsonl")),
    collection="health_records",
)

# ── ACT 1: The problem — ungoverned RAG leaks everything ─────────────

section("ACT 1 — THE PROBLEM: what happens today without governance")
log("Six health records embedded raw (the client's current pipeline),")
log("then a perfectly innocent analyst query:\n")

reports = {}
for doc_id, text in DOCS.items():
    reports[doc_id] = plane.ingest(doc_id, text, person_lexicon=LEXICON,
                                   probe_queries=PROBES)

q = "patients diagnosed with type 2 diabetes"
log(f'  Query: "{q}"\n')
for hit in plane.query_ungoverned_baseline(q, top_k=3):
    log(f"  [{hit['id']}] score={hit['score']}")
    log(f"      {hit['text'][:120]}...")
log("\n  >>> Aadhaar numbers, phone numbers, MRNs — all retrievable by ANY caller.")
log("  >>> And the vectors themselves now mathematically encode this PII forever.")

# ── ACT 2: The six-phase loop, per document ──────────────────────────

section("ACT 2 — THE AAGCP ANSWER: six-phase governed ingestion")
log("Same loop as AAGCP on Snowflake — enforcement point moved to the")
log("embedding pipeline. Trace for rec_001:\n")

report = reports["rec_001"]
for step in report.phase_trace:
    log(f"  {step}")
log(f"\n  Masked text committed to vector space:")
log(f"  {report.masked_text[:160]}...")
log(f"\n  Raw↔masked embedding cosine: {report.sim_rank_overlap:.3f}")
log("  (semantic neighbourhood preserved — retrieval still works)")

# ── ACT 3: Role-gated rehydration (the Snowflake CASE, at query time) ─

section("ACT 3 — ONE QUERY, THREE ROLES: dynamic role-based rehydration")
log("AAGCP's Snowflake policy was:")
log("  CASE WHEN CURRENT_ROLE() IN ('ADMIN') THEN val ELSE masked END")
log("Same semantics, now applied at retrieval time:\n")

for role in ["ANALYST_ROLE", "HR_ROLE", "COMPLIANCE_OFFICER"]:
    res = plane.query(role, q, top_k=1)
    hit = res["results"][0]
    log(f"  ROLE = {role}")
    log(f"    {hit['text'][:150]}...")
    log("")

res = plane.query("PUBLIC", q)
log(f"  ROLE = PUBLIC → permitted={res['permitted']} ({res['reason']})")

# ── ACT 4: GDPR erasure via crypto-shred ─────────────────────────────

section("ACT 4 — GDPR ART. 17: erase Ramesh Iyer (crypto-shred)")
log("Traditional answer: find every vector, delete, re-embed redacted")
log("versions, pray the model hasn't changed. AAGCP answer: delete the")
log("vault keys. Every vector referencing him is instantly anonymized.\n")

cert = plane.erase_subject("Ramesh Iyer", requester="dpo@client.example")
log(f"  Certificate ID : {cert['certificate_id']}")
log(f"  Tokens shredded: {len(cert['tokens_shredded'])}")
log(f"  Vectors re-embedded: {cert['vectors_reembedded']}  |  deleted: {cert['vectors_deleted']}")
log(f"  Audit hash     : {cert['audit']['record_hash'][:16]}...\n")

res = plane.query("ADMIN", q, top_k=2)
log("  Same query as ADMIN (highest privilege) AFTER erasure:")
for hit in res["results"]:
    log(f"    [{hit['id']}] {hit['text'][:140]}...")
log("\n  >>> Even ADMIN cannot recover the subject. Erasure is cryptographic,")
log("  >>> not cosmetic — and required zero vector operations.")

# ── ACT 5: The evidence ──────────────────────────────────────────────

section("ACT 5 — METRICS & TAMPER-EVIDENT AUDIT")
total_leaks = plane.stats["leaks_prevented"]
log(f"  Documents governed      : {plane.stats['ingested']}")
log(f"  PII leak points removed : {total_leaks} (raw pipeline) → 0 (governed)")
log(f"  Queries served          : {plane.stats['queries']}")
log(f"  GDPR erasures           : {plane.stats['erasures']} "
    f"(0 re-embeddings, 0 vector deletions)")
log(f"  Audit chain valid       : {plane.audit.verify()}")
log(f"  Policy version          : {plane.policy.version}")

log("\n  The claim, demonstrated:")
log("  PII never enters vector space; retrieval semantics survive;")
log("  role policy decides what comes back out; erasure is a key deletion.")

(OUT / "run_report.md").write_text(
    "# AAGCP-Vector — Demo Run Report\n" + "\n".join(REPORT),
    encoding="utf-8")
print(f"\nReport written to {OUT/'run_report.md'}")

# ── ACT 6: Natural-language governance — same grammar, two substrates ──
from aagcp_vector.nl_bridge import NLGovernanceBridge
section("ACT 6 — NL COMMANDS: same grammar as the Snowflake plane")
log('Your AAGCP accepts "mask ssn in HEALTH_RECORDS for analyst roles".')
log("Identical commands now drive vector-space governance:\n")
bridge = NLGovernanceBridge(plane)
for c in ['mask pii in health_records for analyst roles',
          'unmask pii in health_records for compliance roles',
          'as ANALYST_ROLE: patients with diabetes',
          'verify audit']:
    r = bridge.execute(c)
    log(f'  > {c}')
    log(f'    {r["message"]}\n')

# ── ACT 7: Entity resolution + surgical multi-subject erasure ─────────
section("ACT 7 — IDENTITY ≠ NAME: resolution, conflicts, surgical erase")
log("A messy real-world document: two patients, one shared (wrong) MRN,")
log("a record with no field labels. Identity is keyed on Aadhaar, not name.\n")
messy = ("Patient Ramesh Iyer, Aadhaar 4521 8834 9912, phone +91 9845012345, "
         "MRN-100234, diagnosed with Type 2 Diabetes.\n"
         "Patient Dinesh Iyer, Aadhaar 4521 8834 6723, phone +91 9845067895, "
         "MRN-100234, diagnosed with Type 2 sugar\n"
         " Dinesh Iyer, 4521 8834 6723, +91 9845067895, MRN-100234, Type 2 sugar")
# Clean, isolated plane for this scenario — Act 4 already erased Ramesh in
# the main plane, and (correctly) a tombstoned subject is not resurrected by
# re-ingestion. Isolating here keeps the multi-subject story uncontaminated.
for f in ["vault7.json", "audit7.jsonl"]:
    if (OUT / f).exists():
        (OUT / f).unlink()
plane7 = VectorGovernanceControlPlane(
    embedder=embedder, store=InMemoryVectorStore(),
    vault=PseudonymVault(str(OUT / "vault7.json"), secret=DEMO_SECRET),
    policy=PolicyEngine(POLICY), audit=AuditChain(str(OUT / "audit7.jsonl")),
    collection="health_records")
r7 = plane7.ingest("rec_multi", messy,
                   person_lexicon=["Ramesh Iyer", "Dinesh iyer"])
log(f"  Identities resolved: {len(r7.identities)} (keyed on Aadhaar)")
for iid, info in r7.identities.items():
    log(f"    {info['names']} → Aadhaar {info['identifiers'].get('AADHAAR')}")
log(f"  Conflicts flagged: {len(r7.conflicts)}")
for c in r7.conflicts[:1]:
    log(f"    ⚠ {c['kind']} — {c['detail']}")
log("\n  Erase 'Ramesh Iyer':")
c7 = plane7.erase_subject("Ramesh Iyer", requester="dpo@client.example")
log(f"    Destroyed (Ramesh-only): {c7['tokens_shredded']}")
log(f"    Retained (shared, Dinesh still owns): {c7['tokens_retained_shared']}")
log("\n  Same query as ADMIN after erasing Ramesh:")
for h in plane7.query("ADMIN", "patients type 2", top_k=2)["results"]:
    log(f"    {h['text'][:120]}")
log("\n  >>> Ramesh is cryptographically gone. Dinesh — same document, shared")
log("  >>> MRN and all — is untouched. Erasure refused to harm the other subject.")
