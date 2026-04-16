"""Sandbox smoke tests — gated per phase.

Usage:
    python -m sandbox.checks.smoke               # run all phases
    python -m sandbox.checks.smoke --phase 3     # only phase 3

Each phase function returns a list of (check_name, ok, detail) tuples.
A phase "passes" when every entry's ok is True.

Phase 7 is a server-up check (requires run.sh start to have been invoked).
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import Callable

Result = tuple[str, bool, str]

# ---------------------------------------------------------------------------
# Phase 1 — bootstrap
# ---------------------------------------------------------------------------


def phase_1() -> list[Result]:
    """Third-party deps import cleanly."""
    results: list[Result] = []
    try:
        import langgraph  # noqa: F401
        import fastapi  # noqa: F401
        import webauthn  # noqa: F401

        results.append(("imports", True, "langgraph, fastapi, webauthn"))
    except Exception as e:
        results.append(("imports", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 2 — settings, LLM, logging, passkey store (MongoDB)
# ---------------------------------------------------------------------------


def phase_2() -> list[Result]:
    results: list[Result] = []

    # Settings
    try:
        from sandbox.config import settings

        _ = settings.jwt_secret  # raises ConfigError if missing
        _ = settings.google_api_key
        results.append(("settings load", True, f"rp_id={settings.rp_id}"))
    except Exception as e:
        results.append(("settings load", False, f"{type(e).__name__}: {e}"))
        return results  # bail — nothing else will work

    # LLM
    try:
        from sandbox.llm import get_llm

        resp = get_llm().invoke("hi")
        text = getattr(resp, "content", "") or ""
        results.append(("llm invoke", bool(text), f"chars={len(text) if isinstance(text, str) else '?'}"))
    except Exception as e:
        results.append(("llm invoke", False, f"{type(e).__name__}: {e}"))

    # Passkey store (MongoDB) — requires MONGODB_ATLAS_URI.
    try:
        from sandbox.webauthn import storage

        if not settings.use_mongodb:
            results.append((
                "passkey store round-trip",
                False,
                "MONGODB_ATLAS_URI not set — passkey storage requires MongoDB.",
            ))
        else:
            storage.init_db()
            storage.register(
                email="smoke@example.com",
                credential_id="smoke-cred",
                public_key=b"\x01\x02\x03",
                sign_counter=0,
                transports="internal",
                aaguid="00000000-0000-0000-0000-000000000000",
                label="smoke",
            )
            rows = storage.list_by_email("smoke@example.com")
            ok = any(r["credential_id"] == "smoke-cred" for r in rows)
            storage.remove("smoke@example.com", "smoke-cred")
            results.append(("passkey store round-trip", ok, f"rows={len(rows)}"))
    except Exception as e:
        results.append(("passkey store round-trip", False, f"{type(e).__name__}: {e}"))

    return results


# ---------------------------------------------------------------------------
# Phase 3 — OTP tools
# ---------------------------------------------------------------------------


def phase_3() -> list[Result]:
    """GHL integration checks — skipped when GHL_API_KEY/LOCATION_ID are blank.

    We explicitly do NOT trigger a real OTP email (that would send mail
    to whoever is in the contact list on every smoke run). Instead we
    verify:
      1. GHL cluster is reachable (custom-fields endpoint responds).
      2. Both OTP custom fields exist in the location.
      3. ghl_contact_lookup returns a graceful "no contact" for a
         known-bogus email (proves the HTTP path works end-to-end).
      4. ghl_contact_lookup finds a known existing contact
         (davidarago99@gmail.com) — proves the location id, API key,
         and search endpoint are all correctly wired.
    To actually send + verify an OTP, use the chat UI with your real
    contact record in GHL.
    """
    results: list[Result] = []
    try:
        from sandbox.config import settings

        if not settings.ghl_configured:
            results.append((
                "phase 3 (GHL)",
                True,
                "SKIPPED — GHL_API_KEY / GHL_LOCATION_ID not set.",
            ))
            return results

        from sandbox.tools import ghl_client
        from sandbox.tools.ghl_contact_lookup import ghl_contact_lookup

        # 1. GHL reachable — hit the custom-fields endpoint directly. A
        #    200 proves the base URL + bearer token + location id all work.
        try:
            client = ghl_client.get_client()
            resp = client.get(
                f"/locations/{settings.ghl_location_id}/customFields"
            )
            ok = resp.status_code == 200
            results.append((
                "GHL connect",
                ok,
                f"GET /locations/{settings.ghl_location_id[:8]}.../customFields → {resp.status_code}",
            ))
            if not ok:
                return results  # bail — everything below needs a working client
        except Exception as e:
            results.append(("GHL connect", False, f"{type(e).__name__}: {e}"))
            return results

        # 2. OTP custom fields exist in the location.
        try:
            code_id = ghl_client.resolve_custom_field_id(
                settings.ghl_otp_code_field_key
            )
            expiry_id = ghl_client.resolve_custom_field_id(
                settings.ghl_otp_expiry_field_key
            )
            fields_ok = bool(code_id) and bool(expiry_id)
            results.append((
                "GHL OTP custom fields resolve",
                fields_ok,
                f"code={code_id[:8]}... expiry={expiry_id[:8]}..." if fields_ok else "missing",
            ))
        except Exception as e:
            results.append((
                "GHL OTP custom fields resolve",
                False,
                f"{type(e).__name__}: {e}",
            ))

        # 3. Bogus email → graceful not-found.
        bogus = "nobody-smoke-test-12345@example.com"
        r_bogus = ghl_contact_lookup.invoke({"search_value": bogus})
        results.append((
            "ghl_contact_lookup handles missing contact",
            "No contact found" in r_bogus,
            r_bogus[:80],
        ))

        # 4. Known contact → Contact found.
        known = "davidarago99@gmail.com"
        r_known = ghl_contact_lookup.invoke({"search_value": known})
        results.append((
            f"ghl_contact_lookup finds {known}",
            r_known.startswith("Contact found"),
            r_known[:100],
        ))

    except Exception as e:
        traceback.print_exc()
        results.append(("phase_3", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 4 — passkey infra
# ---------------------------------------------------------------------------


def phase_4() -> list[Result]:
    results: list[Result] = []
    try:
        from sandbox.tools.passkey_status import passkey_status
        from sandbox.tools.passkey_request_verification import passkey_request_verification
        from sandbox.webauthn import storage, verification

        email = "pk-smoke@example.com"
        # Ensure clean slate
        for row in storage.list_by_email(email):
            storage.remove(email, row["credential_id"])

        status_none = passkey_status.invoke({"user_email": email})
        results.append(("status NONE", status_none == "NONE", status_none))

        # begin_registration returns a serialisable options payload
        options, challenge_id = verification.begin_registration(email)
        payload = getattr(options, "__dict__", None) or options
        results.append(
            (
                "begin_registration returns options",
                bool(payload) and bool(challenge_id),
                f"challenge_id={str(challenge_id)[:8]}...",
            )
        )

        # Pre-seed a passkey row and re-check status
        storage.register(
            email=email,
            credential_id="fake-cred-id",
            public_key=b"\x00" * 32,
            sign_counter=0,
            transports="internal",
            aaguid="",
            label="smoke",
        )
        status_reg = passkey_status.invoke({"user_email": email})
        results.append(("status REGISTERED after seed", status_reg == "REGISTERED", status_reg))

        storage.remove(email, "fake-cred-id")

        # passkey_request_verification literal
        req = passkey_request_verification.invoke({"user_email": email})
        results.append(("request_verification literal", req == "PASSKEY_REQUESTED", req))
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_4", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 5 — agents + graph
# ---------------------------------------------------------------------------


def phase_5() -> list[Result]:
    results: list[Result] = []
    try:
        from sandbox.agents import authenticator as auth_mod
        from sandbox.agents import general_info as ginfo_mod
        from sandbox.agents import greeting as greet_mod
        from sandbox.agents import orchestrator as orch_mod
        from sandbox.config import settings

        auth_agent = auth_mod.build()
        ginfo_agent = ginfo_mod.build()
        greet_agent = greet_mod.build()
        orch_mod.build(
            greeter_agent=greet_agent,
            general_info_agent=ginfo_agent,
            authenticator_agent=auth_agent,
        )
        results.append(
            ("agents build", True,
             "orchestrator + greeter + general_info + authenticator")
        )

        from sandbox.graph import build_graph, run_turn
        import uuid

        graph = build_graph()

        # A bare "Hi" with no email should cause the orchestrator to ask
        # for the email before doing anything else. This runs without
        # hitting GHL because no email has been provided yet.
        session = str(uuid.uuid4())
        reply = run_turn(graph, "Hi", session_id=session)
        asks_for_email = "email" in reply.lower()
        results.append(
            ("orchestrator asks for email first", asks_for_email, reply[:100])
        )

        # The remaining checks drive full orchestrator → greeter flows,
        # which require GHL to resolve the caller's contact. Skip them
        # gracefully when GHL isn't configured — the user can still
        # exercise these paths manually in the chat UI once they add
        # GHL_API_KEY / GHL_LOCATION_ID to .env.
        if not settings.ghl_configured:
            results.append((
                "orchestrator → greeter → authenticator / general_info paths",
                True,
                "SKIPPED — GHL not configured (add GHL_API_KEY + GHL_LOCATION_ID).",
            ))
            return results

        # Pre-seeded passkey path — authenticator surfaces PASSKEY_REQUESTED
        # and does NOT emit "VERIFIED" without user interaction. This is
        # the cheapest live-agent check that exercises the full routing:
        # orchestrator → greeter → authenticator → passkey_status → emit.
        from sandbox.webauthn import storage as _stor

        session_pk = str(uuid.uuid4())
        email_pk = "passkeyflow@example.com"
        # Clean slate, then pre-seed a passkey row.
        for row in _stor.list_by_email(email_pk):
            _stor.remove(email_pk, row["credential_id"])
        _stor.register(
            email=email_pk,
            credential_id="seed-cred",
            public_key=b"\x00" * 32,
            sign_counter=0,
            transports="internal",
            aaguid="",
            label="smoke",
        )
        reply_pk = run_turn(
            graph,
            f"Please verify me. my email is {email_pk}",
            session_id=session_pk,
        )
        results.append(
            (
                "pre-seeded passkey yields PASSKEY_REQUESTED",
                "PASSKEY_REQUESTED" in reply_pk,
                reply_pk[:100],
            )
        )
        _stor.remove(email_pk, "seed-cred")

        # General question + email → orchestrator should route to
        # general_info_agent, which queries the knowledge_base tool and
        # returns a grounded answer. No auth, no OTP, no PASSKEY_REQUESTED.
        # We use "what is the name of your company" because the answer
        # is short, deterministic, and backend-agnostic (both local JSON
        # and the production Mongo collection should return the name).
        session4 = str(uuid.uuid4())
        email3 = "generalflow@example.com"
        for row in _stor.list_by_email(email3):
            _stor.remove(email3, row["credential_id"])
        reply_gen = run_turn(
            graph,
            f"My email is {email3}. What is the name of your company?",
            session_id=session4,
        )
        grounded = "aragrow" in reply_gen.lower()
        results.append(
            (
                "general question answered via knowledge_base",
                "PASSKEY_REQUESTED" not in reply_gen
                and not reply_gen.lstrip().upper().startswith("VERIFIED")
                and grounded,
                reply_gen[:120],
            )
        )
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_5", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 6 — API structural checks (via TestClient, no real server needed)
# ---------------------------------------------------------------------------


def phase_6() -> list[Result]:
    results: list[Result] = []
    try:
        from fastapi.testclient import TestClient

        from sandbox.api import app
        from sandbox.auth import issue_token
        from sandbox.config import settings

        # TestClient as context manager runs the lifespan (builds graph).
        with TestClient(app) as client:
            r = client.get("/health")
            results.append(("/health 200", r.status_code == 200, f"body={r.json()}"))

            r = client.post("/chat", json={"message": "hi"})
            results.append(("/chat no JWT → 401", r.status_code == 401, f"{r.status_code}"))

            tok = issue_token(settings.dev_client_id)
            r = client.post(
                "/chat",
                json={"message": "hi"},
                headers={"Authorization": f"Bearer {tok}"},
            )
            results.append(("/chat with JWT → 200", r.status_code == 200, f"{r.status_code}"))

            r = client.post(
                "/passkey/register/begin",
                json={"session_id": "brand-new", "user_email": "u@e.com"},
                headers={"Authorization": f"Bearer {tok}"},
            )
            results.append(
                ("register/begin unverified → 403", r.status_code == 403, f"{r.status_code}")
            )
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_6", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 8 — MongoDB-specific checks (skipped when MONGODB_ATLAS_URI blank)
# ---------------------------------------------------------------------------


def phase_8() -> list[Result]:
    """MongoDB-specific integration checks.

    Covers the gaps the earlier phases only touch incidentally:
      1. Cluster reachable (ping).
      2. Indexes exist on each of the 3 collections (KB / memory / passkey).
      3. Passkey unique compound index is enforced (duplicate insert fails).
      4. Checkpointer persists state across a graph rebuild (new MongoDBSaver
         instance reads what the previous instance wrote).
      5. A misconfigured URI raises an error promptly (no silent success).

    When MONGODB_ATLAS_URI is blank the whole phase skips cleanly so the
    sandbox can still be validated in local-only mode.
    """
    results: list[Result] = []
    try:
        from sandbox.config import settings

        if not settings.use_mongodb:
            results.append((
                "phase 8 (MongoDB)",
                True,
                "SKIPPED — MONGODB_ATLAS_URI not set; sandbox in local-only mode.",
            ))
            return results

        # --- 1. ping -----------------------------------------------------
        from sandbox.memory import _get_mongo_client

        try:
            client = _get_mongo_client()
            client.admin.command("ping")
            results.append(("mongo ping", True, "ok"))
        except Exception as e:
            results.append(("mongo ping", False, f"{type(e).__name__}: {e}"))
            return results  # bail — nothing else will work

        # --- 2. indexes on the 3 collections -----------------------------
        from sandbox.webauthn import storage

        storage.init_db()  # make sure the passkey indexes exist

        collections = [
            ("knowledge_base",
             client[settings.mongodb_db_name][settings.mongodb_kb_collection]),
            ("memory",
             client[settings.mongodb_memory_db][settings.mongodb_checkpoint_collection]),
            ("passkey",
             client[settings.mongodb_passkey_db][settings.mongodb_passkey_collection]),
        ]
        for label, coll in collections:
            try:
                idx_names = [i["name"] for i in coll.list_indexes()]
                results.append((
                    f"{label} collection has indexes",
                    len(idx_names) > 0,
                    f"{coll.database.name}.{coll.name} → {idx_names}",
                ))
            except Exception as e:
                results.append((
                    f"{label} collection has indexes",
                    False,
                    f"{type(e).__name__}: {e}",
                ))

        # --- 3. passkey unique-index enforcement -------------------------
        from pymongo.errors import DuplicateKeyError

        pk_coll = client[settings.mongodb_passkey_db][settings.mongodb_passkey_collection]
        dup_email = "dup-smoke@example.com"
        dup_cid = "dup-cred-id"
        pk_coll.delete_many({"user_email": dup_email})
        try:
            storage.register(
                email=dup_email,
                credential_id=dup_cid,
                public_key=b"\x00" * 32,
                sign_counter=0,
                label="smoke",
            )
            # Raw insert that bypasses storage.register's upsert. Must fail.
            try:
                pk_coll.insert_one({
                    "user_email": dup_email,
                    "credential_id": dup_cid,
                    "public_key": b"\x00" * 32,
                    "sign_counter": 0,
                    "transports": None,
                    "aaguid": None,
                    "label": "dup",
                    "created_at": None,
                    "last_used_at": None,
                })
                results.append((
                    "passkey unique index enforced",
                    False,
                    "duplicate insert unexpectedly succeeded",
                ))
            except DuplicateKeyError:
                results.append((
                    "passkey unique index enforced",
                    True,
                    "DuplicateKeyError raised as expected",
                ))
            except Exception as e:
                results.append((
                    "passkey unique index enforced",
                    False,
                    f"unexpected {type(e).__name__}: {e}",
                ))
        finally:
            pk_coll.delete_many({"user_email": dup_email})

        # --- 4. checkpointer persistence across graph rebuild ------------
        # Writes a message through one MongoDBSaver instance, rebuilds the
        # graph with a FRESH saver pointed at the same collection (this
        # simulates a server restart), and confirms the message survives.
        # We use `messages` because create_react_agent's built-in state
        # schema includes it; arbitrary custom keys would be ignored by
        # update_state.
        import uuid
        from langchain_core.messages import HumanMessage
        from langgraph.checkpoint.mongodb import MongoDBSaver

        from sandbox.graph import build_graph

        thread_id = f"smoke-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}
        marker = f"persistence-marker-{uuid.uuid4().hex[:6]}"

        try:
            saver_a = MongoDBSaver(
                client=client,
                db_name=settings.mongodb_memory_db,
                collection_name=settings.mongodb_checkpoint_collection,
            )
            graph_a = build_graph(checkpointer=saver_a)
            graph_a.update_state(
                config,
                values={"messages": [HumanMessage(content=marker)]},
            )

            # Fresh saver + graph — this is what happens after a server
            # restart: the prior MongoDBSaver is gone, we construct a new
            # one, and the state must load from Mongo.
            saver_b = MongoDBSaver(
                client=client,
                db_name=settings.mongodb_memory_db,
                collection_name=settings.mongodb_checkpoint_collection,
            )
            graph_b = build_graph(checkpointer=saver_b)
            state = graph_b.get_state(config)
            msgs = (state.values if state else {}).get("messages", []) or []
            contents = [getattr(m, "content", "") for m in msgs]
            found = any(marker in (c or "") for c in contents)
            results.append((
                "checkpointer persists state across graph rebuild",
                found,
                f"thread={thread_id} messages={len(msgs)} marker_found={found}",
            ))
        finally:
            # Best-effort cleanup — checkpoint docs are keyed by thread_id.
            try:
                mem_coll = client[settings.mongodb_memory_db][settings.mongodb_checkpoint_collection]
                mem_coll.delete_many({"thread_id": thread_id})
                # Writes collection (if present) carries the same thread_id key.
                writes_coll = mem_coll.database["checkpoint_writes"]
                writes_coll.delete_many({"thread_id": thread_id})
            except Exception:
                pass

        # --- 5. bad URI raises an error ----------------------------------
        from pymongo import MongoClient

        bad = MongoClient(
            "mongodb://nonexistent.invalid:27017",
            serverSelectionTimeoutMS=500,
        )
        try:
            bad.admin.command("ping")
            results.append((
                "bad URI raises an error",
                False,
                "ping against invalid host unexpectedly succeeded",
            ))
        except Exception as e:
            results.append((
                "bad URI raises an error",
                True,
                f"{type(e).__name__} raised as expected",
            ))
        finally:
            try:
                bad.close()
            except Exception:
                pass
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_8", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 7 — end-to-end liveness
# ---------------------------------------------------------------------------


def phase_7() -> list[Result]:
    """Re-runs every other phase so `--phase 7` is a single-command
    regression sweep."""
    results: list[Result] = []
    for phase_num, fn in _PHASES.items():
        if phase_num == 7:
            continue
        sub = fn()
        for name, ok, detail in sub:
            results.append((f"p{phase_num}:{name}", ok, detail))
    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_PHASES: dict[int, Callable[[], list[Result]]] = {
    1: phase_1,
    2: phase_2,
    3: phase_3,
    4: phase_4,
    5: phase_5,
    6: phase_6,
    7: phase_7,
    8: phase_8,
}


def _print_phase(phase: int, results: list[Result]) -> bool:
    overall = all(ok for _, ok, _ in results)
    icon = "PASS" if overall else "FAIL"
    print(f"\n=== Phase {phase}: {icon} ===")
    for name, ok, detail in results:
        marker = "  ok " if ok else "  FAIL"
        print(f"{marker}  {name:<38s}  {detail}")
    return overall


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, default=0, help="Phase number (1-8) or 0 for all")
    args = parser.parse_args()

    phases = [args.phase] if args.phase else list(_PHASES.keys())
    failed = []
    for p in phases:
        if p not in _PHASES:
            print(f"unknown phase {p}", file=sys.stderr)
            return 2
        ok = _print_phase(p, _PHASES[p]())
        if not ok:
            failed.append(p)

    print()
    if failed:
        print(f"Smoke FAILED for phases: {failed}")
        return 1
    print("Smoke PASSED for all requested phases.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
