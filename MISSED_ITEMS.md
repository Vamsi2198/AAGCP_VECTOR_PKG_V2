# AAGCP-Vector — Eagle's View to Snake's View
### What we're achieving, why this approach, and the full map of what we discussed
**Level: /l99 / Expert**

---

## EAGLE VIEW (40,000 ft) — what this is, in one frame

A control plane that governs PII *inside* a vector database. It answers the
one question Endee's client asked and that no vector DB ships an answer to:
**"once our documents are embedded, how do we mask the PII?"**

The answer is a reframe: you can't mask a vector after the fact, so move
enforcement to ingestion. Same six-phase loop as the Snowflake AAGCP —
the enforcement point just moved from a column masking policy to the
embedding pipeline. **One control plane, two substrates: columns and vectors.**

What it proves on screen: PII never enters the vector, retrieval still
works, role policy decides what comes back out, and erasure is a key
deletion — surgical and provable.

---

## CRUISE VIEW (10,000 ft) — why THIS approach (the 5 masking issues)

This is the "why we chose this" spine of the demo. Five issues specific to
masking in vector space, each answered by a design decision:

**Issue 1 — You cannot redact a vector after embedding.**
The PII is smeared across all 512 dimensions; there's no field to null out.
*Decision:* detect and replace PII **before** embedding. Governance is a
pre-ingestion gate, not a post-hoc filter.

**Issue 2 — Naive masking destroys retrieval.**
Replace every name with `[REDACTED]` and all your documents collapse onto
the same point in embedding space — search breaks.
*Decision:* deterministic pseudonym tokens. `Ramesh Iyer` → the same
`<PERSON_…>` token everywhere, so the text stays differentiated and the
embedding stays meaningful.

**Issue 3 — Cross-document linkage must survive.**
If the same person gets a different token in each document, you can't
retrieve "all records about this patient."
*Decision:* tokens are deterministic on value (HMAC of type|value). Same
entity ⇒ same token across the whole corpus.

**Issue 4 — Erasure must be surgical and provable.**
GDPR/DPDP erasure can't mean "re-embed two million documents," and it
must not collaterally delete other people's data.
*Decision:* vault-key deletion (crypto-shred), **reference-counted** — a
token is destroyed only when no surviving identity still references it.
Zero vectors touched; a tamper-evident certificate is emitted.

**Issue 5 — A name is not an identity.**
Two real people named "Ramesh Iyer" are not the same person; one person
whose name is mistyped across records still is. Keying governance on the
display name silently merges and splits the wrong records.
*Decision:* entity resolution. The data subject is keyed on the
**strongest identifier present** (Aadhaar > PAN > MRN > name). Conflicting
strong IDs are flagged for a human, never silently resolved.

> If the founder asks "why not just redact?", Issues 2–3 are your answer.
> If he asks "what about erasure / duplicates / same name?", Issues 4–5 are.

---

## APPROACH VIEW (1,000 ft) — the data-quality factors, handled

These are the cases you flagged — built and verified against your exact
deployed input:

| Case | Input pattern | System behavior |
|---|---|---|
| **Same person, name typo** | Same Aadhaar, "Dinesh Iyer" vs "Dinesh iyer" | Merged to one identity — Aadhaar wins; case-insensitive name match |
| **Same name, different people** | "Ramesh Iyer" ×2 with different Aadhaars | Kept as two distinct identities — not merged |
| **Shared identifier (bad data)** | Same MRN under two Aadhaars | Flagged `SHARED_MRN_DIFFERENT_AADHAAR` — not merged, escalated to steward |
| **Duplicate record** | Identical identifier set twice | Flagged `DUPLICATE_RECORD` |
| **No field labels** | Bare "Dinesh Iyer, 4521 8834 6723, …" | Detected by value pattern, not label; still masked |
| **Erase one of several subjects** | Erase Ramesh from a 2-patient doc | Only Ramesh's tokens destroyed; shared MRN retained because Dinesh owns it |
| **Name collision on erase** | Erase "Ramesh Iyer" when two exist | Refuses; asks for a disambiguating identifier |

The principle running through all of them: **escalate, don't guess.**
Where the data is ambiguous or contradictory, the system surfaces a
conflict for human review rather than silently merging or splitting — the
same stance as the multi-regulation conflict resolver.

---

## SNAKE VIEW (ground level) — the mechanism that makes it correct

The single most important implementation detail: **reference-counted
erasure.**

```
token  →  { value, owning_identities: {id_A, id_B, ...} }

erase(identity):
    for token in identity.tokens:
        token.owning_identities.remove(identity)
        if token.owning_identities is empty:
            destroy(token)          # crypto-shred
        else:
            retain(token)           # another subject still needs it
```

This one rule is what turns "surgical erasure" from a slogan into a fact:

- A name two people share → erasing one leaves the name token alive for the
  other.
- A wrongly-shared MRN → erasing one patient retains the MRN for the other.
- A unique Aadhaar → owned by exactly one identity → destroyed cleanly.

Verified: erasing Ramesh from your two-patient document destroyed his
Aadhaar, phone and name tokens, retained the shared MRN, and left Dinesh's
record fully intact. The audit hash-chain stayed valid.

Second ground-level detail you must operationalize: **persist the vault
secret.** Tokens are HMAC(secret, type|value); if the secret is minted
fresh per process (as it was on your Render deploy), every restart changes
all tokens, breaks cross-document linkage, and orphans audit references.
Pass the secret from an env var or mounted file. The patched vault accepts
`secret=…` for exactly this.

---

## THE FULL MAP — everything we discussed, and where it stands

This thread ran wide. Here is the eagle-view inventory so nothing is lost.

### Built and in the package
- Six-phase control plane ported to vector space (Observe→Learn)
- PII detection with first-class Indian PII (Aadhaar, PAN, +91)
- Deterministic pseudonym vault + role-gated rehydration
- Pre-ingestion SIMULATE gate (sandbox-embed raw vs masked, leak probe)
- Hash-chained tamper-evident audit
- NL command bridge (same grammar as the Snowflake plane)
- **Entity resolution + reference-counted erasure (this build)**
- Endee adapter stub, declarative YAML policy

### Discussed, designed, NOT yet built (the honest backlog)
Ranked by how soon they matter:

1. **Agent-generated vectors** — memory written by AI agents has no source
   document, no human author, no natural retention. By ~2026 a large share
   of vector writes. The durable moat: this sits *above* the vector DB and
   no DB vendor is positioned to build it. *Not in the demo; it's the
   long-term thesis.*
2. **LLM-generated content amplification** — synthetic text embedded as if
   authoritative; hallucinations propagate through retrieval. Needs the
   source-quality taxonomy (HUMAN_AUTHORED → … → UNKNOWN). *The most
   dangerous unaddressed problem.*
3. **Multi-regulation conflict** — GDPR-delete vs HIPAA-retain on the same
   vector is a legal contradiction. The conflict-resolver pattern is
   designed; only the regulatory tagging is stubbed.
4. **Session-level / mosaic governance** — permitted queries combined to
   extract prohibited facts. Needs a session store; the current sidecar is
   stateless per query. *Phase 3.*
5. **Pre-ingestion simulation (full)** — generate likely queries for a
   document before embedding and check policy boundaries. The SIMULATE gate
   is the seed; the query-generation half is not built. *Highest-leverage
   next feature — shifts cost from O(queries) to O(documents).*
6. **Chunk-level Merkle provenance** — surgical staleness re-embedding and
   precise "which clause caused the bad answer" lineage. *Not built.*
7. **Embedding inversion / model-extraction defense** — architectural
   isolation + encryption, NOT differential-privacy noise (which destroys
   retrieval). *Documented direction only.*
8. **Fine-tuned embedding model governance** — model weights are compressed
   training data; deletion may require retraining. *Registry concept only.*
9. **M&A vector governance** — merging two firms' stores with conflicting
   regulatory status. *High-value niche; not built.*
10. **Multimodal** (image/audio embeddings) — text-only today.

### Strategic threads (decisions, not code)
- **The fork:** vector-DB governance (concrete, sellable wedge) vs the
  broader agent-governance closed loop (the vision). The demo is the wedge.
- **Timing:** your own read is the market needs ~6–12 months and a
  triggering event (a major GDPR/DPDP fine) for real pull. The demo is
  therefore best used *now* as an interview weapon and a door-opener with
  Endee, not as the launch of a company you've decided to defer.
- **Moat honesty:** "Pinecone won't build it" is true but the real
  competitor for agent governance is the orchestration layer (LangGraph,
  LlamaIndex) and the frameworks. The slide that matters is why *you* beat
  them to it.
- **Ratings:** AAGCP 8/10, Axilattice 7.5/10 — strong for a solo build;
  the leverage isn't the score, it's that a technical founder already
  believes you ship ahead of the market.

---

## THE ONE-PARAGRAPH "WHAT / WHY / HOW" (for any audience)

We're making PII governable inside vector databases — the question every
enterprise RAG deployment has and none can answer. We do it because you
cannot redact a vector after embedding, so governance has to happen at
ingestion: PII becomes deterministic tokens before the text is embedded,
role policy decides what is revealed at query time, and erasure is a
reference-counted key deletion that is surgical even when records share
identifiers. The result is a live, auditable proof that an enterprise can
put Aadhaar- and PAN-bearing documents into a vector store and still pass a
DPDP or GDPR review — which is precisely what makes a regulated-industry
sale possible.

---

## POST-FIX CROSS-CHECK (after token-width + Act 7 fixes)

Two one-line fixes shipped: token widened 32-bit → 64-bit (collision-safe at
10M+ tokens), and Act 7 isolated into its own plane (Act 4 had already erased
Ramesh in the shared plane — a tombstoned subject is correctly not resurrected
by re-ingestion, which was masking the real erasure output). A deeper pass
then surfaced the following.

### Two free wins the architecture already gives you (add to the pitch)

**GDPR Art. 16 — Rectification, almost free.** Deterministic tokenization
means a person's value lives in exactly one place: the vault. Correct a wrong
Aadhaar or misspelled name once in the vault, and every document that
references that token is instantly corrected at rehydration — no re-embedding,
no document hunt. Structured systems need an UPDATE across every row; you need
one. This is a genuine selling point we hadn't named.

**GDPR Art. 15/20 — Subject access & portability, almost free.** Identity
resolution already clusters every identifier and record for a subject. A DSAR
("give me everything you hold on this person") becomes a single
identity lookup → all owned tokens → all referencing documents. The identity
model turns a dreaded compliance chore into a function call.

### Two limitations to state plainly (don't let the founder find them first)

**The vault is a plaintext PII honeypot — this is the #1 security priority.**
Crypto-shred protects you when the *vector store* leaks (tokens are
meaningless without the vault). But the *vault itself* is JSON holding every
original value. If it leaks, everything leaks. So the vault must be the most
protected component: encrypted at rest, access-controlled, audited. This is
exactly what per-subject envelope encryption fixes — and note it kills two
birds: it hardens the honeypot AND upgrades the legal position from
"pseudonymised" (weaker) to "unintelligible ciphertext" (stronger Art. 17
claim). One roadmap item, two problems solved. Lead with this when security
is in the room.

**Quasi-identifier re-identification is not addressed.** Tokenizing direct
identifiers (Aadhaar, name, phone) does not stop re-identification from
combinations — "65-year-old male, pincode 560034, diabetic" can single out a
person even with every direct identifier masked. That's k-anonymity /
l-diversity territory, a different and harder problem. The honest line:
"we govern direct identifiers today; quasi-identifier suppression and
k-anonymity are on the roadmap." Related to, but distinct from, the
semantic-inference gap already noted.

### One semantic to be ready to explain

**Erasure persists against re-ingestion.** Once a subject is crypto-shredded,
re-ingesting the same strong identifier does not resurrect them — the token
stays tombstoned. For right-to-be-forgotten this is arguably correct (re-
feeding the same data shouldn't undo an erasure). But if a subject genuinely
re-consents and must be re-added, that needs an explicit, audited un-tombstone
operation — not currently built. Be ready for the DPO who asks "what if the
data comes back?"
