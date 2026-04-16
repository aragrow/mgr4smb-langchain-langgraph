# Passkey + OTP Sandbox

A self-contained prototype that validates the **passkey-as-supplement-to-OTP**
design from the parent `mgr4smb` project. No GoHighLevel, no Jobber, no
MongoDB — just the identity-verification slice, standalone.

**Stack:** LangChain + LangGraph + LangSmith · Google Gemini 2.5 Flash ·
FastAPI · MongoDB Atlas · `webauthn` (FIDO2).

## What's in the box

- **3 agents** — Orchestrator (email-gate + intent classifier),
  General-Info (knowledge-base-backed company Q&A), Authenticator
  (passkey-first, OTP fallback, 3-attempt lockout).
- **5 tools** — `knowledge_base`, `passkey_status`,
  `passkey_request_verification`, `send_otp`, `verify_otp`. The
  `send_otp` tool prints the code to stderr instead of emailing it
  (swap for real email later). The `knowledge_base` tool uses Gemini
  embeddings on a local JSON file with pure-Python cosine similarity
  (swap for MongoDB Atlas vector search later).
- **Prompts live under `src/sandbox/prompts/`** — one file per agent,
  imported by the matching agent module.
- **MongoDB Atlas** for passkey credential storage (required — one
  collection, unique compound index on `user_email + credential_id`).
- **Dual-mode storage** for the knowledge base + LangGraph checkpointer.
  With `MONGODB_ATLAS_URI` blank → local JSON + in-memory checkpointer
  (the passkey routes will error out since those always require Mongo).
  With it set → MongoDB Atlas vector search + MongoDBSaver + passkey
  collection, feature-parity with production. Env var names match the
  production mgr4smb project so the two `.env` files are interchangeable.
- **FastAPI** with `/chat`, `/health`, `/ui`, and the 6 passkey endpoints.
- **Single-file HTML UI** (`index.html`) that handles passkey prompts in
  the browser.
- **In-memory OTP store** and **in-memory challenge cache** — the sandbox
  is ephemeral; restart and pending verifications are lost.

## Quickstart (~3 minutes)

```bash
# 1) one-time setup
cd passkey-otp-sandbox
uv venv .venv
source .venv/bin/activate
uv pip install -e .

# 2) fill in .env (already populated with local defaults for everything
#    except LANGCHAIN_API_KEY / GOOGLE_API_KEY / JWT_SECRET)
cp .env.example .env   # only if .env doesn't exist yet

# 3) sanity check — every phase should PASS
python -m sandbox.checks.smoke

# 4) start the server
./run.sh start

# 5) mint a dev JWT and open the chat UI
python scripts/issue_dev_jwt.py
open http://localhost:8000/ui
```

In the UI, click **Settings**, paste the JWT + your email, save. Then
say "please verify me" in the chat.

## Directory layout

```
passkey-otp-sandbox/
├── README.md, pyproject.toml, menu.sh, run.sh, .env.example, .env, .gitignore
├── index.html                # single-file chat UI (served at /ui)
├── knowledge_base.json       # local corpus used by the knowledge_base tool
├── .kb_embeddings.json       # cached embeddings for the corpus (gitignored)
├── logs/                     # rotating log files
├── scripts/
│   └── issue_dev_jwt.py      # mint a sandbox JWT
└── src/sandbox/
    ├── config.py, state.py, llm.py
    ├── auth.py, api.py       # FastAPI + JWT
    ├── graph.py              # LangGraph assembly + run_turn
    ├── logging_config.py, exceptions.py
    ├── agents/               # agent wiring — each imports its prompt
    │   ├── _helpers.py       # agent_as_tool + InjectedState
    │   ├── orchestrator.py   # email gate + intent classifier + delegator
    │   ├── general_info.py   # answers company questions via knowledge_base
    │   └── authenticator.py  # passkey-first, OTP-fallback, 3-strike lockout
    ├── prompts/              # SYSTEM_PROMPT per agent, kept out of code
    │   ├── orchestrator.py
    │   ├── general_info.py
    │   └── authenticator.py
    ├── tools/
    │   ├── knowledge_base.py           # JSON + embeddings + cosine
    │   ├── otp_store.py, send_otp.py, verify_otp.py
    │   ├── passkey_status.py, passkey_request_verification.py
    ├── webauthn/
    │   ├── storage.py        # MongoDB CRUD
    │   ├── challenges.py     # in-mem challenge cache w/ TTL
    │   └── verification.py   # wrapper over `webauthn` pypi lib
    └── checks/
        └── smoke.py          # phase-gated sanity checks
```

## Manual test scenarios

After `./run.sh start` and entering JWT + email in the UI:

### Scenario 1 — Fresh user, OTP only

1. Say **"please verify me, my email is you@example.com"**.
2. The terminal prints `===== OTP for you@example.com: 123456 =====`.
3. Paste the 6-digit code into the chat → reply starts with `VERIFIED`.
4. The "Register a passkey" banner appears → click it → complete the
   authenticator prompt (Touch ID / Windows Hello).

### Scenario 2 — Returning user, passkey path

1. Click **New session**.
2. Say **"please verify me, my email is you@example.com"** (same email
   as scenario 1).
3. The chat reply starts with `PASSKEY_REQUESTED`.
4. The "Use passkey" button appears → click → complete the authenticator
   prompt.
5. The next agent reply starts with `VERIFIED`. No OTP printed to terminal.

### Scenario 3 — Passkey cancelled → OTP fallback

1. Same as scenario 2, but **cancel** the authenticator dialog.
2. The UI posts `"Passkey verification did not complete..."` to `/chat`.
3. The OTP agent falls through to Step 1 → a fresh code is printed to
   the terminal → continue with the normal OTP flow.

## Smoke test phases

`python -m sandbox.checks.smoke [--phase N]` runs each phase's gate:

| Phase | Coverage |
|-------|----------|
| 1 | third-party imports |
| 2 | settings, LLM round-trip, passkey store (Mongo) round-trip |
| 3 | OTP tools (happy, wrong code, expired) |
| 4 | webauthn wrappers, passkey tools |
| 5 | agents build, OTP path, passkey path |
| 6 | API — `/health`, JWT gating, unverified-register 403 |
| 7 | all of the above |

## `run.sh` subcommands

```bash
./run.sh start      # uvicorn in background, logs to logs/server.log
./run.sh stop       # pkill uvicorn bound to our app
./run.sh restart    # stop + start
./run.sh status     # pid + /health poll
./run.sh smoke      # full phase suite
```

## Switching the knowledge base + checkpointer to MongoDB

Set `MONGODB_ATLAS_URI` in `.env`. That alone flips both:

- `knowledge_base` tool → `MongoDBAtlasVectorSearch` (top-1 on the
  configured collection + vector index).
- LangGraph checkpointer → `MongoDBSaver` (session state persists
  across server restarts; separate DB via `MONGODB_MEMORY_DB` so
  sandbox checkpoints don't mix with production KB content).

To seed the Mongo collection with the sandbox's `knowledge_base.json`:

```bash
python scripts/ingest_kb_to_mongo.py --dry   # preview
python scripts/ingest_kb_to_mongo.py         # upsert
```

or use `./menu.sh` → option 14. After ingest, create an Atlas Vector
Search index named `MONGODB_INDEX_NAME` on field `embedding`, dims =
`EMBEDDING_DIMENSIONS`, similarity = cosine.

To force the local JSON to re-embed (after editing it), delete the
cache: `./menu.sh` → option 15, or `rm .kb_embeddings.json`.

## Porting back to mgr4smb

Once you're satisfied with the flow:

1. Copy `sandbox/webauthn/` → `mgr4smb/webauthn/`.
2. Copy `sandbox/tools/passkey_*.py` → `mgr4smb/tools/`.
3. Passkey storage already uses MongoDB — the collection schema and
   unique compound index (`user_email + credential_id`) are a drop-in.
4. Drop the sandbox `send_otp` / `verify_otp` stubs — keep the
   production `ghl_send_otp` / `ghl_verify_otp`.
5. Add the Step 0 / 0b prompt block from
   `sandbox/agents/authenticator.py` into `mgr4smb/agents/otp.py` (and
   consider renaming mgr4smb/agents/otp.py → authenticator.py too).
6. Wire the 6 passkey endpoints into `mgr4smb/api.py`.
7. Apply the same `PASSKEY_REQUESTED`/register-banner logic to
   `chat-ui/chat.js`.
