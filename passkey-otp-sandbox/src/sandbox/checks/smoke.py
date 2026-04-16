"""Sandbox smoke tests — gated per phase.

Usage:
    python -m sandbox.checks.smoke               # run all phases
    python -m sandbox.checks.smoke --phase 3     # only phase 3

Each phase function returns a list of (check_name, ok, detail) tuples.
A phase "passes" when every entry's ok is True. Phases that depend on
external services (GHL, Mongo) skip gracefully when unconfigured.

Phases:
    1 — third-party imports
    2 — settings + LLM round-trip
    3 — GHL connect + contact lookup (skips if GHL not configured)
    4 — agents build + orchestrator flows (greeter, authenticator, general_info)
    5 — API auth/health via TestClient
    6 — all of the above (regression sweep)
    7 — MongoDB-specific integration (skips if MONGODB_ATLAS_URI blank)
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

        results.append(("imports", True, "langgraph, fastapi"))
    except Exception as e:
        results.append(("imports", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 2 — settings + LLM round-trip
# ---------------------------------------------------------------------------


def phase_2() -> list[Result]:
    results: list[Result] = []

    try:
        from sandbox.config import settings

        _ = settings.jwt_secret  # raises ConfigError if missing
        _ = settings.google_api_key
        results.append(("settings load", True, f"company={settings.company_name}"))
    except Exception as e:
        results.append(("settings load", False, f"{type(e).__name__}: {e}"))
        return results  # bail — nothing below will work

    try:
        from sandbox.llm import get_llm

        resp = get_llm().invoke("hi")
        text = getattr(resp, "content", "") or ""
        results.append((
            "llm invoke",
            bool(text),
            f"chars={len(text) if isinstance(text, str) else '?'}",
        ))
    except Exception as e:
        results.append(("llm invoke", False, f"{type(e).__name__}: {e}"))

    return results


# ---------------------------------------------------------------------------
# Phase 3 — GHL integration (skipped when GHL_API_KEY/LOCATION_ID blank)
# ---------------------------------------------------------------------------


def phase_3() -> list[Result]:
    """GHL reachable + OTP custom fields resolve + known contact lookup.

    We explicitly do NOT trigger a real OTP email (that would send mail
    to whoever is in the contact list on every smoke run). The
    register/verify leg is exercised manually via the chat UI.
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

        # 1. GHL reachable — hit the custom-fields endpoint directly.
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

        # 5. Reschedule / client-notification custom fields resolve.
        #    These only exist in GHL if the admin has created them
        #    under Settings → Custom Fields, so we skip-without-fail
        #    when any of them isn't present.
        results.extend(_phase_3_reschedule_fields(settings))

        # 6. Jobber integration (bundled into phase 3 — skips cleanly
        #    when Jobber isn't configured).
        results.extend(_phase_3_jobber(settings))

    except Exception as e:
        traceback.print_exc()
        results.append(("phase_3", False, f"{type(e).__name__}: {e}"))
    return results


def _phase_3_reschedule_fields(settings) -> list[Result]:
    """Try to resolve every GHL custom-field key the reschedule /
    client-notification flows write to. Missing fields report as a
    warning, not a failure, so the smoke can still go green on a
    freshly-cloned sandbox where the admin hasn't yet created them.
    """
    from sandbox.tools import ghl_client

    checks = [
        ("reschedule_request field", settings.ghl_reschedule_request_field_key),
        ("reschedule_requested_at field", settings.ghl_reschedule_requested_at_field_key),
        ("client_notification field", settings.ghl_client_notification_field_key),
        ("client_notification_at field", settings.ghl_client_notification_at_field_key),
    ]
    results: list[Result] = []
    for label, key in checks:
        try:
            fid = ghl_client.resolve_custom_field_id(key)
            results.append((label, True, f"{key} → {fid[:8]}..."))
        except Exception as e:
            # 404 = field isn't created yet; report as "skipped" not
            # "failed" so the overall phase can still pass.
            msg = str(e)
            if "404" in msg or "not found" in msg.lower():
                results.append((
                    label, True,
                    f"SKIPPED — {key} not yet created in GHL",
                ))
            else:
                results.append((label, False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 3b — Jobber integration (skipped when not configured)
# ---------------------------------------------------------------------------
#
# This runs as part of phase_3 so the numbered phase list stays stable.
# It exercises the Jobber OAuth client + read path without relying on
# any specific client being present in the tenant.


def _phase_3_jobber(settings) -> list[Result]:
    results: list[Result] = []
    if not settings.jobber_configured:
        results.append((
            "Jobber",
            True,
            "SKIPPED — JOBBER_CLIENT_ID/SECRET not set or tokens file missing.",
        ))
        return results

    try:
        from sandbox.tools import jobber_client
        from sandbox.tools.jobber_get_clients import jobber_get_clients

        # 1. Raw GraphQL ping — verifies token load + refresh path.
        try:
            data = jobber_client.execute(
                "query { account { name } }", {}
            )
            account = (data.get("data") or {}).get("account") or {}
            results.append((
                "Jobber connect",
                bool(account.get("name")),
                f"account.name={account.get('name', '')[:40]}",
            ))
        except Exception as e:
            results.append(("Jobber connect", False, f"{type(e).__name__}: {e}"))
            return results

        # 2. Tool-level end-to-end via a bogus email — shouldn't match,
        #    proves the tool + filter path works end-to-end.
        r = jobber_get_clients.invoke({"search_value": "nobody-smoke-jobber@example.com"})
        results.append((
            "jobber_get_clients handles missing email",
            "No clients found" in r,
            r[:80],
        ))

        # 3. Known-client end-to-end for the three record tools. We reuse
        #    davidarago99@gmail.com (known to exist in GHL from phase 3;
        #    expected to exist in Jobber too for this sandbox). If they
        #    aren't a Jobber client, each tool returns a legible "No
        #    clients found" / "No Jobber client found" string — still a
        #    valid, non-erroring path, so we just check we got a
        #    non-empty answer that doesn't start with "Jobber API error".
        from sandbox.tools.jobber_get_properties import jobber_get_properties
        from sandbox.tools.jobber_get_jobs import jobber_get_jobs
        from sandbox.tools.jobber_get_visits import jobber_get_visits

        known = "davidarago99@gmail.com"
        r_clients = jobber_get_clients.invoke({"search_value": known})
        results.append((
            f"jobber_get_clients finds {known}",
            r_clients.startswith("Clients"),
            r_clients.split("\n", 1)[0][:100],
        ))

        # Extract the first base64 Jobber client id from the output so we
        # can hand it to the three detail tools. Pattern: "| ID: <id>".
        import re
        m = re.search(r"ID:\s*([A-Za-z0-9+/=]+)", r_clients)
        if not m:
            results.append((
                "jobber detail tools",
                True,
                f"SKIPPED — {known} not in Jobber (no client id to probe).",
            ))
            return results
        client_id_jobber = m.group(1)

        for label, tool in [
            ("jobber_get_properties", jobber_get_properties),
            ("jobber_get_jobs", jobber_get_jobs),
            ("jobber_get_visits", jobber_get_visits),
        ]:
            try:
                out = tool.invoke({"client_id_jobber": client_id_jobber})
                ok = isinstance(out, str) and out and not out.startswith("Jobber API error")
                results.append((label, ok, out.split("\n", 1)[0][:100]))
            except Exception as e:
                results.append((label, False, f"{type(e).__name__}: {e}"))

        # 4. Tool-level imports for the two outbound notification tools
        #    (send_vendor_reschedule_request + send_client_notification).
        #    We don't actually invoke them here — that would write to
        #    GHL custom fields and fire workflows. Import + @tool
        #    introspection is enough to catch refactor breakage.
        try:
            from sandbox.tools.send_vendor_reschedule_request import (
                send_vendor_reschedule_request,
            )
            from sandbox.tools.send_client_notification import (
                send_client_notification,
            )
            results.append((
                "notifier tools import",
                callable(send_vendor_reschedule_request.invoke)
                and callable(send_client_notification.invoke),
                "send_vendor_reschedule_request + send_client_notification",
            ))
        except Exception as e:
            results.append((
                "notifier tools import", False, f"{type(e).__name__}: {e}",
            ))
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_3 (Jobber)", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 4 — agents + graph
# ---------------------------------------------------------------------------


def phase_4() -> list[Result]:
    results: list[Result] = []
    try:
        from sandbox.agents import account as acct_mod
        from sandbox.agents import authenticator as auth_mod
        from sandbox.agents import client_notifier as client_notifier_mod
        from sandbox.agents import general_info as ginfo_mod
        from sandbox.agents import greeting as greet_mod
        from sandbox.agents import orchestrator as orch_mod
        from sandbox.agents import reschedule as resched_mod
        from sandbox.agents import vendor_notifier as vendor_notifier_mod
        from sandbox.config import settings

        auth_agent = auth_mod.build()
        ginfo_agent = ginfo_mod.build()
        greet_agent = greet_mod.build()
        acct_agent = acct_mod.build()
        vendor_notifier_agent = vendor_notifier_mod.build()
        client_notifier_agent = client_notifier_mod.build()
        resched_agent = resched_mod.build(
            vendor_notifier_agent=vendor_notifier_agent,
            client_notifier_agent=client_notifier_agent,
        )
        orch_mod.build(
            greeter_agent=greet_agent,
            general_info_agent=ginfo_agent,
            authenticator_agent=auth_agent,
            account_agent=acct_agent,
            reschedule_agent=resched_agent,
        )
        results.append(
            ("agents build", True,
             "orchestrator + greeter + general_info + authenticator + account + reschedule (+ vendor_notifier + client_notifier)")
        )

        from sandbox.graph import build_graph, run_turn
        import uuid

        graph = build_graph()

        # A bare "Hi" with no email should cause the orchestrator to ask
        # for the email before doing anything else. Does not hit GHL.
        session = str(uuid.uuid4())
        reply = run_turn(graph, "Hi", session_id=session)
        asks_for_email = "email" in reply.lower()
        results.append(
            ("orchestrator asks for email first", asks_for_email, reply[:100])
        )

        # The remaining check drives the full orchestrator → greeter →
        # general_info flow, which requires GHL + the knowledge base.
        # Skip when GHL isn't configured.
        if not settings.ghl_configured:
            results.append((
                "orchestrator → greeter → general_info (KB-backed answer)",
                True,
                "SKIPPED — GHL not configured.",
            ))
            return results

        session2 = str(uuid.uuid4())
        email = "davidarago99@gmail.com"
        reply_gen = run_turn(
            graph,
            f"My email is {email}. What is the name of your company?",
            session_id=session2,
        )
        grounded = "aragrow" in reply_gen.lower()
        results.append((
            "general question answered via knowledge_base",
            grounded,
            reply_gen[:120],
        ))
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_4", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 5 — API structural checks (via TestClient)
# ---------------------------------------------------------------------------


def phase_5() -> list[Result]:
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
    except Exception as e:
        traceback.print_exc()
        results.append(("phase_5", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 7 — MongoDB-specific checks (skipped when MONGODB_ATLAS_URI blank)
# ---------------------------------------------------------------------------


def phase_7() -> list[Result]:
    """MongoDB integration coverage that the other phases only touch
    incidentally. Covers reachability, index presence, and checkpointer
    persistence across a graph rebuild.

    Skips cleanly when MONGODB_ATLAS_URI is blank so the sandbox can
    still be validated in local-only mode.
    """
    results: list[Result] = []
    try:
        from sandbox.config import settings

        if not settings.use_mongodb:
            results.append((
                "phase 7 (MongoDB)",
                True,
                "SKIPPED — MONGODB_ATLAS_URI not set; sandbox in local-only mode.",
            ))
            return results

        from sandbox.memory import _get_mongo_client

        try:
            client = _get_mongo_client()
            client.admin.command("ping")
            results.append(("mongo ping", True, "ok"))
        except Exception as e:
            results.append(("mongo ping", False, f"{type(e).__name__}: {e}"))
            return results

        # Indexes on the KB + memory collections.
        for label, coll in [
            ("knowledge_base",
             client[settings.mongodb_db_name][settings.mongodb_kb_collection]),
            ("memory",
             client[settings.mongodb_memory_db][settings.mongodb_checkpoint_collection]),
        ]:
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

        # Checkpointer persistence across graph rebuild.
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
            try:
                mem_coll = client[settings.mongodb_memory_db][settings.mongodb_checkpoint_collection]
                mem_coll.delete_many({"thread_id": thread_id})
                writes_coll = mem_coll.database["checkpoint_writes"]
                writes_coll.delete_many({"thread_id": thread_id})
            except Exception:
                pass

        # Bad URI handled cleanly.
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
        results.append(("phase_7", False, f"{type(e).__name__}: {e}"))
    return results


# ---------------------------------------------------------------------------
# Phase 6 — regression sweep (re-run every other phase)
# ---------------------------------------------------------------------------


def phase_6() -> list[Result]:
    results: list[Result] = []
    for phase_num, fn in _PHASES.items():
        if phase_num == 6:
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
    parser.add_argument("--phase", type=int, default=0, help="Phase number (1-7) or 0 for all")
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
