# Deploy to Render

This server uses only the Python standard library for HTTP (no FastAPI).
Runtime deps are just numpy + pyyaml (used by the governance modules).

## Render (web service)
1. Push this folder to a Git repo.
2. New → Web Service → connect the repo.
3. Settings:
   - Build command:  pip install -r requirements.txt
   - Start command:  python server.py
   (Procfile already specifies `web: python server.py`.)
4. Render injects $PORT; server.py binds 0.0.0.0:$PORT automatically.

## Local
    pip install -r requirements.txt
    python server.py            # http://localhost:8000

## Endpoints
GET  /            → console UI (index.html)
GET  /health      → liveness + seeded record count
GET  /audit       → audit-chain validity + stats + policy version
POST /reset       → rebuild a fresh in-memory DB and re-seed (fixes stale state)
POST /ingest      {doc_id, text, lexicon}   → govern + ingest one document
POST /query       {role, query, top_k}      → role-gated retrieval
POST /erase       {subject}                 → reference-counted crypto-shred
POST /nl          {command}                 → natural-language command

## Why /reset matters
State is in-memory and rebuilt on /reset. The previous deploy persisted the
vault on disk, so an erased subject stayed tombstoned across restarts and the
Erase button reported "no identity matches". Tapping Reset (or restarting)
now always yields a clean, fully working demo.
