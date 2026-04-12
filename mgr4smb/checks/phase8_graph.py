"""
Phase 8 sanity check — verify the full orchestration graph.

Usage:
    python -m mgr4smb.checks.phase8_graph                # full end-to-end
    python -m mgr4smb.checks.phase8_graph --structural   # skip LLM invocations
"""

import sys
import uuid

from mgr4smb.logging_config import setup_logging

setup_logging(level="WARNING")

_results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201
    _results.append(ok)
    return ok


def _last_ai_text(messages) -> str:
    from langchain_core.messages import AIMessage

    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        c = getattr(msg, "content", "")
        if isinstance(c, list):
            c = " ".join(
                blk.get("text", "") if isinstance(blk, dict) else str(blk) for blk in c
            )
        if c:
            return c
    return ""


def structural_checks() -> None:
    from mgr4smb.graph import build_agents, build_graph
    from mgr4smb.memory import checkpointer_context

    try:
        agents = build_agents()
        check("build_agents() returns all 7 agents", len(agents) == 7,
              f"got {len(agents)}: {list(agents.keys())}")
    except Exception as e:
        check("build_agents()", False, str(e))

    # Tool duplication check: ghl_support must NOT have booking tools
    try:
        from mgr4smb.agents import ghl_support as ghl_mod
        raw_names = [t.name for t in ghl_mod.RAW_TOOLS]
        forbidden = {"ghl_available_slots", "ghl_book_appointment"}
        has_forbidden = any(name in forbidden for name in raw_names)
        check(
            "ghl_support raw tools do NOT include ghl_available_slots/ghl_book_appointment",
            not has_forbidden,
            f"raw tools: {raw_names}",
        )
    except Exception as e:
        check("ghl_support tool check", False, str(e))

    # Checkpointer connects to MongoDB
    try:
        with checkpointer_context() as cp:
            check("MongoDBSaver initialises (memory DB reachable)", cp is not None)
            try:
                graph = build_graph(cp)
                check("build_graph(checkpointer) returns a compiled graph", graph is not None)
            except Exception as e:
                check("build_graph(checkpointer)", False, str(e))
    except Exception as e:
        check("MongoDB checkpointer context", False, str(e))


def behavioural_checks() -> None:
    from mgr4smb.graph import build_graph, run_turn
    from mgr4smb.memory import checkpointer_context

    # Build once, reuse for all behavioural tests
    with checkpointer_context() as cp:
        graph = build_graph(cp)

        # --- Routing: general info question ---
        try:
            sid = f"test-{uuid.uuid4()}"
            # Turn 1: user provides identity and asks a general question.
            reply = run_turn(
                graph,
                "My email is user@example.com and my phone is +15551234567. "
                "What services do you offer?",
                session_id=sid,
            )
            reply_low = reply.lower()
            # Should have either greeted + answered, OR asked for more info —
            # but NOT demanded OTP (general info is public).
            asks_otp = "verification code" in reply_low or "otp" in reply_low
            check(
                "Orchestrator does NOT require OTP for general_info path",
                not asks_otp,
                f"got: {reply[:200]}",
            )
        except Exception as e:
            check("Routing: general_info path", False, str(e))

        # --- Routing: booking intent ---
        try:
            sid = f"test-{uuid.uuid4()}"
            reply = run_turn(
                graph,
                "My email is user@example.com and my phone is +15551234567. "
                "I want to book a cleaning.",
                session_id=sid,
            )
            reply_low = reply.lower()
            # Booking path should ask for service/timezone details, not reschedule
            is_booking_path = (
                "service" in reply_low
                or "timezone" in reply_low
                or "when" in reply_low
                or "time" in reply_low
                or "appointment" in reply_low
                or "cleaning" in reply_low
            )
            # Should NOT pretend to have scheduled it already
            not_fake_booked = "confirmation id" not in reply_low
            check(
                "Routing: 'book a cleaning' goes to booking_agent path",
                is_booking_path and not_fake_booked,
                f"got: {reply[:200]}",
            )
        except Exception as e:
            check("Routing: booking path", False, str(e))

        # --- Routing: reschedule intent → OTP gate ---
        try:
            sid = f"test-{uuid.uuid4()}"
            reply = run_turn(
                graph,
                "My email is user@example.com and my phone is +15551234567. "
                "I need to reschedule my appointment.",
                session_id=sid,
            )
            reply_low = reply.lower()
            # Should either show identity verification (OTP) OR gracefully refuse
            # because this is a fake identity. Must NOT silently proceed to data.
            gates_access = (
                "verif" in reply_low
                or "code" in reply_low
                or "otp" in reply_low
                or "security" in reply_low
                or "identity" in reply_low
                or "records" in reply_low
                or "cannot" in reply_low
            )
            no_data_leak = (
                "[event_id:" not in reply_low and "appointment_status" not in reply_low
            )
            check(
                "Routing: 'reschedule' triggers OTP gate (or refuses gracefully)",
                gates_access and no_data_leak,
                f"got: {reply[:200]}",
            )
        except Exception as e:
            check("Routing: reschedule path", False, str(e))

        # --- Session persistence: same session_id resumes history ---
        # Turn 1 establishes identity; turn 2 asks a question without
        # re-providing identity. If the checkpointer works, the orchestrator
        # sees the identity from turn 1 and does NOT ask for it again.
        try:
            sid = f"test-persist-{uuid.uuid4()}"
            # Turn 1: provide identity only
            _ = run_turn(
                graph,
                "My email is alex.test@example.com and my phone is +15551234567.",
                session_id=sid,
            )
            # Turn 2: ask a general question WITHOUT providing identity again.
            # Orchestrator should proceed (email+phone already in history)
            # instead of asking for identity a second time.
            reply2 = run_turn(
                graph,
                "What are your business hours?",
                session_id=sid,
            )
            low = reply2.lower()
            # Must not re-prompt for email/phone
            reprompts_identity = (
                "email address" in low or "phone number" in low
            ) and ("could i get" in low or "please provide" in low or "what is your" in low)
            check(
                "Session persistence: turn 2 does NOT re-ask for identity",
                not reprompts_identity,
                f"got: {reply2[:200]}",
            )
        except Exception as e:
            check("Session persistence", False, str(e))

        # --- Shared memory: sub-agent response visible in orchestrator history ---
        try:
            from mgr4smb.graph import get_history

            sid = f"test-history-{uuid.uuid4()}"
            _ = run_turn(
                graph,
                "My email is user@example.com and my phone is +15551234567. "
                "What services do you offer?",
                session_id=sid,
            )
            history = get_history(graph, sid)
            # History should contain ToolMessages from sub-agent delegations
            from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
            has_user_msg = any(isinstance(m, HumanMessage) for m in history)
            has_ai_msg = any(isinstance(m, AIMessage) for m in history)
            has_tool_trace = any(
                isinstance(m, ToolMessage)
                or (isinstance(m, AIMessage) and getattr(m, "tool_calls", None))
                for m in history
            )
            check(
                "Shared memory: conversation history includes user + AI + sub-agent traces",
                has_user_msg and has_ai_msg and has_tool_trace,
                f"user={has_user_msg}, ai={has_ai_msg}, tool_trace={has_tool_trace}, total={len(history)}",
            )
        except Exception as e:
            check("Shared memory", False, str(e))


def main() -> int:
    print("Phase 8 — Full Graph sanity check\n")  # noqa: T201
    print("Structural checks:")  # noqa: T201
    structural_checks()

    if "--structural" not in sys.argv:
        print("\nBehavioural checks (invokes LLM + MongoDB):")  # noqa: T201
        behavioural_checks()

    print()  # noqa: T201
    passed = sum(_results)
    total = len(_results)
    if all(_results):
        print(f"All {total} checks passed.")  # noqa: T201
    else:
        print(f"{passed}/{total} checks passed.")  # noqa: T201
    return 0 if all(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
