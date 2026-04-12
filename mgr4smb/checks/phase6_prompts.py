"""
Phase 6 sanity check — verify all 7 agent system prompts.

Usage:
    python -m mgr4smb.checks.phase6_prompts
"""

import sys

_results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"  {status} {label}"
    if not ok and detail:
        msg += f" — {detail}"
    print(msg)  # noqa: T201
    _results.append(ok)
    return ok


def main() -> int:
    print("Phase 6 — Agent Prompts sanity check\n")  # noqa: T201

    agents = [
        "orchestrator",
        "greeting",
        "general_info",
        "otp",
        "booking",
        "ghl_support",
        "jobber_support",
    ]

    prompts: dict[str, str] = {}

    # 1. Import each agent module's SYSTEM_PROMPT
    for name in agents:
        try:
            mod = __import__(f"mgr4smb.agents.{name}", fromlist=["SYSTEM_PROMPT"])
            prompt = getattr(mod, "SYSTEM_PROMPT")
            prompts[name] = prompt
            check(f"Import mgr4smb.agents.{name}.SYSTEM_PROMPT", True)
        except Exception as e:
            check(f"Import mgr4smb.agents.{name}.SYSTEM_PROMPT", False, str(e))

    # 2. Non-empty and str
    for name, prompt in prompts.items():
        check(
            f"{name}.SYSTEM_PROMPT is a non-empty string",
            isinstance(prompt, str) and len(prompt.strip()) > 200,
            f"type={type(prompt).__name__}, len={len(prompt) if isinstance(prompt, str) else 0}",
        )

    # 3. Each prompt mentions its agent name
    agent_role_names = {
        "orchestrator": "ORCHESTRATOR",
        "greeting": "GREETING_AGENT",
        "general_info": "GENERAL_INFO_AGENT",
        "otp": "OTP_AGENT",
        "booking": "BOOKING_AGENT",
        "ghl_support": "GHL_SUPPORT_AGENT",
        "jobber_support": "JOBBER_SUPPORT_AGENT",
    }
    for name, role in agent_role_names.items():
        prompt = prompts.get(name, "")
        check(
            f"{name} prompt contains '{role}'",
            role in prompt,
        )

    # 4. Each prompt mentions its expected tools by name
    expected_tools = {
        "orchestrator": ["greeting_agent", "general_info_agent", "booking_agent",
                          "ghl_support_agent", "jobber_support_agent"],
        "greeting": ["ghl_contact_lookup"],
        "general_info": ["mongodb_knowledge_base"],
        "otp": ["ghl_send_otp", "ghl_verify_otp"],
        "booking": ["ghl_available_slots", "ghl_book_appointment",
                     "otp_agent", "jobber_support_agent"],
        "ghl_support": ["ghl_get_appointments", "ghl_cancel_appointment",
                         "otp_agent", "booking_agent"],
        "jobber_support": ["jobber_get_clients", "jobber_get_properties",
                            "jobber_get_jobs", "jobber_get_visits",
                            "jobber_create_client", "jobber_create_property",
                            "jobber_create_job", "otp_agent"],
    }
    for name, tools in expected_tools.items():
        prompt = prompts.get(name, "")
        missing = [t for t in tools if t not in prompt]
        check(
            f"{name} mentions all its tools",
            not missing,
            f"missing: {missing}",
        )

    # 5. OTP_AGENT prompt contains the OTP flow steps
    otp_prompt = prompts.get("otp", "")
    check(
        "otp prompt mentions OTP_SENT / OTP_FAILED / VERIFIED / UNVERIFIED",
        all(s in otp_prompt for s in ("OTP_SENT", "OTP_FAILED", "VERIFIED", "UNVERIFIED")),
    )

    # 6. BOOKING_AGENT prompt contains the property intake questionnaire
    booking_prompt = prompts.get("booking", "")
    intake_keywords = ["house", "apartment", "office", "bedrooms", "bathrooms", "offices", "address"]
    missing_intake = [k for k in intake_keywords if k.lower() not in booking_prompt.lower()]
    check(
        "booking prompt covers property intake (house/apartment/office + rooms)",
        not missing_intake,
        f"missing: {missing_intake}",
    )

    # 7. GHL_SUPPORT_AGENT prompt does NOT contain OTP implementation details
    #    (OTP logic was moved to otp_agent). The prompt should reference otp_agent
    #    but should NOT contain ghl_send_otp/ghl_verify_otp tool calls.
    ghl_support_prompt = prompts.get("ghl_support", "")
    has_otp_tools = "ghl_send_otp" in ghl_support_prompt or "ghl_verify_otp" in ghl_support_prompt
    check(
        "ghl_support prompt does NOT include ghl_send_otp/ghl_verify_otp (delegated to otp_agent)",
        not has_otp_tools,
        "found references — OTP logic should live in otp_agent only",
    )
    check(
        "ghl_support prompt DOES reference otp_agent for verification",
        "otp_agent" in ghl_support_prompt,
    )

    # 8. GHL_SUPPORT_AGENT should NOT include ghl_available_slots / ghl_book_appointment
    #    (those live in booking_agent; support delegates for rebooks)
    has_booking_tools = (
        "ghl_available_slots" in ghl_support_prompt
        or "ghl_book_appointment" in ghl_support_prompt
    )
    check(
        "ghl_support prompt does NOT include ghl_available_slots/ghl_book_appointment",
        not has_booking_tools,
        "those belong to booking_agent — support delegates for reschedules",
    )

    # Summary
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
