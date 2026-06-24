# AAGCP-Vector — Demo Guide

## What this demo proves (say this first)
PII can be governed *inside* a vector database. Four claims, each visible
on screen: PII never enters the vector, retrieval still works, role policy
decides what comes back out, erasure is a key deletion — surgical and
provable.

## Use cases (your "what does it solve" list)
- Healthcare RAG with Aadhaar / MRN in clinical notes
- BFSI document search with PAN and account data
- HR / legal RAG with role-based access (analyst de-identified, compliance full)
- DPDP / GDPR right-to-erasure executed against a vector store
- Tamper-evident audit evidence for a regulator or security review
- One query returning different content depending on who asks
- De-duplication and identity resolution across messy records

## The 5 masking issues (your "why this approach" spine)
1. Can't redact a vector after embedding → mask before embedding
2. Naive redaction destroys retrieval → deterministic tokens
3. Cross-document linkage must survive → same entity, same token
4. Erasure must be surgical + provable → reference-counted key deletion
5. A name is not an identity → resolve on strongest ID (Aadhaar > PAN > MRN > name)

## Run order (maps to the API-tester buttons)
1. **/health** — it's live, not slides.
2. **/ingest** a single-patient record — narrate the phase trace; show
   `masked_text` (every Aadhaar/phone/MRN tokenized); point at
   `SIMULATE: leaks raw=N masked=0`. → "PII never entered the vector."
3. **/query as ANALYST_ROLE** — tokens stay masked in results.
4. **/query the same text as COMPLIANCE_OFFICER** — values rehydrated.
   → "Same query, different role, different output — my Snowflake
   CURRENT_ROLE() policy, applied at retrieval time."
5. **/erase** that patient, then **/query as ADMIN** → `[ERASED-GDPR]`,
   even top privilege can't recover them. → "Erasure was a key deletion.
   Vectors touched: zero."
6. **/audit** → chain valid. One **/nl-command** → same grammar, two substrates.

## The showpiece (do this once the patch is deployed)
Ingest a **two-patient** document with a shared MRN and a label-less
record, then erase one patient:
- Two identities resolve, keyed on Aadhaar (not name)
- The shared MRN is flagged as a conflict, not merged
- Erasing Ramesh destroys only his tokens; the shared MRN is **retained**
  because Dinesh still owns it; Dinesh's record is untouched
→ "I erased one patient. The other — same document, shared MRN and all —
is fully intact. The system refused to over-erase." This is the moment.

## Guardrails
- The two-patient erase is safe **only on the patched build** (this one).
  On the old deploy it destroys the other patient — don't show that.
- Don't restart the server mid-demo unless the vault secret is persisted
  (env var / mounted file), or tokens change.
- Don't claim medical conditions are masked — name that as roadmap.
- One concrete ask, in order: (1) wire the Endee adapter together in a
  working session, (2) co-present to the client who raised the question,
  (3) then the role conversation.

## Lines to memorize
"You can't mask a vector, so we moved enforcement upstream."
"Same person, same token, across every document — that's why search works."
"A name isn't an identity; we key on Aadhaar, so the right person is erased."
"Erasure is a key deletion. Zero vectors touched. And it won't harm the other subject."
"This makes your database sellable into healthcare — it's not a competitor."
