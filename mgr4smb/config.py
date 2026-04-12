"""Centralized settings loaded from .env — single source of truth for all config."""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from mgr4smb.exceptions import ConfigError

logger = logging.getLogger(__name__)

# Load .env from project root
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")


def _require(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise ConfigError(f"Missing required environment variable: {key}")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class _Settings:
    """Lazy-loaded settings container. Access via `from mgr4smb.config import settings`."""

    # --- LangSmith ---
    @property
    def langchain_tracing(self) -> bool:
        return _optional("LANGCHAIN_TRACING_V2", "false").lower() == "true"

    @property
    def langchain_api_key(self) -> str:
        return _optional("LANGCHAIN_API_KEY")

    @property
    def langchain_project(self) -> str:
        return _optional("LANGCHAIN_PROJECT", "mgr4smb")

    # --- Auth ---
    @property
    def jwt_secret(self) -> str:
        return _require("JWT_SECRET")

    @property
    def jwt_algorithm(self) -> str:
        return _optional("JWT_ALGORITHM", "HS256")

    @property
    def clients_file(self) -> Path:
        return _project_root / _optional("CLIENTS_FILE", "clients.json")

    # --- Google AI ---
    @property
    def google_api_key(self) -> str:
        return _require("GOOGLE_API_KEY")

    # --- GoHighLevel ---
    @property
    def ghl_api_key(self) -> str:
        return _require("GHL_API_KEY")

    @property
    def ghl_location_id(self) -> str:
        return _require("GHL_LOCATION_ID")

    @property
    def ghl_calendar_id(self) -> str:
        return _require("GHL_CALENDAR_ID")

    @property
    def ghl_org_timezone(self) -> str:
        return _optional("GHL_ORG_TIMEZONE", "America/Chicago")

    @property
    def ghl_slot_duration_minutes(self) -> int:
        return int(_optional("GHL_SLOT_DURATION_MINUTES", "30"))

    # --- MongoDB (knowledge base) ---
    @property
    def mongodb_atlas_uri(self) -> str:
        return _require("MONGODB_ATLAS_URI")

    @property
    def mongodb_db_name(self) -> str:
        return _optional("MONGODB_DB_NAME", "aragrow-llc")

    @property
    def mongodb_collection(self) -> str:
        return _optional("MONGODB_COLLECTION", "knowledge_base")

    @property
    def mongodb_index_name(self) -> str:
        return _optional("MONGODB_INDEX_NAME", "aragrow_vector_index")

    # --- MongoDB (shared memory / checkpointer) ---
    @property
    def mongodb_memory_db(self) -> str:
        return _optional("MONGODB_MEMORY_DB", "mgr4smb-memory")

    @property
    def mongodb_memory_collection(self) -> str:
        return _optional("MONGODB_MEMORY_COLLECTION", "checkpoints")

    # --- Jobber ---
    @property
    def jobber_client_id(self) -> str:
        return _require("JOBBER_CLIENT_ID")

    @property
    def jobber_client_secret(self) -> str:
        return _require("JOBBER_CLIENT_SECRET")

    @property
    def jobber_tokens_file(self) -> Path:
        return _project_root / _optional("JOBBER_TOKENS_FILE", ".tokens.json")


settings = _Settings()
