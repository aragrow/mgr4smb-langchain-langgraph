# OTP Sandbox

A self-contained prototype of the mgr4smb identity-verification flow
using **email OTP** (via the production GoHighLevel tenant) as the only
authentication factor. Users re-authenticate on every new session.

Passkeys (WebAuthn/FIDO2) were prototyped here earlier and then removed
in favour of the OTP-only flow; the directory is still named
`passkey-otp-sandbox/` to preserve git history.

**Stack:** LangChain + LangGraph + LangSmith · Google Gemini 2.5 Flash ·
FastAPI · GoHighLevel REST API · MongoDB Atlas (optional).

## What's in the box

- **4 agents** — Orchestrator (email gate + intent classifier), Greeter
  (GHL contact lookup), General-Info (knowledge-base-backed company
  Q&A), Authenticator (email + phone → OTP → 3-attempt lockout).
- **5 tools** — `ghl_client`, `ghl_contact_lookup`, `knowledge_base`,
  `send_otp`, `verify_otp`. `send_otp` / `verify_otp` hit the real GHL
  tenant — the code is emailed by GHL's workflow, not stubbed.
  `knowledge_base` uses Gemini embeddings; with `MONGODB_ATLAS_URI`
  set it goes through `MongoDBAtlasVectorSearch`, otherwise it falls
  back to a local JSON file + pure-Python cosine.
- **Prompts live under `src/sandbox/prompts/`** — one file per agent,
  imported by the matching agent module.
- **Optional MongoDB** for the knowledge base + LangGraph checkpointer.
  With `MONGODB_ATLAS_URI` blank: local JSON + `InMemorySaver` (session
  state is lost on server restart). With it set: vector search +
  `MongoDBSaver` (sessions survive restarts).
- **FastAPI** with `/chat`, `/health`, `/ui`.
- **Single-file HTML UI** (`index.html`) — paste JWT in Settings, chat.

## Quickstart

```bash
cd passkey-otp-sandbox
uv venv .venv
source .venv/bin/activate
uv pip install -e .

cp .env.example .env
# fill in GOOGLE_API_KEY, JWT_SECRET, GHL_API_KEY, GHL_LOCATION_ID at minimum

python -m sandbox.checks.smoke       # every phase should PASS
./run.sh start
python scripts/issue_dev_jwt.py      # copy the token that prints
open http://localhost:8000/ui
```

In the UI, click **Settings**, paste the JWT, save. Then chat normally —
introduce yourself with your email, ask a general question, or ask
something sensitive to trigger the OTP flow.

## Manual test scenarios

After `./run.sh start` and pasting a JWT in the chat UI:

### General question (no auth)

1. Say **"do you do wordpress development?"**.
2. Agent asks for your email.
3. Give it (`my email is you@example.com`).
4. Agent greets you by name (if in GHL) and answers the question from
   the knowledge base.

### Sensitive action → OTP

1. In the same session, say **"yes, please set an appointment"**.
2. Authenticator asks for your phone number.
3. Give it (`my phone is 5551234567`).
4. GHL emails the 6-digit code to the address on your contact record.
5. Paste the code into the chat.
6. Agent replies with `VERIFIED`.

A new session (New session button) drops identity and forces OTP again.

## Directory layout

```
passkey-otp-sandbox/
├── README.md, pyproject.toml, menu.sh, run.sh, .env.example, .env, .gitignore
├── index.html                # single-file chat UI (served at /ui)
├── knowledge_base.json       # local corpus (fallback when MONGODB_ATLAS_URI blank)
├── .kb_embeddings.json       # cached embeddings (gitignored)
├── logs/                     # rotating log files
├── scripts/
│   ├── issue_dev_jwt.py      # mint a dev JWT
│   └── ingest_kb_to_mongo.py # seed Mongo collection from knowledge_base.json
└── src/sandbox/
    ├── config.py, state.py, llm.py
    ├── auth.py, api.py       # FastAPI + JWT
    ├── graph.py              # LangGraph assembly + run_turn
    ├── memory.py             # checkpointer factory (MongoDBSaver / InMemorySaver)
    ├── logging_config.py, exceptions.py
    ├── agents/               # each imports its prompt from sandbox.prompts
    │   ├── _helpers.py       # agent_as_tool + InjectedState
    │   ├── orchestrator.py
    │   ├── greeting.py
    │   ├── general_info.py
    │   └── authenticator.py
    ├── prompts/              # SYSTEM_PROMPT per agent
    │   ├── orchestrator.py
    │   ├── greeting.py
    │   ├── general_info.py
    │   └── authenticator.py
    ├── tools/
    │   ├── ghl_client.py, ghl_contact_lookup.py
    │   ├── knowledge_base.py
    │   ├── send_otp.py, verify_otp.py
    └── checks/
        └── smoke.py
```

## Smoke phases

`python -m sandbox.checks.smoke [--phase N]` (also `./menu.sh` → 7 / 8):

| Phase | Coverage |
|-------|----------|
| 1 | third-party imports |
| 2 | settings + LLM round-trip |
| 3 | GHL connect + custom fields resolve + known contact lookup *(skips if GHL not configured)* |
| 4 | agents build + orchestrator routes general question through greeter → general_info |
| 5 | API — `/health`, JWT gating via `TestClient` |
| 6 | regression sweep — reruns 1–5 + 7 |
| 7 | MongoDB ping + index presence + checkpointer persistence across graph rebuild + bad-URI error *(skips if Mongo not configured)* |

## `run.sh` subcommands

```bash
./run.sh start     # uvicorn in background, logs to logs/server.log
./run.sh stop
./run.sh restart
./run.sh status
./run.sh smoke
```

## Switching storage to MongoDB

Set `MONGODB_ATLAS_URI` in `.env`. Flips both:

- `knowledge_base` tool → `MongoDBAtlasVectorSearch` (top-1 on the
  configured collection + vector index).
- LangGraph checkpointer → `MongoDBSaver` (sessions survive restarts;
  separate DB via `MONGODB_MEMORY_DB` so sandbox checkpoints don't mix
  with production KB content).

To seed the Mongo knowledge_base collection from the local JSON:

```bash
python scripts/ingest_kb_to_mongo.py --dry   # preview
python scripts/ingest_kb_to_mongo.py         # upsert
```

or `./menu.sh` → option 10. After ingest, create an Atlas Vector Search
index named `MONGODB_INDEX_NAME` on field `embedding`, dims =
`EMBEDDING_DIMENSIONS`, similarity = cosine.

To force a rebuild of the local embeddings cache:
`./menu.sh` → option 11, or `rm .kb_embeddings.json`.
