"""The confirmation gate sequence, from full satisfaction to each refusal.

Confirmation is where the program's fifteen gates all bite at once, so this file
walks them one at a time: the fully satisfied path that must fire every declared
side effect, the sub-gate that must pre-empt the aggregate readiness gate, the
two request-time refusals that carry their own semantic codes instead of the
generic shape error, and the aggregate and cross-entity gates whose verdicts
depend on rows other than the one being confirmed.
"""
from test_helpers import (
    ERR_CANDIDATE_NOT_READY,
    ERR_COMMUTE_LIMIT_EXCEEDED,
    ERR_FINGERPRINT_CLEARANCE_REQUIRED,
    ERR_PLACEMENT_CAP_EXCEEDED,
    ERR_SUBJECT_BAND_NOT_ALLOWED,
    ERR_SUPERVISOR_CASELOAD_EXCEEDED,
    ERR_TERM_OUTSIDE_AGREEMENT_WINDOW,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    add_teacher,
    assert_agreement_ledger,
    assert_caseload,
    assert_date_equals,
    assert_placement_dimensions,
    assert_stipend,
    confirm,
    factories as f,
    open_request,
    read_agreement,
    read_candidate,
    read_item,
    read_placement,
    read_request,
    read_supervisor,
    read_teacher,
    route,
    setup_bench,
    setup_proposed_placement,
    setup_ready_candidate,
    validate_error,
    validate_page,
    validate_success,
)

STATE_ONLY_CLEARANCE = {"clearance_scope": "STATE_ONLY"}
TWELVE_CREDITS = {"credits": 12}
TIGHT_CEILING = {"max_caseload_points_override": 2}
SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
SECOND_HOME = {"home_grid_x": 2, "home_grid_y": 5}
ABOVE_THE_PROGRAM_CEILING = 60
LATE_TERM_START = "2026-12-01"
LATE_TERM_END = "2027-03-08"
PROVISIONAL_GROSS_CENTS = 181468
PROVISIONAL_TRAVEL_CENTS = 137886


def test_confirmation_fires_every_declared_side_effect(api):
    """Both dimensions advance and the money settles provisionally in one call.

    PRD §3.6: "the placement moves `PROPOSED → ACTIVE` ... its `stipend_status`
    moves `NOT_ACCRUED → ACCRUED` with the provisional stipend and the travel
    reimbursement computed as described in §3.4, the owning request moves
    `ROUTED → MATCHED`, the agreement's `seats_reserved` falls by one while
    `seats_committed` rises by one and `stipend_committed_cents` rises by the
    accrued gross, and both the supervisor's `caseload_points` and the teacher's
    `active_placement_count` are re-derived."

    Design: Corner/validations/confirmation_succeeds_when_every_gate_is_satisfied
    """
    scenario = setup_proposed_placement(api)

    confirmed = confirm(api, scenario.placement_id)

    assert_placement_dimensions(confirmed, "ACTIVE", "ACCRUED")
    assert_stipend(confirmed, variant="PROVISIONAL", weekly_cents=12962,
                   weeks_credited=14, gross_cents=PROVISIONAL_GROSS_CENTS,
                   travel_cents=PROVISIONAL_TRAVEL_CENTS)
    assert read_request(api, scenario.request_id)["status"] == "MATCHED"
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=PROVISIONAL_GROSS_CENTS,
                            capacity_posture="CAP_REACHED")
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 3)
    assert read_teacher(api, scenario.teacher_id)["active_placement_count"] == 1


def test_the_fingerprint_subgate_pre_empts_the_readiness_gate(api):
    """A STATE_ONLY clearance earns the 35 points and still fails the sub-gate.

    PRD §3.6: "a `STATE_ONLY` clearance is not enough for such a district, even
    though it is enough to earn the 35 readiness points. A candidate without one
    is refused with `ERR_FINGERPRINT_CLEARANCE_REQUIRED` ... Because the sub-gate
    precedes the aggregate gate, a candidate who is both short of 90 points *and*
    missing the district fingerprint receives the fingerprint error, never the
    readiness error."

    Design: Corner/validations/fingerprint_subgate_runs_before_the_readiness_gate
    """
    scenario = setup_proposed_placement(api, clearance=STATE_ONLY_CLEARANCE)

    validate_error(api.confirm_placement(scenario.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_FINGERPRINT_CLEARANCE_REQUIRED, 422)

    candidate = read_candidate(api, scenario.candidate_id)
    assert candidate["readiness_score"] == 90, (
        "the priority-25 gate would have passed on points alone")
    assert candidate["readiness_status"] == "READY"
    district = validate_success(api.get_district(scenario.district_id,
                                                 PROGRAM_ADMIN))
    assert district["requires_district_fingerprint"] is True
    assert read_item(api, scenario.clearance_item["id"])["clearance_scope"] == (
        "STATE_ONLY")
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "PROPOSED", "NOT_ACCRUED")


def _a_ready_candidate_on_the_bench(api, **coursework):
    """The organisation bench plus one candidate, ready or deliberately short."""
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario, coursework=coursework or None)
    return scenario


def _two_proposals_under_a_single_seat(api):
    """Two routed proposals on two mentors, sharing an agreement capped at one."""
    scenario = setup_bench(api)
    add_teacher(api, scenario, **SECOND_SITE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id)
    scenario.placement = route(api, scenario.request_id)
    second = setup_ready_candidate(api, candidate=SECOND_HOME)
    second.request = open_request(api, second.candidate_id,
                                  preferred_district_id=scenario.district_id)
    second.placement = route(api, second.request_id)
    return scenario, second


def test_a_commute_ask_above_forty_five_miles_is_refused_at_creation(api):
    """60 is a legal integer and an illegal ask, so the code is semantic.

    PRD §3.5: "`max_commute_miles` is an integer from 1 through 200 in shape, but
    the program will not tolerate a commute beyond 45 miles under any
    circumstances, so a request asking for more than 45 is refused with
    `ERR_COMMUTE_LIMIT_EXCEEDED`."

    Design: Corner/validations/commute_limit_above_the_program_maximum_returns_commute_limit_exceeded
    """
    scenario = _a_ready_candidate_on_the_bench(api)

    validate_error(api.create_placement_request(
        f.placement_request_payload(
            scenario.candidate_id,
            preferred_district_id=scenario.district_id,
            max_commute_miles=ABOVE_THE_PROGRAM_CEILING),
        PLACEMENT_COORDINATOR), ERR_COMMUTE_LIMIT_EXCEEDED, 422)

    rows, meta = validate_page(api.list_placement_requests(
        PLACEMENT_COORDINATOR, {"candidate_id": scenario.candidate_id}))
    assert rows == []
    assert meta["total_count"] == 0


def test_a_subject_outside_the_agreement_list_is_refused_before_the_matcher(api):
    """SCIENCE is not in [MATH, ELA], and that answer arrives before the search.

    PRD §3.5: "The `requested_subject` and `requested_grade_band` must both appear
    in that `ACTIVE` agreement's `allowed_subjects` and `allowed_grade_bands`,
    failing which the answer is `ERR_SUBJECT_BAND_NOT_ALLOWED`".

    Design: Corner/validations/a_subject_outside_the_agreement_allowed_list_returns_subject_band_not_allowed
    """
    scenario = _a_ready_candidate_on_the_bench(api)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id,
                                    requested_subject="SCIENCE")
    assert read_agreement(api, scenario.agreement_id)["allowed_subjects"] == [
        "MATH", "ELA"]

    validate_error(api.route_request(scenario.request_id, PLACEMENT_COORDINATOR),
                   ERR_SUBJECT_BAND_NOT_ALLOWED, 422)

    request = read_request(api, scenario.request_id)
    assert request["status"] == "SUBMITTED", "never ROUTED, never FAILED"
    assert request["routing_round"] == 0
    _rows, meta = validate_page(api.list_placements(PLACEMENT_COORDINATOR))
    assert meta["total_count"] == 0


def test_a_term_ending_past_the_agreement_window_is_refused_at_routing(api):
    """A start inside the window is not enough when the end falls outside it.

    PRD §3.5: "the request's whole term interval from `term_start_date` through
    `term_end_date` must lie inside the agreement's interval from `window_start`
    through `window_end`, failing which the answer is
    `ERR_TERM_OUTSIDE_AGREEMENT_WINDOW`."  PRD §3.5: "the system computes
    `term_end_date` as the start date plus seven days per scheduled week, minus
    one day".

    Design: Corner/validations/a_term_extending_past_the_agreement_window_returns_term_outside_agreement_window
    """
    scenario = _a_ready_candidate_on_the_bench(api)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id,
                                    term_start_date=LATE_TERM_START)
    assert_date_equals(scenario.request["term_end_date"], LATE_TERM_END,
                       "term_end_date")
    assert_date_equals(read_agreement(api, scenario.agreement_id)["window_end"],
                       "2027-01-31", "window_end")

    validate_error(api.route_request(scenario.request_id, PLACEMENT_COORDINATOR),
                   ERR_TERM_OUTSIDE_AGREEMENT_WINDOW, 422)

    assert read_request(api, scenario.request_id)["status"] == "SUBMITTED"
    _rows, meta = validate_page(api.list_placements(PLACEMENT_COORDINATOR))
    assert meta["total_count"] == 0


def test_the_second_confirmation_hits_the_seat_cap_the_first_one_filled(api):
    """Routing over-subscribes on purpose; the cap bites only at confirmation.

    PRD §3.6: "Finally the agreement's `seats_committed` must be strictly below
    its `placement_cap`. Routing was allowed to over-subscribe with proposals, so
    this is the only place the hard cap bites, and an agreement already at its cap
    answers `ERR_PLACEMENT_CAP_EXCEEDED`."

    Design: Corner/validations/a_second_confirmation_beyond_the_seat_cap_returns_placement_cap_exceeded
    """
    scenario, second = _two_proposals_under_a_single_seat(api)
    confirm(api, scenario.placement_id)

    validate_error(api.confirm_placement(second.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_PLACEMENT_CAP_EXCEEDED, 409)

    agreement = read_agreement(api, scenario.agreement_id)
    assert agreement["status"] == "ACTIVE", "a perfectly healthy agreement"
    assert agreement["placement_cap"] == 1
    assert_agreement_ledger(agreement, seats_reserved=1, seats_committed=1,
                            stipend_committed_cents=PROVISIONAL_GROSS_CENTS,
                            capacity_posture="CAP_REACHED")
    assert_placement_dimensions(read_placement(api, second.placement_id),
                                "PROPOSED", "NOT_ACCRUED")


def test_a_caseload_that_fitted_while_proposed_is_refused_at_confirmation(api):
    """2 points fit under a ceiling of 2; the ACTIVE re-score needs 3.

    PRD §3.6: "The supervisor's `caseload_points` is re-scored with this placement
    moved from its `PROPOSED` base of 1 point to its `ACTIVE` base of 2 points,
    keeping the same distance surcharge, and the resulting total must remain no
    greater than `max_caseload_points`; a placement that fitted comfortably while
    proposed can therefore still be refused here, with
    `ERR_SUPERVISOR_CASELOAD_EXCEEDED`."  PRD §3.4: "`accepting_new_placements`
    ... is additionally forced to false by any caseload recomputation that finds
    `caseload_points` at or above `max_caseload_points`".

    Design: Corner/validations/a_caseload_that_fit_at_routing_exceeds_the_cap_at_confirmation
    """
    scenario = setup_proposed_placement(api, supervisor=TIGHT_CEILING)
    before = read_supervisor(api, scenario.supervisor_id)
    assert_caseload(before, 2, max_caseload_points=2)
    assert before["accepting_new_placements"] is False

    validate_error(api.confirm_placement(scenario.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_SUPERVISOR_CASELOAD_EXCEEDED, 409)

    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "PROPOSED"
    assert placement["supervisor_points"] == 2
    # The refused confirmation did not charge the extra point.
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 2)


def test_a_candidate_eighty_five_points_short_of_ready_cannot_be_routed(api):
    """The readiness gate guards routing, not just confirmation.

    PRD §3.5: "Before the matcher runs, the owning candidate's readiness is
    re-evaluated under the `STRICT` variant and must leave `readiness_status` at
    `READY`, failing which the routing attempt is refused with
    `ERR_CANDIDATE_NOT_READY`."  PRD §3.2: "a 12-credit block earns 10 ...
    `READY` requires a `readiness_score` of at least 90".

    Design: Corner/validations/a_candidate_below_the_ready_threshold_cannot_be_routed
    """
    scenario = _a_ready_candidate_on_the_bench(api, **TWELVE_CREDITS)
    scenario.request = open_request(api, scenario.candidate_id,
                                    preferred_district_id=scenario.district_id)

    validate_error(api.route_request(scenario.request_id, PLACEMENT_COORDINATOR),
                   ERR_CANDIDATE_NOT_READY, 422)

    candidate = read_candidate(api, scenario.candidate_id)
    assert candidate["readiness_score"] == 85, "40 exam + 35 clearance + 10 credits"
    assert candidate["readiness_status"] == "NOT_READY"
    assert read_request(api, scenario.request_id)["status"] == "SUBMITTED"
    _rows, meta = validate_page(api.list_placements(PLACEMENT_COORDINATOR))
    assert meta["total_count"] == 0
