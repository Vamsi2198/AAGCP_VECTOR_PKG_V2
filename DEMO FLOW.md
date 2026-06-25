# AAGCP-Vector — Run & Speak (Live Console)

The console has a **Guided flow** bar (steps 1–6) and editable cards below.
Each guided step fills the input fields then runs, so the founder always
sees the input that produced the output — nothing is canned.

Open the page. Then walk it in this order.

---

## Step 0 — Frame it (before touching anything)

> "Your client asked: once documents are embedded in a vector DB, how do
> you mask the PII? You can't — the PII is smeared across every dimension.
> So we move enforcement upstream. Let me show you, live, on Indian
> healthcare records with Aadhaar and PAN."

## Step 1 — Reset & seed

Tap **1 · Reset & seed**.

> "Six patient records, just ingested. Each one went through detect →
> tokenize → embed. The PII is already gone from what's stored — let me
> prove both halves: that it's gone, and that search still works."

## Step 2 — Query as analyst

Tap **2 · Query as analyst**.

> "An analyst searches 'patients with type 2 diabetes'. Search worked —
> the right records came back. But look what they see: every name, Aadhaar,
> PAN is a token. Aadhaar shows only last-4. This analyst can do their job
> and never touch real PII."

## Step 3 — Query as compliance

Tap **3 · Query as compliance**.

> "Same query, same stored vectors, different role. The compliance officer
> is allowed to see the real values, so the layer rehydrates them at
> retrieval time. The vector DB did nothing different — my layer decided.
> This is my Snowflake CURRENT_ROLE() masking policy, applied to vectors."

## Step 4 — Erase Ramesh Iyer

Tap **4 · Erase Ramesh Iyer**.

> "DPDP / GDPR erasure request for Ramesh. Watch the numbers: tokens
> destroyed, zero vectors re-embedded, zero vectors deleted. Erasure is a
> key deletion in the vault, not a re-embedding marathon. And notice one
> token was _retained_ — that's Dr. Anil Kumar, who treats other patients.
> The system refused to erase the doctor while erasing the patient."

## Step 5 — Re-query (erased)

Tap **5 · Re-query (erased)**.

> "Same compliance query again — the highest-privilege role. Ramesh's
> record now reads ERASED-GDPR on every identifier. The other patients are
> untouched. Even an admin cannot recover him. Surgical, and provable."

## Step 6 — Audit

Tap **6 · Audit**.

> "Every action just produced a tamper-evident, hash-chained audit record.
> Chain valid. This is the evidence a DPO hands a regulator."

---

## Then — make it theirs (this is what wins the room)

**Let the founder type.** Scroll to **Ingest your own document**.

> "Don't take my word for it — paste any record you like."
> Tap **Govern & ingest**. Point at `leaks_raw → masked = 0`.
> "Whatever you typed, the PII was detected and tokenized before embedding.
> leaks-masked is zero."

**Natural language.** In the NL card:

> "And it speaks the same command language as my Snowflake control plane."
> Run `as COMPLIANCE_OFFICER: patients with diabetes`, then
> `mask pii in health_records for analyst roles`.

---

## If he probes (have these ready)

- **"Does this slow the vector DB?"** → "No. The similarity search runs
  natively on the masked vectors at full speed. My layer only adds a
  cached policy check and rehydrates the handful of returned results —
  microseconds. The detection cost is on ingestion, which is batch."
- **"Is the masking legally 'erased'?"** → "Operational-grade today via
  tokenization; regulator-grade with per-subject envelope encryption on
  the roadmap — that upgrades it from pseudonymised to unintelligible."
- **"What if PII has no field label?"** → paste a bare line; detection is
  pattern-based, not label-based.
- **"Two patients, one record?"** → reference-counting keeps erasure
  surgical even when they share an identifier.

## The ask (in order)

1. Wire the Endee adapter together in a working session.
2. Co-present to the client who raised the question.
3. Then the role conversation.

## Data note (for when you add your own records)

Attribution treats each line as one subject and keys identity on the
strongest ID (Aadhaar > PAN > MRN > name). If a clinician shares a line
with a patient, the clinician's name attaches to that patient's identity —
but reference-counting means erasing the patient won't remove a clinician
who appears with other patients. Cleanest demo data: one patient per line.
