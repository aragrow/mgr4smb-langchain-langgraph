# Plan: Standalone Passkey + OTP Sandbox

## Context

You want to prove out the passkey-as-supplement-to-OTP design without
pulling in the rest of the mgr4smb stack (GHL, Jobber, MongoDB knowledge
base, booking, support agents, case management, etc.). The sandbox is a
minimal, self-contained project that implements exactly the verification
layer — so it runs in its own directory, has its own venv, its own
`.env`, and can be iterated on without affecting production mgr4smb.

**What's in scope**
- LangChain / LangGraph / LangSmith — so the graph orchestration and
  tracing behave identically to the real project.
- Two agents: ORCHESTRATOR (routes) + OTP (handles both OTP and passkey).
- The **verification tools only** — send OTP, verify OTP, passkey status,
  passkey request. No GHL, no Jobber, no booking/support tools.
- FastAPI with a single chat endpoint + the 4 WebAuthn endpoints.
- Minimal chat UI (one HTML file) with a passkey button + register banner.

**What's out of scope**
- GoHighLevel and Jobber — replaced by a console-logging OTP stub so
  you see the code directly in the terminal and can paste it back into
  the chat.
- MongoDB — replaced by SQLite (single file, no server, zero setup) for
  passkey credential storage.
- Booking / scheduling / knowledge-base agents — the only thing the
  orchestrator does is delegate to the OTP agent when verification is
  needed, then echo success/failure back to the user.

**Intended outcome**
After running the sandbox you should be able to, from a browser:
1. Send a message like "verify me please" to `/chat`.
2. On first login, get an email OTP (printed to the terminal), type it
   in, see VERIFIED, then tap "Register a passkey" and complete Touch ID.
3. On next session, skip straight to the passkey tap — no OTP.
4. Cancel the passkey dialog to see the fall-back to OTP.

Once this works, porting back into mgr4smb is mechanical (copy the
agents/tools/webauthn modules into `mgr4smb/`, swap the SQLite storage
for MongoDB, swap the stub OTP for the real `ghl_send_otp`).

---

## Project name and layout

```
passkey-otp-sandbox/
├── README.md
├── pyproject.toml
├── .env.example
├── .env                       # gitignored
├── .gitignore
├── run.sh                     # start / stop / smoke helpers
├── index.html                 # served at /ui — chat + passkey button
├── passkeys.db                # SQLite, auto-created, gitignored
├── logs/                      # gitignored
└── src/
    └── sandbox/
        ├── __init__.py
        ├── config.py
        ├── state.py
        ├── llm.py
        ├── graph.py
        ├── api.py
        ├── logging_config.py
        ├── exceptions.py
        ├── agents/
        │   ├── __init__.py
        │   ├── _helpers.py        # agent_as_tool w/ InjectedState
        │   ├── orchestrator.py
        │   └── otp.py             # OTP + passkey logic in the prompt
        ├── tools/
        │   ├── __init__.py
        │   ├── otp_store.py
        │   ├── send_otp.py
        │   ├── verify_otp.py
        │   ├── passkey_status.py
        │   └── passkey_request_verification.py
        ├── webauthn/
        │   ├── __init__.py
        │   ├── storage.py         # SQLite CRUD
        │   ├── challenges.py      # in-memory challenge cache w/ TTL
        │   └── verification.py    # webauthn lib wrapper
        └── checks/
            ├── __init__.py
            └── smoke.py           # phase gate
```

---

## Phase 1 — Bootstrap (files + deps)

**What you need**

- `pyproject.toml` with the minimal dependency set:
  ```
  langchain>=1.2.22
  langchain-core>=1.2.22
  langchain-google-genai>=4.0.0
  langgraph>=1.1.0
  langsmith>=0.7.0
  fastapi>=0.115.0
  uvicorn>=0.34.0
  pyjwt>=2.10.0
  python-dotenv>=1.2.0
  httpx>=0.28.0,<1.0
  webauthn>=2.0.0
  ```
  Deliberately NO: pymongo, langchain-mongodb, langgraph-checkpoint-mongodb,
  langchain-text-splitters. You get a stateless in-memory sandbox.

- `.env.example` with:
  ```
  # LangSmith (tracing)
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=
  LANGCHAIN_PROJECT=passkey-otp-sandbox
  LANGCHAIN_ENDPOINT=https://api.smith.langchain.com

  # Google Gemini
  GOOGLE_API_KEY=

  # Auth (one shared JWT secret for simplicity)
  JWT_SECRET=

  # Passkey / WebAuthn
  PASSKEY_RP_ID=localhost
  PASSKEY_RP_NAME=Passkey Sandbox
  PASSKEY_USER_VERIFICATION=preferred
  PASSKEY_CHALLENGE_TTL_SECONDS=60

  # Company contact (escalation text when OTP runs out)
  COMPANY_NAME=Sandbox
  COMPANY_SUPPORT_EMAIL=
  COMPANY_SUPPORT_PHONE=

  # OTP
  OTP_LIFETIME_MINUTES=5
  ```

- `.gitignore`: `.env`, `.venv`, `passkeys.db*`, `logs/`, `__pycache__/`,
  `*.pyc`, `.pytest_cache`.

- `run.sh` helper (bash): `./run.sh start | stop | restart | status | smoke`.
  Same colour-output pattern as `menu.sh` in the main project, but no
  menu — just subcommands.

- **Sanity gate:** `./run.sh smoke` (or `python -m sandbox.checks.smoke`)
  must pass for the current phase's work before you move on.

**Verification for Phase 1**
```bash
cd passkey-otp-sandbox
uv venv .venv
source .venv/bin/activate
uv pip install -e .
cp .env.example .env   # then fill in GOOGLE_API_KEY, LANGCHAIN_API_KEY, JWT_SECRET
python -c "import langgraph, webauthn, fastapi; print('ok')"
```

---

## Phase 2 — Skeleton (config, state, LLM, logging, exceptions, SQLite)

**What you need**

- `src/sandbox/config.py` — `settings` singleton that mirrors the main
  project's pattern: `_require()` for mandatory keys (JWT_SECRET,
  GOOGLE_API_KEY), `_optional()` for defaults. Exposes `rp_id`,
  `rp_name`, `user_verification`, `challenge_ttl_seconds`,
  `otp_lifetime_minutes`, etc.

- `src/sandbox/state.py` — `AgentState` TypedDict (only the fields the
  sandbox actually uses):
  ```python
  class AgentState(TypedDict):
      messages: Annotated[list, add_messages]
      session_id: str
      user_email: str
      is_verified: bool              # set to True by either path
      is_passkey_verified: bool      # True only after passkey verify
  ```

- `src/sandbox/llm.py` — `get_llm()` returns a singleton
  `ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)`.
  No embeddings (no knowledge base in the sandbox).

- `src/sandbox/logging_config.py` — `setup_logging()` writing to stderr
  + `logs/sandbox.log` with rotation. Same structured format as the main
  project so traces are familiar.

- `src/sandbox/exceptions.py` — minimal hierarchy: `SandboxError` →
  `AuthError`, `PasskeyError`, `ConfigError`.

- `src/sandbox/webauthn/storage.py` — SQLite bootstrap. One table:
  ```sql
  CREATE TABLE IF NOT EXISTS passkeys (
      user_email TEXT NOT NULL,
      credential_id TEXT NOT NULL,
      public_key BLOB NOT NULL,
      sign_counter INTEGER NOT NULL DEFAULT 0,
      transports TEXT,
      aaguid TEXT,
      label TEXT,
      created_at TEXT NOT NULL,
      last_used_at TEXT,
      PRIMARY KEY (user_email, credential_id)
  );
  CREATE INDEX IF NOT EXISTS idx_passkeys_user ON passkeys(user_email);
  ```
  CRUD helpers: `register(email, credential)`, `list_by_email(email)`,
  `find(email, credential_id)`, `bump_counter(email, credential_id, new)`,
  `remove(email, credential_id)`.

**Verification for Phase 2**

`python -m sandbox.checks.smoke --phase 2` passes:
- `from sandbox.config import settings` loads `.env`
- `get_llm()` returns a working LLM (one real `invoke("hi")` round-trip)
- `passkeys.db` is created on first `storage.get_conn()` call
- Inserting + selecting a dummy row round-trips correctly

---

## Phase 3 — OTP tools (stub delivery, in-memory store)

**What you need**

- `src/sandbox/tools/otp_store.py` — single in-process dict keyed by
  `email` holding `{code, expires_at}`. No database.

- `src/sandbox/tools/send_otp.py` — `@tool` that:
  - Generates a 6-digit code with `secrets.randbelow`.
  - Stores it in `otp_store` with `expires_at = now + OTP_LIFETIME_MINUTES`.
  - "Sends" by **printing to stderr with a clearly-visible banner**
    (`===== OTP for <email>: 123456 =====`). Comment at the top of the
    file explains: "In production swap this with the real GHL/ SES /
    Twilio call. The interface stays the same."
  - Returns `"OTP_SENT: verification code emailed (check terminal for this sandbox)."`.

- `src/sandbox/tools/verify_otp.py` — `@tool` that reads `otp_store`,
  checks the expiry, compares, deletes on success. Returns the same
  `VERIFIED` / `UNVERIFIED: ...` markers the main project's agent
  expects.

**Verification for Phase 3**

`python -m sandbox.checks.smoke --phase 3` passes:
- `send_otp("test@x.com")` prints the banner and stores a code
- `verify_otp("test@x.com", "<the stored code>")` returns `VERIFIED`
- `verify_otp("test@x.com", "<wrong code>")` returns `UNVERIFIED`
- Expired code path: monkey-patch `expires_at` into the past, verify
  returns `UNVERIFIED: expired`

---

## Phase 4 — Passkey infrastructure (storage, challenges, verification)

**What you need**

- `src/sandbox/webauthn/challenges.py` — in-memory dict keyed by
  `challenge_id` (UUID) with a timestamp. `put(challenge_id, challenge,
  user_email, mode)` + `pop(challenge_id)` with TTL enforcement. Single
  process is fine for a sandbox.

- `src/sandbox/webauthn/verification.py` — thin wrapper over duo-labs
  `webauthn`:
  - `begin_registration(user_email)` → returns
    `PublicKeyCredentialCreationOptions` + stores challenge.
  - `finish_registration(challenge_id, credential)` → verifies
    attestation, writes to SQLite.
  - `begin_authentication(user_email)` → returns
    `PublicKeyCredentialRequestOptions` (allow-list built from SQLite).
  - `finish_authentication(challenge_id, assertion)` → verifies
    signature, increments counter, returns the matched credential.

- `src/sandbox/tools/passkey_status.py` — `@tool` that counts passkeys
  for the email, returns `"REGISTERED"` or `"NONE"`.

- `src/sandbox/tools/passkey_request_verification.py` — `@tool` that
  returns the literal string `"PASSKEY_REQUESTED"`. This is the marker
  the UI watches for — the tool does NOT do any WebAuthn itself.

**Verification for Phase 4**

`python -m sandbox.checks.smoke --phase 4` passes:
- End-to-end registration: `begin_registration` → simulated
  `finish_registration` with a fixture credential (duo-labs ships these
  in its tests) → SQLite row written
- End-to-end authentication with the same fixture credential rotates
  the counter and returns success
- Replay: re-submitting the same assertion fails (counter rollback)
- `passkey_status("unknown@x.com")` returns `"NONE"`
- After registration, `passkey_status(email)` returns `"REGISTERED"`

---

## Phase 5 — Agents (orchestrator + OTP with passkey awareness)

**What you need**

- `src/sandbox/agents/_helpers.py` — copy of the main project's
  `agent_as_tool` helper with `InjectedState`. Zero changes.

- `src/sandbox/agents/orchestrator.py` — tiny prompt: "Your only job is
  to delegate to `otp_agent` when the user asks to verify or when a
  sensitive action requires identity. Otherwise say you're a test
  harness and can only help with verification." Returns the compiled
  react agent via `build(otp_agent)`.

- `src/sandbox/agents/otp.py` — **the core of Phase 12**. Prompt
  structure:
  ```
  STEP 0 — PASSKEY CHECK
    Call passkey_status(user_email).
    REGISTERED → Step 0b. NONE → Step 1.

  STEP 0b — REQUEST PASSKEY VERIFICATION
    Call passkey_request_verification(user_email).
    Reply with text STARTING with "PASSKEY_REQUESTED — please tap the
    button below". Stop. Do not call other tools this turn.
    On the next user turn:
      "Passkey verified"              → reply "VERIFIED ..."
      "Passkey verification did not complete" → fall to Step 1

  STEP 1 — SEND THE CODE (once per session)
    Scan history for prior OTP_SENT. If present, remind the user to
    check their inbox (terminal, for the sandbox) and proceed to Step 2.
    Otherwise call send_otp(email).

  STEP 2 — VERIFY (max 2 attempts)
    Call verify_otp(email, code). VERIFIED → reply "VERIFIED ...".
    Two wrong codes → Step 3.

  STEP 3 — ESCALATE
    Reply starting with "UNVERIFIED" + the contact line from config.
  ```
  Tools: `[send_otp, verify_otp, passkey_status, passkey_request_verification]`.

- `src/sandbox/graph.py` — `build_graph(checkpointer=None)`. For the
  sandbox, checkpointer is `None` by default — LangGraph's in-memory
  checkpointer is fine (the sandbox is ephemeral per run). Expose
  `run_turn(graph, message, session_id)` with the same pre-turn
  message-count snapshot + one-retry-on-empty logic as the main
  project (copy from `mgr4smb/graph.py`).

**Verification for Phase 5**

`python -m sandbox.checks.smoke --phase 5` passes:
- Every agent `build()` returns a compiled graph
- Orchestrator replies to "Hi" with an intro message (LLM call succeeds)
- OTP agent, given a fresh email, walks Step 1 → sends code → asks for it
- OTP agent, given a user_email with a pre-seeded passkey row, emits a
  reply starting with `PASSKEY_REQUESTED` and calls no `send_otp` tool

---

## Phase 6 — API + chat UI

**What you need**

- `src/sandbox/api.py` — FastAPI app with exactly these routes:
  - `GET /ui` → serves `index.html`
  - `POST /chat` → JWT-protected (`require_client` copied from main
    project). Body: `{message, session_id?}`. Response:
    `{response, session_id}`.
  - `GET /health` → unauthenticated, returns `{status:"ok"}`
  - `POST /passkey/register/begin` → JWT-protected. Refuses if the
    session's `is_verified` is False (prevents rogue registration).
  - `POST /passkey/register/finish` → JWT-protected.
  - `POST /passkey/verify/begin` → JWT-protected.
  - `POST /passkey/verify/finish` → JWT-protected; on success, calls
    `graph.update_state(config={"configurable": {"thread_id":
    session_id}}, values={"is_verified": True, "is_passkey_verified":
    True})`.
  - `GET /passkey/list?user_email=...` → list this user's registered
    credentials (for the settings UI).
  - `DELETE /passkey/{credential_id}` → remove one credential.

- `index.html` — single-file chat UI (copy the dark theme + sender
  labels from `chat-ui/` in the main project). Add:
  - Passkey button that renders when the last AI message starts with
    `PASSKEY_REQUESTED`. On click → verify/begin → `navigator.credentials
    .get()` → verify/finish → POST `/chat` with `"Passkey verified"` or
    `"Passkey verification did not complete. Please use email code
    instead."`.
  - Register banner shown after a `VERIFIED` reply if
    `/passkey/list?user_email=...` returns empty. On click → register/
    begin → `navigator.credentials.create()` → register/finish → toast.
  - Settings panel with JWT input + API base URL (default
    `window.location.origin`).

**Verification for Phase 6**

`python -m sandbox.checks.smoke --phase 6` passes:
- `./run.sh start` boots uvicorn
- `GET /health` → 200
- `POST /chat` without JWT → 401
- `POST /chat` with JWT + message "Hi" → 200 with orchestrator reply
- `POST /passkey/register/begin` with session not yet OTP-verified → 403
- Browser smoke (manual, documented in README): register a passkey,
  then in a fresh session see PASSKEY_REQUESTED and verify via Touch
  ID; then cancel the dialog on a subsequent try and watch OTP kick in

---

## Phase 7 — End-to-end manual test + packaging

**What you verify**

1. **Fresh user — OTP only**
   - Start server. Open `/ui`. Paste JWT (create one via a tiny helper
     script `scripts/issue_dev_jwt.py`).
   - Message: "please verify me, my email is dev@example.com".
   - Terminal prints `===== OTP for dev@example.com: 123456 =====`.
   - Paste `123456` into the chat → reply starts with `VERIFIED`.
   - Register banner appears. Click it. Touch ID prompt. Register ok.

2. **Returning user — passkey path**
   - Click "New session" (fresh `session_id`).
   - Message: "verify me, email dev@example.com".
   - Chat shows `PASSKEY_REQUESTED — tap the button below`.
   - Button appears. Tap → Touch ID → success → chat continues and the
     next orchestrator turn sees `is_verified=True` (via
     `graph.update_state`).
   - No OTP banner in the terminal this session.

3. **Fallback**
   - Same setup as (2), but CANCEL the authenticator dialog.
   - UI posts `"Passkey verification did not complete..."` into /chat.
   - OTP agent falls through to Step 1 → terminal prints a fresh code →
     normal OTP flow.

4. **LangSmith**
   - Each run_turn tagged `session:<uuid>`. Confirm the trace appears
     in the `passkey-otp-sandbox` project dashboard.

**Packaging**

Once the sandbox works on this machine, ship it as a zip:

```bash
cd ..
zip -r passkey-otp-sandbox.zip passkey-otp-sandbox \
    -x '*/.venv/*' '*/__pycache__/*' '*/.env' '*/passkeys.db*' \
       '*/logs/*' '*/.pytest_cache/*'
```

The zip contains everything needed to run from scratch:
- `README.md` with the 4-step quickstart (unzip → venv → env → run).
- Source code under `src/`.
- `run.sh` for lifecycle.
- Fixtures: none — SQLite is created on first run.

Deliverable: `passkey-otp-sandbox.zip` dropped into the parent dir, ready
to email / drop on another machine. The user unzips and runs
`./run.sh start` after filling in `.env`.

---

## Summary table

| Phase | Deliverable | Verification |
|-------|-------------|--------------|
| 1 | pyproject.toml, .env.example, run.sh, directory skeleton | `uv pip install -e .`; import smoke |
| 2 | config, state, llm, logging, exceptions, SQLite bootstrap | LLM round-trip, DB write/read |
| 3 | OTP tools (stub delivery, in-memory store) | code stored, verify matches/rejects |
| 4 | WebAuthn storage, challenges, verification + passkey tools | register/auth with fixtures; counter monotonic |
| 5 | Orchestrator + OTP agent prompts + graph wiring | agents build; OTP path; passkey path via pre-seeded row |
| 6 | FastAPI routes + index.html chat UI | health OK; 401 without JWT; 403 on unauth'd register-begin |
| 7 | Manual browser test + zip the project | all three scenarios work; zip extracts cleanly |

## Critical files to be created / modified

All NEW (no modifications to existing mgr4smb project):

- `passkey-otp-sandbox/pyproject.toml`
- `passkey-otp-sandbox/run.sh`
- `passkey-otp-sandbox/.env.example`
- `passkey-otp-sandbox/.gitignore`
- `passkey-otp-sandbox/README.md`
- `passkey-otp-sandbox/index.html`
- `passkey-otp-sandbox/src/sandbox/config.py`
- `passkey-otp-sandbox/src/sandbox/state.py`
- `passkey-otp-sandbox/src/sandbox/llm.py`
- `passkey-otp-sandbox/src/sandbox/graph.py`
- `passkey-otp-sandbox/src/sandbox/api.py`
- `passkey-otp-sandbox/src/sandbox/logging_config.py`
- `passkey-otp-sandbox/src/sandbox/exceptions.py`
- `passkey-otp-sandbox/src/sandbox/agents/_helpers.py`
- `passkey-otp-sandbox/src/sandbox/agents/orchestrator.py`
- `passkey-otp-sandbox/src/sandbox/agents/otp.py`
- `passkey-otp-sandbox/src/sandbox/tools/otp_store.py`
- `passkey-otp-sandbox/src/sandbox/tools/send_otp.py`
- `passkey-otp-sandbox/src/sandbox/tools/verify_otp.py`
- `passkey-otp-sandbox/src/sandbox/tools/passkey_status.py`
- `passkey-otp-sandbox/src/sandbox/tools/passkey_request_verification.py`
- `passkey-otp-sandbox/src/sandbox/webauthn/storage.py`
- `passkey-otp-sandbox/src/sandbox/webauthn/challenges.py`
- `passkey-otp-sandbox/src/sandbox/webauthn/verification.py`
- `passkey-otp-sandbox/src/sandbox/checks/smoke.py`
- `passkey-otp-sandbox/scripts/issue_dev_jwt.py`    # one-liner helper

## Existing code that can be copied verbatim (not reinvented)

All paths are relative to the main mgr4smb project — copy into the
corresponding sandbox paths:

- `mgr4smb/agents/_helpers.py` → `src/sandbox/agents/_helpers.py`
  (the `agent_as_tool` helper with `InjectedState` — works unchanged)
- `mgr4smb/logging_config.py` → `src/sandbox/logging_config.py`
  (trim imports but keep the format / rotation / stderr+file handlers)
- `mgr4smb/exceptions.py` → `src/sandbox/exceptions.py`
  (drop GHL/Jobber/MongoDB classes, keep the hierarchy pattern)
- `mgr4smb/auth.py` → `src/sandbox/auth.py`
  (JWT verify/issue unchanged; points at a simpler `clients.json` or
  even a single hard-coded dev client)
- `mgr4smb/graph.py` `run_turn()` implementation → sandbox `graph.py`
  (the pre-turn count snapshot + empty-retry logic is pure; no project-
  specific dependencies)
- `chat-ui/chat.js` + `chat.css` → `index.html` (inline both into a
  single file for zip-ability)

## Verification (overall)

1. `./run.sh smoke` passes every phase gate (1–6 structural, 7 manual).
2. Manual end-to-end: fresh OTP flow → register → passkey flow →
   fallback flow — all three work in a single browser session.
3. `LangSmith` project "passkey-otp-sandbox" shows traces tagged per
   session.
4. `passkey-otp-sandbox.zip` extracts in a fresh directory on a different
   machine and runs with only `.env` edits.
