"""One call, two broken rules, one predictable error.

The ladder in §2.6 decides which of two simultaneous violations is reported: a
lazily expired agreement (rung 14) outranks the fiscal seat cap (rung 45), and
an invalid placement state (rung 17) outranks segregation of duties (rung 23).
Each test proves both rules really were broken before pinning the winner.
"""
from test_helpers import (
    DUAL_ROLE_USER_ID,
    ERR_AGREEMENT_EXPIRED,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_PLACEMENT_CAP_EXCEEDED,
    ERR_PLACEMENT_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    PROGRAM_ADMIN_USER_ID,
    add_teacher,
    assert_caseload,
    assert_placement_dimensions,
    confirm,
    factories as f,
    make_headers,
    open_request,
    read_agreement,
    read_placement,
    read_supervisor,
    read_teacher,
    route,
    set_clock,
    setup_active_placement,
    setup_proposed_placement,
    setup_ready_candidate,
    validate_error,
    validate_success,
)

SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
SECOND_HOME = {"home_grid_x": 2, "home_grid_y": 5}
PAST_WINDOW_CLOCK = "2027-02-01T00:00:00Z"

DUAL_COORDINATOR = make_headers(DUAL_ROLE_USER_ID, "PlacementCoordinator")
DUAL_ADMIN = make_headers(DUAL_ROLE_USER_ID, "ProgramAdmin")


def _two_proposals_one_seat(api):
    """A one-seat agreement with one confirmed placement and one still proposed."""
    scenario = setup_proposed_placement(api)
    add_teacher(api, scenario, **SECOND_SITE)
    second = setup_ready_candidate(api, candidate=dict(SECOND_HOME))
    second.request = open_request(api, second.candidate_id,
                                  preferred_district_id=scenario.district_id)
    second.placement = route(api, second.request_id)
    scenario.placement = confirm(api, scenario.placement_id)
    return scenario, second


def _dismissed_removal_case(api):
    """An active placement whose removal case was filed and then dismissed."""
    scenario = setup_active_placement(api)
    validate_success(api.request_removal(
        scenario.placement_id,
        f.removal_request_payload(
            removal_narrative="Classroom management concerns raised at week 6."),
        DUAL_COORDINATOR))
    validate_success(api.decide_removal(
        scenario.placement_id,
        f.removal_decision_payload(
            decision="DISMISSED",
            decision_note="Improvement plan accepted instead."),
        PROGRAM_ADMIN))
    return scenario


def test_the_expired_agreement_outranks_the_seat_cap_at_confirmation(api):
    """Both rungs fail; the answer is the state error, never the fiscal one.

    PRD §2.8: "An `ACTIVE` partnership agreement whose `window_end` is strictly
    earlier than the current logical-clock date becomes `EXPIRED`, and this
    check is evaluated **before every other agreement check**".  PRD §2.6 rung
    45: "The agreement's `seats_committed` is strictly below `placement_cap` at
    confirmation time".

    Design: Difficulty/priority_pair_validation_conflict/expired_agreement_state_error_outranks_placement_cap_fiscal_error
    """
    scenario, second = _two_proposals_one_seat(api)
    set_clock(api, PAST_WINDOW_CLOCK)

    error = validate_error(
        api.confirm_placement(second.placement_id, PLACEMENT_COORDINATOR),
        ERR_AGREEMENT_EXPIRED, 409)
    assert error["error_id"] not in (ERR_PLACEMENT_CAP_EXCEEDED,
                                    ERR_AGREEMENT_NOT_ACTIVE)

    agreement = read_agreement(api, scenario.agreement_id)
    assert agreement["status"] == "EXPIRED"
    assert agreement["placement_cap"] == 1
    assert agreement["seats_committed"] == 1, (
        "the fiscal cap check at rung 45 would also have failed")


def test_the_refused_confirmation_neither_consumes_nor_releases_a_seat(api):
    """A rejected confirmation settles nothing and moves no counter.

    PRD §2.10: "the reroute is rejected with `ERR_STALE_REQUEST_VERSION` and
    HTTP 412, and nothing is mutated."  PRD §3.6: "Confirmation is the
    commitment point, and it re-checks the world rather than trusting the
    proposal."

    Design: Difficulty/priority_pair_validation_conflict/expired_agreement_state_error_outranks_placement_cap_fiscal_error
    """
    scenario, second = _two_proposals_one_seat(api)
    set_clock(api, PAST_WINDOW_CLOCK)

    validate_error(api.confirm_placement(second.placement_id,
                                         PLACEMENT_COORDINATOR),
                   ERR_AGREEMENT_EXPIRED, 409)

    refused = read_placement(api, second.placement_id)
    assert_placement_dimensions(refused, "PROPOSED", "NOT_ACCRUED")
    assert refused["stipend_gross_cents"] == 0
    assert read_placement(api, scenario.placement_id)["placement_status"] == "ACTIVE"
    assert read_agreement(api, scenario.agreement_id)["seats_committed"] == 1
    assert read_teacher(api, scenario.second_teacher["id"])[
        "active_placement_count"] == 1


def test_the_invalid_placement_state_outranks_segregation_of_duties(api):
    """Replaying a decided case answers the state error, not the SoD error.

    PRD §2.6 rung 17: "The placement's `placement_status` permits the action —
    `PROPOSED` to confirm, `ACTIVE` to file a removal request or to complete,
    `REMOVAL_PENDING` to decide a removal".  PRD §2.11: "The `X-User-ID`
    recorded in `removal_requested_by_user_id` when a removal case is opened
    may not be the `X-User-ID` that decides that case".

    Design: Difficulty/priority_pair_validation_conflict/invalid_placement_state_error_outranks_segregation_of_duties_error
    """
    scenario = _dismissed_removal_case(api)
    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "ACTIVE"
    assert placement["removal_requested_by_user_id"] == DUAL_ROLE_USER_ID, (
        "the trigger acts with exactly this id, so the SoD rule is violated too")

    error = validate_error(api.decide_removal(
        scenario.placement_id,
        f.removal_decision_payload(decision="UPHELD",
                                   decision_note="Reopening the same removal."),
        DUAL_ADMIN), ERR_PLACEMENT_STATE_INVALID, 409)
    assert error["error_id"] != ERR_SEGREGATION_OF_DUTIES


def test_a_dismissal_retains_the_audit_trail_the_replay_cannot_overwrite(api):
    """The dismissed case keeps its reason, narrative and requester.

    PRD §3.9: "First, `removal_reason`, `removal_narrative` and
    `removal_requested_by_user_id` are **retained** as the permanent audit trail
    of the attempt; they are not cleared."

    Design: Difficulty/priority_pair_validation_conflict/invalid_placement_state_error_outranks_segregation_of_duties_error
    """
    scenario = _dismissed_removal_case(api)
    before = read_placement(api, scenario.placement_id)
    assert before["removal_reason"] == "CANDIDATE_PERFORMANCE"
    assert before["removal_narrative"] == (
        "Classroom management concerns raised at week 6.")
    assert before["removal_decided_by_user_id"] == PROGRAM_ADMIN_USER_ID
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 3)

    validate_error(api.decide_removal(
        scenario.placement_id, f.removal_decision_payload(), DUAL_ADMIN),
        ERR_PLACEMENT_STATE_INVALID, 409)

    after = read_placement(api, scenario.placement_id)
    assert after["removal_reason"] == before["removal_reason"]
    assert after["removal_narrative"] == before["removal_narrative"]
    assert after["removal_requested_by_user_id"] == DUAL_ROLE_USER_ID
    assert after["version"] == before["version"], "a refused call mutates nothing"
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 3)
