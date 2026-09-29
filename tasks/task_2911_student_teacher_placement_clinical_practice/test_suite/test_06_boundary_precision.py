"""Two step functions, probed on the exact rung where they change value.

The readiness gate is a hundred-point score with a discrete coursework term, so
the reachable scores bracket the READY cut without touching it: 18 credits land
exactly on 90 and 12 credits on 85.  The final settlement's week count is a
truncating division, so the last day of an eight-week term still credits seven
weeks.  Each test pins the value on the boundary and the value one rung away.
"""
from test_helpers import (
    CREDENTIAL_ANALYST,
    READY_THRESHOLD,
    assert_agreement_ledger,
    assert_date_equals,
    assert_readiness,
    assert_stipend,
    complete_placement,
    coursework_points,
    factories as f,
    read_agreement,
    read_candidate,
    read_placement,
    set_clock,
    setup_passed_assessment,
    setup_ready_candidate,
    validate_success,
)

SHORT_COURSEWORK = {"credits": 12}

# An 8-week term beginning 2026-09-01 ends 2026-10-26, and its clinical calendar
# has to fit inside that shorter term.
EIGHT_WEEK_REQUEST = {"weeks_scheduled": 8}
EIGHT_WEEK_CYCLE_PLAN = (
    (1, "FORMATIVE", "2026-09-14T00:00:00Z", "2026-09-19T00:00:00Z",
     "2026-09-16T15:00:00Z", 4.0),
    (2, "FORMATIVE", "2026-10-05T00:00:00Z", "2026-10-10T00:00:00Z",
     "2026-10-06T15:00:00Z", 4.0),
    (3, "SUMMATIVE", "2026-10-19T00:00:00Z", "2026-10-24T00:00:00Z",
     "2026-10-20T15:00:00Z", 4.5),
)
EIGHT_WEEK_ASSESSMENT = {
    "window_opens_at": "2026-10-01T00:00:00Z",
    "window_closes_at": "2026-10-25T00:00:00Z",
    "submission_clock": "2026-10-21T09:00:00Z",
}
FINAL_TERM_DAY_CLOCK = "2026-10-26T00:00:00Z"


def _eight_week_placement_ready_to_complete(api):
    """An 8-week placement observed, assessed and standing on its end_date."""
    scenario = setup_passed_assessment(api, cycle_plan=EIGHT_WEEK_CYCLE_PLAN,
                                       request=dict(EIGHT_WEEK_REQUEST),
                                       **EIGHT_WEEK_ASSESSMENT)
    set_clock(api, FINAL_TERM_DAY_CLOCK)
    return scenario


def test_ninety_points_is_ready_and_the_next_rung_down_is_not(api):
    """18 credits score exactly the cut; 12 credits score the 85 below it.

    PRD §3.2: "a candidate with a passing exam, a clearance and only 18 credits
    scores exactly 90 — the threshold itself — and is `READY`. Drop those
    credits to 12 and the score is 85, and the candidate is `NOT_READY`."

    Design: Difficulty/boundary_precision_check/readiness_score_exactly_at_the_ready_threshold_is_ready
    """
    on_the_cut = setup_ready_candidate(api)
    below_the_cut = setup_ready_candidate(api,
                                          coursework=dict(SHORT_COURSEWORK))

    at_threshold = validate_success(api.evaluate_readiness(
        on_the_cut.candidate_id, f.readiness_evaluate_payload("STRICT"),
        CREDENTIAL_ANALYST))
    assert_readiness(at_threshold, READY_THRESHOLD, "READY", "STRICT")

    under_threshold = validate_success(api.evaluate_readiness(
        below_the_cut.candidate_id, f.readiness_evaluate_payload("STRICT"),
        CREDENTIAL_ANALYST))
    assert_readiness(under_threshold, 85, "NOT_READY", "STRICT")


def test_the_five_point_gap_is_the_coursework_step_and_nothing_else(api):
    """Only the coursework term differs, and the persisted field agrees.

    PRD §3.2: "the `credits` of every counted coursework block are added
    together, that total is multiplied by 25 and divided by the 30 credits the
    program requires, the quotient is rounded half up to a whole number of
    points ... eighteen credits yield 15 points, twelve credits yield 10
    points".  PRD §3.2: "Reading a single candidate performs exactly this sweep
    and re-derives `readiness_score` and `readiness_status` under `STRICT`".

    Design: Difficulty/boundary_precision_check/readiness_score_exactly_at_the_ready_threshold_is_ready
    """
    below_the_cut = setup_ready_candidate(api,
                                          coursework=dict(SHORT_COURSEWORK))

    scored = validate_success(api.evaluate_readiness(
        below_the_cut.candidate_id, f.readiness_evaluate_payload("STRICT"),
        CREDENTIAL_ANALYST))

    assert coursework_points(18) - coursework_points(12) == 5, (
        "15 points against 10 is the whole distance to the cut")
    assert scored["readiness_score"] == READY_THRESHOLD - 5
    assert_readiness(read_candidate(api, below_the_cut.candidate_id), 85,
                     "NOT_READY")


def test_completing_on_the_final_term_day_credits_seven_of_eight_weeks(api):
    """55 elapsed days truncate to 7 weeks, so the gross is 93234.

    PRD §3.9: "An 8-week term completed on 2026-10-27 is 56 days, exactly 8
    weeks, giving 103696 plus 2500, or 106196 cents; complete the same term one
    day earlier, on 2026-10-26, and 55 days truncates to 7 weeks, giving 90734
    plus 2500, or 93234 cents — a single day costs a full week of pay, because
    the division truncates."

    Design: Difficulty/boundary_precision_check/weeks_credited_floor_boundary_on_the_final_term_day
    """
    scenario = _eight_week_placement_ready_to_complete(api)

    completed = complete_placement(api, scenario.placement_id)

    assert completed["placement_status"] == "COMPLETED"
    assert_date_equals(completed["end_date"], "2026-10-26", "end_date")
    assert_stipend(completed, variant="FINAL", weekly_cents=12962,
                   weeks_credited=7, gross_cents=93234, travel_cents=68943)
    assert completed["stipend_gross_cents"] != 106196, (
        "106196 credits the full 8 weeks the term only reaches on 2026-10-27")


def test_the_floored_week_count_replaces_the_provisional_eight_everywhere(api):
    """The provisional 103696 is replaced by 93234, not added to.

    PRD §3.6: "Under the `PROVISIONAL` variant — the one confirmation uses,
    recorded in `stipend_variant` — the number of credited weeks is the full
    planned `weeks_scheduled` and the premium is zero."  PRD §3.9: "The
    agreement's `stipend_committed_cents` is re-derived from the new gross".

    Design: Difficulty/boundary_precision_check/weeks_credited_floor_boundary_on_the_final_term_day
    """
    scenario = _eight_week_placement_ready_to_complete(api)
    provisional = read_placement(api, scenario.placement_id)
    assert_stipend(provisional, variant="PROVISIONAL", weeks_credited=8,
                   gross_cents=103696, travel_cents=78792)

    complete_placement(api, scenario.placement_id)

    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=0, seats_committed=1,
                            stipend_committed_cents=93234,
                            capacity_posture="CAP_REACHED")
    settled = read_placement(api, scenario.placement_id)
    assert_stipend(settled, variant="FINAL", weeks_credited=7,
                   gross_cents=93234)
    assert settled["weeks_scheduled"] == 8, (
        "the plan is unchanged; only the credited weeks are floored")
