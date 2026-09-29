"""Destroy-and-recreate pairs, checked against what must not change.

A reroute voids one proposal and creates its replacement in a single request, so
the agreement's reserved seats, the supervisor's caseload points and the sum of
the mentors' active placements must all come out exactly where they went in.  A
clawback undoes a payment that already left the program, so the agreement's
committed money must return to its pre-confirmation zero — not to a negative
figure, and not to the paid amount a missed re-derivation would leave.
"""
from test_helpers import (
    PLACEMENT_COORDINATOR,
    PROGRAM_ADMIN,
    SUPERVISION_LEAD,
    add_teacher,
    assert_agreement_ledger,
    assert_caseload,
    assert_date_equals,
    assert_instant_equals,
    assert_placement_dimensions,
    assert_stipend,
    factories as f,
    open_request,
    read_agreement,
    read_placement,
    read_request,
    read_supervisor,
    read_teacher,
    route,
    setup_bench,
    setup_completed_placement,
    setup_ready_candidate,
    validate_success,
)

# A second mentor one grid mile further out: the commute rises 14 -> 15 miles but
# both sites stay inside the supervisor's 16..40-mile surcharge band.
SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
SETTLED_GROSS_CENTS = 183968


def _one_proposal_and_a_spare_mentor(api):
    """A proposed placement on the nearer mentor, with a second one available."""
    scenario = setup_bench(api)
    add_teacher(api, scenario, **SECOND_SITE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                   preferred_district_id=scenario.district_id)
    scenario.placement = route(api, scenario.request_id)
    return scenario


def _paid_placement_under_a_disqualified_mentor(api):
    """A completed placement whose stipend was paid before misconduct surfaced."""
    scenario = setup_completed_placement(api)
    for target, note in (("APPROVED", "End-of-term stipend approval."),
                         ("PAID", "Disbursed with the December payroll.")):
        validate_success(api.transition_stipend(
            scenario.placement_id,
            f.stipend_transition_payload(target, note=note), PROGRAM_ADMIN))
    validate_success(api.disqualify_teacher(
        scenario.teacher_id,
        f.disqualify_payload(
            disqualification_reason="Substantiated misconduct finding after payroll."),
        SUPERVISION_LEAD))
    return scenario


def test_the_reroute_supersedes_the_proposal_without_failing_the_request(api):
    """The void and the replacement happen in one 201, and the request stays ROUTED.

    PRD §3.5: "The current `PROPOSED` placement moves `PROPOSED → VOIDED` with
    `voided_reason` set to `REROUTED`, and because the reason is `REROUTED`
    rather than `AGREEMENT_SUSPENDED` the request deliberately stays `ROUTED`
    instead of falling back to `SUBMITTED`: this is a supersede, not a failure
    ... `reroute_count` rises by one, `routing_round` is untouched".

    Design: Difficulty/compensating_invariant/reroute_conserves_agreement_seats_and_supervisor_caseload
    """
    scenario = _one_proposal_and_a_spare_mentor(api)
    before = read_request(api, scenario.request_id)
    assert scenario.placement["cooperating_teacher_id"] == scenario.teacher_id, (
        "the nearer mentor wins the first round on commute distance")

    replacement = validate_success(api.reroute_request(
        scenario.request_id, f.reroute_payload(before["version"]),
        PLACEMENT_COORDINATOR), 201)

    assert replacement["cooperating_teacher_id"] == scenario.second_teacher["id"]
    assert replacement["commute_miles"] == 15
    assert replacement["placement_status"] == "PROPOSED"

    voided = read_placement(api, scenario.placement_id)
    assert voided["placement_status"] == "VOIDED"
    assert voided["voided_reason"] == "REROUTED"

    after = read_request(api, scenario.request_id)
    assert after["status"] == "ROUTED"
    assert after["reroute_count"] == 1
    assert after["routing_round"] == before["routing_round"]
    assert after["excluded_cooperating_teacher_ids"] == [scenario.teacher_id]
    assert after["current_placement_id"] == replacement["id"]
    assert after["version"] == before["version"] + 1


def test_the_reroute_conserves_every_occupancy_counter(api):
    """One seat, two caseload points and one mentor slot, before and after.

    PRD §3.5: "the seat, headcount and caseload counters are re-derived so that
    the void-and-create pair leaves `seats_reserved`, `active_placement_count`
    and `caseload_points` exactly where they were."  PRD §3.4: "The distance
    surcharge is derived from the Manhattan distance between the supervisor's
    base and the teacher's site: 0 points when that distance is 15 miles or
    less, 1 point when it is from 16 through 40 miles".

    Design: Difficulty/compensating_invariant/reroute_conserves_agreement_seats_and_supervisor_caseload
    """
    scenario = _one_proposal_and_a_spare_mentor(api)
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0)
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 2)

    replacement = validate_success(api.reroute_request(
        scenario.request_id,
        f.reroute_payload(read_request(api, scenario.request_id)["version"]),
        PLACEMENT_COORDINATOR), 201)

    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=0,
                            stipend_committed_cents=0,
                            capacity_posture="OPEN")
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 2)
    assert read_teacher(api, scenario.teacher_id)["active_placement_count"] == 0
    assert read_teacher(api, scenario.second_teacher["id"])[
        "active_placement_count"] == 1
    assert_placement_dimensions(read_placement(api, scenario.placement_id),
                                "VOIDED", "NOT_ACCRUED")
    assert_placement_dimensions(read_placement(api, replacement["id"]),
                                "PROPOSED", "NOT_ACCRUED")


def test_the_clawback_zeroes_the_paid_money_and_restores_the_ledger(api):
    """183968 cents leave the placement and the agreement together.

    PRD §3.9: "A clawback forces both `stipend_gross_cents` and `weeks_credited`
    to 0 and lowers `stipend_committed_cents` back to its pre-confirmation value,
    and it leaves the clinical dimension entirely alone: a `COMPLETED` placement
    whose money was clawed back stays `COMPLETED`."

    Design: Difficulty/compensating_invariant/paid_stipend_clawback_restores_agreement_committed_money
    """
    scenario = _paid_placement_under_a_disqualified_mentor(api)
    paid = read_placement(api, scenario.placement_id)
    assert paid["stipend_status"] == "PAID"
    assert_stipend(paid, variant="FINAL", weeks_credited=14,
                   gross_cents=SETTLED_GROSS_CENTS)
    assert read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"] == SETTLED_GROSS_CENTS

    clawed_back = validate_success(api.transition_stipend(
        scenario.placement_id,
        f.stipend_transition_payload("CLAWED_BACK",
                                    note="Recovering the paid stipend."),
        PROGRAM_ADMIN))

    assert clawed_back["stipend_status"] == "CLAWED_BACK"
    assert clawed_back["stipend_gross_cents"] == 0
    assert clawed_back["weeks_credited"] == 0
    committed = read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"]
    assert committed == 0, (
        "the pre-confirmation value, never a negative figure and never 183968")


def test_the_clawback_leaves_the_clinical_record_and_the_seat_alone(api):
    """The placement stays COMPLETED and the seat stays committed.

    PRD §3.9: "The agreement's `stipend_committed_cents` is re-derived from the
    new gross, but its `seats_committed` is **unchanged**, because a completed
    placement never leaves the committed set and the seat is spent for the term."
    PRD §3.9: "`PAID → CLAWED_BACK` ... is admissible only once the cooperating
    teacher's `qualification_status` is `DISQUALIFIED`".

    Design: Difficulty/compensating_invariant/paid_stipend_clawback_restores_agreement_committed_money
    """
    scenario = _paid_placement_under_a_disqualified_mentor(api)
    assert read_teacher(api, scenario.teacher_id)["qualification_status"] == (
        "DISQUALIFIED")

    validate_success(api.transition_stipend(
        scenario.placement_id, f.stipend_transition_payload("CLAWED_BACK"),
        PROGRAM_ADMIN))

    placement = read_placement(api, scenario.placement_id)
    assert placement["placement_status"] == "COMPLETED"
    assert_instant_equals(placement["completed_at"], "2026-12-08T00:00:00Z",
                          "completed_at")
    assert_date_equals(placement["settlement_date"], "2026-12-08",
                       "settlement_date")
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=0,
                            capacity_posture="CAP_REACHED")
