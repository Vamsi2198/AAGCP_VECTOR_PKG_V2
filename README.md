# AAGCP-Vector

**PII governance for vector databases — the AAGCP six-phase control plane,
ported from structured data to embedding space.**

Answers one question, completely:

> _"Our documents contain PII. Once they're embedded in a vector database,
> how do we mask it?"_

## The answer in three sentences

You cannot mask a vector after embedding — the PII is mathematically
distributed across every dimension. So AAGCP moves enforcement to
ingestion: PII is detected and replaced with deterministic vault tokens
_before_ embedding, role policy decides what gets rehydrated at query
time, and GDPR erasure becomes a vault-key deletion (crypto-shred) that
instantly anonymizes every vector referencing the subject — with zero
re-embedding and zero vector operations.

## Run it

```bash
python demo.py        # numpy + pyyaml only; no network, no API keys
```

Or run the web demo with UI and API endpoints:

```bash
python server.py
```

Then open `http://127.0.0.1:8000` in your browser. The top buttons drive
real backend actions and print responses into the terminal-style pane below.

Five acts: the ungoverned leak baseline → six-phase governed ingestion →
one query under three roles → GDPR crypto-shred → metrics + tamper-evident
audit verification. A full run report lands in `demo_output/run_report.md`.

## Architecture

```
            ┌─────────────────────────────────────────────┐
 documents  │      VectorGovernanceControlPlane           │
 ──────────▶│                                             │
            │  OBSERVE   PII detection (Aadhaar, PAN,     │
            │            +91 phone, email, MRN, person)   │
            │  ANALYZE   risk score + data-subject        │
            │            attribution ("Patient <name>")   │
            │  PLAN      deterministic pseudonym tokens   │
            │            (linkage-preserving, HMAC)       │
            │  SIMULATE  sandbox-embed raw vs masked,     │
            │            leak probe, similarity check —   │
            │            pre-ingestion gate               │
            │  EXECUTE   commit masked embedding only     │
            │  LEARN     hash-chained audit + metrics     │
            └──────┬──────────────────────┬───────────────┘
                   │                      │
            ┌──────▼──────┐        ┌──────▼──────────────┐
            │ Pseudonym   │        │ VectorStoreAdapter  │
            │ Vault       │        │  InMemory (demo)    │
            │ token→value │        │  Endee / Pinecone / │
            │ crypto-shred│        │  Qdrant / pgvector  │
            └─────────────┘        └─────────────────────┘
                   ▲
   query(role) ────┘  rehydration: CASE WHEN role IN (...) THEN value
                      ELSE token — Snowflake masking semantics,
                      applied at retrieval time
```

## Lineage: one control plane, two substrates

|                   | AAGCP (existing)        | AAGCP-Vector (this repo)          |
| ----------------- | ----------------------- | --------------------------------- |
| Substrate         | Snowflake columns       | Embedding pipelines               |
| Enforcement point | `CREATE MASKING POLICY` | Pre-embedding tokenization        |
| Role gating       | `CURRENT_ROLE()` CASE   | Query-time rehydration policy     |
| Erasure           | `DELETE` / `UPDATE`     | Crypto-shred (vault key deletion) |
| Audit             | SQLite audit log        | Hash-chained JSONL (WORM-style)   |
| Loop              | Observe→…→Learn         | Identical six phases              |

## What's demo-grade vs production (read this, it's honest)

| Component           | Demo                                         | Production path                                                                                 |
| ------------------- | -------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| PII detection       | Regex + lexicon (Indian PII first-class)     | Presidio / NER adapter — same interface as AAGCP's existing `PIIAnalyzer` fallback chain        |
| Embeddings          | Feature-hashing (numpy, deterministic)       | `EmbedderAdapter` → sentence-transformers / OpenAI / provider-native                            |
| Vector store        | In-memory cosine                             | `VectorStoreAdapter` → Endee/Pinecone/Qdrant (~30 lines each)                                   |
| Vault               | JSON + HMAC tokens; shred = mapping deletion | Per-subject envelope encryption, shred the key not the row; HSM-backed secret; Postgres/KMS     |
| Subject attribution | "Patient <name>" anchor heuristic            | Entity-resolution model + human review queue                                                    |
| Policy              | Single YAML                                  | Versioned policy store with conflict resolution + approval workflow (already designed in AAGCP) |

Known limitations worth saying out loud: token substitution shifts the
embedding (cosine ≈ 0.74 raw↔masked in the demo) — acceptable because
_all_ corpus documents are tokenized identically, so relative rankings
hold; semantic-inference leakage ("the diabetic patient in ward 3") is
not addressed by tokenization and needs the session-level behavioral
layer on the roadmap; deterministic tokens trade unlinkability for
retrieval quality by design — frequency analysis of tokens is possible,
which is why the vault secret matters.

## Roadmap (sequenced, not aspirational)

1. Endee adapter + real embedder benchmarks (retrieval-quality deltas)
2. Chunk-level Merkle provenance for surgical staleness re-embedding
3. Session-level behavioral governance (mosaic-attack detection)
4. Agent-generated vector governance — memory written by agents has no
   source document; provenance unit becomes the agent session
