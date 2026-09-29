"""Declared transitions, refused transitions and the states rows start in.

Each test drives one edge of one state machine: an item's first verification and
the replay that is refused, an agreement's round trip through suspension and the
lockdown that follows termination, a request's initial counters and the second
route that cannot happen, a cycle refused at the exclusive end of its own window,
and the one removal reason that reaches into the money dimension.
"""
from test_helpers import (
    CREDENTIAL_ANALYST,
    ERR_AGREEMENT_STATE_INVALID,
    ERR_ITEM_STATE_INVALID,
    ERR_OBSERVATION_OUTSIDE_WINDOW,
    ERR_REQUEST_STATE_INVALID,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    add_coursework_item,
    assert_agreement_ledger,
    assert_date_equals,
    assert_instant_equals,
    assert_ratio_equals,
    assert_readiness,
    assert_stipend,
    create_agreement,
    create_candidate,
    create_district,
    factories as f,
    open_request,
    read_agreement,
    read_candidate,
    read_cycle,
    read_item,
    read_placement,
    read_request,
    read_supervisor,
    read_teacher,
    schedule_cycle,
    set_clock,
    setup_active_placement,
    setup_bench,
    setup_proposed_placement,
    setup_ready_candidate,
    validate_error,
    validate_page,
    validate_success,
)

CLOCK_AT_START = "2026-08-01T00:00:00Z"
FULL_COURSEWORK = {"credits": 30}
TERMINATION_REASON = "District exited the partnership."
SUSPENSION_REASON = "Site safety review."

# Cycle 1's window, and an observation offered at the exclusive upper bound.
FIRST_CYCLE = (1, "FORMATIVE", "2026-09-14T00:00:00Z", "2026-09-19T00:00:00Z")
INSIDE_THE_WINDOW_CLOCK = "2026-09-18T12:00:00Z"
LATE_OBSERVATION = "2026-09-19T00:00:00Z"

# A misconduct removal upheld 35 days into a 14-week term.
MISCONDUCT_CLOCK = "2026-10-06T00:00:00Z"
MISCONDUCT_NARRATIVE = "Substantiated site misconduct report."
FIVE_WEEK_TRAVEL_CENTS = 50652


def test_verify_a_pending_readiness_item_moves_it_to_verified(api):
    """One decision moves the item and re-scores the candidate in the same request.

    PRD §3.1: "Both decisions record `verified_by_user_id` from the acting
    principal and `verified_at` from the logical clock ... Whichever way the
    decision falls, the owning candidate's readiness is immediately recomputed
    under the `STRICT` variant".  PRD §3.2: "thirty or more credits yield the
    full 25."

    Design: Corner/state_machines/verify_a_pending_readiness_item_moves_it_to_verified
    """
    candidate = create_candidate(api)
    item = add_coursework_item(api, candidate["id"], verify=False,
                              **FULL_COURSEWORK)

    verified = validate_success(api.verify_readiness_item(
        item["id"], f.verify_item_payload(), CREDENTIAL_ANALYST))

    assert verified["status"] == "VERIFIED"
    assert_instant_equals(verified["verified_at"], CLOCK_AT_START, "verified_at")
    assert_readiness(read_candidate(api, candidate["id"]), 25, "NOT_READY", "STRICT")


def test_verify_an_already_verified_item_returns_item_state_invalid(api):
    """The replay is refused and the coursework term is not counted twice.

    PRD §3.1: "Verification is only available while the item's `status` is
    `PENDING_VERIFICATION`; anything else — including a second decision on the
    same item — is refused with `ERR_ITEM_STATE_INVALID`."

    Design: Corner/state_machines/verify_an_already_verified_item_returns_item_state_invalid
    """
    candidate = create_candidate(api)
    item = add_coursework_item(api, candidate["id"], **FULL_COURSEWORK)
    first_verified_at = item["verified_at"]

    validate_error(api.verify_readiness_item(
        item["id"], f.verify_item_payload(), CREDENTIAL_ANALYST),
        ERR_ITEM_STATE_INVALID, 409)

    unchanged = read_item(api, item["id"])
    assert unchanged["status"] == "VERIFIED"
    assert_instant_equals(unchanged["verified_at"], first_verified_at, "verified_at")
    assert read_candidate(api, candidate["id"])["readiness_score"] == 25, (
        "25, never 50: the refused replay did not re-add the coursework term")


def test_route_an_already_routed_request_returns_request_state_invalid(api):
    """route is declared from SUBMITTED only, so no second placement appears.

    PRD §3.5: "A `PlacementCoordinator` routes a request that is `SUBMITTED`; a
    request in any other status is refused with `ERR_REQUEST_STATE_INVALID` ...
    The request itself moves `SUBMITTED → ROUTED`, its `routing_round` rises by
    one, its `reroute_count` is reset to 0, and `current_placement_id` is
    re-derived to the new placement."

    Design: Corner/state_machines/route_an_already_routed_request_returns_request_state_invalid
    """
    scenario = setup_proposed_placement(api)

    validate_error(api.route_request(scenario.request_id, PLACEMENT_COORDINATOR),
                   ERR_REQUEST_STATE_INVALID, 409)

    request = read_request(api, scenario.request_id)
    assert request["status"] == "ROUTED"
    assert request["routing_round"] == 1
    assert request["current_placement_id"] == scenario.placement_id
    _rows, meta = validate_page(api.list_placements(
        PLACEMENT_COORDINATOR, params={"request_id": scenario.request_id}))
    assert meta["total_count"] == 1


def test_a_new_placement_request_starts_in_submitted_with_zero_counters(api):
    """SUBMITTED, both counters at zero, and a term end date the server computes.

    PRD §3.5: "From `term_start_date` and `weeks_scheduled` the system computes
    `term_end_date` as the start date plus seven days per scheduled week, minus
    one day — a 14-week term beginning 2026-09-01 therefore ends 2026-12-07. A
    new request is `SUBMITTED` with `routing_round` at 0, `reroute_count` at 0, an
    empty `excluded_cooperating_teacher_ids` list and a null
    `current_placement_id`."

    Design: Corner/state_machines/a_new_placement_request_starts_in_submitted_with_zero_counters
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario)

    request = open_request(api, scenario.candidate_id,
                          preferred_district_id=scenario.district_id)

    assert request["status"] == "SUBMITTED"
    assert request["routing_round"] == 0
    assert request["reroute_count"] == 0
    assert request["excluded_cooperating_teacher_ids"] == []
    assert request["current_placement_id"] is None
    assert_date_equals(request["term_end_date"], "2026-12-07", "term_end_date")


def test_a_terminated_agreement_rejects_reactivation(api):
    """TERMINATED is terminal: neither reactivation nor activation is admissible.

    PRD §3.3: "Termination is the permanent exit and can be taken from either
    `ACTIVE` or `SUSPENDED`, recording the supplied `suspension_reason` — the
    field records why the agreement left `ACTIVE`, whichever way it left ...
    `TERMINATED` and `EXPIRED` are both terminal."  PRD §2.6: "The partnership
    agreement is in a status that permits the requested lifecycle action ...
    otherwise `ERR_AGREEMENT_STATE_INVALID` (409)."

    Design: Corner/state_machines/a_terminated_agreement_rejects_reactivation
    """
    district = create_district(api)
    agreement = create_agreement(api, district["id"])
    validate_success(api.terminate_agreement(
        agreement["id"], f.terminate_payload(TERMINATION_REASON), PROGRAM_ADMIN))

    validate_error(api.reactivate_agreement(agreement["id"], PROGRAM_ADMIN),
                   ERR_AGREEMENT_STATE_INVALID, 409)
    validate_error(api.activate_agreement(agreement["id"], PROGRAM_ADMIN),
                   ERR_AGREEMENT_STATE_INVALID, 409)

    stored = read_agreement(api, agreement["id"])
    assert stored["status"] == "TERMINATED"
    assert stored["suspension_reason"] == TERMINATION_REASON


def test_activating_an_already_active_agreement_is_state_invalid(api):
    """The second activation is refused rather than quietly repeated.

    PRD §3.3: "Activation moves the agreement `DRAFT → ACTIVE` and is the moment
    it starts backing placements; it requires the agreement to be `DRAFT` ... Any
    lifecycle action attempted against the wrong status — activating a non-`DRAFT`
    agreement ... — is refused with `ERR_AGREEMENT_STATE_INVALID`."  PRD §2.4:
    "`version` is an integer that starts at `1` when the row is created and
    increases by exactly 1 on every mutation of that row."

    Design: Corner/state_machines/activating_an_already_active_agreement_returns_agreement_state_invalid
    """
    district = create_district(api)
    agreement = create_agreement(api, district["id"])
    assert agreement["status"] == "ACTIVE"

    validate_error(api.activate_agreement(agreement["id"], PROGRAM_ADMIN),
                   ERR_AGREEMENT_STATE_INVALID, 409)

    stored = read_agreement(api, agreement["id"])
    assert stored["status"] == "ACTIVE"
    assert stored["version"] == 2, (
        "one create and one successful activation; the refused call mutated nothing")


def test_suspending_then_reactivating_an_agreement_returns_it_to_active(api):
    """ACTIVE to SUSPENDED and back, with the reason cleared on the way home.

    PRD §3.3: "Reactivation returns a `SUSPENDED` agreement to `ACTIVE` and clears
    `suspension_reason` back to null, but it does **not** resurrect anything ...
    This closes the agreement cycle `ACTIVE → SUSPENDED → ACTIVE`."

    Design: Corner/state_machines/suspending_then_reactivating_an_agreement_returns_it_to_active
    """
    district = create_district(api)
    agreement = create_agreement(api, district["id"])
    suspended = validate_success(api.suspend_agreement(
        agreement["id"], f.suspend_payload(SUSPENSION_REASON), PROGRAM_ADMIN))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_reason"] == SUSPENSION_REASON

    reactivated = validate_success(
        api.reactivate_agreement(agreement["id"], PROGRAM_ADMIN))

    assert reactivated["status"] == "ACTIVE"
    assert reactivated["suspension_reason"] is None
    assert_agreement_ledger(reactivated, seats_reserved=0, seats_committed=0,
                            stipend_committed_cents=0, capacity_posture="OPEN")


def test_completing_a_cycle_at_the_window_end_instant_is_outside_the_window(api):
    """window_end is exclusive, so an observation offered on it is late.

    PRD §3.7: "`observed_at` must fall at or after `window_start` and strictly
    before `window_end`; an observation recorded exactly at `window_end` is late
    and is refused with `ERR_OBSERVATION_OUTSIDE_WINDOW`".  PRD §3.7: "A cycle is
    created `SCHEDULED` with `observed_at`, `rubric_score` and `resolution_note`
    null".

    Design: Corner/state_machines/completing_a_cycle_at_the_window_end_instant_returns_observation_outside_window
    """
    scenario = setup_active_placement(api)
    cycle = schedule_cycle(api, scenario.placement_id, *FIRST_CYCLE)
    set_clock(api, INSIDE_THE_WINDOW_CLOCK)

    validate_error(api.complete_observation_cycle(
        cycle["id"], f.cycle_complete_payload(LATE_OBSERVATION, 4.0),
        scenario.supervisor_headers), ERR_OBSERVATION_OUTSIDE_WINDOW, 422)

    unchanged = read_cycle(api, cycle["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["observed_at"] is None
    assert unchanged["rubric_score"] is None
    placement = read_placement(api, scenario.placement_id)
    assert_ratio_equals(placement["observation_compliance_ratio"], 0.0)
    assert placement["summative_completed_count"] == 0


def test_misconduct_removal_voids_the_stipend_but_not_the_travel_record(api):
    """The settled five weeks are computed, then the gross alone is forced to zero.

    PRD §3.9: "When and only when `removal_reason` is
    `COOPERATING_TEACHER_MISCONDUCT`, the money dimension additionally moves an
    `ACCRUED` or `APPROVED` stipend to `VOIDED` with `stipend_gross_cents` forced
    to 0, and the cooperating teacher's `qualification_status` becomes
    `DISQUALIFIED` with `disqualification_reason` recorded".  PRD §3.9: "Travel
    reimbursement is recomputed on whatever `weeks_credited` the settlement
    produced, using the same tier rules described in §3.6."

    Design: Corner/state_machines/misconduct_removal_voids_the_accrued_stipend_but_not_the_travel_record
    """
    scenario = setup_active_placement(api)
    set_clock(api, MISCONDUCT_CLOCK)
    validate_success(api.request_removal(
        scenario.placement_id,
        f.removal_request_payload(
            removal_reason="COOPERATING_TEACHER_MISCONDUCT",
            removal_narrative=MISCONDUCT_NARRATIVE), PLACEMENT_COORDINATOR))

    removed = validate_success(api.decide_removal(
        scenario.placement_id,
        f.removal_decision_payload("UPHELD",
                                  decision_note="Removal upheld; teacher barred."),
        PROGRAM_ADMIN))

    assert removed["placement_status"] == "REMOVED"
    assert_date_equals(removed["settlement_date"], "2026-10-06", "settlement_date")
    assert removed["stipend_status"] == "VOIDED"
    assert_stipend(removed, variant="FINAL", weekly_cents=12962, weeks_credited=5,
                   gross_cents=0, travel_cents=FIVE_WEEK_TRAVEL_CENTS)
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=0,
                            stipend_committed_cents=0, capacity_posture="OPEN")
    assert read_supervisor(api, scenario.supervisor_id)["caseload_points"] == 0
    teacher = read_teacher(api, scenario.teacher_id)
    assert teacher["qualification_status"] == "DISQUALIFIED"
    assert teacher["disqualification_reason"] == MISCONDUCT_NARRATIVE
