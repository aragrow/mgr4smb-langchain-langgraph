"""FastAPI app — single public endpoint for chat + unauthenticated /health.

The only public-facing entry point is POST /chat. All sub-agents are internal
graph nodes and have NO API routes. GET /health is unauthenticated for load
balancers / monitoring / menu.sh status checks.

The compiled graph + checkpointer live in app.state for the lifetime of the
process, created on startup and disposed on shutdown.
"""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mgr4smb.auth import verify_token
from mgr4smb.exceptions import (
    AuthError,
    ExternalAPIError,
    InvalidClientError,
    Mgr4smbError,
    MongoDBError,
    TokenExpiredError,
)
from mgr4smb.graph import build_graph, run_turn
from mgr4smb.llm import get_llm
from mgr4smb.logging_config import setup_logging
from mgr4smb.memory import _get_mongo_client, checkpointer_context

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Request / response models
# --------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str


# --------------------------------------------------------------------------
# Lifespan — build the graph once per process
# --------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Construct the graph + checkpointer on startup; clean up on shutdown."""
    setup_logging(level="INFO")
    logger.info("Starting mgr4smb API")

    # Enter the checkpointer context for the app's full lifetime.
    cp_ctx = checkpointer_context()
    checkpointer = cp_ctx.__enter__()
    try:
        graph = build_graph(checkpointer)
        app.state.graph = graph
        app.state.checkpointer = checkpointer
        logger.info("Graph compiled — mgr4smb API ready")
        yield
    finally:
        cp_ctx.__exit__(None, None, None)
        logger.info("mgr4smb API shut down")


app = FastAPI(
    title="mgr4smb Orchestrator",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,   # Disable Swagger UI (private deployment)
    redoc_url=None,  # Disable ReDoc
    openapi_url=None,
)


# --------------------------------------------------------------------------
# Auth dependency
# --------------------------------------------------------------------------

def require_client(authorization: str | None = Header(default=None)) -> str:
    """Verify the bearer token and return the authenticated client_id."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing or malformed Authorization header")
    token = authorization.split(None, 1)[1].strip()
    return verify_token(token)


# --------------------------------------------------------------------------
# Exception handlers — map custom exceptions to HTTP status codes
# --------------------------------------------------------------------------

@app.exception_handler(TokenExpiredError)
async def _token_expired_handler(request: Request, exc: TokenExpiredError):
    return JSONResponse(status_code=401, content={"error": "Token expired"})


@app.exception_handler(InvalidClientError)
async def _invalid_client_handler(request: Request, exc: InvalidClientError):
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


@app.exception_handler(AuthError)
async def _auth_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=401, content={"error": "Unauthorized"})


@app.exception_handler(ExternalAPIError)
async def _external_handler(request: Request, exc: ExternalAPIError):
    logger.error(
        "External API failure",
        extra={"service": exc.service, "status": exc.status_code},
    )
    return JSONResponse(
        status_code=502,
        content={"error": f"{exc.service} service unavailable"},
    )


@app.exception_handler(MongoDBError)
async def _mongo_handler(request: Request, exc: MongoDBError):
    logger.error("MongoDB error", extra={"error": str(exc)})
    return JSONResponse(status_code=502, content={"error": "Storage unavailable"})


@app.exception_handler(Mgr4smbError)
async def _generic_handler(request: Request, exc: Mgr4smbError):
    logger.error("mgr4smb error", extra={"error": str(exc)}, exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal error"})


@app.exception_handler(Exception)
async def _catch_all_handler(request: Request, exc: Exception):
    logger.critical("Unhandled exception", exc_info=True)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Unauthenticated health check. Returns 200 if all subsystems are up."""
    checks = {"mongodb": "unknown", "llm": "unknown"}

    # MongoDB ping
    try:
        _get_mongo_client().admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = f"error: {e}"

    # LLM ping — cheap no-op invoke
    try:
        llm = get_llm()
        # A minimal, short prompt — just verify the client is functional.
        _ = llm.invoke("ok")
        checks["llm"] = "ok"
    except Exception as e:
        checks["llm"] = f"error: {e}"

    overall_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if overall_ok else 503
    body = {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }
    return JSONResponse(status_code=status_code, content=body)


@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    request: Request,
    client_id: str = Depends(require_client),
):
    """Main chat endpoint — invokes the orchestrator graph for one turn."""
    session_id = (req.session_id or "").strip() or str(uuid.uuid4())

    logger.info(
        "Chat request",
        extra={
            "client_id": client_id[:8] + "...",
            "session_id": session_id,
            "message_chars": len(req.message),
        },
    )

    response = run_turn(
        request.app.state.graph,
        message=req.message,
        session_id=session_id,
        client_id=client_id,
    )

    return ChatResponse(response=response, session_id=session_id)
