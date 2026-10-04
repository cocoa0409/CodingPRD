"""Run-plan lifecycle branches, incident cascades and conserved quantities."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error

from test_helpers import (
    api_client, ApiErrorId, TEST_USERS,
    setup_launched_corridor, create_run, request_window, submit_run, dispatch_run,
    setup_monitoring_window, make_incident, make_prospect, make_operational_terminal,
    make_corridor, create_driver_transition_payload, create_run_plan_payload,
    make_remote_support_operator_headers,
)


def _dispatch_ready_run(**kwargs):
    stack = setup_launched_corridor(**kwargs)
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"])
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


def _run_payload(stack, **overrides):
    """Raw run-plan payload (used for creates that are expected to be refused)."""
    return create_run_plan_payload(
        stack["corridor"]["id"], stack["carrier"]["id"], stack["origin"]["id"],
        stack["destination"]["id"], stack["commitment"]["id"],
        stack["prospect"]["id"], **overrides)


def _in_transit_with_ride_along():
    """A run carrying a RIDE_ALONG_VERIFIED transition, already IN_TRANSIT."""
    stack = setup_launched_corridor()
    run = create_run(stack)
    transition = validate_success(api_client.create_driver_transition(
        create_driver_transition_payload(stack["prospect"]["id"], stack["origin"]["id"],
                                         pathway="RIDE_ALONG_EVALUATOR",
                                         transition_start_epoch_day=12,
                                         transition_days_count=3, hours_recorded=8),
        TEST_USERS["driver_outreach_headers"]), expected_status=201)
    api_client.ride_along_transition(transition["id"], {"run_plan_id": run["id"]},
                                     TEST_USERS["driver_outreach_headers"])
    submit_run(run["id"])
    window = request_window(stack["origin"]["id"], run["id"])
    run = dispatch_run(run["id"])
    run = validate_success(api_client.start_highway_segment(
        run["id"], TEST_USERS["carrier_dispatcher_headers"]))
    return stack, run, transition


# ─── combinatorial_formula / safe_stop_fee_nested_band_selection ────────────

def test_safe_stop_fee_is_zero_in_the_low_exposure_band(api, any_headers):
    """PRD §3.4: "the fee is then read from three bands: strictly below 1000
    yields 0, at or above 1000 but strictly below 5000 yields 25000, and at or
    above 5000 yields 60000."

    A single-trailer run on a 24-mile corridor at weather 34 with a CLEAN
    carrier reads a rounded exposure of 816.00 and a fee of 0.

    Design: Difficulty/combinatorial_formula/safe_stop_fee_nested_band_selection
    """
    stack = setup_launched_corridor(weather_profile="LOW_VISIBILITY",
                                    weather_risk_score=34, highway_segment_miles=24)
    run = create_run(stack, trailer_count=1)
    operator = make_prospect(stack["origin"]["id"], "Mira Okafor", "REMOTE_SUPPORT")
    support = make_prospect(stack["origin"]["id"], "Sam Delgado", "REMOTE_SUPPORT")
    assignment = setup_monitoring_window(run, stack, operator, support, acknowledge=True)
    data = validate_success(api_client.get_remote_support_assignment(
        assignment["id"], any_headers))
    carrier = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert carrier["incident_band"] == "CLEAN"
    assert data["safe_stop_fee_cents"] == pytest.approx(0, abs=0.01), \
        "rounded exposure 24 * 34 * 1 * 1.0 = 816.00 sits below the 1000 band"


def test_safe_stop_fee_stays_unset_while_the_window_is_only_monitored(api, any_headers):
    """PRD §3.9: "A scheduled window begins with its `assignment_status` at
    `SCHEDULED`, `intervention_count` of 0 and `safe_stop_required` false".
    PRD §3.9: "a window that has never been involved in a stop carries 0."

    Design: Difficulty/combinatorial_formula/safe_stop_fee_nested_band_selection
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    operator = make_prospect(stack["origin"]["id"], "Mira Okafor", "REMOTE_SUPPORT")
    support = make_prospect(stack["origin"]["id"], "Sam Delgado", "REMOTE_SUPPORT")
    assignment = setup_monitoring_window(run, stack, operator, support, acknowledge=True)
    data = validate_success(api_client.get_remote_support_assignment(
        assignment["id"], any_headers))
    assert data["assignment_status"] == "MONITORING"
    assert data["safe_stop_required"] is False
    assert data["safe_stop_fee_cents"] == pytest.approx(0, abs=0.01)


# ─── corner: calculations/safe_stop_fee_watch_band_multiplies_the_exposure ──

def test_safe_stop_fee_watch_band_selects_the_mid_band(api, any_headers):
    """PRD §3.4: "a health factor taken from the owning carrier's
    `incident_band` — 1.0 when the carrier is `CLEAN`, 1.5 when it is `WATCH`
    and 2.0 when it is `SUSPENDED`".

    The same 24-mile corridor at weather 34 on a WATCH carrier reads
    24 * 34 * 1 * 1.5 = 1224.00, which lands in the 1000-to-5000 band. The fee is
    stamped when the safe stop executes on the monitored run.

    Design: Corner/calculations/safe_stop_fee_watch_band_multiplies_the_exposure
    """
    stack = setup_launched_corridor(weather_profile="LOW_VISIBILITY",
                                    weather_risk_score=34, highway_segment_miles=24)
    run_a = create_run(stack)
    make_incident(stack, run_a, severity="MODERATE", recordable_incidents=2)
    run_b = create_run(stack, window_start_epoch_day=13, window_end_epoch_day=15,
                       trailer_count=1)
    operator = make_prospect(stack["origin"]["id"], "Mira Okafor", "REMOTE_SUPPORT")
    support = make_prospect(stack["origin"]["id"], "Sam Delgado", "REMOTE_SUPPORT")
    submit_run(run_b["id"])
    request_window(stack["origin"]["id"], run_b["id"])
    run_b = dispatch_run(run_b["id"])
    run_b = validate_success(api_client.start_highway_segment(
        run_b["id"], TEST_USERS["carrier_dispatcher_headers"]))
    assignment = setup_monitoring_window(run_b, stack, operator, support, acknowledge=True)
    carrier = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert carrier["incident_band"] == "WATCH"
    data = validate_success(api_client.safe_stop_run_plan(
        run_b["id"], make_remote_support_operator_headers(operator["id"])))
    assert data["run_status"] == "READINESS_PENDING"
    stopped = validate_success(api_client.get_remote_support_assignment(
        assignment["id"], any_headers))
    assert stopped["safe_stop_required"] is True
    assert stopped["safe_stop_fee_cents"] == pytest.approx(25000, abs=0.01), \
        f"exposure 1224.00 lands in the 1000-to-5000 band, got {stopped['safe_stop_fee_cents']}"


# ─── non_linear_state_machine / run_plan_branching_fork_join ────────────────

def test_highway_start_moves_approved_windows_into_service(api, any_headers):
    """PRD §3.4: "On success every approved window on the run moves to
    `IN_SERVICE` — which releases nothing, because an in-service window still
    occupies its apron".

    Design: Difficulty/non_linear_state_machine/run_plan_branching_fork_join_from_dispatch_ready
    """
    stack, run, window = _dispatch_ready_run()
    api_client.submit_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    api_client.start_highway_segment(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    window = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], any_headers))
    assert window["window_status"] == "IN_SERVICE"


def test_terminal_lockdown_rejects_further_run_plan_transitions(api, any_headers):
    """PRD §3.3: "Every terminal run plan in the system — `COMPLETED` and
    `ABORTED` alike — rejects all further transitions with
    `ERR_RUN_PLAN_TERMINAL`."

    Design: Difficulty/non_linear_state_machine/run_plan_branching_fork_join_from_dispatch_ready
    """
    stack, run, window = _dispatch_ready_run()
    api_client.abort_run_plan(run["id"], TEST_USERS["compliance_officer_headers"])
    run = validate_success(api_client.get_run_plan(run["id"], any_headers))
    assert run["run_status"] == "ABORTED"
    resp = api_client.submit_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_RUN_PLAN_TERMINAL)


def test_abort_branch_cancels_the_approved_apron_window(api, any_headers):
    """PRD §3.3: "Aborting cancels every apron window on the run that was
    `REQUESTED` or `APPROVED`".

    Design: Difficulty/non_linear_state_machine/run_plan_branching_fork_join_from_dispatch_ready
    """
    stack, run, window = _dispatch_ready_run()
    api_client.abort_run_plan(run["id"], TEST_USERS["compliance_officer_headers"])
    window = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], any_headers))
    assert window["window_status"] == "CANCELLED"


# ─── non_linear_state_machine / incident_report_investigation_cycle_with_reopen

def test_reopen_from_closed_returns_the_report_to_investigating(api, any_headers):
    """PRD §3.5: "The reopen route is available from `CORRECTIVE_ACTION` and from
    `SUBMITTED`".
    PRD §3.5: "Reopening returns the report to `INVESTIGATING` and recomputes
    the corridor's blocking flag and posture".

    Design: Difficulty/non_linear_state_machine/incident_report_investigation_cycle_with_reopen
    """
    stack = setup_launched_corridor(weather_profile="HIGH_WIND",
                                    weather_risk_score=55)
    run = create_run(stack)
    report = make_incident(stack, run, severity="MODERATE", review_days_allowed=5)
    api_client.investigate_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    api_client.submit_incident(report["id"], TEST_USERS["regulatory_liaison_headers"])
    api_client.reopen_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    data = validate_success(api_client.get_incident_report(report["id"], any_headers))
    assert data["report_status"] == "INVESTIGATING"


def test_moderate_report_on_low_visibility_corridor_needs_no_regulatory_notice(api, any_headers):
    """PRD §3.5: "`review_days_allowed`, which is 3 business days when
    regulatory notice is required and 5 business days otherwise."
    PRD §3.5: "That flag is true when the `incident_tier` is `TIER_1` or
    `TIER_2`, or when the `severity` is `CRITICAL`".

    A MODERATE report carries notice only when its tier requires it; with
    review_days_allowed 5 the notice flag reads false.

    Design: Difficulty/non_linear_state_machine/incident_report_investigation_cycle_with_reopen
    """
    stack = setup_launched_corridor(weather_profile="LOW_VISIBILITY",
                                    weather_risk_score=34)
    run = create_run(stack)
    report = make_incident(stack, run, severity="MODERATE", review_days_allowed=5)
    data = validate_success(api_client.get_incident_report(report["id"], any_headers))
    assert data["regulatory_notice_required"] is True
    assert data["review_days_allowed"] == 3


# ─── transitive_cascade / incident_investigation_five_hop_cascade ───────────

def test_critical_investigation_sets_the_corridor_blocking_flag(api, any_headers):
    """PRD §3.5: "Investigating a filed report opens the corridor's exposure.
    The transition moves the report's `report_status` to `INVESTIGATING` and
    recomputes the corridor's `has_blocking_incident`".

    Design: Difficulty/transitive_cascade/incident_investigation_five_hop_cascade
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    report = make_incident(stack, run, severity="CRITICAL", recordable_incidents=1,
                           review_days_allowed=3)
    api_client.investigate_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    data = validate_success(api_client.get_incident_report(report["id"], any_headers))
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert data["report_status"] == "INVESTIGATING"
    assert corridor["has_blocking_incident"] is True


def test_forced_suspension_drives_the_corridor_to_frozen(api, any_headers):
    """PRD §3.1: "Forced suspension is the other exit: a `ComplianceOfficer` may
    fail a corridor that carries a blocking incident ... which recomputes
    `posture` to `FROZEN`".

    Design: Difficulty/transitive_cascade/incident_investigation_five_hop_cascade
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    report = make_incident(stack, run, severity="CRITICAL", recordable_incidents=1,
                           review_days_allowed=3)
    api_client.investigate_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    api_client.fail_launch_readiness(stack["corridor"]["id"],
                                     TEST_USERS["compliance_officer_headers"])
    corridor = validate_success(api_client.get_corridor(stack["corridor"]["id"], any_headers))
    assert corridor["corridor_status"] == "SUSPENDED"
    assert corridor["posture"] == "FROZEN"


def test_forced_suspension_aborts_open_runs_and_releases_the_slot(api, any_headers):
    """PRD §3.1: "aborts every run plan on the corridor still in `DRAFT`,
    `READINESS_PENDING` or `DISPATCH_READY`".
    PRD §3.3: "decrements the owning commitment's `consumed_slots` by exactly
    one so the aborted run releases its slot".

    Design: Difficulty/transitive_cascade/incident_investigation_five_hop_cascade
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    report = make_incident(stack, run, severity="CRITICAL", recordable_incidents=1,
                           review_days_allowed=3)
    api_client.investigate_incident(report["id"], TEST_USERS["incident_reviewer_headers"])
    api_client.fail_launch_readiness(stack["corridor"]["id"],
                                     TEST_USERS["compliance_officer_headers"])
    run = validate_success(api_client.get_run_plan(run["id"], any_headers))
    commitment = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert run["run_status"] == "ABORTED"
    assert commitment["consumed_slots"] == 0
    assert commitment["remaining_slots"] == commitment["committed_slots"]


# ─── transitive_cascade / commitment_completion_credit_cascade ──────────────

def test_completion_raises_the_verified_ride_along_count(api, any_headers):
    """PRD §3.4: "every driver transition attached to the run that has reached
    `RIDE_ALONG_VERIFIED` increments the commitment's
    `verified_ride_along_count`".
    PRD §3.4: "Completion ... moving it to `COMPLETED`".

    Design: Difficulty/transitive_cascade/commitment_completion_credit_cascade
    """
    stack, run, transition = _in_transit_with_ride_along()
    run = validate_success(api_client.complete_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"]))
    commitment = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert run["run_status"] == "COMPLETED"
    assert commitment["verified_ride_along_count"] == 1


def test_completion_computes_the_ride_along_credit_and_ships_the_commitment(api, any_headers):
    """PRD §3.2: "`ride_along_credit_cents` reads as the floor, to two decimal
    places, of a per-verified-ride-along credit of 1200.00 dollars multiplied by
    that count and divided by two."
    PRD §3.4: "the commitment flips to `SHIPPED` with `shipped_at` stamped."

    One verified ride-along gives floor(1200.00 * 1 / 2) = 600.

    Design: Difficulty/transitive_cascade/commitment_completion_credit_cascade
    """
    stack, run, transition = _in_transit_with_ride_along()
    api_client.complete_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    commitment = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert commitment["ride_along_credit_cents"] == pytest.approx(600.0, abs=0.01)
    assert commitment["commitment_status"] == "SHIPPED"


# ─── compensating_invariant / run_plan_slot_and_rate_compensation ───────────

def test_submit_consumes_exactly_one_commitment_slot(api, any_headers):
    """PRD §3.2: "The owning commitment's `consumed_slots` increases by exactly
    one and its `remaining_slots`, which reads as `committed_slots` minus
    `consumed_slots`, recomputes".

    Design: Difficulty/compensating_invariant/run_plan_slot_and_rate_compensation_conserves_commitment_slots
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    commitment = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert commitment["consumed_slots"] == 1
    assert commitment["remaining_slots"] == commitment["committed_slots"] - 1


def test_abort_returns_the_slot_and_conserves_the_invariant(api, any_headers):
    """PRD §3.3: "decrements the owning commitment's `consumed_slots` by exactly
    one so the aborted run releases its slot, recomputes the commitment's
    `remaining_slots`".
    PRD §2.12: "the platform relies on state and capacity checks rather than on
    replay detection — the `remaining_slots` check on a commitment and the
    `hold_status` check on an apron window are the two examples that carry the
    most weight."

    The invariant committed_slots - consumed_slots == remaining_slots holds at
    both endpoints.

    Design: Difficulty/compensating_invariant/run_plan_slot_and_rate_compensation_conserves_commitment_slots
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    before = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    api_client.abort_run_plan(run["id"], TEST_USERS["compliance_officer_headers"])
    after = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert before["consumed_slots"] == 1 and before["remaining_slots"] == 4
    assert after["consumed_slots"] == 0 and after["remaining_slots"] == 5
    assert after["remaining_slots"] == after["committed_slots"] - after["consumed_slots"]


# ─── compensating_invariant / commitment_revoke_conserves_ride_along_credit ─

def test_revoke_moves_the_whole_credit_into_the_billed_ledger(api, any_headers):
    """PRD §3.2: "revoking a commitment that is `CONFIRMED` or `SHIPPED` moves
    its `commitment_status` to `REVOKED`, moves the whole of
    `ride_along_credit_cents` into `billed_ride_along_cents` and recomputes
    `ride_along_credit_cents` to 0".

    A commitment carrying a 600-cent credit moves the whole amount across on
    revocation.

    Design: Difficulty/compensating_invariant/commitment_revoke_conserves_ride_along_credit
    """
    stack, run, transition = _in_transit_with_ride_along()
    api_client.complete_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    before = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert before["ride_along_credit_cents"] == pytest.approx(600.0, abs=0.01)
    api_client.revoke_shipper_commitment(stack["commitment"]["id"],
                                         TEST_USERS["shipper_partnership_headers"])
    after = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert after["ride_along_credit_cents"] == pytest.approx(0.0, abs=0.01)
    assert after["billed_ride_along_cents"] == pytest.approx(600.0, abs=0.01)


def test_revoke_conserves_the_credit_ledger_sum(api, any_headers):
    """PRD §3.2: "so the sum of the two readings is conserved across the
    revocation rather than lost."
    PRD §3.2: "revoking a commitment that is `CONFIRMED` or `SHIPPED` moves its
    `commitment_status` to `REVOKED`, moves the whole of
    `ride_along_credit_cents` into `billed_ride_along_cents`".

    Design: Difficulty/compensating_invariant/commitment_revoke_conserves_ride_along_credit
    """
    stack, run, transition = _in_transit_with_ride_along()
    api_client.complete_run_plan(run["id"], TEST_USERS["carrier_dispatcher_headers"])
    before = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    sum_before = before["ride_along_credit_cents"] + before["billed_ride_along_cents"]
    api_client.revoke_shipper_commitment(stack["commitment"]["id"],
                                         TEST_USERS["shipper_partnership_headers"])
    after = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    sum_after = after["ride_along_credit_cents"] + after["billed_ride_along_cents"]
    assert sum_after == pytest.approx(sum_before, abs=0.01)
    assert after["commitment_status"] == "REVOKED"


# ─── corner: state_machines/corridor_validate_from_planned_returns_invalid_state

def test_launch_validate_from_planned_is_refused(api, any_headers):
    """PRD §3.1: "the corridor must actually be in `PLANNED` (anything else is
    `ERR_INVALID_STATE`, 409)".
    PRD §2.4: "A freshly registered corridor is `FROZEN` — registration itself
    reports `posture` as `FROZEN` until launch readiness is formally opened".

    A validate call against a corridor that has never opened review is refused.

    Design: Corner/state_machines/corridor_validate_from_planned_returns_invalid_state
    """
    stack = setup_launched_corridor()
    # A fresh corridor that has not started its review.
    corridor = make_corridor(stack["origin"]["id"], stack["destination"]["id"])
    resp = api_client.validate_launch_readiness(
        corridor["id"], TEST_USERS["corridor_manager_headers"],
        {"expected_corridor_version": corridor["version"]})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api_client.get_corridor(corridor["id"], any_headers))
    assert data["corridor_status"] == "PLANNED"
    assert data["launch_authorized_at"] is None
    assert data["version"] == 1


# ─── corner: state_machines/terminal_service_window_approve_requires_dispatch_ready_run_plan

def test_apron_approval_requires_a_dispatch_ready_run_plan(api, any_headers):
    """PRD §3.9: "The referenced run must be `DISPATCH_READY` or `IN_TRANSIT`,
    or the approval is refused with `ERR_INVALID_STATE` (409)".

    Design: Corner/state_machines/terminal_service_window_approve_requires_dispatch_ready_run_plan
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"])
    resp = api_client.approve_service_window(window["id"], TEST_USERS["terminal_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    win = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], any_headers))
    assert win["window_status"] == "REQUESTED"
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    assert terminal["approved_window_count"] == 0
    assert terminal["reserved_apron_units"] == 0


# ─── corner: state_machines/carrier_offboard_with_a_live_run_plan_is_rejected

def test_offboard_carrier_with_a_live_run_plan_is_refused(api, any_headers):
    """PRD §3.6: "a carrier with no run plan in `READINESS_PENDING`,
    `DISPATCH_READY` or `IN_TRANSIT` may be offboarded to `OFFBOARDED`, while a
    carrier still holding such a run is refused with
    `ERR_CARRIER_HAS_LIVE_RUN_PLANS` (409)."

    Design: Corner/state_machines/carrier_offboard_with_a_live_run_plan_is_rejected
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    resp = api_client.offboard_carrier(stack["carrier"]["id"],
                                       TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_CARRIER_HAS_LIVE_RUN_PLANS)
    carrier = validate_success(api_client.get_carrier(stack["carrier"]["id"], any_headers))
    assert carrier["carrier_status"] == "ACTIVE"


def test_offboard_carrier_with_no_live_run_plan_succeeds(api, any_headers):
    """PRD §3.6: "a carrier with no run plan in `READINESS_PENDING`,
    `DISPATCH_READY` or `IN_TRANSIT` may be offboarded to `OFFBOARDED`".
    PRD §3.3: "Aborting cancels every apron window on the run that was `REQUESTED`
    or `APPROVED`, decrements the owning commitment's `consumed_slots` by
    exactly one so the aborted run releases its slot".

    Design: Corner/state_machines/carrier_offboard_with_a_live_run_plan_is_rejected
    """
    stack = setup_launched_corridor()
    run = create_run(stack)
    submit_run(run["id"])
    api_client.abort_run_plan(run["id"], TEST_USERS["compliance_officer_headers"])
    data = validate_success(api_client.offboard_carrier(
        stack["carrier"]["id"], TEST_USERS["compliance_officer_headers"]))
    assert data["carrier_status"] == "OFFBOARDED"


# ─── corner: validations/create_corridor_with_the_same_terminal_on_both_ends

def test_corridor_with_the_same_terminal_on_both_ends_is_refused(api, any_headers):
    """PRD §3.1: "the two terminal identifiers must be different terminals, and
    naming the same one for both is a round trip and is refused with
    `ERR_INVALID_ROUTE` (422)".

    Design: Corner/validations/create_corridor_with_the_same_terminal_on_both_ends_returns_invalid_route
    """
    origin = make_operational_terminal("PHX-WEST")
    resp = api_client.create_corridor(
        {"corridor_name": "Loop Route", "origin_terminal_id": origin["id"],
         "destination_terminal_id": origin["id"], "highway_segment_miles": 40,
         "mapped_route": {"route_code": "LOOP-01", "waypoint_count": 4,
                          "has_hov_lane": True, "requires_tunnel_clearance": False},
         "weather_profile": "CLEAR_DEFAULT"},
        TEST_USERS["corridor_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_ROUTE)
    listing, meta = api_client.list_corridors(any_headers), None
    data = validate_success(listing)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert len(rows) == 0, "nothing was persisted for the refused corridor"


# ─── corner: validations/create_run_plan_with_three_trailers ────────────────

def test_run_plan_with_three_trailers_is_refused(api, any_headers):
    """PRD §3.2: "`trailer_count` must be exactly 1 or exactly 2 — every other
    value is `ERR_INVALID_TRAILER_COUNT` (422)".

    Design: Corner/validations/create_run_plan_with_three_trailers_returns_invalid_trailer_count
    """
    stack = setup_launched_corridor()
    resp = api_client.create_run_plan(
        _run_payload(stack, trailer_count=3),
        TEST_USERS["carrier_dispatcher_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_TRAILER_COUNT)


def test_run_plan_accepts_trailer_counts_one_and_two(api, any_headers):
    """PRD §3.2: "`trailer_count` must be exactly 1 or exactly 2 — every other
    value is `ERR_INVALID_TRAILER_COUNT` (422)".

    The accepted set is exactly {1, 2}.

    Design: Corner/validations/create_run_plan_with_three_trailers_returns_invalid_trailer_count
    """
    stack = setup_launched_corridor()
    one = validate_success(api_client.create_run_plan(
        _run_payload(stack, trailer_count=1),
        TEST_USERS["carrier_dispatcher_headers"]), expected_status=201)
    two = validate_success(api_client.create_run_plan(
        _run_payload(stack, trailer_count=2, window_start_epoch_day=14,
                                    window_end_epoch_day=16),
        TEST_USERS["carrier_dispatcher_headers"]), expected_status=201)
    assert one["trailer_count"] == 1
    assert two["trailer_count"] == 2


# ─── corner: consistency_model/immediate_consistency_all_side_effects_visible

def test_abort_side_effects_are_visible_on_the_immediate_read(api, any_headers):
    """PRD §2.4: "filing a critical incident, voiding an inspection programme,
    letting a calibration window lapse, or rolling the ledger epoch will all
    reach upward and move corridor posture, corridor status, carrier standing,
    terminal staffing and apron reservations in the same operation."

    Design: Corner/consistency_model/immediate_consistency_all_side_effects_visible_in_one_response
    """
    stack, run, window = _dispatch_ready_run()
    api_client.abort_run_plan(run["id"], TEST_USERS["compliance_officer_headers"])
    run = validate_success(api_client.get_run_plan(run["id"], any_headers))
    win = validate_success(api_client.get_service_window(
        stack["origin"]["id"], window["id"], any_headers))
    terminal = validate_success(api_client.get_terminal(stack["origin"]["id"], any_headers))
    commitment = validate_success(api_client.get_shipper_commitment(
        stack["commitment"]["id"], any_headers))
    assert run["run_status"] == "ABORTED"
    assert win["window_status"] == "CANCELLED"
    assert terminal["reserved_apron_units"] == 0
    assert terminal["approved_window_count"] == 0
    assert commitment["consumed_slots"] == 0
    assert commitment["remaining_slots"] == commitment["committed_slots"]