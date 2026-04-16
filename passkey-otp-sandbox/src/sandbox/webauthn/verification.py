"""Thin wrapper over `webauthn` for register/authenticate flows.

Each begin_* call issues a challenge, stores it in the challenge cache
keyed by a fresh challenge_id, and returns the serialisable options JSON.
Each finish_* call pops the challenge, verifies the browser's response
against it, and (on success) persists/rotates the credential in MongoDB
via sandbox.webauthn.storage.

The wrapper hides the WebAuthn library's parameter shape and lets the
rest of the sandbox speak in plain dicts.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, NamedTuple

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from sandbox.config import settings
from sandbox.exceptions import PasskeyError
from sandbox.webauthn import challenges, storage

logger = logging.getLogger(__name__)


def _user_verification_enum() -> UserVerificationRequirement:
    mapping = {
        "required": UserVerificationRequirement.REQUIRED,
        "preferred": UserVerificationRequirement.PREFERRED,
        "discouraged": UserVerificationRequirement.DISCOURAGED,
    }
    return mapping.get(settings.user_verification.lower(), UserVerificationRequirement.PREFERRED)


def _b64url_decode(s: str) -> bytes:
    """Decode a base64url string (with or without padding)."""
    s = s.strip()
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


class BeginResult(NamedTuple):
    options_json: str          # ready to hand to the browser
    challenge_id: str          # opaque id the browser echoes back on finish


# --- Registration -----------------------------------------------------------


def begin_registration(user_email: str) -> BeginResult:
    existing = storage.list_by_email(user_email)
    exclude = [
        PublicKeyCredentialDescriptor(
            id=_b64url_decode(row["credential_id"]),
            transports=[AuthenticatorTransport(t) for t in (row.get("transports") or "").split(",") if t]
            or None,
        )
        for row in existing
    ]

    opts = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_name=user_email,
        user_display_name=user_email,
        exclude_credentials=exclude or None,
    )
    challenge_id = challenges.put(opts.challenge, user_email, "register")
    return BeginResult(options_json=options_to_json(opts), challenge_id=challenge_id)


def finish_registration(challenge_id: str, credential: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    try:
        entry = challenges.pop(challenge_id, "register")
    except (KeyError, TimeoutError, ValueError) as e:
        raise PasskeyError(f"invalid challenge: {e}") from e

    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=entry.challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.rp_origin,
            require_user_verification=(settings.user_verification.lower() == "required"),
        )
    except Exception as e:
        raise PasskeyError(f"registration verification failed: {e}") from e

    cred_id_b64 = _b64url_encode(verified.credential_id)
    transports_csv = ",".join(
        credential.get("response", {}).get("transports", []) or []
    )
    storage.register(
        email=entry.user_email,
        credential_id=cred_id_b64,
        public_key=verified.credential_public_key,
        sign_counter=verified.sign_count,
        transports=transports_csv or None,
        aaguid=str(verified.aaguid) if verified.aaguid else None,
        label=label,
    )
    logger.info(
        "passkey registered",
        extra={"user_email": entry.user_email, "credential_id": cred_id_b64[:10] + "..."},
    )
    return {"credential_id": cred_id_b64, "user_email": entry.user_email}


# --- Authentication ---------------------------------------------------------


def begin_authentication(user_email: str) -> BeginResult:
    rows = storage.list_by_email(user_email)
    if not rows:
        raise PasskeyError("no passkey registered for this user")

    allow = [
        PublicKeyCredentialDescriptor(
            id=_b64url_decode(row["credential_id"]),
            transports=[AuthenticatorTransport(t) for t in (row.get("transports") or "").split(",") if t]
            or None,
        )
        for row in rows
    ]

    opts = generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=allow,
        user_verification=_user_verification_enum(),
    )
    challenge_id = challenges.put(opts.challenge, user_email, "authenticate")
    return BeginResult(options_json=options_to_json(opts), challenge_id=challenge_id)


def finish_authentication(challenge_id: str, credential: dict[str, Any]) -> dict[str, Any]:
    try:
        entry = challenges.pop(challenge_id, "authenticate")
    except (KeyError, TimeoutError, ValueError) as e:
        raise PasskeyError(f"invalid challenge: {e}") from e

    raw_id = credential.get("id") or credential.get("rawId")
    if not raw_id:
        raise PasskeyError("credential missing id/rawId")
    cred_id_b64 = raw_id if isinstance(raw_id, str) else _b64url_encode(raw_id)

    row = storage.find(entry.user_email, cred_id_b64)
    if row is None:
        raise PasskeyError("unknown credential for this user")

    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=entry.challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.rp_origin,
            credential_public_key=row["public_key"],
            credential_current_sign_count=int(row["sign_counter"]),
            require_user_verification=(settings.user_verification.lower() == "required"),
        )
    except Exception as e:
        raise PasskeyError(f"authentication verification failed: {e}") from e

    if verified.new_sign_count <= int(row["sign_counter"]) and verified.new_sign_count != 0:
        raise PasskeyError("sign counter did not increase — possible replay")

    storage.bump_counter(entry.user_email, cred_id_b64, verified.new_sign_count)
    logger.info(
        "passkey authenticated",
        extra={"user_email": entry.user_email, "credential_id": cred_id_b64[:10] + "..."},
    )
    return {"credential_id": cred_id_b64, "user_email": entry.user_email}
