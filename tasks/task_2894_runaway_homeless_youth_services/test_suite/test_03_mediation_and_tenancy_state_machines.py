"""Non-linear state machines: a counter-bounded cycle and two parallel dimensions.

A reunification case loops back through mediation until its round ceiling stops
it, while a transitional-living placement carries an occupancy dimension and a
savings dimension that advance on independent axes.
"""

from test_helpers import (
    ApiErrorId,
    COORDINATOR,
    SPECIALIST,
    assert_instant_equals,
    assert_mediation_session,
    assert_reunification_case,
    assert_tlp_placement,
    fetch_case,
    fetch_placement,
    instant,
    intake_youth,
    mediation_session_payload,
    move_clock,
    open_case,
    post_savings_entry,
    record_session_outcome,
    run_review,
    schedule_session,
    setup_placement_at_days_elapsed,
    validate_error,
    validate_paginated,
)

# ─── Instance: the mediation cycle is bounded at three rounds ───

LAPS = (
    (instant("2026-08-03", "14:00:00"), instant("2026-08-03", "15:00:00"), "PROGRESS"),
    (instant("2026-08-07", "14:00:00"), instant("2026-08-07", "15:00:00"), "IMPASSE"),
    (instant("2026-08-11", "14:00:00"), instant("2026-08-11", "15:00:00"), "IMPASSE"),
)
FOURTH_WINDOW = (instant("2026-08-15", "14:00:00"), instant("2026-08-15", "15:00:00"))


def _case_after_three_held_rounds():
    """A case driven through three complete schedule-then-record laps, each lap
    starting more than seventy-two hours after the previous session was held."""
    youth = intake_youth(
        legal_first_name="Mia",
        legal_last_name="Alvarez",
        date_of_birth="2010-03-15",
        unaccompanied=True,
    )
    case = open_case(youth["id"], youth["version"],
                     household_label="Alvarez household - maternal aunt")
    sessions = []
    for start_at, end_at, outcome in LAPS:
        session = schedule_session(case["id"], start_at, end_at)
        move_clock(end_at)
        sessions.append(record_session_outcome(session["id"], outcome, SPECIALIST))
    return youth, case, sessions


def test_each_mediation_lap_raises_the_round_number_and_the_case_round(api):
    """PRD §3.6: "The server stores the session against its case through `case_id`,
    sets `round_number` to the case's current `mediation_round` plus one, records
    `scheduler_user_id`, and leaves `outcome` and `held_at` null."
    PRD §3.6: "An accepted recording stores the outcome, stamps `held_at` with the
    clock instant, records the acting identifier as `recorded_by_user_id` — the
    value that later governs who may decide the case — and raises the case's
    `mediation_round` by one, moving the case `MEDIATION_SCHEDULED →
    MEDIATION_HELD`."
    PRD §3.6: "A new case opens in `status` `OPENED` with `opened_at` stamped from
    the clock, `mediation_round` at 0, `max_mediation_rounds` fixed by the server
    at 3, `safety_assessment_result` null, `aftercare_plan_due_at` null,
    `aftercare_contacts_completed` at 0 and `closed_at` null."

    Design: Difficulty/non_linear_state_machine/reunification_case_mediation_cycle_bounded_at_three_rounds
    """
    _youth, case, sessions = _case_after_three_held_rounds()

    assert [session["round_number"] for session in sessions] == [1, 2, 3], (
        "each lap numbers its session one higher than the last, got "
        f"{[session['round_number'] for session in sessions]}"
    )
    for session in sessions:
        assert_mediation_session(session)
    assert_instant_equals(sessions[-1]["held_at"], instant("2026-08-11", "15:00:00"),
                          "the third session's held_at")

    current = fetch_case(case["id"])
    assert_reunification_case(current)
    assert current["mediation_round"] == 3, (
        f"three held rounds raise the case's round to 3, got {current['mediation_round']}"
    )
    assert current["max_mediation_rounds"] == 3, (
        f"the server fixes the ceiling at 3, got {current['max_mediation_rounds']}"
    )
    assert current["status"] == "MEDIATION_HELD", (
        f"the case rests in MEDIATION_HELD after the third recording, got {current['status']}"
    )


def test_fourth_scheduling_attempt_exhausts_the_round_ceiling(api):
    """PRD §3.6: "The loop `MEDIATION_HELD → MEDIATION_SCHEDULED → MEDIATION_HELD`
    is genuine and is bounded only by the round ceiling: the case's
    `mediation_round` must be strictly below its `max_mediation_rounds` of 3, and a
    fourth attempt is refused with `ERR_MEDIATION_ROUNDS_EXHAUSTED`."
    PRD §3.6: "Sessions of a case can be listed in creation order."

    Design: Difficulty/non_linear_state_machine/reunification_case_mediation_cycle_bounded_at_three_rounds
    """
    _youth, case, _sessions = _case_after_three_held_rounds()

    response = api.create_mediation_session(
        case["id"], mediation_session_payload(*FOURTH_WINDOW), SPECIALIST
    )
    validate_error(response, ApiErrorId.ERR_MEDIATION_ROUNDS_EXHAUSTED.value)

    rows, meta = validate_paginated(api.list_mediation_sessions(case["id"], SPECIALIST))
    assert meta["total_count"] == 3, (
        f"the refused fourth attempt persisted no session, got {meta['total_count']}"
    )
    assert len(rows) == 3, f"three sessions were scheduled in total, got {len(rows)}"

    still_open = fetch_case(case["id"])
    assert still_open["status"] == "MEDIATION_HELD", (
        "the exhausted ceiling leaves the case in its non-terminal held state, got "
        f"{still_open['status']}"
    )
    assert still_open["mediation_round"] == 3, (
        f"the refusal raises no counter, got {still_open['mediation_round']}"
    )


# ─── Instance: tenancy and compliance dimensions move independently ───

TLP_PROGRAM = {
    "name": "Northside Transitional Living",
    "licensed_bed_capacity": 3,
    "min_age_years": 16,
    "max_age_years": 20,
    "max_placement_days": 540,
    "savings_match_rate_bp": 2500,
    "required_savings_rate_bp": 2000,
}
NOA = {
    "legal_first_name": "Noa",
    "legal_last_name": "Feld",
    "date_of_birth": "2010-03-15",
    "unaccompanied": True,
}
DAY_61 = instant("2026-10-01")


def _placement_on_second_probation_review():
    """A placement whose savings balance is empty two savings months in, reviewed
    once on day sixty and again on day sixty-one."""
    setup = setup_placement_at_days_elapsed(
        60,
        documented_monthly_income_cents=120000,
        tlp_program_overrides=dict(TLP_PROGRAM),
        youth_overrides=dict(NOA),
    )
    setup["review_one"] = run_review(setup["placement"]["id"])
    move_clock(DAY_61)
    setup["review_two"] = run_review(setup["placement"]["id"])
    return setup


def test_second_consecutive_probation_review_gives_tenancy_notice(api):
    """PRD §3.8: "The number of full elapsed months is `days_elapsed` divided by
    thirty and floored. The monthly requirement in cents is the placement's
    `documented_monthly_income_cents` multiplied by the program's
    `required_savings_rate_bp`, divided by 10000 and floored to whole cents.
    `required_savings_cents` is that monthly requirement multiplied by the number of
    full elapsed months — so a youth in the first thirty days of a placement owes
    nothing at all."
    PRD §3.8: "Otherwise a balance at or above half the required savings, that half
    being floored to whole cents, lands on `SAVINGS_DEFICIENT`. Otherwise the review
    lands on `PROBATION`."
    PRD §3.7: "A second consecutive savings-probation review also gives notice, and
    this is the **only** coupling between the two dimensions: when
    `consecutive_probation_reviews` reaches two while the tenancy is still `PLACED`,
    the tenancy moves to `NOTICE_GIVEN` while `compliance_status` stays `PROBATION`."

    Design: Difficulty/non_linear_state_machine/tlp_placement_parallel_tenancy_and_compliance_dimensions_move_independently
    """
    setup = _placement_on_second_probation_review()
    first, second = setup["review_one"], setup["review_two"]

    assert first["required_savings_cents"] == 48000, (
        "two full savings months at 24000 cents each require 48000 cents, got "
        f"{first['required_savings_cents']}"
    )
    assert first["compliance_status"] == "PROBATION", (
        "an empty balance sits below half of the requirement, got "
        f"{first['compliance_status']}"
    )
    assert first["consecutive_probation_reviews"] == 1, (
        f"the first probation review counts one, got {first['consecutive_probation_reviews']}"
    )
    assert first["tenancy_status"] == "PLACED", (
        f"one probation review leaves the tenancy alone, got {first['tenancy_status']}"
    )

    assert_tlp_placement(second)
    assert second["consecutive_probation_reviews"] == 2, (
        f"the second probation review counts two, got {second['consecutive_probation_reviews']}"
    )
    assert second["compliance_status"] == "PROBATION", (
        f"the compliance dimension stays on probation, got {second['compliance_status']}"
    )
    assert second["tenancy_status"] == "NOTICE_GIVEN", (
        "two consecutive probation reviews give notice on the tenancy, got "
        f"{second['tenancy_status']}"
    )


def test_recovered_compliance_does_not_undo_the_tenancy_notice(api):
    """PRD §3.8: "Three outcomes are possible and they are evaluated as inclusive
    comparisons, so an exactly-met requirement counts as met. A balance at or above
    `required_savings_cents` lands on `IN_COMPLIANCE`."
    PRD §3.8: "In short, any review that does not land on `PROBATION` resets the
    consecutive-probation counter to zero, and any review that lands on `PROBATION`
    raises it by one."
    PRD §3.7: "The two dimensions evolve independently: a compliance review never
    moves the tenancy dimension except in the single coupled case described below,
    and a tenancy change never alters `compliance_status` at all."

    Design: Difficulty/non_linear_state_machine/tlp_placement_parallel_tenancy_and_compliance_dimensions_move_independently
    """
    setup = _placement_on_second_probation_review()
    placement_id = setup["placement"]["id"]

    entry = post_savings_entry(placement_id, "DEPOSIT", 38400,
                               source_note="catch-up deposit", headers=COORDINATOR)
    assert entry["match_component_cents"] == 9600, (
        "38400 cents at 2500 basis points matches 9600 cents, got "
        f"{entry['match_component_cents']}"
    )

    third = run_review(placement_id)
    assert third["savings_balance_cents"] == 48000, (
        "38400 deposited plus 9600 matched cents is exactly the 48000-cent "
        f"requirement, got {third['savings_balance_cents']}"
    )
    assert third["match_awarded_cents"] == 9600, (
        f"the placement's match total is 9600 cents, got {third['match_awarded_cents']}"
    )
    assert third["compliance_status"] == "IN_COMPLIANCE", (
        "an exactly-met requirement counts as met, got "
        f"{third['compliance_status']}"
    )
    assert third["consecutive_probation_reviews"] == 0, (
        "a review that does not land on probation resets the counter, got "
        f"{third['consecutive_probation_reviews']}"
    )
    assert third["tenancy_status"] == "NOTICE_GIVEN", (
        "the notice already given is not undone by recovered compliance, got "
        f"{third['tenancy_status']}"
    )

    current = fetch_placement(placement_id)
    assert current["days_elapsed"] == 61, (
        f"sixty-one whole days have elapsed, got {current['days_elapsed']}"
    )
    assert current["consumed_ratio_bp"] == 1129, (
        "61 times 10000 divided by 540 floors to 1129 basis points, got "
        f"{current['consumed_ratio_bp']}"
    )
    assert current["allowance_days"] == 540, (
        f"no curriculum hours are credited, so the allowance is the base 540 days, "
        f"got {current['allowance_days']}"
    )
