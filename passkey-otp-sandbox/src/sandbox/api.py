"""FastAPI app for the sandbox.

Exposes the chat endpoint, a health probe, and the /ui mount. Identity
verification is handled entirely through the chat flow (greeter → OTP
via GHL). There is no browser-side or server-side passkey support.
"""

from __future__ import annotations

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
    SandboxError,
    TokenExpiredError,
)
from sandbox.graph import build_graph, run_turn
from sandbox.llm import get_llm
from sandbox.logging_config import setup_logging
from sandbox.memory import checkpointer_context

logger = logging.getLogger(__name__)


# --- Request / response models ---------------------------------------------


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


# --- Lifespan --------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level="INFO")
    logger.info("Starting otp-sandbox API")

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
    title="OTP Sandbox",
    version="0.2.0",
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


@app.exception_handler(SandboxError)
async def _sandbox(_, exc: SandboxError):
    logger.error("sandbox error", exc_info=True)
    return JSONResponse(status_code=500, content={"error": str(exc)})


# --- Endpoints -------------------------------------------------------------


@app.get("/health")
async def health():
    checks: dict[str, str] = {"llm": "unknown"}
    try:
        get_llm()
        checks["llm"] = "ok"
    except Exception as e:
        checks["llm"] = f"error: {e}"
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

    # Flip is_verified when the authenticator signals success so
    # subsequent sensitive actions in the SAME session don't re-prompt
    # for OTP. A fresh session_id always starts unverified.
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
