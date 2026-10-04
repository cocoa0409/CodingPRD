"""State-machine tests: redaction revision cycle, recording parallel dimensions,
docking single-occupancy, policy mutual exclusion, case transitions, terminal
lockdown, redaction release side effects, share-grant revoke idempotency."""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    make_officer_headers,
    make_redaction_technician_headers,
    make_records_officer_headers,
    make_supervisor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    close_case,
    create_agency,
    create_active_policy,
    create_case,
    create_redaction_job,
    link_evidence,
    list_custody_events,
    refresh_officer,
    refresh_recording,
    run_retention,
    set_clock,
    setup_agency_with_policy,
    setup_agency_with_policy_and_officer,
    setup_closed_case_with_grant,
    setup_officer_with_device,
    submit_case,
    upload_recording,
)
from test_helpers.factories import create_policy_payload

ADMIN = TEST_USERS["agency_admin_headers"]
DC = TEST_USERS["device_coordinator_headers"]
RO = TEST_USERS["records_officer_headers"]
TECH_1 = make_redaction_technician_headers("tech-1")
RO_1 = make_records_officer_headers("ro-1")


# ===========================================================================
# non_linear_state_machine / redaction_job_revision_cycle_returns_to_in_progress
# ===========================================================================

def test_redaction_returned_restart_resets_actual_minutes(api):
    """PRD §3.6: "A returned job is restarted by the technician (`RETURNED →
    IN_PROGRESS`, recording still `ACTIVE` required), and the restart resets
    `actual_minutes` to null — each revision cycle re-reports effort afresh."

    Design: Difficulty/non_linear_state_machine/redaction_job_revision_cycle_returns_to_in_progress
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    job = create_redaction_job(agency["id"], rec["id"])
    api.start_redaction_job(agency["id"], job["id"], TECH_1)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 40}, TECH_1)
    api.return_redaction_job(agency["id"], job["id"], RO_1)
    resp = api.start_redaction_job(agency["id"], job["id"], TECH_1)
    restarted = validate_success(resp)
    assert restarted["status"] == "IN_PROGRESS"
    assert restarted["actual_minutes"] is None, (
        f"RETURNED -> IN_PROGRESS restart must reset actual_minutes to null, "
        f"got {restarted['actual_minutes']}"
    )


def test_redaction_revision_cycle_reaches_released_with_new_effort(api):
    """PRD §3.6: "The job then walks `QUEUED → IN_PROGRESS → SUBMITTED → APPROVED
    → RELEASED`, with a revision loop and a cancel escape hatch."
    PRD §3.6: "return moves it `SUBMITTED → RETURNED` for rework."

    Design: Difficulty/non_linear_state_machine/redaction_job_revision_cycle_returns_to_in_progress
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    job = create_redaction_job(agency["id"], rec["id"])
    api.start_redaction_job(agency["id"], job["id"], TECH_1)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 40}, TECH_1)
    api.return_redaction_job(agency["id"], job["id"], RO_1)
    api.start_redaction_job(agency["id"], job["id"], TECH_1)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 55}, TECH_1)
    api.approve_redaction_job(agency["id"], job["id"], RO_1)
    resp = api.release_redaction_job(agency["id"], job["id"], RO_1)
    final = validate_success(resp)
    assert final["status"] == "RELEASED"
    assert final["actual_minutes"] == 55, (
        f"the second submit's effort must survive to RELEASED, got {final['actual_minutes']}"
    )


# ===========================================================================
# non_linear_state_machine / recording_parallel_dims_flagging_independent_of_upload_state
# ===========================================================================

def test_purged_recording_keeps_pending_review_status(api):
    """PRD §3.4: "A `Supervisor` discharges the flag by marking the recording
    reviewed, which requires the recording's `upload_status` to be `ACTIVE`
    (otherwise `ERR_INVALID_STATE`, 409) and moves `review_status` to `REVIEWED`,
    decrements the officer's `pending_review_count` by one".
    PRD §3.5: "each `RETENTION_DUE` recording whose `legal_hold_count` is zero
    moves to `PURGED`".

    Design: Difficulty/non_linear_state_machine/recording_parallel_dims_flagging_independent_of_upload_state
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 100})
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["review_status"] == "PENDING_REVIEW"
    set_clock("2027-03-20T00:00:00Z")
    run_retention(agency["id"])
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["upload_status"] == "PURGED"
    assert rec["review_status"] == "PENDING_REVIEW", (
        f"the review dimension never auto-advances with purge, got {rec['review_status']}"
    )


def test_purge_decrements_upload_count_but_not_pending_review_count(api):
    """PRD §3.5: "Each purge removes the recording's `size_bytes` from the
    agency's `storage_used_bytes`, recomputes `storage_posture`, decrements the
    officer's `recordings_uploaded_count` by one".
    PRD §2.6: "their `pending_review_count` counts their recordings whose
    `review_status` is `PENDING_REVIEW`."

    Design: Difficulty/non_linear_state_machine/recording_parallel_dims_flagging_independent_of_upload_state
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer(
        policy_overrides={"supervisor_review_rate_pct": 100})
    upload_recording(agency["id"], device, officer, duration_seconds=600,
                     category="INCIDENT")
    set_clock("2027-03-20T00:00:00Z")
    run_retention(agency["id"])
    officer_now = refresh_officer(agency["id"], officer["id"])
    assert officer_now["recordings_uploaded_count"] == 0, (
        f"purge decrements the upload count, got {officer_now['recordings_uploaded_count']}"
    )
    assert officer_now["pending_review_count"] == 1, (
        f"the purged recording is still PENDING_REVIEW so the counter stays 1, "
        f"got {officer_now['pending_review_count']}"
    )


# ===========================================================================
# resource_temporal_overlap / docking_session_single_occupancy_half_open
# ===========================================================================

def test_dock_while_docked_and_undock_while_undocked_rejected(api):
    """PRD §3.3: "Docking a device that is already `DOCKED` — or undocking one
    that is already `UNDOCKED` — is rejected with `ERR_INVALID_STATE` (409)."

    Design: Difficulty/resource_temporal_overlap/docking_session_single_occupancy_half_open
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_device
    device = create_device(agency["id"])
    # device starts DOCKED
    resp = api.dock_device(agency["id"], device["id"], DC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    api.undock_device(agency["id"], device["id"], DC)
    resp = api.undock_device(agency["id"], device["id"], DC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dock_after_undock_reopens_the_session(api):
    """PRD §3.3: "Only one open docking session exists per device at a time."
    PRD §3.3: "Docking an `UNDOCKED` device captures `battery_pct_at_dock` from
    the current `battery_pct` and stamps `docked_at` with the logical now".

    Design: Difficulty/resource_temporal_overlap/docking_session_single_occupancy_half_open
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_device
    device = create_device(agency["id"])
    api.undock_device(agency["id"], device["id"], DC)
    resp = api.dock_device(agency["id"], device["id"], DC)
    docked = validate_success(resp)
    assert docked["dock_status"] == "DOCKED", (
        f"after undock the same instant is available to the next session, "
        f"got {docked['dock_status']}"
    )


# ===========================================================================
# resource_temporal_overlap / policy_activation_mutual_exclusion_across_supersede_window
# ===========================================================================

def test_second_policy_activation_rejected_while_incumbent_active(api):
    """PRD §3.1: "Exactly one policy per agency may be `ACTIVE` at a time:
    activating a policy while another is already `ACTIVE` is rejected with
    `ERR_POLICY_ALREADY_ACTIVE` (409) — the incumbent must first be superseded."

    Design: Difficulty/resource_temporal_overlap/policy_activation_mutual_exclusion_across_supersede_window
    """
    set_clock("2026-09-01T00:00:00Z")
    agency = create_agency()
    p1 = get_success_data(api.create_policy(
        agency["id"], create_policy_payload(tagging_required=False), ADMIN))
    p2 = get_success_data(api.create_policy(
        agency["id"],
        create_policy_payload(recording_triggers=["MANUAL", "TASER_ARMED"],
                              tagging_required=True, supervisor_review_rate_pct=50,
                              default_share_expiry_days=14), ADMIN))
    api.activate_policy(agency["id"], p1["id"], ADMIN)
    resp = api.activate_policy(agency["id"], p2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_POLICY_ALREADY_ACTIVE)


def test_policy_activation_succeeds_after_supersede(api):
    """PRD §3.1: "An `AgencyAdmin` may explicitly supersede the active policy
    (moving it `ACTIVE → SUPERSEDED`) before activating a replacement".

    Design: Difficulty/resource_temporal_overlap/policy_activation_mutual_exclusion_across_supersede_window
    """
    set_clock("2026-09-01T00:00:00Z")
    agency = create_agency()
    p1 = get_success_data(api.create_policy(
        agency["id"], create_policy_payload(tagging_required=False), ADMIN))
    p2 = get_success_data(api.create_policy(
        agency["id"],
        create_policy_payload(recording_triggers=["MANUAL", "TASER_ARMED"],
                              tagging_required=True, supervisor_review_rate_pct=50,
                              default_share_expiry_days=14), ADMIN))
    api.activate_policy(agency["id"], p1["id"], ADMIN)
    api.supersede_policy(agency["id"], p1["id"], ADMIN)
    resp = api.activate_policy(agency["id"], p2["id"], ADMIN)
    activated = validate_success(resp)
    assert activated["status"] == "ACTIVE"
    # exactly one ACTIVE policy for the agency
    data, meta = validate_paginated(api.list_policies(ADMIN, params={"agency_id": agency["id"]}))
    statuses = {p["id"]: p["status"] for p in data}
    assert statuses[p1["id"]] == "SUPERSEDED"
    assert statuses[p2["id"]] == "ACTIVE"


# ===========================================================================
# boundary_precision_check / dock_charge_floor_at_3599_vs_3600_seconds
# ===========================================================================

def test_dock_charge_3599_seconds_gains_zero(api):
    """PRD §3.3: "The charge gain is computed from the dwell time: the elapsed
    seconds between `docked_at` and the logical now are converted to whole hours
    by flooring (so 3599 seconds yields no gain, while 3600 seconds yields one
    hour's worth)."

    Design: Difficulty/boundary_precision_check/dock_charge_floor_at_3599_vs_3600_seconds
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_device
    device = create_device(agency["id"], battery_pct=50)
    api.undock_device(agency["id"], device["id"], DC)
    api.dock_device(agency["id"], device["id"], DC)
    set_clock("2026-09-01T00:59:59Z")
    resp = api.undock_device(agency["id"], device["id"], DC)
    undocked = validate_success(resp)
    assert undocked["battery_pct"] == 50, (
        f"floor(3599/3600) == 0 hours -> gain 0 -> battery stays 50, "
        f"got {undocked['battery_pct']}"
    )


def test_dock_charge_3600_seconds_gains_ten(api):
    """PRD §3.3: "Each whole hour of dwell accrues 10 percentage points of
    charge, but the gain is capped by headroom — it can never exceed the gap
    between `battery_pct_at_dock` and a full 100."

    Design: Difficulty/boundary_precision_check/dock_charge_floor_at_3599_vs_3600_seconds
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy = setup_agency_with_policy()
    from test_helpers.fixtures import create_device
    device = create_device(agency["id"], battery_pct=50)
    api.undock_device(agency["id"], device["id"], DC)
    api.dock_device(agency["id"], device["id"], DC)
    set_clock("2026-09-01T01:59:59Z")
    resp = api.undock_device(agency["id"], device["id"], DC)
    undocked = validate_success(resp)
    assert undocked["battery_pct"] == 60, (
        f"floor(3600/3600) == 1 hour -> gain min(10, 100-50) == 10 -> battery 60, "
        f"got {undocked['battery_pct']}"
    )
    assert undocked["docked_at"] is None
    assert undocked["dock_status"] == "UNDOCKED"


# ===========================================================================
# cross_entity_state_dependency / case_submit_review_blocked_by_integrity_failed_recording
# ===========================================================================

def test_submit_review_blocked_by_uncategorized_linked_recording(api):
    """PRD §3.8: "An `Officer` submits the case for review, but only when
    `evidence_count` is at least 1 — an empty case fails with `ERR_CASE_EMPTY`
    (409) — and every `LINKED` recording's `upload_status` is `ACTIVE` or
    `RETENTION_DUE`; a linked recording in any other state blocks submission
    with `ERR_EVIDENCE_NOT_READY` (409)."

    Design: Difficulty/cross_entity_state_dependency/case_submit_review_blocked_by_integrity_failed_recording
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    ra = upload_recording(agency["id"], device, officer, category="INCIDENT")
    rb = upload_recording(agency["id"], device, officer, category="TEST")
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], ra["id"], officer)
    link_evidence(agency["id"], case["id"], rb["id"], officer)
    from test_helpers.fixtures import get_case
    case_now = get_case(agency["id"], case["id"])
    assert case_now["evidence_count"] == 2
    # Drive rb (still LINKED) into PURGED — a state that is neither ACTIVE
    # nor RETENTION_DUE — via the retention run. rb's case-extended due date
    # is link creation (2026-09-01T00:00:00Z) + 7 days; ra's is link + 730
    # days, so at 2026-09-10 only rb is due and purgeable.
    set_clock("2026-09-10T00:00:00Z")
    run_retention(agency["id"])
    rb_now = refresh_recording(agency["id"], rb["id"])
    assert rb_now["upload_status"] == "PURGED"
    resp = api.submit_case_review(agency["id"], case["id"],
                                  make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_NOT_READY)
    case_now = get_case(agency["id"], case["id"])
    assert case_now["status"] == "OPEN"


def test_submit_review_integrity_gate_reads_recording_state_across_link(api):
    """PRD §3.8: "every `LINKED` recording's `upload_status` is `ACTIVE` or
    `RETENTION_DUE`; a linked recording in any other state blocks submission
    with `ERR_EVIDENCE_NOT_READY` (409)."

    Design: Difficulty/cross_entity_state_dependency/case_submit_review_blocked_by_integrity_failed_recording
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    # A well-formed hash that does not match the server-recomputed hash of
    # the submitted media payload lands the recording in INTEGRITY_FAILED
    # (PRD section 3.4); a quarantined recording cannot be linked
    # (PRD section 3.8: ERR_INTEGRITY_FAILED).
    resp = api.create_recording(
        agency["id"],
        {"device_id": device["id"], "trigger_code": "MANUAL", "duration_seconds": 60,
         "size_bytes": 1048576, "recorded_at": "2026-09-01T00:00:00Z",
         "content_hash_sha256": "b" * 64, "category": "INCIDENT",
         "payload": "tampered-media-bytes"},
        make_officer_headers(officer["id"]),
    )
    rb = validate_success(resp, expected_status=201)
    assert rb["upload_status"] == "INTEGRITY_FAILED"
    # an INTEGRITY_FAILED recording cannot be linked: ERR_INTEGRITY_FAILED
    case = create_case(agency["id"], officer)
    resp = api.link_evidence(agency["id"], case["id"], {"recording_id": rb["id"]},
                             make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_INTEGRITY_FAILED)


# ===========================================================================
# cross_entity_state_dependency / officer_retire_blocked_by_lead_case_and_suspend_blocked_by_device
# ===========================================================================

def test_officer_suspend_blocked_while_device_assigned(api):
    """PRD §3.2: "Suspension by an `AgencyAdmin` requires that no device is
    currently `ASSIGNED` to the officer, failing with `ERR_DEVICE_STILL_ASSIGNED`
    (409) otherwise".

    Design: Difficulty/cross_entity_state_dependency/officer_retire_blocked_by_lead_case_and_suspend_blocked_by_device
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    create_case(agency["id"], officer)
    resp = api.suspend_officer(agency["id"], officer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_DEVICE_STILL_ASSIGNED)
    officer_now = refresh_officer(agency["id"], officer["id"])
    assert officer_now["status"] == "ACTIVE"


def test_officer_retire_blocked_by_lead_open_case(api):
    """PRD §3.2: "Retirement is terminal and more heavily gated: the officer must
    have no assigned device (`ERR_DEVICE_STILL_ASSIGNED`) and must not be the
    `lead_officer_id` of any case in `OPEN` or `UNDER_REVIEW` status — a
    violation surfaces `ERR_LEAD_CASES_OPEN` (409)."

    Design: Difficulty/cross_entity_state_dependency/officer_retire_blocked_by_lead_case_and_suspend_blocked_by_device
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    create_case(agency["id"], officer)
    api.unassign_device(agency["id"], device["id"], DC)
    resp = api.retire_officer(agency["id"], officer["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_LEAD_CASES_OPEN)
    officer_now = refresh_officer(agency["id"], officer["id"])
    assert officer_now["status"] == "ACTIVE"


# ===========================================================================
# state_machines / recording_upload_initial_state_and_terminal_purge_lockdown
# ===========================================================================

def test_purged_recording_rejects_categorize(api):
    """PRD §3.4: "From `INTEGRITY_VERIFIED`, a recording becomes `ACTIVE` as soon
    as it has a category".
    PRD §3.11: "Then state-machine admissibility: a transition attempted from the
    wrong state fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/recording_upload_initial_state_and_terminal_purge_lockdown
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="INCIDENT")
    set_clock("2027-03-20T00:00:00Z")
    run_retention(agency["id"])
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["upload_status"] == "PURGED"
    resp = api.categorize_recording(agency["id"], rec["id"], {"category": "ARREST"},
                                    make_officer_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    rec = refresh_recording(agency["id"], rec["id"])
    assert rec["upload_status"] == "PURGED"


# ===========================================================================
# state_machines / case_reopen_cycle_under_review_to_open_then_resubmit
# ===========================================================================

def test_case_reopen_cycle_reenters_open_and_resubmits(api):
    """PRD §3.8: "Reopening, also a `Supervisor` action, returns the case to
    `OPEN` from either `UNDER_REVIEW` or `CLOSED` and writes `CASE_REOPENED`."
    PRD §3.8: "Unlinking is allowed only while the case is `OPEN` (otherwise
    `ERR_INVALID_STATE`)".

    Design: Corner/state_machines/case_reopen_cycle_under_review_to_open_then_resubmit
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    ra = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:00:00Z", category="INCIDENT")
    # Advance the clock so the second upload is not future-dated relative to
    # the logical clock (PRD section 3.4).
    set_clock("2026-09-01T00:01:00Z")
    rb = upload_recording(agency["id"], device, officer,
                          recorded_at="2026-09-01T00:01:00Z", category="INCIDENT")
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], ra["id"], officer)
    submit_case(agency["id"], case["id"], officer)
    # reopen from UNDER_REVIEW
    resp = api.reopen_case(agency["id"], case["id"], make_supervisor_headers(officer["id"]))
    reopened = validate_success(resp)
    assert reopened["status"] == "OPEN"
    # link recording B only possible in OPEN
    link_evidence(agency["id"], case["id"], rb["id"], officer)
    from test_helpers.fixtures import get_case
    case_now = get_case(agency["id"], case["id"])
    assert case_now["evidence_count"] == 2
    # resubmit
    submit_case(agency["id"], case["id"], officer)
    case_now = get_case(agency["id"], case["id"])
    assert case_now["status"] == "UNDER_REVIEW"


# ===========================================================================
# state_machines / invalid_transition_close_from_open_rejected
# ===========================================================================

def test_case_close_from_open_rejected(api):
    """PRD §3.8: "The case lifecycle itself runs `OPEN → UNDER_REVIEW → CLOSED →
    ARCHIVED`."
    PRD §3.8: "A `Supervisor` then closes the case once no linked recording
    remains `PENDING_REVIEW`".

    Design: Corner/state_machines/invalid_transition_close_from_open_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, category="INCIDENT")
    case = create_case(agency["id"], officer)
    link_evidence(agency["id"], case["id"], rec["id"], officer)
    resp = api.close_case(agency["id"], case["id"], make_supervisor_headers(officer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    from test_helpers.fixtures import get_case
    case_now = get_case(agency["id"], case["id"])
    assert case_now["status"] == "OPEN"


# ===========================================================================
# state_machines / redaction_release_side_effects_write_custody_and_audit
# ===========================================================================

def test_redaction_release_writes_custody_and_audit(api):
    """PRD §3.6: "Only when the job is `APPROVED` and the recording is still
    `ACTIVE` (not `RETENTION_DUE` or `PURGED`, else `ERR_INVALID_STATE`) may the
    `RecordsOfficer` release it, producing a `REDACTION_RELEASED` custody event
    and a `REDACTION_RELEASED` audit entry."

    Design: Corner/state_machines/redaction_release_side_effects_write_custody_and_audit
    """
    set_clock("2026-09-01T00:00:00Z")
    agency, policy, officer, device = setup_agency_with_policy_and_officer()
    rec = upload_recording(agency["id"], device, officer, duration_seconds=600,
                           category="INCIDENT")
    job = create_redaction_job(agency["id"], rec["id"])
    api.start_redaction_job(agency["id"], job["id"], TECH_1)
    api.submit_redaction_job(agency["id"], job["id"], {"actual_minutes": 25}, TECH_1)
    api.approve_redaction_job(agency["id"], job["id"], RO_1)
    resp = api.release_redaction_job(agency["id"], job["id"], RO_1)
    released = validate_success(resp)
    assert released["status"] == "RELEASED"
    events = list_custody_events(agency["id"], rec["id"])
    event_types = [e["event_type"] for e in events]
    assert "REDACTION_RELEASED" in event_types, (
        f"release must write a REDACTION_RELEASED custody event, got {event_types}"
    )
    data, meta = validate_paginated(api.list_audit_log(
        RO, params={"agency_id": agency["id"], "action": "REDACTION_RELEASED"}))
    assert len(data) >= 1, "release must write a REDACTION_RELEASED audit entry"
    assert any(e["entity_id"] in (job["id"], rec["id"]) for e in data)


# ===========================================================================
# state_machines / idempotent_double_revoke_second_call_fails
# ===========================================================================

def test_double_revoke_second_call_rejected(api):
    """PRD §3.9: "A `RecordsOfficer` may revoke an `ACTIVE` grant at any time,
    moving it to `REVOKED` and writing `SHARE_GRANT_REVOKED`."
    PRD §3.11: "Then state-machine admissibility: a transition attempted from the
    wrong state fails with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/idempotent_double_revoke_second_call_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_closed_case_with_grant()
    agency = ctx["agency"]
    grant = ctx["grant"]
    resp = api.revoke_share_grant(agency["id"], grant["id"], RO)
    revoked = validate_success(resp)
    assert revoked["status"] == "REVOKED"
    resp = api.revoke_share_grant(agency["id"], grant["id"], RO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
