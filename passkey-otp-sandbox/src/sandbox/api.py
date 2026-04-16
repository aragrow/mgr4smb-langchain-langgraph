"""FastAPI app for the sandbox.

Exposes the chat endpoint, a health probe, and the 6 passkey endpoints
(register/verify begin+finish, list, delete). The chat UI is served
from /ui (the index.html at the sandbox root).
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from sandbox.auth import verify_token
from sandbox.config import PROJECT_ROOT
from sandbox.exceptions import (
    AuthError,
    InvalidClientError,
    PasskeyError,
    SandboxError,
    TokenExpiredError,
)
from sandbox.graph import build_graph, run_turn
from sandbox.llm import get_llm
from sandbox.logging_config import setup_logging
from sandbox.memory import checkpointer_context
from sandbox.webauthn import storage, verification

logger = logging.getLogger(__name__)


# --- Request / response models ---------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


class PasskeyBeginRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_email: str = Field(..., min_length=3)


class PasskeyFinishRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    challenge_id: str = Field(..., min_length=1)
    credential: dict


# --- Lifespan --------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level="INFO")
    logger.info("Starting passkey-otp-sandbox API")
    storage.init_db()

    # Enter the checkpointer context for the app's full lifetime — this
    # is a MongoDBSaver when MONGODB_ATLAS_URI is set, else InMemorySaver.
    cp_ctx = checkpointer_context()
    checkpointer = cp_ctx.__enter__()
    try:
        app.state.graph = build_graph(checkpointer)
        app.state.checkpointer = checkpointer
        logger.info("Graph compiled — sandbox ready")
        yield
    finally:
        cp_ctx.__exit__(None, None, None)
        logger.info("Sandbox shut down")


app = FastAPI(
    title="Passkey OTP Sandbox",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# --- Auth dependency -------------------------------------------------------


def require_client(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing or malformed Authorization header")
    token = authorization.split(None, 1)[1].strip()
    return verify_token(token)


# --- Exception handlers ----------------------------------------------------


@app.exception_handler(TokenExpiredError)
async def _token_expired(_, __):
    return JSONResponse(status_code=401, content={"error": "Token expired"})


@app.exception_handler(InvalidClientError)
async def _invalid_client(_, __):
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


@app.exception_handler(AuthError)
async def _auth(_, __):
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


@app.exception_handler(PasskeyError)
async def _passkey(_, exc: PasskeyError):
    logger.warning("passkey error: %s", exc)
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(SandboxError)
async def _sandbox(_, exc: SandboxError):
    logger.error("sandbox error", exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})


# --- Endpoints -------------------------------------------------------------


@app.get("/health")
async def health():
    checks: dict[str, str] = {"llm": "unknown", "passkey_store": "unknown"}
    try:
        get_llm()
        checks["llm"] = "ok"
    except Exception as e:
        checks["llm"] = f"error: {e}"
    try:
        storage.init_db()
        checks["passkey_store"] = "ok"
    except Exception as e:
        checks["passkey_store"] = f"error: {e}"
    overall_ok = all(v == "ok" for v in checks.values())
    body = {"status": "ok" if overall_ok else "degraded", "checks": checks}
    return JSONResponse(status_code=200 if overall_ok else 503, content=body)


@app.get("/ui")
async def ui():
    path = PROJECT_ROOT / "index.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(str(path), media_type="text/html")


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    client_id: str = Depends(require_client),
):
    session_id = (req.session_id or "").strip() or str(uuid.uuid4())
    logger.info(
        "chat request",
        extra={"client": client_id[:8], "session": session_id,
               "chars": len(req.message)},
    )
    graph = request.app.state.graph
    response = run_turn(graph, req.message, session_id)

    # If the authenticator (via the orchestrator) signalled success, flip
    # is_verified on the session state. This is what lets the UI's
    # register-passkey banner actually succeed at POST
    # /passkey/register/begin — that endpoint 403s unless the session is
    # already verified. Separately, a passkey verification flips the
    # flag directly inside /passkey/verify/finish.
    if response.lstrip().upper().startswith("VERIFIED"):
        try:
            graph.update_state(
                {"configurable": {"thread_id": session_id}},
                values={"is_verified": True},
            )
            logger.info("session flipped to verified via OTP",
                        extra={"session": session_id})
        except Exception as e:
            logger.warning("could not update state after VERIFIED: %s", e)

    return ChatResponse(response=response, session_id=session_id)


# --- Passkey: registration ---


def _session_is_verified(graph, session_id: str) -> bool:
    config = {"configurable": {"thread_id": session_id}}
    state = graph.get_state(config)
    if state is None or not state.values:
        return False
    return bool(state.values.get("is_verified"))


@app.post("/passkey/register/begin")
async def passkey_register_begin(
    req: PasskeyBeginRequest,
    request: Request,
    client_id: str = Depends(require_client),
):
    if not _session_is_verified(request.app.state.graph, req.session_id):
        raise HTTPException(
            status_code=403,
            detail="Session must be OTP-verified before registering a passkey.",
        )
    result = verification.begin_registration(req.user_email)
    return {"options": json.loads(result.options_json), "challenge_id": result.challenge_id}


@app.post("/passkey/register/finish")
async def passkey_register_finish(
    req: PasskeyFinishRequest,
    request: Request,
    client_id: str = Depends(require_client),
):
    if not _session_is_verified(request.app.state.graph, req.session_id):
        raise HTTPException(status_code=403, detail="Session must be OTP-verified.")
    info = verification.finish_registration(req.challenge_id, req.credential)
    return {"status": "ok", **info}


# --- Passkey: authentication ---


@app.post("/passkey/verify/begin")
async def passkey_verify_begin(
    req: PasskeyBeginRequest,
    client_id: str = Depends(require_client),
):
    result = verification.begin_authentication(req.user_email)
    return {"options": json.loads(result.options_json), "challenge_id": result.challenge_id}


@app.post("/passkey/verify/finish")
async def passkey_verify_finish(
    req: PasskeyFinishRequest,
    request: Request,
    client_id: str = Depends(require_client),
):
    info = verification.finish_authentication(req.challenge_id, req.credential)
    # Flip session state so subsequent /chat turns see is_verified=True.
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": req.session_id}}
    try:
        graph.update_state(
            config,
            values={"is_verified": True, "is_passkey_verified": True},
        )
    except Exception as e:
        logger.warning("could not update session state after passkey verify: %s", e)
    return {"status": "ok", **info}


# --- Passkey: management ---


@app.get("/passkey/list")
async def passkey_list(user_email: str, client_id: str = Depends(require_client)):
    rows = storage.list_by_email(user_email)
    # Strip the public_key bytes and return only metadata.
    return {
        "user_email": user_email,
        "credentials": [
            {
                "credential_id": r["credential_id"],
                "label": r.get("label"),
                "created_at": r["created_at"],
                "last_used_at": r.get("last_used_at"),
                "sign_counter": r["sign_counter"],
                "transports": r.get("transports"),
            }
            for r in rows
        ],
    }


@app.delete("/passkey/{credential_id}")
async def passkey_delete(
    credential_id: str,
    user_email: str,
    client_id: str = Depends(require_client),
):
    removed = storage.remove(user_email, credential_id)
    if removed == 0:
        raise HTTPException(status_code=404, detail="credential not found for user")
    return {"status": "ok", "removed": removed}
