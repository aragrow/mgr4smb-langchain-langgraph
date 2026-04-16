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

    # --- GHL custom fields used by the reschedule flow ---------------------
    # The vendor_notifier_agent writes to these two fields on the caller's
    # contact. A GHL workflow, triggered on change to
    # `ghl_reschedule_requested_at_field_key`, picks up the payload and
    # emails it to the vendor (same pattern as the OTP workflow).
    @property
    def ghl_reschedule_request_field_key(self) -> str:
        return _optional("GHL_RESCHEDULE_REQUEST_FIELD_KEY", "contact.reschedule_request")

    @property
    def ghl_reschedule_requested_at_field_key(self) -> str:
        return _optional("GHL_RESCHEDULE_REQUESTED_AT_FIELD_KEY", "contact.reschedule_requested_at")

    # --- Vendor display name ------------------------------------------------
    # The "vendor" in this project is the Jobber team member who performs
    # the service; they're notified through the GHL workflow pipeline
    # (same pattern as OTP). The actual recipient email is set inside the
    # GHL workflow itself, not here. This property only surfaces a
    # human-readable label ("the scheduling team") for user-facing copy.
    @property
    def vendor_name(self) -> str:
        return _optional("VENDOR_NAME", "the scheduling team")

    # --- GHL custom fields used by the client notification flow ----------
    # Mirror of the reschedule pair, but aimed at the CLIENT (the caller)
    # rather than the vendor. The client_notifier_agent writes the
    # payload to `ghl_client_notification_field_key` on the caller's
    # contact and bumps `ghl_client_notification_at_field_key` — a
    # second GHL workflow, triggered on change to the timestamp field,
    # emails the caller. Keeping it separate from the OTP + reschedule
    # pairs means three independent workflows, one per outbound channel.
    @property
    def ghl_client_notification_field_key(self) -> str:
        return _optional(
            "GHL_CLIENT_NOTIFICATION_FIELD_KEY",
            "contact.client_notification",
        )

    @property
    def ghl_client_notification_at_field_key(self) -> str:
        return _optional(
            "GHL_CLIENT_NOTIFICATION_AT_FIELD_KEY",
            "contact.client_notification_at",
        )

    @property
    def ghl_configured(self) -> bool:
        """True when both API key and location id are set — used by smoke
        to skip GHL phases gracefully when the sandbox is air-gapped."""
        import os
        return bool(
            os.environ.get("GHL_API_KEY", "").strip()
            and os.environ.get("GHL_LOCATION_ID", "").strip()
        )

    # --- Jobber (OAuth2 + GraphQL) -----------------------------------------
    # The sandbox shares mgr4smb's OAuth tokens by default — JOBBER_TOKENS_FILE
    # points at the parent project's `.tokens.json` so both processes use the
    # same refresh-token lifecycle (Jobber only allows one active refresh
    # token at a time per app, so having two files would rotate each other out).
    @property
    def jobber_address_id_field_key(self) -> str:
        """Custom-field key on the Jobber Property entity that stores the
        human-readable Address ID the caller knows. Used by the
        reschedule flow to match the caller's input to their property.
        The key is a dotted path understood by jobber_client's custom
        field lookup (e.g. `property.address_id`).
        """
        return _optional("JOBBER_ADDRESS_ID_FIELD_KEY", "property.address_id")

    @property
    def jobber_client_id(self) -> str:
        return _require("JOBBER_CLIENT_ID")

    @property
    def jobber_client_secret(self) -> str:
        return _require("JOBBER_CLIENT_SECRET")

    @property
    def jobber_tokens_file(self) -> Path:
        default = (_project_root.parent / ".tokens.json").resolve()
        override = _optional("JOBBER_TOKENS_FILE", "")
        if override:
            return Path(override).expanduser().resolve()
        return default

    @property
    def jobber_configured(self) -> bool:
        """True when client id + secret are present AND the tokens file
        exists. Used by smoke to skip Jobber phases cleanly when the
        sandbox hasn't been bootstrapped against a Jobber app yet.
        """
        import os
        if not (
            os.environ.get("JOBBER_CLIENT_ID", "").strip()
            and os.environ.get("JOBBER_CLIENT_SECRET", "").strip()
        ):
            return False
        return self.jobber_tokens_file.exists()

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
