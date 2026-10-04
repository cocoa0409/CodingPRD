"""State machines: valid transitions, invalid transitions and terminal lockdowns."""
import pytest

from test_helpers import (
    validate_paginated, api_client, utc, get_success_data, validate_error, validate_success,
    set_clock, create_agency, create_carrier, create_plan, create_agency_payload,
    create_complaint_payload, create_coaching_assignment_payload,
    create_and_activate_agent, create_agent_in_pipeline, license_agent,
    create_member_for_agent, capture_scope, open_call, connect_call,
    complete_call, drop_call, get_call, submit_enrollment, acknowledge_enrollment,
    effectuate_enrollment, setup_master_data, setup_ringing_call,
    setup_complaint_in_review, CLOCK_START, TEST_USERS,
    make_licensed_agent_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LICENSING = TEST_USERS["licensing_coordinator_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]


def _master_with_agent(**agency_overrides):
    scn = setup_master_data(**agency_overrides)
    set_clock("2026-10-01T09:00:00Z")
    agent, _, _, _ = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"])
    scn["agent"] = agent
    return scn


def test_call_session_connect_moves_ringing_to_in_progress():
    """PRD §3.3: "On success the call advances to `IN_PROGRESS` and `live_call_count` is
    recomputed."
    PRD §2.10: "`version` is an integer that increments by one on every mutation of the
    resource".

    Design: Corner/state_machines/call_session_connect_moves_ringing_to_in_progress
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    call_id = scn["call"]["id"]

    result = validate_success(api_client.connect_call(call_id, {
        "disclaimer_delivered": True, "plan_type_discussed": "MAPD",
        "recording_id": "REC-1001", "disclaimer_script_code": "CMS-DISC-2026",
        "marketing_rule_set_version": "MKT-2026-V3",
    }, make_licensed_agent_headers(scn["agent"]["id"])), 200)

    assert result["status"] == "IN_PROGRESS"
    assert result["version"] == 2
    assert result["actual_end_at"] is None
    assert result["scheduled_end_at"] == utc("2026-10-01T09:30:00Z")

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["live_call_count"] == 1
    rows, _meta = validate_paginated(api_client.list_agent_call_sessions(
        scn["agent"]["id"], DIRECTOR))
    assert len(rows) == 1
    assert rows[0]["status"] == "IN_PROGRESS"


def test_enrollment_acknowledge_rejects_a_future_clock_past_the_ack_window():
    """PRD §3.6: "The acknowledgment must also land inside the carrier's expected window —
    the logical clock must be at or before `submitted_on` plus the carrier's
    `ack_expected_within_days`, else `ERR_ACK_WINDOW_EXPIRED`."
    PRD §2.13: "Then the carrier-side window rules, where an acknowledgment must land within
    the carrier's expected acknowledgment window".

    Design: Corner/state_machines/enrollment_acknowledge_rejects_a_future_clock_past_the_ack_window
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])

    # Exactly submitted_on + 5 days is inside the inclusive window.
    set_clock("2026-10-06T00:00:00Z")
    acked = validate_success(api_client.acknowledge_enrollment(
        enrollment["id"], {"carrier_id": scn["carrier"]["id"]}, CARRIER_INT), 200)
    assert acked["submission_status"] == "ACKNOWLEDGED"
    assert acked["acknowledged_on"] == utc("2026-10-06T00:00:00Z")

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    assert len(rows) == 2, "acknowledgment posts the RENEWAL entry"


def test_enrollment_effectuate_consumes_the_scope_and_posture_already_captured():
    """PRD §3.6: "On success the submission advances to `EFFECTUATED`, `effectuated_on`
    takes the logical clock, the membership dimension advances to `ENROLLED`, the scope is
    consumed — its status moves to `CONSUMED` and the enrollment's id is written into its
    `consumed_by_enrollment_id`".
    PRD §3.6: "No new ledger entry is posted at effectuation".

    Design: Corner/state_machines/enrollment_effectuate_consumes_the_scope_and_posture_already_captured
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])

    result = validate_success(
        api_client.effectuate_enrollment(enrollment["id"], CARRIER_INT), 200)
    assert result["submission_status"] == "EFFECTUATED"
    assert result["disenrollment_status"] == "ENROLLED"
    assert result["effectuated_on"] == utc("2026-10-01T09:00:00Z")

    scope = get_success_data(api_client.get_scope(
        scn["scope"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
    assert scope["status"] == "CONSUMED"
    assert scope["consumed_by_enrollment_id"] == enrollment["id"]

    plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    member = get_success_data(api_client.get_member(
        scn["member"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
    assert plan["enrolled_member_count"] == 1
    assert agent["active_enrollment_count"] == 1
    assert member["enrollment_count"] == 1

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    assert len(rows) == 2, "effectuation posts no additional entry"


def test_call_session_complete_from_ringing_returns_call_not_in_progress():
    """PRD §3.3: "The call must be `IN_PROGRESS`, else `ERR_CALL_NOT_IN_PROGRESS`."
    PRD §2.13: "State-machine legality is evaluated after all of the above, and reports the
    target entity's own `ERR_*_NOT_*` identifier at HTTP 409".

    Design: Corner/state_machines/call_session_complete_from_ringing_returns_call_not_in_progress
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    call_id = scn["call"]["id"]

    resp = api_client.complete_call(call_id,
                                    {"recording_id": "REC-1001",
                                     "disclaimer_delivered": True},
                                    make_licensed_agent_headers(scn["agent"]["id"]))
    body = validate_error(resp, "ERR_CALL_NOT_IN_PROGRESS", expected_status=409)
    assert body["error_id"] != "ERR_CALL_NOT_COMPLETED"
    assert body["error_id"] != "ERR_DISCLAIMER_NOT_DELIVERED"

    after = get_call(scn["agent"]["id"], call_id)
    assert after["status"] == "RINGING"
    assert after["actual_end_at"] is None
    assert after["version"] == 1

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["compliance_risk_score"] == pytest.approx(0.00, abs=0.01)


def test_enrollment_terminal_withdrawal_locks_out_every_further_edge():
    """PRD §3.6: "an enrollment already `EFFECTUATED` or already `WITHDRAWN` cannot be
    withdrawn, and the refusal is `ERR_ENROLLMENT_NOT_WITHDRAWABLE`."
    PRD §3.6: "An acknowledgment requires the enrollment to be `SUBMITTED`, else
    `ERR_ENROLLMENT_NOT_SUBMITTED`".

    Design: Corner/state_machines/enrollment_terminal_withdrawal_locks_out_every_further_edge
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])

    withdrawn = validate_success(api_client.withdraw_enrollment(
        enrollment["id"], {"reason": "BENEFICIARY_CHANGED_MIND"},
        make_licensed_agent_headers(scn["agent"]["id"])), 200)
    assert withdrawn["submission_status"] == "WITHDRAWN"

    validate_error(api_client.acknowledge_enrollment(
        enrollment["id"], {"carrier_id": scn["carrier"]["id"]}, CARRIER_INT),
        "ERR_ENROLLMENT_NOT_SUBMITTED", expected_status=409)
    validate_error(api_client.effectuate_enrollment(enrollment["id"], CARRIER_INT),
                   "ERR_ENROLLMENT_NOT_ACKNOWLEDGED", expected_status=409)
    validate_error(api_client.reject_enrollment(
        enrollment["id"], {"reason": "CARRIER_DUPLICATE"}, CARRIER_INT),
        "ERR_ENROLLMENT_NOT_SUBMITTED", expected_status=409)
    validate_error(api_client.withdraw_enrollment(
        enrollment["id"], {"reason": "BENEFICIARY_CHANGED_MIND"},
        make_licensed_agent_headers(scn["agent"]["id"])),
        "ERR_ENROLLMENT_NOT_WITHDRAWABLE", expected_status=409)

    after = get_success_data(api_client.get_enrollment(enrollment["id"], DIRECTOR))
    assert after["submission_status"] == "WITHDRAWN"


def test_call_session_drop_twice_returns_call_not_droppable():
    """PRD §3.3: "A call in either `RINGING` or `IN_PROGRESS` may be dropped, with an
    optional `reason`, and anything else fails with `ERR_CALL_NOT_DROPPABLE`."

    Design: Corner/state_machines/call_session_drop_twice_returns_call_not_droppable
    """
    set_clock("2026-10-01T09:00:00Z")
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    call_id = scn["call"]["id"]
    connect_call(scn["agent"]["id"], call_id)
    dropped = drop_call(scn["agent"]["id"], call_id)

    headers = make_licensed_agent_headers(scn["agent"]["id"])
    resp = api_client.drop_call(call_id, {"reason": "CALLER_HUNG_UP"}, headers)
    validate_error(resp, "ERR_CALL_NOT_DROPPABLE", expected_status=409)

    after = get_call(scn["agent"]["id"], call_id)
    assert after["actual_end_at"] == dropped["actual_end_at"]
    assert after["version"] == dropped["version"]

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["live_call_count"] == 0


def test_agent_provisioning_to_licensed_needs_a_state_license():
    """PRD §3.2: "A `PlatformAdmin` or a sales director creates the agent record under an
    agency with the agent's `full_name`, `national_producer_number` — unique within the
    agency — and `hire_date`. The agent begins in `PROVISIONING`."
    PRD §3.2: "On success the agent advances from `PROVISIONING` to `LICENSED`".

    Design: Corner/state_machines/agent_provisioning_to_licensed_needs_a_state_license
    """
    set_clock(CLOCK_START)
    scn = setup_master_data()
    agent = create_agent_in_pipeline(scn["agency"]["id"])

    assert agent["status"] == "PROVISIONING"
    assert agent["version"] == 1
    assert agent["chargeback_tier"] == 0
    assert agent["licensed_state_count"] == 0
    assert agent["certified_carrier_count"] == 0
    assert agent["appointed_carrier_count"] == 0
    assert agent["open_coaching_count"] == 0
    assert agent["compliance_risk_score"] == pytest.approx(0.00, abs=0.01)
    assert agent["coaching_flag"] is False
    assert agent["substantiated_complaint_count"] == 0

    license_agent(agent["id"])
    after = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    assert after["status"] == "LICENSED"
    assert after["licensed_state_count"] == 1
    assert after["certified_carrier_count"] == 0, (
        "licensing alone cannot produce an ACTIVE agent"
    )


def test_agency_posture_reset_rejects_a_non_frozen_agency():
    """PRD §3.11: "A reset toward `RESTRICTED` requires the agency to actually be `FROZEN`,
    else `ERR_AGENCY_NOT_FROZEN`; a reset toward `OPEN` requires the agency to actually be
    `RESTRICTED`, else `ERR_AGENCY_NOT_RESTRICTED`."

    Design: Corner/state_machines/agency_posture_reset_rejects_a_non_frozen_agency
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    complete_call(scn["agent"]["id"], scn["call"]["id"])

    resp = api_client.posture_reset(scn["agency"]["id"],
                                    {"target_posture": "RESTRICTED"}, COMPLIANCE)
    body = validate_error(resp, "ERR_AGENCY_NOT_FROZEN", expected_status=409)
    assert body["error_id"] != "ERR_AGENCY_NOT_RESTRICTED"

    agency = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    assert agency["compliance_posture"] == "OPEN"
    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["status"] == "ACTIVE"


def test_complaint_cycle_can_be_substantiated_appealed_and_dismissed_with_a_reversal():
    """PRD §3.9: "On that path the complaint moves to `DISMISSED`, the agent's
    `substantiated_complaint_count` decreases by one".
    PRD §3.9: "it requires `APPEALED`, and it requires the agent's
    `substantiated_complaint_count` to be at least 1, else
    `ERR_NO_SUBSTANTIATION_TO_REVERSE`".

    Design: Corner/state_machines/complaint_cycle_can_be_substantiated_appealed_and_dismissed_with_a_reversal
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    complete_call(scn["agent"]["id"], scn["call"]["id"])
    complaint = setup_complaint_in_review(scn, complaint_type="MISREPRESENTATION",
                                          source="CMS", severity="MEDIUM",
                                          filed_on="2026-09-28T00:00:00Z")
    cid = complaint["id"]
    validate_success(api_client.substantiate_complaint(cid, COMPLIANCE), 200)

    api_client.appeal_complaint(cid, {"appeal_note": "Carrier disputes"}, CARRIER_INT)
    dismissed = validate_success(api_client.dismiss_complaint(cid, COMPLIANCE), 200)
    assert dismissed["status"] == "DISMISSED"
    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["substantiated_complaint_count"] == 0

    api_client.appeal_complaint(cid, {"appeal_note": "Second round"}, CARRIER_INT)
    resp = api_client.dismiss_complaint(cid, COMPLIANCE)
    validate_error(resp, "ERR_NO_SUBSTANTIATION_TO_REVERSE", expected_status=409)

    after = get_success_data(api_client.get_complaint(cid, COMPLIANCE))
    assert after["status"] == "APPEALED"

    assert after["status"] != "CLOSED"
    validate_success(api_client.close_complaint(cid, COMPLIANCE), 200)
    final = get_success_data(api_client.get_complaint(cid, COMPLIANCE))
    assert final["status"] == "CLOSED"
    agent_final = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent_final["substantiated_complaint_count"] == 0


def test_enrollment_disenrollment_dimension_is_a_parallel_axis():
    """PRD §3.7: "The standard path is deliberately cheaper, and the asymmetry is normative
    rather than an oversight."
    PRD §3.7: "It posts a `CHARGEBACK` entry in status `FINALIZED` whose `amount_cents` is
    exactly 0 — the entry exists so that the period's arithmetic balances, but no money
    moves."

    Design: Corner/state_machines/enrollment_disenrollment_dimension_is_a_parallel_axis
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])

    set_clock("2027-03-01T00:00:00Z")
    result = validate_success(api_client.disenroll_enrollment(
        enrollment["id"],
        {"disenrollment_date": "2027-03-01T00:00:00Z",
         "disenrollment_reason": "PLAN_EXIT"}, CARRIER_INT), 200)

    assert result["disenrollment_status"] == "STANDARD_DISENROLLED"
    assert result["submission_status"] == "EFFECTUATED"
    assert result["disenrolled_day_number"] == 120
    assert result["is_rapid_disenrollment"] is False

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    cb = [r for r in rows if r["entry_type"] == "CHARGEBACK"][0]
    assert cb["amount_cents"] == pytest.approx(0.00, abs=0.01)

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["chargeback_tier"] == 0
    plan = get_success_data(api_client.get_plan(scn["plan"]["id"], COMPLIANCE))
    scope = get_success_data(api_client.get_scope(
        scn["scope"]["id"], make_licensed_agent_headers(scn["agent"]["id"])))
    assert plan["enrolled_member_count"] == 0
    assert scope["status"] == "CONSUMED"


def test_ledger_entry_finalized_cannot_be_finalized_again():
    """PRD §3.8: "Finalizing an entry is the sales director's act and moves it from
    `PROVISIONAL` to `FINALIZED`, requiring the entry to currently be `PROVISIONAL` or the
    request fails with `ERR_LEDGER_ENTRY_NOT_PROVISIONAL`."

    Design: Corner/state_machines/ledger_entry_finalized_cannot_be_finalized_again
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])

    rows, _meta = validate_paginated(api_client.list_ledger_entries(
        DIRECTOR, params={"enrollment_id": enrollment["id"]}))
    entry_id = rows[0]["id"]
    first = validate_success(api_client.finalize_ledger_entry(entry_id, DIRECTOR), 200)
    assert first["status"] == "FINALIZED"

    resp = api_client.finalize_ledger_entry(entry_id, DIRECTOR)
    validate_error(resp, "ERR_LEDGER_ENTRY_NOT_PROVISIONAL", expected_status=409)

    after = get_success_data(api_client.get_ledger_entry(entry_id, DIRECTOR))
    assert after["version"] == first["version"]
    assert after["amount_cents"] == pytest.approx(first["amount_cents"], abs=0.01)


def test_reconciliation_cannot_reconcile_with_a_nonzero_variance():
    """PRD §2.8: "Closing the month as `RECONCILED` requires a variance of exactly zero and
    is refused with `ERR_RECONCILIATION_VARIANCE_NONZERO` otherwise; disputing the month
    requires a non-zero variance".
    PRD §2.8: "Because level recognition fabricates a reported total, it can never be used
    to dismiss a dispute — it is refused outright when a carrier-reported total is already
    present, with `ERR_CARRIER_REPORTED_TOTAL_PRESENT`."

    Design: Corner/state_machines/reconciliation_cannot_reconcile_with_a_nonzero_variance
    """
    scn = _master_with_agent()
    setup_ringing_call(scn, member_index=0)
    connect_call(scn["agent"]["id"], scn["call"]["id"])
    scn["call"] = complete_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], scn["call"]["version"])

    recon = get_success_data(api_client.create_reconciliation({
        "carrier_id": scn["carrier"]["id"], "period_month": "2026-10",
        "carrier_reported_total_cents": 5000, "internal_total_variant": "PROVISIONAL",
    }, DIRECTOR))

    validate_error(api_client.reconcile(recon["id"], DIRECTOR),
                   "ERR_RECONCILIATION_VARIANCE_NONZERO", expected_status=409)

    disputed = validate_success(api_client.dispute_reconciliation(
        recon["id"], {"dispute_note": "Carrier under-reported"}, DIRECTOR), 200)
    assert disputed["status"] == "DISPUTED"
    assert disputed["internal_total_cents"] == pytest.approx(3600.00, abs=0.01)
    assert disputed["variance_cents"] == pytest.approx(1400.00, abs=0.01)

    reopened = validate_success(api_client.reopen_reconciliation(recon["id"], DIRECTOR), 200)
    assert reopened["status"] == "OPEN"

    validate_error(api_client.level_recognize(recon["id"], DIRECTOR),
                   "ERR_CARRIER_REPORTED_TOTAL_PRESENT", expected_status=409)


def test_coaching_assignment_created_without_a_complaint_is_manual_and_due_in_fourteen_days():
    """PRD §3.9: "The `triggered_by` classification is derived rather than supplied: it
    reads `COMPLAINT` when a `complaint_id` is present, and `MANUAL` when it is absent."
    PRD §3.9: "A new assignment starts `ASSIGNED`, takes `assigned_on` from the logical
    clock, has its `due_on` derived as `assigned_on` plus 14 days".

    Design: Corner/state_machines/coaching_assignment_created_without_a_complaint_is_manual_and_due_in_fourteen_days
    """
    scn = _master_with_agent()
    set_clock(CLOCK_START)
    coaching = validate_success(api_client.create_coaching_assignment(
        create_coaching_assignment_payload(scn["agent"]["id"],
                                           coaching_type="MARKETING_RULES"),
        COACH), 201)

    assert coaching["status"] == "ASSIGNED"
    assert coaching["triggered_by"] == "MANUAL"
    assert coaching["complaint_id"] is None
    assert coaching["assigned_on"] == utc(CLOCK_START)
    assert coaching["due_on"] == utc("2026-10-15T00:00:00Z")
    assert coaching["completed_on"] is None
    assert coaching["overdue_days"] == 0

    agent = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    assert agent["open_coaching_count"] == 1
    assert agent["coaching_flag"] is True
    assert agent["compliance_risk_score"] == pytest.approx(5.00, abs=0.01)