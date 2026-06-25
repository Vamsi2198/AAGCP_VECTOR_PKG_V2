# AAGCP-Vector — Demo Run Report

## ACT 1 — THE PROBLEM: what happens today without governance

Six health records embedded raw (the client's current pipeline),
then a perfectly innocent analyst query:

  Query: "patients diagnosed with type 2 diabetes"

  [rec_002] score=0.4884
      Patient Priya Sharma, PAN ABCDE1234F, email priya.sharma@gmail.com, MRN-100871, diagnosed with Type 2 Diabetes with earl...
  [rec_001] score=0.4646
      Patient Ramesh Iyer, Aadhaar 4521 8834 9912, phone +91 9845012345, MRN-100234, diagnosed with Type 2 Diabetes. Treating ...
  [rec_005] score=0.4343
      Patient Vikram Reddy, Aadhaar 9911 2233 4455, phone +91 9123456780, MRN-102388, Type 2 Diabetes with peripheral neuropat...

  >>> Aadhaar numbers, phone numbers, MRNs — all retrievable by ANY caller.
  >>> And the vectors themselves now mathematically encode this PII forever.

## ACT 2 — THE AAGCP ANSWER: six-phase governed ingestion

Same loop as AAGCP on Snowflake — enforcement point moved to the
embedding pipeline. Trace for rec_001:

  OBSERVE: 5 PII entities (AADHAAR, IN_PHONE, MRN, PERSON)
  ANALYZE: risk=1.00, identities=1, subject=Anil Kumar, conflicts=0
  PLAN: 5 tokens minted across 1 identities, strategy=pseudonym_vault
  SIMULATE: leaks raw=5 masked=0, raw↔masked cosine=0.728
  EXECUTE: masked embedding committed, raw discarded
  LEARN: audit chained, stats updated

  Masked text committed to vector space:
  Patient <PERSON_43993b71ec50d1a7>, Aadhaar <AADHAAR_6d92a7facb34846e>, phone <IN_PHONE_790ae95c098486ac>, <MRN_f7ff6b4fe6e96a57>, diagnosed with Type 2 Diabetes...

  Raw↔masked embedding cosine: 0.728
  (semantic neighbourhood preserved — retrieval still works)

## ACT 3 — ONE QUERY, THREE ROLES: dynamic role-based rehydration

AAGCP's Snowflake policy was:
  CASE WHEN CURRENT_ROLE() IN ('ADMIN') THEN val ELSE masked END
Same semantics, now applied at retrieval time:

  ROLE = ANALYST_ROLE
    Patient <PERSON_3366496e0c7cba28>, PAN <PAN_54c2f282c07ab66b>, email <EMAIL_f2de6c66618a21ac>, <MRN_fc5efba8403c8c06>, diagnosed with Type 2 Diabetes ...

  ROLE = HR_ROLE
    Patient Priya Sharma, PAN <PAN_54c2f282c07ab66b>, email priya.sharma@gmail.com, <MRN_fc5efba8403c8c06>, diagnosed with Type 2 Diabetes with early neph...

  ROLE = COMPLIANCE_OFFICER
    Patient Priya Sharma, PAN ABCDE1234F, email priya.sharma@gmail.com, MRN-100871, diagnosed with Type 2 Diabetes with early nephropathy. Dr. Anil Kumar ...

  ROLE = PUBLIC → permitted=False (collection blocked for role)

## ACT 4 — GDPR ART. 17: erase Ramesh Iyer (crypto-shred)

Traditional answer: find every vector, delete, re-embed redacted
versions, pray the model hasn't changed. AAGCP answer: delete the
vault keys. Every vector referencing him is instantly anonymized.

  Certificate ID : 27337c47-32ac-4802-a21c-7afbea7c048a
  Tokens shredded: 4
  Vectors re-embedded: 0  |  deleted: 0
  Audit hash     : eb113890535071dc...

  Same query as ADMIN (highest privilege) AFTER erasure:
    [rec_002] Patient Priya Sharma, PAN ABCDE1234F, email priya.sharma@gmail.com, MRN-100871, diagnosed with Type 2 Diabetes with early nephropathy. Dr. A...
    [rec_001] Patient [ERASED-GDPR], Aadhaar [ERASED-GDPR], phone [ERASED-GDPR], [ERASED-GDPR], diagnosed with Type 2 Diabetes. Treating physician Dr. Ani...

  >>> Even ADMIN cannot recover the subject. Erasure is cryptographic,
  >>> not cosmetic — and required zero vector operations.

## ACT 5 — METRICS & TAMPER-EVIDENT AUDIT

  Documents governed      : 6
  PII leak points removed : 28 (raw pipeline) → 0 (governed)
  Queries served          : 4
  GDPR erasures           : 1 (0 re-embeddings, 0 vector deletions)
  Audit chain valid       : True
  Policy version          : 2026.06.12

  The claim, demonstrated:
  PII never enters vector space; retrieval semantics survive;
  role policy decides what comes back out; erasure is a key deletion.