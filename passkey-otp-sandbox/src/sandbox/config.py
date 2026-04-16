"""Sandbox settings singleton — loaded from .env, lazily accessed.

Access via `from sandbox.config import settings`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from sandbox.exceptions import ConfigError

logger = logging.getLogger(__name__)

_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env")

PROJECT_ROOT = _project_root


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ConfigError(f"Missing required environment variable: {key}")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class _Settings:
    # --- LangSmith ----------------------------------------------------------
    @property
    def langchain_tracing(self) -> bool:
        return _optional("LANGCHAIN_TRACING_V2", "false").lower() == "true"

    @property
    def langchain_api_key(self) -> str:
        return _optional("LANGCHAIN_API_KEY")

    @property
    def langchain_project(self) -> str:
        return _optional("LANGCHAIN_PROJECT", "passkey-otp-sandbox")

    # --- Auth ---------------------------------------------------------------
    @property
    def jwt_secret(self) -> str:
        return _require("JWT_SECRET")

    @property
    def jwt_algorithm(self) -> str:
        return _optional("JWT_ALGORITHM", "HS256")

    @property
    def dev_client_id(self) -> str:
        return _optional("DEV_CLIENT_ID", "dev-local")

    @property
    def dev_client_name(self) -> str:
        return _optional("DEV_CLIENT_NAME", "Sandbox Dev")

    # --- Google Gemini ------------------------------------------------------
    @property
    def google_api_key(self) -> str:
        return _require("GOOGLE_API_KEY")

    # --- Embeddings ---------------------------------------------------------
    @property
    def embedding_model(self) -> str:
        return _optional("EMBEDDING_MODEL", "models/gemini-embedding-001")

    @property
    def embedding_dimensions(self) -> int:
        return int(_optional("EMBEDDING_DIMENSIONS", "768"))

    @property
    def embedding_task_type(self) -> str:
        return _optional("EMBEDDING_TASK_TYPE", "RETRIEVAL_QUERY")

    # --- MongoDB (optional) -------------------------------------------------
    # When mongodb_atlas_uri is blank, the knowledge_base tool uses a
    # local JSON file and the checkpointer is LangGraph's InMemorySaver.
    # When it's set, both switch to MongoDB Atlas transparently.
    @property
    def mongodb_atlas_uri(self) -> str:
        return _optional("MONGODB_ATLAS_URI", "")

    @property
    def use_mongodb(self) -> bool:
        return bool(self.mongodb_atlas_uri)

    # Env var names intentionally mirror the production mgr4smb project
    # so the sandbox and production use identical .env schemas.
    @property
    def mongodb_db_name(self) -> str:
        return _optional("MONGODB_DB_NAME", "sandbox")

    @property
    def mongodb_kb_collection(self) -> str:
        return _optional("MONGODB_COLLECTION", "knowledge_base")

    @property
    def mongodb_kb_index_name(self) -> str:
        return _optional("MONGODB_INDEX_NAME", "kb_vector_index")

    @property
    def mongodb_memory_db(self) -> str:
        # Separate DB for session state by default (matches production
        # pattern of isolating checkpoints from the knowledge base).
        # Falls back to mongodb_db_name when not set.
        return _optional("MONGODB_MEMORY_DB", "") or self.mongodb_db_name

    @property
    def mongodb_checkpoint_collection(self) -> str:
        return _optional("MONGODB_MEMORY_COLLECTION", "checkpoints")

    @property
    def mongodb_passkey_db(self) -> str:
        return _optional("MONGODB_PASSKEY_DB", "") or self.mongodb_db_name

    @property
    def mongodb_passkey_collection(self) -> str:
        return _optional("MONGODB_PASSKEY_COLLECTION", "passkeys")

    # --- Passkey / WebAuthn -------------------------------------------------
    @property
    def rp_id(self) -> str:
        return _optional("PASSKEY_RP_ID", "localhost")

    @property
    def rp_name(self) -> str:
        return _optional("PASSKEY_RP_NAME", "Passkey Sandbox")

    @property
    def rp_origin(self) -> str:
        # Full origin URL for WebAuthn (must match `window.location.origin`).
        return _optional("PASSKEY_RP_ORIGIN", "http://localhost:8000")

    @property
    def user_verification(self) -> str:
        return _optional("PASSKEY_USER_VERIFICATION", "preferred")

    @property
    def challenge_ttl_seconds(self) -> int:
        return int(_optional("PASSKEY_CHALLENGE_TTL_SECONDS", "60"))

    # --- OTP ----------------------------------------------------------------
    @property
    def otp_lifetime_minutes(self) -> int:
        return int(_optional("OTP_LIFETIME_MINUTES", "5"))

    # --- GoHighLevel --------------------------------------------------------
    # The sandbox uses the same GHL tenant + custom fields as production
    # mgr4smb. OTP send/verify and the greeter's contact lookup all hit
    # this single location.
    @property
    def ghl_api_key(self) -> str:
        return _require("GHL_API_KEY")

    @property
    def ghl_location_id(self) -> str:
        return _require("GHL_LOCATION_ID")

    @property
    def ghl_otp_code_field_key(self) -> str:
        return _optional("GHL_OTP_CODE_FIELD_KEY", "contact.otp_code")

    @property
    def ghl_otp_expiry_field_key(self) -> str:
        return _optional("GHL_OTP_EXPIRY_FIELD_KEY", "contact.otp_expires_at")

    @property
    def ghl_otp_lifetime_minutes(self) -> int:
        return int(_optional("GHL_OTP_LIFETIME_MINUTES", "15"))

    @property
    def ghl_configured(self) -> bool:
        """True when both API key and location id are set — used by smoke
        to skip GHL phases gracefully when the sandbox is air-gapped."""
        import os
        return bool(
            os.environ.get("GHL_API_KEY", "").strip()
            and os.environ.get("GHL_LOCATION_ID", "").strip()
        )

    # --- Company contact (escalation text) ----------------------------------
    @property
    def company_name(self) -> str:
        return _optional("COMPANY_NAME", "Sandbox")

    @property
    def company_support_email(self) -> str:
        return _optional("COMPANY_SUPPORT_EMAIL", "")

    @property
    def company_support_phone(self) -> str:
        return _optional("COMPANY_SUPPORT_PHONE", "")

    # --- Server -------------------------------------------------------------
    @property
    def host(self) -> str:
        return _optional("HOST", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(_optional("PORT", "8000"))


settings = _Settings()
