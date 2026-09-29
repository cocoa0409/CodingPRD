"""Formulas checked at the constants and the tiers the contract names.

Each figure asserted here is one the PRD writes out in full: the seat and
caseload aggregations partitioned by stage, the 3-percent travel band on a
45-mile commute, the 1.10 longevity band, a perfect rubric summing to 100, the
0.3333 compliance quotient and the 45-day state-reporting deadline.
"""
from test_helpers import (
    ASSESSMENT_SCORER,
    ASSESSMENT_SCORER_USER_ID,
    ERR_OBSERVATION_COMPLIANCE_LOW,
    PROGRAM_ADMIN,
    PROGRAM_ADMIN_2,
    PROGRAM_ADMIN_USER_ID,
    SECOND_PROGRAM_ADMIN_USER_ID,
    SUBMISSION_CLOCK,
    add_teacher,
    assert_agreement_ledger,
    assert_caseload,
    assert_date_equals,
    assert_instant_equals,
    assert_ratio_equals,
    assert_stipend,
    complete_cycle,
    confirm,
    factories as f,
    open_assessment,
    open_request,
    read_agreement,
    read_assessment,
    read_candidate,
    read_cycle,
    read_placement,
    read_supervisor,
    route,
    set_clock,
    setup_active_placement,
    setup_bench,
    setup_completed_placement,
    setup_observed_placement,
    setup_ready_candidate,
    setup_scheduled_cycles,
    submit_assessment,
    validate_error,
    validate_success,
)

SECOND_SITE = {"site_grid_x": 10, "site_grid_y": 11, "years_experience": 6}
SECOND_HOME = {"home_grid_x": 2, "home_grid_y": 5}
FAR_HOME = {"home_grid_x": 10, "home_grid_y": 55}
AT_THE_CEILING = {"max_commute_miles": 45}
TOP_LONGEVITY = {"consecutive_terms_hosted": 3}
PERFECT_RUBRIC = {
    "task_planning": 5.0,
    "task_instruction": 5.0,
    "task_assessment": 5.0,
    "task_professionalism": 5.0,
}
PROVISIONAL_GROSS_CENTS = 181468
DEADLINE_DATE = "2027-01-21"
ON_THE_DEADLINE_CLOCK = "2027-01-21T10:00:00Z"
REPORTING_CYCLE = "2026-27-FALL"


def test_agreement_ledger_and_caseload_count_only_open_stage_placements(api):
    """One confirmation moves a seat between buckets and a point onto the caseload.

    PRD §2.9: "`seats_reserved` is the count of that agreement's placements whose
    `placement_status` is `PROPOSED`, and `seats_committed` is the count of those
    whose `placement_status` is `ACTIVE`, `REMOVAL_PENDING` or `COMPLETED` ...
    `stipend_committed_cents` is the sum of `stipend_gross_cents` over that
    agreement's placements whose `stipend_status` is `ACCRUED`, `APPROVED` or
    `PAID`".  PRD §3.4: "The stage base is 1 point while the placement is
    `PROPOSED`, 2 points while it is `ACTIVE`".

    Design: Corner/calculations/agreement_ledger_and_caseload_count_only_open_stage_placements
    """
    scenario = setup_bench(api, agreement={"placement_cap": 2})
    add_teacher(api, scenario, **SECOND_SITE)
    setup_ready_candidate(api, scenario=scenario)
    scenario.request = open_request(api, scenario.candidate_id,
                                   preferred_district_id=scenario.district_id)
    scenario.placement = route(api, scenario.request_id)
    second = setup_ready_candidate(api, candidate=dict(SECOND_HOME))
    second.request = open_request(api, second.candidate_id,
                                 preferred_district_id=scenario.district_id)
    second.placement = route(api, second.request_id)
    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=2, seats_committed=0,
                            stipend_committed_cents=0)
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 4)

    confirm(api, scenario.placement_id)

    assert_agreement_ledger(read_agreement(api, scenario.agreement_id),
                            seats_reserved=1, seats_committed=1,
                            stipend_committed_cents=PROVISIONAL_GROSS_CENTS,
                            capacity_posture="OPEN")
    assert_caseload(read_supervisor(api, scenario.supervisor_id), 5,
                    max_caseload_points=24)


def test_travel_reimbursement_third_tier_applies_to_the_largest_subtotal(api):
    """6300 billable miles put the subtotal past 150000, so the band is 3 percent.

    PRD §3.6: "an administrative allowance is layered on top at a percentage
    **selected from that pre-allowance subtotal**: 8 percent when the subtotal is
    50000 cents or less, 5 percent when it is above 50000 and no more than 150000
    cents, and 3 percent when it exceeds 150000 cents."  PRD §3.5: "the program
    will not tolerate a commute beyond 45 miles under any circumstances".

    Design: Corner/calculations/travel_reimbursement_third_tier_applies_to_the_largest_subtotal
    """
    scenario = setup_bench(api)
    setup_ready_candidate(api, scenario=scenario, candidate=dict(FAR_HOME))
    scenario.request = open_request(api, scenario.candidate_id,
                                   preferred_district_id=scenario.district_id,
                                   **AT_THE_CEILING)
    scenario.placement = route(api, scenario.request_id)
    assert scenario.placement["commute_miles"] == 45

    confirmed = confirm(api, scenario.placement_id)

    assert confirmed["commute_miles"] == 45
    assert_stipend(confirmed, variant="PROVISIONAL", weeks_credited=14,
                   gross_cents=PROVISIONAL_GROSS_CENTS, travel_cents=434763)


def test_stipend_weekly_rate_uses_the_top_longevity_constant(api):
    """Three consecutive terms select 1.10, and 13579.5 rounds up to 13580.

    PRD §3.6: "no bonus at all for a teacher with zero consecutive terms, 5
    percent for a teacher with one or two, and 10 percent for a teacher with
    three or more ... a teacher with three or more earns 12345 multiplied by 1.10,
    or 13579.5, which rounds half up to 13580 per week."

    Design: Corner/calculations/stipend_weekly_rate_uses_the_top_longevity_constant
    """
    scenario = setup_active_placement(api, teacher=dict(TOP_LONGEVITY))

    confirmed = scenario.placement

    assert_stipend(confirmed, variant="PROVISIONAL", weekly_cents=13580,
                   weeks_credited=14, gross_cents=190120, travel_cents=137886)
    assert read_agreement(api, scenario.agreement_id)[
        "stipend_committed_cents"] == 190120


def test_assessment_full_marks_reach_one_hundred_points(api):
    """30 plus 35 plus 20 plus 15, with no rounding drift anywhere.

    PRD §3.8: "planning is weighted 0.30, instruction 0.35, assessment 0.20 and
    professionalism 0.15, so the maxima are 30, 35, 20 and 15 points respectively
    and `total_score` runs from 0 to 100 ... A flat 5.0 gives the full 100."  PRD
    §3.8: "A `SCORE` whose `total_score` is at least 70 moves the assessment
    `SUBMITTED → PASSED`, records all four dimensions, `total_score`,
    `scored_by_user_id` and `scored_at`".

    Design: Corner/calculations/assessment_full_marks_reach_one_hundred_points
    """
    scenario = setup_observed_placement(api)
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)
    submit_assessment(api, scenario.assessment_id, scenario.candidate_id)

    scored = validate_success(api.score_assessment(
        scenario.assessment_id, f.assessment_score_payload(**PERFECT_RUBRIC),
        ASSESSMENT_SCORER))

    assert scored["total_score"] == 100
    assert scored["status"] == "PASSED"
    assert scored["attempt_no"] == 1
    assert scored["scored_by_user_id"] == ASSESSMENT_SCORER_USER_ID
    assert_instant_equals(scored["scored_at"], SUBMISSION_CLOCK, "scored_at")
    assert read_placement(api, scenario.placement_id)["placement_status"] == (
        "ACTIVE"), "passing the assessment does not itself complete the placement"


def test_observation_compliance_ratio_rounds_to_four_decimals(api):
    """One of three counted cycles is 0.3333, which is under the submission floor.

    PRD §3.7: "The denominator is the larger of 3 and the size of the counted set
    ... and the ratio is the completed count divided by that denominator, rounded
    half up to four decimal places ... Three counted with one completed give
    0.3333, which is below the 0.5 floor that assessment submission requires."

    Design: Corner/calculations/observation_compliance_ratio_rounds_to_four_decimals
    """
    scenario = setup_active_placement(api)
    setup_scheduled_cycles(api, scenario)
    complete_cycle(api, scenario.cycles[0]["id"], scenario.supervisor_id,
                   "2026-09-16T15:00:00Z", 4.0)
    scenario.assessment = open_assessment(api, scenario.placement_id)
    set_clock(api, SUBMISSION_CLOCK)

    assert_ratio_equals(
        read_placement(api, scenario.placement_id)["observation_compliance_ratio"],
        0.3333)
    assert read_cycle(api, scenario.cycles[1]["id"])["status"] == "MISSED"

    validate_error(api.submit_assessment(scenario.assessment_id,
                                         f.assessment_submit_payload(),
                                         scenario.candidate_headers),
                   ERR_OBSERVATION_COMPLIANCE_LOW, 422)

    refused = read_assessment(api, scenario.assessment_id)
    assert refused["status"] == "OPEN"
    assert refused["attempt_no"] == 0


def test_state_report_deadline_is_forty_five_days_after_the_term_end(api):
    """2026-12-07 plus 45 days is 2027-01-21, and that day is still on time.

    PRD §3.9: "the candidate's `state_report_deadline` becomes the closed
    request's `term_end_date` plus 45 days."  PRD §3.9: "A 14-week term starting
    2026-09-01 ends on 2026-12-07, so the deadline is 45 days later, on
    2027-01-21: a report filed on 2027-01-21 is on time, because the deadline day
    itself still counts".

    Design: Corner/calculations/state_report_deadline_is_forty_five_days_after_the_term_end
    """
    scenario = setup_completed_placement(api)
    validate_success(api.recommend_licensure(
        scenario.candidate_id, f.licensure_payload("RECOMMENDED"), PROGRAM_ADMIN))
    recommended = read_candidate(api, scenario.candidate_id)
    assert recommended["licensure_status"] == "RECOMMENDED"
    assert recommended["recommended_by_user_id"] == PROGRAM_ADMIN_USER_ID
    assert_date_equals(recommended["state_report_deadline"], DEADLINE_DATE,
                       "state_report_deadline")
    set_clock(api, ON_THE_DEADLINE_CLOCK)

    reported = validate_success(api.file_state_report(
        scenario.candidate_id, f.state_report_payload(REPORTING_CYCLE),
        PROGRAM_ADMIN_2))

    assert reported["report_status"] == "REPORTED_ON_TIME"
    assert reported["reported_by_user_id"] == SECOND_PROGRAM_ADMIN_USER_ID
    assert_instant_equals(reported["reported_at"], ON_THE_DEADLINE_CLOCK,
                          "reported_at")
    assert reported["reporting_cycle"] == REPORTING_CYCLE
