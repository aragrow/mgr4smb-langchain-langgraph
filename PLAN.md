# Plan: Migrate mgr4smb Langflow Orchestrator V9 to LangChain + LangGraph

## Context

The project is a multi-agent customer assistant currently built as a Langflow visual flow (`mgr4smb - Orquestrator V9.json`). It uses an **Orchestrator pattern**: a central agent collects user identity (email + phone), greets them, then routes to one of 6 specialist sub-agents (greeting, general info, booking, OTP verification, GHL support, Jobber support). Each sub-agent has its own tools (GoHighLevel API, Jobber GraphQL API, MongoDB Atlas vector search). All agents use **Google Gemini 2.5 Flash** via `ChatGoogleGenerativeAI`.

The goal is to reimplement this entire system as a pure Python project using **LangChain** (for LLM/tool abstractions) and **LangGraph** (for the multi-agent orchestration graph with state management).

---

## Architecture Summary from Langflow

```
┌─────────────────────────────────────────────────────────────────────┐
│  PUBLIC (Internet)                                                  │
│                                                                     │
│  POST /chat ──► FastAPI ──► JWT + client_id validation              │
│                    │                                                │
│                    ▼         (401 if invalid)                       │
├─────────────────────────────────────────────────────────────────────┤
│  PRIVATE (internal only — no public endpoints)                      │
│                                                                     │
│  ORCHESTRATOR AGENT                                                 │
│       ├── GREETING_AGENT        (tool: GHL Contact Lookup)          │
│       ├── GENERAL_INFO_AGENT    (tool: MongoDB Atlas Vector Search) │
│       ├── BOOKING_AGENT         (tools: GHL Available Slots,        │
│       │                          GHL Book Appointment;              │
│       │                          + delegates to JOBBER_SUPPORT_AGENT│
│       │                            for job creation)                │
│       ├── OTP_AGENT             (tools: GHL Send OTP, GHL Verify    │
│       │      ↑ called by BOOKING, GHL_SUPPORT, and JOBBER_SUPPORT   │
│       │        before any sensitive operation                       │
│       ├── GHL_SUPPORT_AGENT     (tools: GHL Get Appointments,       │
│       │                          GHL Cancel Appointment;            │
│       │                          delegates to BOOKING_AGENT         │
│       │                            for rebook step of reschedule)   │
│       └── JOBBER_SUPPORT_AGENT  (tools: Jobber Get Clients,         │
│                                  Jobber Get Properties,             │
│                                  Jobber Get Jobs, Jobber Get Visits, │
│                                  Jobber Create Client,              │
│                                  Jobber Create Property,            │
│                                  Jobber Create Job,                 │
│                                  Jobber Send Message [future])      │
└─────────────────────────────────────────────────────────────────────┘
```

**External services:**
- **GoHighLevel (GHL)** REST API (`https://services.leadconnectorhq.com`) — contacts, calendars, appointments, OTP
- **Jobber** GraphQL API (`https://api.getjobber.com/api/graphql`) — clients, properties, jobs, visits (OAuth2 token refresh)
- **MongoDB Atlas** — vector store for company knowledge base (cosine similarity, 768 dimensions, Gemini embeddings)
- **Google Generative AI** — LLM (gemini-2.5-flash) + embeddings (gemini-embedding-001)

**Security boundary:**
- Only `POST /chat` is exposed publicly — protected by JWT + client_id
- All sub-agents are internal graph nodes — no API routes, no direct access
- Each client runs their own instance — `clients.json` holds client identity, `JWT_SECRET` in `.env` signs tokens
- JWT tokens carry `client_id` + expiration — validated on every request

---

## Implementation Phases

### Phase 1: Local Environment Setup

**Goal:** Set up a working Python environment with all dependencies.

**Files to create:**
- `pyproject.toml` — project metadata and dependencies
- `.env.example` — template for required environment variables
- `.env` — actual secrets (already in .gitignore)
- `scripts/check_env.py` — standalone Phase 1 sanity check (runs before package exists)

**Dependencies (verified April 2026):**
```
langchain>=1.2.0             # Core framework (stable 1.x, no breaking changes until 2.0)
langchain-core>=1.2.22       # PINNED — fixes CVE-2025-68664 (deserialization RCE, CVSS 9.3)
                             #          and CVE-2026-34070 (path traversal, CVSS 7.5)
langchain-google-genai>=4.0.0  # ChatGoogleGenerativeAI + Embeddings (v4 migrated to google-genai SDK)
langgraph>=1.1.0             # Latest stable 1.x (CVE-2025-64439 fixed in checkpoint pkg)
langchain-mongodb>=0.10.0    # MongoDBAtlasVectorSearch integration
langgraph-checkpoint-mongodb>=0.3.0  # Persist graph state/conversations to MongoDB
pymongo>=4.12.0              # MongoDB driver (constrained by langgraph-checkpoint-mongodb<4.16)
httpx>=0.28.0,<1.0           # HTTP client for GHL/Jobber APIs (pre-1.0 — pin minor version)
python-dotenv>=1.2.0         # Load .env files
fastapi>=0.115.0             # API layer — only the orchestrator is public-facing
uvicorn>=0.34.0              # ASGI server for FastAPI
pyjwt>=2.10.0                # JWT token validation (client auth)
# NOTE: LangSmith tracing requires NO extra dependency — it's bundled in langchain-core.
#       Just set the LANGCHAIN_* env vars in .env to enable.
```

**Security notes:**
- `langchain-core>=1.2.22` is critical — older versions allow secret extraction from env vars and arbitrary file reads during deserialization.
- `langgraph>=3.0.0` fixes checkpoint deserialization RCE. If using SQLite checkpoints, also pin `langgraph-checkpoint-sqlite>=3.0.1` (CVE-2025-67644 SQL injection).
- `langchain-google-genai` v4.0 was a major breaking change from v3 (dropped gRPC, new google-genai SDK backend). Use v4+.
- `httpx` is still pre-1.0 — minor versions can contain breaking changes. Pin to `0.28.x`. Hardcode base URLs in tools; never interpolate user input into URLs. Disable `follow_redirects`.
- Verify MongoDB Atlas cluster is patched against CVE-2025-14847 (MongoBleed — server-side, not pymongo).

**Security hardening (to implement in Phase 2):**
- Never use `eval()` or `exec()` in tool definitions
- Use `allowed_objects` allowlist when deserializing LangChain objects
- Ensure `secrets_from_env=False` (default in patched langchain-core)
- Sanitize all tool inputs — treat LLM outputs as untrusted
- Each agent gets only the minimum tools it needs (already in design)
- Log tool invocations for audit trail (LangSmith handles this automatically when tracing is enabled)

**Environment variables needed:**
```
# --- LangSmith (observability — enabled from day one) ---
LANGCHAIN_TRACING_V2=true              # Enable automatic tracing
LANGCHAIN_API_KEY=                     # LangSmith API key
LANGCHAIN_PROJECT=mgr4smb             # Project name in LangSmith dashboard
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com

# --- Auth (API layer) ---
JWT_SECRET=                  # Secret key for signing/verifying JWT tokens (KEEP SECRET)
JWT_ALGORITHM=HS256          # JWT signing algorithm
CLIENTS_FILE=clients.json    # Path to client registry file

# --- Google AI ---
GOOGLE_API_KEY=              # Gemini LLM + Embeddings

# --- GoHighLevel ---
GHL_API_KEY=                 # GoHighLevel Private Integration Token
GHL_LOCATION_ID=             # GoHighLevel Sub-Account ID
GHL_CALENDAR_ID=             # GoHighLevel Calendar ID
GHL_ORG_TIMEZONE=America/Chicago
GHL_SLOT_DURATION_MINUTES=30

# --- GoHighLevel OTP custom fields (override per client if needed) ---
# Must match the fieldKey of the custom fields created in GHL under
# Settings > Custom Fields. The values must include the "contact." prefix.
GHL_OTP_CODE_FIELD_KEY=contact.otp_code
GHL_OTP_EXPIRY_FIELD_KEY=contact.otp_expires_at
GHL_OTP_LIFETIME_MINUTES=15

# --- Company contact info (used in escalation messages) ---
COMPANY_NAME=Aragrow LLC
COMPANY_SUPPORT_EMAIL=        # Optional — appears in OTP escalation reply
COMPANY_SUPPORT_PHONE=        # Optional — appears in OTP escalation reply

# --- MongoDB (knowledge base) ---
MONGODB_ATLAS_URI=           # MongoDB connection string
MONGODB_DB_NAME=aragrow-llc
MONGODB_COLLECTION=knowledge_base
MONGODB_INDEX_NAME=aragrow_vector_index

# --- MongoDB (shared memory / checkpointer) ---
MONGODB_MEMORY_DB=mgr4smb-memory      # Separate DB for conversation persistence
MONGODB_MEMORY_COLLECTION=checkpoints  # Stores full graph state per session

# --- Jobber ---
JOBBER_CLIENT_ID=            # Jobber OAuth app Client ID
JOBBER_CLIENT_SECRET=        # Jobber OAuth app Client Secret
JOBBER_TOKENS_FILE=.tokens.json  # Path to Jobber OAuth tokens file
```

**Client registry file (`clients.json`):**
```json
{
  "clients": [
    {
      "client_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "name": "Aragrow LLC",
      "enabled": true,
      "created_at": "2026-04-12T00:00:00Z"
    }
  ]
}
```
- `client_id` is a UUID v4 — generated via `menu.sh` (see Phase 9d)
- Each client has their own instance of the app, so `clients.json` holds identity only (no secrets)
- The JWT signing secret lives in `.env` (never in the JSON file)
- The JSON file validates that the `client_id` claim in the JWT is a known, enabled client
- File permissions should be `600` (owner read/write only)
- Add to `.gitignore`: `clients.json`, `.tokens.json`, `.mgr4smb.pid`, `logs/`

**Steps:**
1. Create `pyproject.toml` with all dependencies
2. Create `.env.example` with all keys listed (no values)
3. Create virtual environment and install dependencies:
   ```bash
   # Using uv (preferred — faster)
   uv venv .venv
   source .venv/bin/activate
   uv pip install -e .

   # Or using pip (fallback)
   python -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
4. Verify install with a smoke test script (`python -c "from langchain_google_genai import ChatGoogleGenerativeAI; print('OK')"`)

**Note:** `uv` is the preferred package manager (faster installs, better dependency resolution). Fall back to `pip` if `uv` is not available. Both read from the same `pyproject.toml`.

**Sanity check — `python scripts/check_env.py`** (standalone — runs before package exists):
- [ ] Python version >= 3.10
- [ ] `.venv` exists and is activated
- [ ] All required packages import successfully (langchain, langgraph, fastapi, httpx, pyjwt, etc.)
- [ ] `.env` file exists and all required keys are present (values non-empty)
- [ ] LangSmith env vars set (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY` non-empty)

---

### Phase 2: Project Structure & Shared Utilities

**Goal:** Create the project skeleton and shared modules.

**Directory structure (current):**
```
.                              # Project root
├── pyproject.toml             # Dependencies, build backend
├── .env / .env.example        # Secrets and config
├── clients.json               # Client + JWT registry (gitignored)
├── .tokens.json               # Jobber OAuth tokens (gitignored)
├── .mgr4smb.pid               # Server PID file (gitignored)
├── logs/                      # Rotating log directory (gitignored)
├── menu.sh                    # Operations menu (start/stop/health/clients)
├── main.py                    # CLI entry: python main.py --cli
├── PLAN.md                    # This file
├── chat-ui/                   # Self-contained web chat UI (served by FastAPI)
│   ├── index.html             # Topbar + settings + chat + composer
│   ├── chat.css               # Dark theme + sender labels + typing dots
│   └── chat.js                # JWT in localStorage, /chat polling, session_id
├── scripts/
│   ├── check_env.py                       # Phase 1 standalone gate
│   └── replay_session_22e348a2.py         # Replay-the-failing-flow script
└── mgr4smb/                   # Main package
    ├── __init__.py
    ├── config.py              # Settings singleton — all .env reads
    ├── llm.py                 # get_llm() + get_embeddings() singletons
    ├── state.py               # AgentState TypedDict — single source of truth
    ├── graph.py               # build_graph() + run_turn() + get_history()
    ├── memory.py              # checkpointer_context() yields MongoDBSaver
    ├── api.py                 # FastAPI app + /health + /chat + chat-ui mount
    ├── auth.py                # verify_token() + issue_token()
    ├── logging_config.py      # setup_logging() — stderr + rotating file
    ├── exceptions.py          # Mgr4smbError hierarchy
    ├── checks/                # Sanity gates — one per phase
    │   ├── __init__.py
    │   ├── run_all.py         # Cumulative runner with --fast / --up-to N
    │   ├── phase2_skeleton.py
    │   ├── phase3_ghl.py
    │   ├── phase4_jobber.py
    │   ├── phase5_mongodb.py
    │   ├── phase6_prompts.py
    │   ├── phase7_agents.py
    │   ├── phase8_graph.py
    │   ├── phase9_api.py
    │   └── phase10_full.py    # End-to-end via FastAPI TestClient
    ├── tools/
    │   ├── __init__.py
    │   ├── ghl_client.py            # Shared httpx.Client + search_contact +
    │   │                            # fetch_contact + resolve_custom_field_id
    │   ├── jobber_client.py         # Shared GraphQL client + OAuth refresh
    │   ├── ghl_contact_lookup.py
    │   ├── ghl_available_slots.py
    │   ├── ghl_book_appointment.py
    │   ├── ghl_get_appointments.py
    │   ├── ghl_cancel_appointment.py
    │   ├── ghl_send_otp.py          # Always overwrites; session-once is the prompt's job
    │   ├── ghl_verify_otp.py        # Reads via fresh GET; keeps code on wrong attempts
    │   ├── jobber_get_clients.py
    │   ├── jobber_get_properties.py
    │   ├── jobber_get_jobs.py
    │   ├── jobber_get_visits.py
    │   ├── jobber_create_client.py
    │   ├── jobber_create_property.py
    │   ├── jobber_create_job.py
    │   ├── jobber_send_message.py   # [future stub]
    │   └── mongodb_knowledge_base.py
    └── agents/                # Each file: SYSTEM_PROMPT + TOOLS + build()
        ├── __init__.py
        ├── _helpers.py        # agent_as_tool() — wraps subgraph w/ InjectedState
        ├── orchestrator.py
        ├── greeting.py
        ├── general_info.py
        ├── booking.py
        ├── otp.py             # Imports settings for company contact escalation
        ├── ghl_support.py
        └── jobber_support.py
```

**Key files in this phase:**
- `mgr4smb/config.py` — centralized settings from env vars
- `mgr4smb/llm.py` — factory functions: `get_llm()` returns `ChatGoogleGenerativeAI(model="gemini-2.5-flash")`, `get_embeddings()` returns `GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")`
- `mgr4smb/state.py` — LangGraph `TypedDict` state (single source of truth — defined here, referenced everywhere):
  ```python
  class AgentState(TypedDict):
      messages: Annotated[list, add_messages]  # SHARED — all agents read/write
      client_id: str              # Authenticated client (from JWT)
      session_id: str             # Conversation session ID
      contact_id: str             # GHL contact ID (cached after first lookup — avoids redundant searches)
      user_email: str
      user_phone: str
      user_timezone: str
      user_name: str
      is_existing_contact: bool
      is_verified: bool           # OTP verified — persists for session
  ```
- `mgr4smb/logging_config.py` — structured logging setup
- `mgr4smb/exceptions.py` — custom exception hierarchy

#### Error Handling & Logging Standards

All code must follow these patterns from Phase 2 onward. This is not optional — it's built into the skeleton so every module inherits it.

##### Logging (`mgr4smb/logging_config.py`)

Use Python's built-in `logging` module with **structured JSON output** for production and **human-readable** for development.

```python
import logging
import sys

def setup_logging(level: str = "INFO", json_output: bool = False):
    """Call once at startup (main.py / api.py)."""
    ...

# Every module gets its own logger — never use print()
logger = logging.getLogger(__name__)
```

**Rules every module must follow:**
1. **One logger per module:** `logger = logging.getLogger(__name__)` at module top
2. **Never use `print()` for diagnostics** — always `logger.info()`, `logger.debug()`, etc.
3. **Log levels used consistently:**
   - `DEBUG` — tool input/output details, LLM prompt fragments (dev only)
   - `INFO` — request received, agent routed, tool called, session started/resumed
   - `WARNING` — retryable failures, token refresh triggered, OTP retry
   - `ERROR` — tool call failed, API returned non-2xx, unhandled agent error
   - `CRITICAL` — config missing, MongoDB unreachable, server cannot start
4. **Structured context in every log line** — use `extra={}` or f-strings with key=value:
   ```python
   logger.info("Tool called", extra={"tool": "ghl_contact_lookup", "input": email, "session_id": sid})
   logger.error("GHL API error", extra={"status": resp.status_code, "body": resp.text[:200], "tool": "ghl_book_appointment"})
   ```
5. **Never log secrets** — no API keys, JWT tokens, OTP codes, or full MongoDB URIs. Mask them:
   ```python
   logger.info("Using GHL API key ending in ...%s", api_key[-4:])
   ```
6. **Log file rotation** — write to `logs/mgr4smb.log` with `RotatingFileHandler` (10MB max, 5 backups). Also output to stderr for container/systemd environments.

**Log output locations:**
- `stderr` — always (for `uvicorn` / terminal / container logs)
- `logs/mgr4smb.log` — rotating file (add `logs/` to `.gitignore`)
- **LangSmith** — LLM calls and tool invocations are traced automatically (separate from Python logging)

##### Custom Exceptions (`mgr4smb/exceptions.py`)

Define a hierarchy so every `except` block catches the right granularity:

```python
class Mgr4smbError(Exception):
    """Base exception for all project errors."""
    pass

# --- External API errors ---
class ExternalAPIError(Mgr4smbError):
    """Base for all external service failures."""
    def __init__(self, service: str, status_code: int, detail: str):
        self.service = service
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{service} API error {status_code}: {detail}")

class GHLAPIError(ExternalAPIError):
    """GoHighLevel API returned a non-2xx response."""
    def __init__(self, status_code: int, detail: str):
        super().__init__("GHL", status_code, detail)

class JobberAPIError(ExternalAPIError):
    """Jobber GraphQL API returned an error."""
    def __init__(self, status_code: int, detail: str):
        super().__init__("Jobber", status_code, detail)

class MongoDBError(Mgr4smbError):
    """MongoDB connection or query failure."""
    pass

# --- Auth errors ---
class AuthError(Mgr4smbError):
    """JWT validation or client_id lookup failure."""
    pass

class TokenExpiredError(AuthError):
    pass

class InvalidClientError(AuthError):
    pass

# --- Agent errors ---
class AgentError(Mgr4smbError):
    """An agent failed to produce a valid response."""
    def __init__(self, agent_name: str, detail: str):
        self.agent_name = agent_name
        super().__init__(f"Agent '{agent_name}' failed: {detail}")

# --- Tool errors ---
class ToolError(Mgr4smbError):
    """A tool invocation failed."""
    def __init__(self, tool_name: str, detail: str):
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' failed: {detail}")

# --- Config errors ---
class ConfigError(Mgr4smbError):
    """Missing or invalid configuration."""
    pass
```

##### Error Handling Patterns (apply everywhere)

**Pattern 1 — Tool functions (GHL, Jobber, MongoDB):**
```python
@tool
def ghl_contact_lookup(email: str) -> str:
    """Look up a contact in GoHighLevel by email."""
    logger = logging.getLogger(__name__)
    try:
        resp = httpx.post(f"{GHL_BASE}/contacts/search", ...)
        resp.raise_for_status()
        # ... process response
        logger.info("Contact found", extra={"tool": "ghl_contact_lookup", "email": email})
        return result
    except httpx.HTTPStatusError as e:
        logger.error("GHL API error", extra={
            "tool": "ghl_contact_lookup",
            "status": e.response.status_code,
            "body": e.response.text[:200]
        })
        raise GHLAPIError(e.response.status_code, e.response.text[:200]) from e
    except httpx.ConnectError as e:
        logger.error("GHL unreachable", extra={"tool": "ghl_contact_lookup", "error": str(e)})
        raise GHLAPIError(503, "Service unreachable") from e
```

**Pattern 2 — API endpoint (FastAPI):**
```python
@app.exception_handler(AuthError)
async def auth_error_handler(request, exc):
    logger.warning("Auth rejected", extra={"error": str(exc), "path": request.url.path})
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})

@app.exception_handler(ExternalAPIError)
async def api_error_handler(request, exc):
    logger.error("External API failure", extra={"service": exc.service, "status": exc.status_code})
    return JSONResponse(status_code=502, content={"error": f"{exc.service} service unavailable"})

@app.exception_handler(Exception)
async def catch_all_handler(request, exc):
    logger.critical("Unhandled exception", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})
```

**Pattern 3 — Agent nodes (graceful degradation):**
```python
def run_agent(state: AgentState) -> AgentState:
    try:
        result = agent.invoke(state)
        return result
    except ToolError as e:
        logger.error("Tool failed in agent", extra={"agent": "booking_agent", "tool": e.tool_name})
        # Return a user-friendly message instead of crashing the graph
        state["messages"].append(AIMessage(content="I'm having trouble accessing that service. Let me try again or connect you with support."))
        return state
    except Exception as e:
        logger.critical("Agent crashed", extra={"agent": "booking_agent"}, exc_info=True)
        state["messages"].append(AIMessage(content="Something went wrong. Please try again or contact the office directly."))
        return state
```

**Rules:**
1. **Never swallow exceptions silently** — every `except` must log
2. **Always use `exc_info=True` for unexpected errors** — captures full traceback in log
3. **Never expose internal details to the user** — log the real error, return a generic message
4. **Use the custom exception hierarchy** — never raise bare `Exception` or `ValueError` for business logic
5. **Catch specific exceptions first, broad last** — `except httpx.HTTPStatusError` before `except Exception`
6. **Tools return error strings to the LLM, not raise** — when a tool fails in a way the LLM can handle (e.g., "contact not found"), return a descriptive string. Only raise for infrastructure failures.
7. **FastAPI catches everything** — `exception_handler` for each custom type + a catch-all that logs `CRITICAL` and returns 500

**Sanity check — `python -m mgr4smb.checks.phase2_skeleton`:**
- [ ] `from mgr4smb.config import settings` loads all env vars
- [ ] `from mgr4smb.llm import get_llm` returns a working `ChatGoogleGenerativeAI` instance
- [ ] `get_llm().invoke("Say hello")` returns a valid response
- [ ] `from mgr4smb.llm import get_embeddings` returns a working embeddings instance
- [ ] `get_embeddings().embed_query("test")` returns a 768-dim vector
- [ ] `from mgr4smb.state import AgentState` imports without error
- [ ] `from mgr4smb.exceptions import GHLAPIError, JobberAPIError, AuthError` imports without error
- [ ] `from mgr4smb.logging_config import setup_logging` works; calling it creates logger + log file at `logs/mgr4smb.log`
- [ ] Logging writes to both stderr and `logs/mgr4smb.log`
- [ ] `logger.error("test", exc_info=True)` captures traceback in log output
- [ ] No `print()` statements in any `mgr4smb/` module (grep check)
- [ ] LangSmith trace appears in dashboard for the `get_llm().invoke()` call above

---

### Phase 3: Tools — GoHighLevel API

**Goal:** Implement all 7 GHL tools as LangChain `@tool` functions.

Each tool wraps an `httpx` call to the GHL REST API at `https://services.leadconnectorhq.com`. All share headers: `Authorization: Bearer {api_key}`, `Version: 2021-07-28`, `Content-Type: application/json`.

**Shared GHL client (`mgr4smb/tools/ghl_client.py`):**
- Single `httpx.Client` instance with connection pooling (reused across all GHL tools — avoids new TCP connection per call)
- Shared auth headers, base URL, and timeouts: `httpx.Timeout(10.0, connect=5.0)`
- `search_contact(email_or_phone)` method — returns contact_id + contact data
- Tools that need a contact_id should accept it as an optional parameter. If provided, skip the search. If not, call `search_contact()`. This avoids redundant `/contacts/search` calls when multiple tools chain in the same flow (e.g., OTP → get appointments → cancel).
- The `contact_id` is cached in graph state after the first lookup (by GREETING_AGENT) and passed to subsequent tools.

| Tool | GHL Endpoints | Langflow Source |
|------|--------------|-----------------|
| `ghl_contact_lookup` | POST `/contacts/search` | GoHighLevelContactLookup (5,966 chars) |
| `ghl_available_slots` | POST `/contacts/search` + GET `/calendars/{id}/free-slots` | GoHighLevelAvailableSlots (9,604 chars) |
| `ghl_book_appointment` | POST `/contacts/search` + POST `/calendars/events/appointments` | GoHighLevelBookAppointment (9,393 chars) |
| `ghl_get_appointments` | POST `/contacts/search` + GET `/contacts/{id}/appointments` | GoHighLevelGetAppointments (9,983 chars) |
| `ghl_cancel_appointment` | GET+PUT or DELETE `/calendars/events/appointments/{eventId}` | GoHighLevelCancelAppointment (9,671 chars) |
| `ghl_send_otp` | POST `/contacts/search` + PUT `/contacts/{contactId}` | GoHighLevelSendOTP (11,735 chars) |
| `ghl_verify_otp` | POST `/contacts/search` + PUT `/contacts/{contactId}` | GoHighLevelVerifyOTP (11,297 chars) |

Implementation approach: Extract the core HTTP logic from each Langflow component's `code` field and wrap it in a `@tool` decorated function. All tools use the shared `GHLClient` for HTTP calls.

**Sanity check — `python -m mgr4smb.checks.phase3_ghl [--dry-run|--live]`:**

`--dry-run` (default, safe for CI — no API calls):
- [ ] All 7 tools import successfully
- [ ] All tools have proper `@tool` decorator with name and description
- [ ] `GHLClient` instantiates with correct base URL and headers
- [ ] No user input is interpolated into URLs (static analysis / grep for f-string in URL paths)
- [ ] Each tool function signature matches expected parameters

`--live` (hits real GHL API — requires credentials):
- [ ] `GHLClient.search_contact("known-test-email@example.com")` returns a contact object
- [ ] `GHLClient.search_contact("nonexistent@fake.com")` returns empty/not-found gracefully
- [ ] `ghl_contact_lookup` tool returns contact name for a known email
- [ ] `ghl_available_slots` tool returns at least one slot
- [ ] `ghl_get_appointments` tool returns appointments for a known contact
- [ ] `ghl_send_otp` tool returns `OTP_SENT` for matching email+phone
- [ ] `ghl_send_otp` tool returns `OTP_FAILED` for mismatched email+phone
- [ ] LangSmith traces show tool invocations

---

### Phase 4: Tools — Jobber GraphQL API

**Goal:** Implement all 7 Jobber tools (4 read + 3 write) as LangChain `@tool` functions.

All Jobber tools use GraphQL at `https://api.getjobber.com/api/graphql` with OAuth2 token refresh. They share:
- Header: `Authorization: Bearer {access_token}`, `X-JOBBER-GRAPHQL-VERSION: 2026-03-10`
- Token refresh: POST to `https://api.getjobber.com/api/oauth/token` with client_id, client_secret, refresh_token
- Tokens stored in `.tokens.json` file with in-memory cache

**Read tools (existing in Langflow):**

| Tool | GraphQL Operation |
|------|------------------|
| `jobber_get_clients` | Query clients by name/email/phone/ID |
| `jobber_get_properties` | Query properties by client_id |
| `jobber_get_jobs` | Query jobs by client_id |
| `jobber_get_visits` | Query visits by client_id |

**Write tools (new — needed for BOOKING_AGENT → JOBBER_SUPPORT_AGENT job creation flow):**

| Tool | GraphQL Mutation | Purpose |
|------|-----------------|---------|
| `jobber_create_client` | `clientCreate` mutation | Create a new client (name, email, phone) if not found by `jobber_get_clients` |
| `jobber_create_property` | `propertyCreate` mutation | Create a property for a client with: address, type (house/apartment/office), bedrooms, bathrooms, offices |
| `jobber_create_job` | `jobCreate` mutation | Create a new job tied to a client + property, with service type and preferred schedule |
| `jobber_send_message` | **[FUTURE]** — notify the vendor about the new job | Placeholder — plan for future implementation |

Implementation approach: Create a shared `JobberClient` class in `mgr4smb/tools/jobber_client.py` that handles auth, token refresh, GraphQL execution, and timeouts (`httpx.Timeout(10.0, connect=5.0)`). Single `httpx.Client` instance with connection pooling. Each tool function calls this client.

**Sanity check — `python -m mgr4smb.checks.phase4_jobber [--dry-run|--live]`:**

`--dry-run` (default, safe for CI):
- [ ] All 7 tools import successfully (4 read + 3 write)
- [ ] All tools have proper `@tool` decorator with name and description
- [ ] `JobberClient` instantiates with correct GraphQL URL and headers
- [ ] Each tool function signature matches expected parameters

`--live` (hits real Jobber API — requires credentials):
- [ ] `JobberClient` authenticates and gets a valid access token
- [ ] Token refresh works (force-expire the token, verify refresh succeeds)
- [ ] `.tokens.json` is updated after refresh
- [ ] `jobber_get_clients` returns results for a known client name
- [ ] `jobber_get_clients` with empty search returns a list (up to 50)
- [ ] `jobber_get_properties` returns properties for a known client_id
- [ ] `jobber_get_jobs` returns jobs for a known client_id
- [ ] `jobber_get_visits` returns visits for a known client_id
- [ ] GraphQL errors are handled gracefully (not raised as unhandled exceptions)
- [ ] LangSmith traces show tool invocations

---

### Phase 5: Tool — MongoDB Knowledge Base

**Goal:** Implement the vector search tool for the General Info Agent.

- Use `langchain-mongodb` `MongoDBAtlasVectorSearch` with:
  - Collection: `knowledge_base` in DB `aragrow-llc`
  - Index: `aragrow_vector_index` (768 dimensions, cosine)
  - Embeddings: `GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")`
- Expose as a `@tool` that takes a search query string and returns top-1 result

**Sanity check — `python -m mgr4smb.checks.phase5_mongodb`:**
- [ ] MongoDB connection succeeds (pymongo ping)
- [ ] Collection `knowledge_base` exists in DB `aragrow-llc`
- [ ] Vector index `aragrow_vector_index` is present and active
- [ ] `mongodb_knowledge_base("What services do you offer?")` returns a non-empty result
- [ ] Query with no matches returns a graceful "no results" response (not an error)
- [ ] Embedding dimension matches index (768)
- [ ] LangSmith trace shows the embedding call + vector search

---

### Phase 6: Agent Prompts

**Goal:** Port all 7 agent system prompts (6 from Langflow + 1 new OTP_AGENT prompt).

Store each prompt as a `SYSTEM_PROMPT` string constant inside its corresponding `mgr4smb/agents/*.py` file (no separate `prompts/` directory — each prompt is ~50-100 lines, co-located with the agent that uses it). The Langflow prompts will be copied and adapted (OTP logic extracted from old customer_support prompt into OTP_AGENT; GHL_SUPPORT_AGENT prompt cleaned of OTP steps).

Agents and their prompts:
1. **ORCHESTRATOR** — Collects email+phone, calls greeting_agent, routes to specialist
2. **GREETING_AGENT** — Looks up contact via GHL, returns personalized greeting
3. **GENERAL_INFO_AGENT** — Answers company questions via MongoDB knowledge base
4. **OTP_AGENT** — Dedicated identity verification agent (new — extracted from old customer_support prompt). Handles the full OTP flow:
   - Calls GHL Send OTP with user's email + phone → validates they match a contact on file
   - If OTP_SENT → asks user for the 6-digit code → calls GHL Verify OTP
   - If VERIFIED → sets `is_verified = true` in graph state → returns control to the calling agent
   - If OTP_FAILED or UNVERIFIED → handles retries (up to 3), expired codes, and graceful failure
   - Prompt rules: never reveal which field (email/phone) didn't match, allow up to 2 code retries, suggest calling the office after 3 failures
5. **BOOKING_AGENT** — Handles all new bookings. Delegates to OTP_AGENT before finalizing any booking. Two paths:
   - **GHL path:** Retrieve available slots → OTP verification → book appointment
   - **Jobber path:** Collect client info (email, phone, name), service, schedule, and property details → OTP verification → delegate to JOBBER_SUPPORT_AGENT to create client/property/job
   - Prompt must include the intake questionnaire logic for property details:
     - Property address
     - Property type: house, apartment, or office
     - If house/apartment: number of bedrooms, number of bathrooms
     - If office: number of offices, number of bathrooms
6. **GHL_SUPPORT_AGENT** — View/reschedule/cancel existing appointments. Delegates to OTP_AGENT before any data access or modification
7. **JOBBER_SUPPORT_AGENT** — Read AND write Jobber data: look up clients/properties/jobs/visits, create new clients, create properties, create jobs, send vendor messages [future]. Delegates to OTP_AGENT before any data access or modification

**Sanity check — `python -m mgr4smb.checks.phase6_prompts`:**
- [ ] All 7 prompts import successfully (e.g., `from mgr4smb.agents.orchestrator import SYSTEM_PROMPT`)
- [ ] No prompt is empty or None
- [ ] Each prompt contains the agent's name (e.g., "ORCHESTRATOR", "BOOKING_AGENT")
- [ ] Each prompt mentions its expected tools by name
- [ ] OTP_AGENT prompt contains OTP flow steps (SEND → VERIFY → VERIFIED)
- [ ] BOOKING_AGENT prompt contains property intake questionnaire (house/apartment/office)
- [ ] GHL_SUPPORT_AGENT prompt does NOT contain OTP steps (extracted to OTP_AGENT)

---

### Phase 7: LangGraph Agent Nodes

**Goal:** Implement each agent as a LangGraph node using `create_react_agent` from `langgraph.prebuilt`.

Each agent node:
1. Gets its system prompt from `mgr4smb/prompts/`
2. Gets its tools from `mgr4smb/tools/`
3. Uses the shared LLM from `mgr4smb/llm.py`
4. Is created via `create_react_agent(llm, tools, prompt=system_prompt)`

| Agent Node | Tools | Notes |
|-----------|-------|-------|
| `orchestrator` | greeting, general_info, booking, ghl_support, jobber_support (all as sub-graphs) | Routes only — never answers specialist questions |
| `greeting_agent` | ghl_contact_lookup | Caches `contact_id` in graph state for downstream tools |
| `general_info_agent` | mongodb_knowledge_base | No OTP required (read-only public info) |
| `otp_agent` | ghl_send_otp, ghl_verify_otp | Followed by `otp_state_updater` node (see below) |
| `booking_agent` | ghl_available_slots, ghl_book_appointment, otp_agent, jobber_support_agent (as sub-graph for job creation) | Owns all new bookings (GHL + Jobber) |
| `ghl_support_agent` | ghl_get_appointments, ghl_cancel_appointment, otp_agent, booking_agent (as sub-graph for rebook step) | For rescheduling: cancels old → delegates to booking_agent for new slot. No duplicate booking tools. |
| `jobber_support_agent` | jobber_get_clients, jobber_get_properties, jobber_get_jobs, jobber_get_visits, jobber_create_client, jobber_create_property, jobber_create_job, jobber_send_message [future], otp_agent | Read + write Jobber data |

**Key design decision — no tool duplication:**
- `ghl_available_slots` and `ghl_book_appointment` live only in BOOKING_AGENT
- GHL_SUPPORT_AGENT delegates to BOOKING_AGENT for the rebook step of rescheduling (cancel old → route to booking_agent for new)
- This prevents the LLM from confusing "book new" vs "rebook during reschedule" contexts

**`otp_state_updater` node:**
- A `create_react_agent` node can only append messages — it cannot directly set `is_verified = true` in state
- After OTP_AGENT returns, a lightweight state updater node runs: reads the last message, checks if it contains "VERIFIED", and sets `is_verified = true` in graph state
- This is a plain Python function node, not an LLM node:
  ```python
  def otp_state_updater(state: AgentState) -> dict:
      last_msg = state["messages"][-1].content
      if "VERIFIED" in last_msg:
          return {"is_verified": True}
      return {}
  ```

**Sanity check — `python -m mgr4smb.checks.phase7_agents`:**

Test each agent in isolation with a single message. Verify it responds coherently and calls the right tools.

- [ ] `greeting_agent` — input: email+phone → calls `ghl_contact_lookup` → returns greeting
- [ ] `general_info_agent` — input: "What services do you offer?" → calls `mongodb_knowledge_base` → returns answer
- [ ] `otp_agent` — input: email+phone → calls `ghl_send_otp` → asks for code
- [ ] `booking_agent` — input: "I want to book a cleaning" → asks for service/timezone details (does not hallucinate slots)
- [ ] `ghl_support_agent` — input: "I need to reschedule" → delegates to otp_agent (does not access data before verification)
- [ ] `jobber_support_agent` — input: "Show me my jobs" → delegates to otp_agent (does not access data before verification)
- [ ] Each agent uses only its assigned tools (no tool leakage)
- [ ] LangSmith traces show correct agent → tool call chains

---

### Phase 8: LangGraph Orchestration Graph

**Goal:** Wire all agents into a LangGraph `StateGraph` that implements the orchestrator pattern.

**Graph design:**
```
              ┌─────────────┐
  User ──────>│ Orchestrator │──────> User
              └──────┬──────┘
                     │ (routes via tool call)
         ┌───────────┼───────────┬──────────────┬──────────────┐
         v           v           v              v              v
    Greeting    General Info  Booking    GHL Support     Jobber Support
     Agent        Agent       Agent        Agent             Agent
                                │              │              │
                                └──────┬───────┴──────────────┘
                                       v
                                   OTP Agent
                              (shared verification;
                               is_verified persists
                               in graph state for
                               the full session)
```

**Approach:** Use LangGraph's **multi-agent supervisor pattern**:
- The Orchestrator is a supervisor node that decides which sub-agent to invoke
- Sub-agents are implemented as sub-graphs or tool-calling nodes
- State flows: `user input → orchestrator → sub-agent → orchestrator → user output`

#### Shared Memory Architecture

All agents read and write to a **single shared `messages` list** in the graph state. This means:

- When the orchestrator routes to a sub-agent, the sub-agent sees the **full conversation history** — user messages, other agents' responses, tool calls and results
- When a sub-agent responds, its response is appended to the same shared list
- The orchestrator sees everything every sub-agent has done when deciding the next action
- OTP verification status, user identity, and all context is visible to every agent in the chain

**Graph state:** Uses `AgentState` from `mgr4smb/state.py` (defined once in Phase 2 — single source of truth). All agents share the same `messages` list and state fields (`contact_id`, `is_verified`, etc.).

#### Memory & Observability (two complementary layers)

| Layer | Purpose | Storage | What it captures |
|-------|---------|---------|-----------------|
| **MongoDB checkpointer** | In-session memory + cross-session persistence | MongoDB Atlas (`mgr4smb-memory.checkpoints`) | Full graph state: messages, user fields, is_verified — enables session resume |
| **LangSmith** | Observability, debugging, evaluation | LangSmith cloud | Every LLM call, tool invocation, agent routing decision, latency, token usage, errors |

**MongoDB checkpointer** — keeps conversations alive across requests and restarts:

```python
from langgraph.checkpoint.mongodb import MongoDBSaver

checkpointer = MongoDBSaver(
    connection_string=MONGODB_ATLAS_URI,
    db_name="mgr4smb-memory",
    collection_name="checkpoints"
)

graph = workflow.compile(checkpointer=checkpointer)
graph.invoke(state, config={"configurable": {"thread_id": session_id}})
```

**LangSmith** — automatic tracing with zero code changes. Just set the env vars in `.env`:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<key>
LANGCHAIN_PROJECT=mgr4smb
```

Once enabled, every graph invocation is traced end-to-end in the LangSmith dashboard:
- Full conversation replay (what the user said → what the orchestrator decided → which sub-agent ran → what tools were called → final response)
- Latency breakdown per node/tool
- Token usage and cost tracking
- Error traces with full context
- Built-in evaluation: create datasets from real conversations, score agent quality, compare prompt changes

**This replaces the need for custom JSONL export or dual checkpointers.** MongoDB handles session persistence, LangSmith handles evaluation and debugging.

**Files:**
- `mgr4smb/state.py` — shared state definition
- `mgr4smb/memory.py` — checkpointer setup (MongoDBSaver factory)
- `mgr4smb/graph.py` — builds and compiles the `StateGraph` with checkpointer

**Sanity check — `python -m mgr4smb.checks.phase8_graph`:**

Test the full graph end-to-end via CLI (no API/auth — just the graph directly).

- [ ] Graph compiles without error
- [ ] Checkpointer connects to MongoDB (`mgr4smb-memory.checkpoints`)
- [ ] **Routing test:** "What are your hours?" → orchestrator asks for email+phone → provide them → greeting_agent fires → routes to general_info_agent → returns knowledge base answer
- [ ] **Routing test:** "I want to book a cleaning" → routes to booking_agent (not ghl_support_agent)
- [ ] **Routing test:** "I need to reschedule my appointment" → routes to ghl_support_agent (not booking_agent)
- [ ] **No tool duplication test:** ghl_support_agent does NOT have ghl_available_slots or ghl_book_appointment tools — it delegates to booking_agent for rebook
- [ ] **Contact caching test:** After greeting_agent runs, `contact_id` is populated in graph state. Subsequent GHL tools receive it (no redundant `/contacts/search` calls)
- [ ] **Shared memory test:** Sub-agent response is visible in the orchestrator's message history
- [ ] **Session persistence test:** Invoke graph with session_id, stop, re-invoke with same session_id → conversation continues (not restarted)
- [ ] **OTP gate test:** ghl_support_agent triggers otp_agent before accessing appointment data
- [ ] **OTP state updater test:** After otp_agent returns "VERIFIED", `otp_state_updater` node sets `is_verified = true` in state
- [ ] **OTP persistence test:** After verification, a second agent in the same session does NOT re-trigger OTP (checks `is_verified` in state)
- [ ] LangSmith trace shows the full chain: orchestrator → sub-agent → tools → response

---

### Phase 9: API Layer & Entry Points

**Goal:** Create a secured FastAPI app as the only public-facing access point, plus a CLI for local testing.

#### 9a. Authentication (`mgr4smb/auth.py`)

**How it works:**
1. Client sends request with `Authorization: Bearer <jwt_token>` header
2. `auth.py` decodes the JWT using `JWT_SECRET` from `.env`
3. Extracts `client_id` claim from the token payload
4. Validates `client_id` exists and is `enabled` in `clients.json`
5. If valid → request proceeds to orchestrator. If invalid → `401 Unauthorized`

**JWT token payload structure:**
```json
{
  "client_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "exp": 1744444800,
  "iat": 1744441200
}
```

**Key design decisions:**
- JWT secret is in `.env` — never in `clients.json` or code
- `clients.json` is a lightweight registry (identity + enabled flag only)
- Token expiration is enforced — expired tokens are rejected
- No sub-agents are exposed via API — only the orchestrator endpoint

#### 9b. FastAPI App (`mgr4smb/api.py`)

**Endpoints:**

```
POST /chat
Headers: Authorization: Bearer <jwt_token>
Body: { "message": "I want to book a cleaning", "session_id": "optional-uuid" }
Response: { "response": "...", "session_id": "uuid" }

GET /health     (unauthenticated)
Response: { "status": "ok", "checks": { "mongodb": "ok", "llm": "ok" } }
         or 503 with { "status": "degraded", "checks": { "mongodb": "ok", "llm": "error" } }
```

**Features:**
- Auth middleware validates JWT + client_id on every `/chat` request
- `/health` is unauthenticated — used by load balancers, monitoring, and `menu.sh` status check
- `/health` verifies: MongoDB checkpointer reachable + LLM responds to a ping
- `session_id` maintains conversation state across turns (maps to LangGraph thread)
- Only the orchestrator graph is invoked — sub-agents are internal
- Rate limiting per client_id (optional, recommended)
- CORS disabled by default (enable per deployment)

**File:** `main.py`
```python
# Production: uvicorn mgr4smb.api:app --host 0.0.0.0 --port 8000
# Dev CLI:    python main.py --cli   (interactive terminal chat, bypasses auth)
```

#### 9c. CLI Mode (for local testing)

- `python main.py --cli` runs an interactive terminal chat loop
- Bypasses JWT auth (local dev only)
- Same graph, same orchestrator — just a different input/output interface

#### 9d. Operations Menu (`menu.sh`)

Interactive shell script for managing the service and client credentials.

```
═══════════════════════════════════════
  mgr4smb — Operations Menu
═══════════════════════════════════════
  1) Start server
  2) Stop server
  3) Restart server
  4) Server status
  5) Health check (GET /health)
  6) Create new client + JWT
  7) List clients
  8) Reissue JWT for existing client
  9) Revoke client (disable)
 10) Exit
═══════════════════════════════════════
```

**Option 1 — Start server:**
- Checks if already running (PID file at `.mgr4smb.pid`)
- Cleans up stale PID file when the recorded PID is not actually running
- Refuses to start if another process is already bound to the configured port,
  printing the occupying command + PID so you can decide to kill it or set
  `MGR4SMB_PORT` to a different port
- Activates `.venv` (checks for `.venv/bin/activate`, exits with error if missing)
- Loads `.env` and validates required vars are set
- Starts `uvicorn mgr4smb.api:app --host 0.0.0.0 --port 8000` in background
- Writes PID to `.mgr4smb.pid`
- Prints status confirmation

**Option 2 — Stop server:**
- Reads PID from `.mgr4smb.pid`
- Sends `SIGTERM` to the process
- Waits for graceful shutdown (up to 10s), then `SIGKILL` if needed
- Removes PID file

**Option 3 — Restart server:**
- Stop + Start (sequential)

**Option 4 — Server status:**
- Checks if PID file exists and process is alive
- Shows uptime, port, PID
- If our server isn't running but something else holds the port, reports the
  occupying process

**Option 5 — Health check (GET /health):**
- Calls `GET http://localhost:<PORT>/health` (unauthenticated)
- Pretty-prints the JSON response (`{ "status": ..., "checks": { "mongodb": ..., "llm": ... } }`)
- Reports `OK` (200), `DEGRADED` (503), or `UNEXPECTED` (other)
- Useful for verifying both the server AND its downstream dependencies
  (MongoDB checkpointer + Gemini) are reachable

**Option 6 — Create new client + JWT:**
1. Prompts for client name (e.g., "Aragrow LLC")
2. Generates a UUID v4 for `client_id` (via `python -c "import uuid; print(uuid.uuid4())"`)
3. Prompts for token expiration (default: 365 days)
4. Acquires a file lock on `clients.json` (prevents race conditions if two admins run simultaneously)
5. Adds client entry to `clients.json` with `enabled: true` and `created_at` timestamp
6. Releases file lock
7. Generates a signed JWT using `JWT_SECRET` from `.env`:
   ```
   python -c "
   import jwt, os, time, uuid
   from dotenv import load_dotenv
   load_dotenv()
   secret = os.environ['JWT_SECRET']
   client_id = '<generated-uuid>'
   token = jwt.encode({
       'client_id': client_id,
       'iat': int(time.time()),
       'exp': int(time.time()) + (365 * 86400)
   }, secret, algorithm='HS256')
   print(token)
   "
   ```
6. Prints the client_id (UUID) and the JWT token
7. Warns: "Save this token — it cannot be retrieved later"

**Option 7 — List clients:**
- Reads `clients.json` and prints a table: client_id (UUID), name, enabled, created_at

**Option 8 — Reissue JWT for existing client:**
- Lists enabled clients (client_id, name)
- Prompts for the client_id (UUID) to reissue
- Validates client exists and is enabled in `clients.json`
- Prompts for new token expiration (default: 365 days)
- Generates a new signed JWT with the same `client_id` but fresh `iat` and `exp`
- Prints the new token
- Note: the old token remains valid until it expires — if you need to invalidate it immediately, revoke the client (option 8) and re-enable + reissue

**Option 9 — Revoke client (disable):**
- Lists active clients
- Prompts for client_id to disable
- Sets `enabled: false` in `clients.json`
- Existing JWT tokens for that client_id will be rejected on next request

**Files:**
- `menu.sh` — the script itself (root of project)
- `.mgr4smb.pid` — PID file (add to `.gitignore`)

**Sanity check — `python -m mgr4smb.checks.phase9_api`:**

Test the API layer, auth, and menu.sh.

- [ ] `uvicorn mgr4smb.api:app` starts without error
- [ ] `GET /health` → 200 with `{"status": "ok", "checks": {"mongodb": "ok", "llm": "ok"}}`
- [ ] `GET /health` with MongoDB down → 503 with `{"status": "degraded", ...}`
- [ ] `POST /chat` with valid JWT → 200 + orchestrator response
- [ ] `POST /chat` with expired JWT → 401
- [ ] `POST /chat` with missing header → 401
- [ ] `POST /chat` with unknown client_id → 401
- [ ] `POST /chat` with disabled client → 401
- [ ] `POST /chat` with `session_id` → returns same `session_id`, conversation continues
- [ ] `POST /chat` without `session_id` → returns a new UUID session_id
- [ ] No endpoint exists for sub-agents (e.g., `POST /greeting` → 404)
- [ ] `menu.sh` option 1 (start) → server starts, PID file created
- [ ] `menu.sh` option 2 (stop) → server stops, PID file removed
- [ ] `menu.sh` option 3 (restart) → stop + start succeeds
- [ ] `menu.sh` option 5 (create client) → UUID generated, added to `clients.json`, JWT printed
- [ ] `menu.sh` option 7 (reissue) → new JWT works for existing client
- [ ] `menu.sh` option 8 (revoke) → client disabled, existing JWT rejected on next request
- [ ] LangSmith traces show full request lifecycle (auth → graph → response)

---

### Phase 10: Testing & Verification

**Goal:** Verify each component works end-to-end.

**Test scenarios:**
1. **Environment check** — All env vars loaded, LLM responds to a test prompt
2. **Auth tests:**
   - Valid JWT + known client_id → `200 OK`, orchestrator responds
   - Valid JWT + unknown client_id → `401 Unauthorized`
   - Valid JWT + disabled client → `401 Unauthorized`
   - Expired JWT → `401 Unauthorized`
   - Missing Authorization header → `401 Unauthorized`
   - Malformed token → `401 Unauthorized`
   - Direct access to sub-agent (not possible — no endpoint exists)
3. **Tool smoke tests** — Each tool callable independently (e.g., `ghl_contact_lookup("test@example.com")`)
4. **Agent isolation tests** — Each agent responds correctly with mock tool responses
5. **Full flow tests:**
   - New user: provides email+phone → greeted → asks general question → routed to general_info_agent → answer from knowledge base
   - GHL booking: provides email+phone → greeted by name → wants to book appointment → routed to booking_agent → sees GHL slots → **OTP verification via otp_agent** → books
   - Jobber booking: provides email+phone → greeted → wants to book a service/job → routed to booking_agent → collects service, schedule, property address, property type (house/apt → bedrooms+bathrooms, office → offices+bathrooms) → **OTP verification via otp_agent** → delegates to jobber_support_agent → creates client if new → creates property → creates job
   - GHL support flow: provides email+phone → greeted → wants to reschedule → routed to ghl_support_agent → **OTP verification via otp_agent** → sees appointments → reschedules
   - Jobber lookup flow: asks about a client's jobs → routed to jobber_support_agent → **OTP verification via otp_agent** → client lookup → job list
   - OTP persistence: user verified once → switches from ghl_support to booking_agent in same session → **no re-verification** (is_verified persists in state)

**How to test:**
```bash
# Use the operations menu
chmod +x menu.sh
./menu.sh
# → Option 5: Create new client + JWT (generates UUID client_id + token)
# → Option 1: Start server

# Test auth + chat via curl (use the token from menu option 5)
curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer <jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "session_id": null}'

# Local CLI (bypasses auth)
python main.py --cli

# Test individual tools
python -m mgr4smb.tools.ghl_contact_lookup

# Stop/restart
./menu.sh   # → Option 2 (stop) or Option 3 (restart)
```

---

## Sanity Check Strategy

Every phase has a gate check in `mgr4smb/checks/`. The rule is simple: **the gate must pass before you start the next phase.**

**How to run:**
```bash
# Run a specific phase gate
python -m mgr4smb.checks.phase1_env
python -m mgr4smb.checks.phase2_skeleton
# ... etc

# Run ALL gates up to phase N (cumulative — catches regressions)
python -m mgr4smb.checks.run_all --up-to 5
```

**What each gate does:**
1. Prints each check with `[PASS]` or `[FAIL]`
2. Exits with code 0 (all passed) or 1 (any failed)
3. Failed checks print the error details and what to fix
4. LangSmith checks verify traces appeared (from Phase 2 onward)

**Cumulative checks (`run_all`)** — when you complete Phase 5, run gates 1–5 together. This catches regressions (e.g., a Phase 4 change broke a Phase 2 assumption). Fast to run because earlier gates are lightweight.

**Gate summary:**

| Phase | Gate | What it verifies |
|-------|------|-----------------|
| 1 | `scripts/check_env.py` | Dependencies installed, `.env` complete, Python >= 3.10, LangSmith vars set |
| 2 | `phase2_skeleton` | Config loads, LLM responds, embeddings return 768-dim vector, logging works, exceptions import, no print() statements, LangSmith trace appears |
| 3 | `phase3_ghl` | `--dry-run`: imports, decorators, signatures, no SSRF. `--live`: all 7 GHL tools call API successfully |
| 4 | `phase4_jobber` | `--dry-run`: imports, decorators, signatures. `--live`: auth + token refresh + all tools return data |
| 5 | `phase5_mongodb` | MongoDB connects, vector index active, search returns results |
| 6 | `phase6_prompts` | All 7 SYSTEM_PROMPTs load from agents/, non-empty, mention correct tools, OTP logic in right place |
| 7 | `phase7_agents` | Each agent responds to a test message, calls correct tools, no tool leakage, otp_state_updater sets is_verified |
| 8 | `phase8_graph` | Full graph compiles, routing works, shared memory works, OTP gate works, contact_id caching works, session persistence works |
| 9 | `phase9_api` | Auth rejects invalid tokens, /chat returns responses, /health returns status, menu.sh operations work |

---

## Implementation Order Summary

| Phase | What | Gate | Depends On |
|-------|------|------|-----------|
| 1 | Environment setup (pyproject.toml, .env) | `scripts/check_env.py` | Nothing |
| 2 | Project skeleton, config, LLM factory, state | `phase2_skeleton` | Phase 1 |
| 3 | GHL tools (7 tools) | `phase3_ghl` | Phase 2 |
| 4 | Jobber tools (4 tools) | `phase4_jobber` | Phase 2 |
| 5 | MongoDB knowledge base tool | `phase5_mongodb` | Phase 2 |
| 6 | Agent prompts (7 prompts) | `phase6_prompts` | Nothing (text only) |
| 7 | Agent nodes (7 agents) | `phase7_agents` | Phases 3-6 |
| 8 | LangGraph orchestration graph | `phase8_graph` | Phase 7 |
| 9 | API layer (FastAPI + JWT auth + CLI + menu.sh) | `phase9_api` | Phase 8 |
| 10 | Full end-to-end testing | `run_all --up-to 9` | Phase 9 |

Phases 3, 4, 5, and 6 can be done **in parallel** since they are independent.

**After each phase:** run `python -m mgr4smb.checks.run_all --up-to N` to verify the current phase AND all previous phases still pass.

---

## Post-Build Refinements

The following changes were made after the initial 10-phase build, in response to live debugging and policy refinements. All are reflected in the directory structure, env vars, and behavior described above.

### Web chat UI (`chat-ui/`)
- Self-contained vanilla HTML/CSS/JS chat window served same-origin from FastAPI at `/chat-ui/`. No build step, no npm dependency.
- Visible "YOU" / "AGENT" sender labels with timestamps on every message; typing indicator shows "AGENT …" while the turn is in flight.
- JWT lives in `localStorage` when "remember" is checked; settings panel handles API base + token entry.

### LangSmith trace tagging
- `run_turn` now passes `run_name="Turn — <session-prefix>"`, `tags=["mgr4smb", "session:<uuid>", "client:<uuid8>"]`, and `metadata={"session_id": ..., "client_id": ...}` to `graph.invoke`.
- Conversations are searchable in the LangSmith UI by `tags has "session:<uuid>"`.

### LLM determinism
- `get_llm()` pins `temperature=0.2` to reduce Gemini's empty-output flakiness on agent tool-routing turns.
- `run_turn` snapshots the message count BEFORE invoking so empty turns no longer surface a stale older AI message.
- One automatic retry on empty output, with a short "please respond or take the appropriate next action" nudge.

### Booking agent — service handling
- Services come from the conversation history; the agent never presents services as a numbered menu.
- Multiple listed services become one combined appointment by default.
- Numbered lists are reserved exclusively for slot times. A bare `"4"` after a slot offer is treated as slot #4.

### GHL custom fields — write & read paths
- New `ghl_client.resolve_custom_field_id(key_or_id)` resolves human-readable field keys (e.g. `contact.otp_code`) to GHL field UUIDs via `GET /locations/{loc}/customFields`. Cached per process.
- New `ghl_client.fetch_contact(contact_id)` does `GET /contacts/{id}` for canonical fresh values. Use this for any field that was just written; `/contacts/search` returns a stale index.
- Both `ghl_send_otp` and `ghl_verify_otp` now PUT and read using field IDs (not keys). Without this, GHL silently accepted writes but persisted nothing.

### Phone normalization
- `_normalize_phone` returns the last 10 significant digits, so `'+19522281752'`, `'(952) 228-1752'`, `'9522281752'` all match. Genuinely different numbers still mismatch.

### OTP session policy (definitive)
- **Tool layer (`ghl_send_otp`)**: stateless. Every call generates a fresh code, computes a fresh expiry, and overwrites the GHL custom fields. No reuse logic.
- **Tool layer (`ghl_verify_otp`)**: keeps the stored code intact on wrong-code attempts (so retries hit the same code); clears it only on success or expiry. Reads via `fetch_contact` to bypass the search-index lag.
- **Prompt layer (`OTP_AGENT`)**: enforces "send once per session" by scanning the conversation history for a prior `OTP_SENT` before deciding to call `ghl_send_otp`. If a prior `OTP_SENT` exists, paraphrases the reminder; if the code expired mid-session, escalates rather than regenerating.
- **Prompt layer (`OTP_AGENT`)**: caps verify attempts at 2. On a 3rd wrong code (or any unrecoverable UNVERIFIED), produces an escalation reply that always starts with `"UNVERIFIED"` and includes the company contact info from `COMPANY_NAME` / `COMPANY_SUPPORT_EMAIL` / `COMPANY_SUPPORT_PHONE`.

### Operations menu (`menu.sh`)
- Added option **5 (Health check)** — calls `GET /health` and pretty-prints the JSON.
- `start_server` cleans stale PID files and refuses to start if another process holds the port.
- `status_server` reports occupants when our server isn't running but the port is bound.

### `run_turn` and graph improvements
- `run_turn(graph, message, session_id, client_id="")` is the single chat invocation helper.
- Tracks pre-turn message count for clean response extraction.
- Retries once on empty output before falling back to a graceful "I wasn't able to produce a response" message.
- Tags every invocation for LangSmith filtering.

### Replay script (`scripts/replay_session_22e348a2.py`)
- Walks the exact failing conversation (WordPress help → email → phone → service → timezone → slot offer → OTP) so the full flow can be tested with one command.
- `--stop-before-otp` is a non-interactive smoke gate; default mode pauses for slot pick and OTP code entry.
