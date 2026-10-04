"""Error-catalogue behaviour: codes that are declared but shadowed or unreachable, and
the OCC guard observable on a sequential resubmission.
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error, validate_success, validate_paginated,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_carrier_payload, create_and_activate_agent, create_member_for_agent,
    capture_scope, open_call, connect_call, complete_call, get_call,
    submit_enrollment, acknowledge_enrollment, effectuate_enrollment,
    setup_master_data, CLOCK_START, TEST_USERS, make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_recording_expired_error_is_declared_but_not_raised_by_any_endpoint():
    """PRD §2.6: "It reads `EXPIRED` when the logical clock is strictly past
    `recording_retained_until`. Otherwise it reads `RECORDED` — a clock reading exactly at
    `recording_retained_until` is still `RECORDED`."
    PRD §2.6: "If a recording's retention window has already elapsed while the call is still
    the subject of an open compliance review, the reference fails with
    `ERR_RECORDING_EXPIRED`."

    Design: Corner/errors/recording_expired_error_is_declared_but_not_raised_by_any_endpoint
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])

    now = get_success_data(api_client.get_call_session(call["id"], COMPLIANCE))
    assert now["recording_status"] == "RECORDED"

    set_clock("2033-10-01T00:00:00Z")
    later = get_success_data(api_client.get_call_session(call["id"], COMPLIANCE))
    assert later["recording_status"] == "EXPIRED"
    assert later["recording_id"] == "REC-1001"
    assert later["version"] == now["version"], "the row was never rewritten"

    rows, _meta = validate_paginated(api_client.list_call_sessions(
        COMPLIANCE, params={"recording_status": "EXPIRED"}))
    assert len(rows) == 1


def test_live_call_limit_error_is_declared_but_unreachable_under_the_overlap_rule():
    """PRD §3.3: "An agent may not run two live calls at once: if another call of the same
    agent is in `IN_PROGRESS` and its half-open interval contains the current logical clock,
    the new call is refused with `ERR_AGENT_HAS_ACTIVE_CALL`."
    PRD §3.3: "Separately, the agency's `max_live_calls_per_agent` caps the number of live
    intervals an agent may have open at once, and exceeding that cap produces
    `ERR_LIVE_CALL_LIMIT_EXCEEDED`."

    Design: Corner/errors/live_call_limit_error_is_declared_but_unreachable_under_the_overlap_rule
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])

    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    member_two, version_two = create_member_for_agent(
        scn["agency"]["id"], agent["id"], full_name="Hollis Pike",
        medicare_beneficiary_id="3GH6-VG7-PM94",
        date_of_birth="1952-11-19T00:00:00Z")
    scope_two = capture_scope(member_two["id"], agent["id"], version_two)

    live = open_call(agent["id"], member["id"], scope["id"],
                     started_at="2026-10-01T09:00:00Z",
                     scheduled_end_at="2026-10-01T10:00:00Z",
                     recording_id="REC-1001")
    connect_call(agent["id"], live["id"])

    headers = make_licensed_agent_headers(agent["id"])
    resp = api_client.create_call_session({
        "agent_id": agent["id"], "member_id": member_two["id"],
        "scope_of_appointment_id": scope_two["id"],
        "started_at": "2026-10-01T09:30:00Z",
        "scheduled_end_at": "2026-10-01T10:30:00Z",
        "recording_id": "REC-1002", "disclaimer_script_code": "CMS-DISC-2026",
        "disclaimer_delivered": True, "marketing_rule_set_version": "MKT-2026-V3",
    }, headers)
    body = validate_error(resp, "ERR_AGENT_HAS_ACTIVE_CALL", expected_status=409)
    assert body["error_id"] != "ERR_LIVE_CALL_LIMIT_EXCEEDED"

    rows, _meta = validate_paginated(api_client.list_agent_call_sessions(agent["id"], DIRECTOR))
    assert len(rows) == 1
    agent_row = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert agent_row["live_call_count"] == 1
    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["max_live_calls_per_agent"] == 1


def test_stale_version_on_a_sequential_enrollment_resubmission():
    """PRD §2.12: "The request must carry `expected_call_session_version`, and that value
    must equal the current `version` of the target call session. If the call session's
    version has advanced since the client last read it, the submission is refused with
    `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/errors/stale_version_on_a_sequential_enrollment_resubmission
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    stale_version = call["version"]

    submit_enrollment(agent["id"], call["id"], member["id"], scn["plan"]["id"],
                      scope["id"], stale_version)

    refreshed = get_call(agent["id"], call["id"])
    assert refreshed["version"] == stale_version + 1, (
        "the first submission advanced the call session version"
    )

    headers = make_licensed_agent_headers(agent["id"])
    resp = api_client.create_enrollment({
        "call_session_id": call["id"], "member_id": member["id"],
        "plan_id": scn["plan"]["id"], "agent_id": agent["id"],
        "scope_of_appointment_id": scope["id"],
        "effective_date": "2026-11-02T00:00:00Z", "plan_type_discussed": "MAPD",
        "expected_call_session_version": stale_version,
    }, headers)
    validate_error(resp, "ERR_STALE_VERSION", expected_status=412)

    rows, _meta = validate_paginated(api_client.list_enrollments(
        DIRECTOR, params={"call_session_id": call["id"]}))
    assert len(rows) == 1, "the stale request persisted nothing"


def test_amount_variant_mismatch_is_declared_but_the_finalize_edge_always_derives():
    """PRD §3.8: "At finalization the entry's `amount_cents` is recomputed from current
    inputs under the final variant of the amount rule, so a rate change or a plan change
    that occurred since posting is picked up rather than carried forward."
    PRD §3.8: "An `INITIAL` entry takes the annual initial commission as its `amount_cents`,
    unmodified."

    Design: Corner/errors/amount_variant_mismatch_is_declared_but_the_finalize_edge_always_derives
    """
    scn = setup_master_data()
    agent, _, _, _ = create_and_activate_agent(scn["agency"]["id"], scn["carrier"]["id"])
    member, version = create_member_for_agent(scn["agency"]["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    call = open_call(agent["id"], member["id"], scope["id"])
    connect_call(agent["id"], call["id"])
    call = complete_call(agent["id"], call["id"])
    enrollment = submit_enrollment(agent["id"], call["id"], member["id"],
                                  scn["plan"]["id"], scope["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    entry_id = rows[0]["id"]
    assert rows[0]["amount_cents"] == pytest.approx(3600.00, abs=0.01)

    carrier = get_success_data(api_client.get_carrier(scn["carrier"]["id"], ADMIN))
    api_client.update_carrier(scn["carrier"]["id"], {
        "initial_commission_rate_pct": 0.25,
        "expected_carrier_version": carrier["version"],
    }, ADMIN)

    finalized = validate_success(
        api_client.finalize_ledger_entry(entry_id, DIRECTOR), 200)
    assert finalized["status"] == "FINALIZED"
    # 1500 x 12 x 0.25 = 4500.00 recomputed at the new rate
    assert finalized["amount_cents"] == pytest.approx(4500.00, abs=0.01)
    assert finalized["amount_cents"] != pytest.approx(3600.00, abs=0.01), (
        "the finalize derived rather than compared"
    )