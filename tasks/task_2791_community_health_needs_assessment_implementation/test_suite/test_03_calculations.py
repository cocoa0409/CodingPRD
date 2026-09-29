"""Calculation corners: the concern index, the severity constants and valuation."""

from test_helpers import (
    COMPLIANCE,
    PUBLIC,
    CandidateStatus,
    Category,
    CycleStatus,
    DataState,
    IndicatorDomain,
    InterviewStatus,
    ReportStatus,
    ScoringVariant,
    Sector,
    Subgroup,
    ValuationBasis,
    add_candidate,
    add_data_point,
    add_indicator,
    add_interview,
    advance_to,
    assert_close,
    build_scenario,
    complete_interview,
    create_cycle,
    finalize_report,
    open_report,
    post_charge_based,
    post_cost_based,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C


def _cycle_with_two_completed_sessions(api):
    """One session rating BEHAVIORAL_HEALTH 5 with 12 attendees, a second rating
    the same domain 3 with 8 attendees, and a candidate ready to be scored."""
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    second = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    complete_interview(
        api, second["id"], domain=IndicatorDomain.BEHAVIORAL_HEALTH, rating=3, attendee_count=8
    )
    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)
    candidate = add_candidate(api, sc.cycle_id, sc.indicator_id)
    return sc, candidate


def test_the_concern_index_weights_each_session_by_its_attendance(api):
    """PRD §3.4: "For each qualifying session, that domain's rating is multiplied by
    the session's `attendee_count`, and those products are summed; that sum is
    divided by the sum of the same sessions' `attendee_count` values, giving an
    attendance-weighted mean rating on the 1-to-5 scale."

    PRD §3.4: "That mean is then multiplied by 20 to place it on the same 0-to-100
    footing as the other three criteria, and the result is rounded half up to two
    decimal places."

    Design: Corner/calculations/concern_index_weights_two_completed_interviews_by_attendance
    """
    sc, candidate = _cycle_with_two_completed_sessions(api)

    scored = validate_success(api.score_candidate(candidate["id"], ScoringVariant.EQUAL_WEIGHT))

    # (5*12 + 3*8) / (12 + 8) = 4.2; 4.2 * 20 = 84.00.  The unweighted mean of the
    # two ratings would be 4.0 and would have given 80.00.
    assert_close(scored["community_concern_index"], 84.00, "community_concern_index")
    assert_close(scored["severity_input"], 77.50, "severity_input")
    assert_close(scored["disparity_points"], 60.00, "disparity_points")
    assert scored["hospital_capacity_score"] == C.HOSPITAL_CAPACITY_SCORE
    assert scored["status"] == CandidateStatus.SCORED
    assert scored["scoring_variant"] == ScoringVariant.EQUAL_WEIGHT
    assert sc.cycle()["completed_interview_count"] == 2


def test_the_composite_carries_the_attendance_weighted_index_into_its_quarter(api):
    """PRD §3.4: "Under the `EQUAL_WEIGHT` variant — the statutory reading, in which
    severity, disparities, community concern and hospital capacity carry the same
    weight — every term carries a weight of 0.25: the composite score is one
    quarter of the severity term plus one quarter of the disparity term plus one
    quarter of the concern term plus one quarter of the capacity term."

    Design: Corner/calculations/concern_index_weights_two_completed_interviews_by_attendance
    """
    _sc, candidate = _cycle_with_two_completed_sessions(api)

    scored = validate_success(api.score_candidate(candidate["id"], ScoringVariant.EQUAL_WEIGHT))

    # 0.25 * (77.50 + 60.00 + 84.00 + 70) = 72.875 -> 72.88; the unweighted-mean
    # reading of the index would have produced 76.88 here.
    assert_close(scored["composite_score"], 72.88, "composite_score")
    assert_close(scored["community_concern_index"], 84.00, "community_concern_index")


def test_scheduled_and_cancelled_sessions_contribute_no_rating_and_no_weight(api):
    """PRD §3.4: "Its input set is every session on the candidate's cycle whose
    `status` is `COMPLETED` and whose `concern_ratings` object contains a key equal
    to the candidate's indicator `domain`; sessions still `SCHEDULED` and sessions
    `CANCELLED` are excluded, and there is no time window, so a session completed
    during `PRIORITIZATION` counts exactly as much as one completed during
    `INPUT_GATHERING`."

    Design: Corner/calculations/concern_index_excludes_scheduled_and_cancelled_interviews
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    still_scheduled = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    to_cancel = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Eastside Food Bank",
        sector=Sector.RESIDENT_COALITION,
        starts_at="2026-04-08T14:00:00Z",
        ends_at="2026-04-08T15:00:00Z",
    )
    cancelled = validate_success(api.cancel_interview(to_cancel["id"], "Organisation withdrew"))
    assert cancelled["status"] == InterviewStatus.CANCELLED
    assert (
        validate_success(api.get_interview(still_scheduled["id"]))["status"]
        == InterviewStatus.SCHEDULED
    )

    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)
    candidate = add_candidate(api, sc.cycle_id, sc.indicator_id)

    scored = validate_success(api.score_candidate(candidate["id"], ScoringVariant.EQUAL_WEIGHT))

    # Only the one completed 5-rating session qualifies: 5 * 20 = 100.00.
    assert_close(scored["community_concern_index"], 100.00, "community_concern_index")
    # 0.25 * (77.50 + 60.00 + 100.00 + 70) = 76.875 -> 76.88.
    assert_close(scored["composite_score"], 76.88, "composite_score")


def test_only_the_completed_session_of_the_three_reaches_the_cycle_counter(api):
    """PRD §3.3: "On success `status` moves `SCHEDULED` to `COMPLETED`, `completed_at`
    is stamped from the logical clock, and the cycle's `completed_interview_count`
    increases by 1."

    Design: Corner/calculations/concern_index_excludes_scheduled_and_cancelled_interviews
    """
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-07T14:00:00Z",
        ends_at="2026-04-07T15:00:00Z",
    )
    to_cancel = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Eastside Food Bank",
        sector=Sector.RESIDENT_COALITION,
        starts_at="2026-04-08T14:00:00Z",
        ends_at="2026-04-08T15:00:00Z",
    )
    validate_success(api.cancel_interview(to_cancel["id"], "Organisation withdrew"))

    rows, meta = validate_paginated(api.list_interviews(cycle_id=sc.cycle_id))
    assert meta["total_count"] == 3
    assert len(rows) == 3

    # The public surface sees the counter, not the rows.
    public_view = validate_success(api.get_cycle(sc.cycle_id, headers=PUBLIC))
    assert public_view["completed_interview_count"] == 1


def test_an_indicator_at_and_below_its_benchmark_reads_off_the_parity_multiplier(api):
    """PRD §3.2: "The multiplier of 50 encodes benchmark parity: an indicator whose
    community rate exactly equals its benchmark scores 50.00, and an indicator
    running at twice its benchmark reaches the ceiling."

    Design: Corner/calculations/severity_constants_parity_score_and_ceiling_applied
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    at_parity = add_indicator(
        api,
        cycle["id"],
        domain=IndicatorDomain.BEHAVIORAL_HEALTH,
        name="At-benchmark indicator",
        benchmark_value=12.0,
    )
    below = add_indicator(
        api,
        cycle["id"],
        domain=IndicatorDomain.ACCESS_TO_CARE,
        name="Below-benchmark indicator",
        benchmark_value=12.0,
    )

    add_data_point(api, at_parity["id"], population_subgroup=Subgroup.OVERALL, value=12.0)
    add_data_point(api, below["id"], population_subgroup=Subgroup.OVERALL, value=9.0)

    parity_row = validate_success(api.get_indicator(at_parity["id"]))
    # 12.0 / 12.0 * 50 = 50.00.
    assert_close(parity_row["severity_score"], 50.00, "severity_score")
    assert_close(parity_row["latest_overall_value"], 12.0, "latest_overall_value")

    below_row = validate_success(api.get_indicator(below["id"]))
    # 9.0 / 12.0 * 50 = 37.50 — scores under parity are not floored at 50.
    assert_close(below_row["severity_score"], 37.50, "severity_score")

    for row in (parity_row, below_row):
        assert row["data_state"] == DataState.INSUFFICIENT
        assert row["disparity_ratio"] is None
        assert row["subgroup_count"] == 0
        assert row["evidence_count"] == 1


def test_a_rate_far_above_the_benchmark_is_capped_after_the_rounding(api):
    """PRD §3.2: "Otherwise `severity_score` is the community's rate divided by the
    indicator's `benchmark_value`, multiplied by 50, rounded half up to two decimal
    places, and then capped at 100.00 — the cap is applied *after* the rounding,
    never before."

    Design: Corner/calculations/severity_constants_parity_score_and_ceiling_applied
    """
    cycle = create_cycle(api)
    advance_to(api, cycle["id"], CycleStatus.DATA_COLLECTION)
    far_above = add_indicator(
        api,
        cycle["id"],
        domain=IndicatorDomain.CHRONIC_DISEASE,
        name="Far-above-benchmark indicator",
        benchmark_value=12.0,
    )

    add_data_point(api, far_above["id"], population_subgroup=Subgroup.OVERALL, value=30.0)

    stored = validate_success(api.get_indicator(far_above["id"]))
    # 30.0 / 12.0 * 50 = 125.00, clipped to the 100.00 ceiling.
    assert_close(stored["severity_score"], 100.00, "severity_score")
    assert_close(stored["latest_overall_value"], 30.0, "latest_overall_value")
    assert stored["data_state"] == DataState.INSUFFICIENT
    assert stored["disparity_ratio"] is None


def test_each_charge_posting_is_rounded_before_the_category_total_sums_them(api):
    """PRD §3.9: "each posting's `valued_cents` is rounded to a whole number of
    cents when the posting is valued, and the totals are sums of those
    already-rounded integers."

    Design: Corner/calculations/charge_based_posting_rounds_half_up_at_the_cent
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    small = post_charge_based(api, report["id"], 1005, category=Category.FINANCIAL_ASSISTANCE)
    # 1005 * 0.32 = 321.6 -> 322.
    assert small["valued_cents"] == 322

    large = post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    # 1234567 * 0.32 = 395061.44 -> 395061.
    assert large["valued_cents"] == 395061

    stored = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    # 322 + 395061 = 395383; rounding the summed product would have given 395382.
    assert stored["financial_assistance_cents"] == 395383
    assert stored["total_valued_cents"] == 395383


def test_the_ratio_each_charge_posting_used_is_recorded_on_the_row(api):
    """PRD §3.9: "For a charge-based posting, `valued_cents` is the posting's
    `charges_cents` multiplied by the report's current `cost_to_charge_ratio`,
    rounded half up to a whole number of cents, and `ratio_applied` stores the
    exact ratio used."

    Design: Corner/calculations/charge_based_posting_rounds_half_up_at_the_cent
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    assert report["valuation_basis"] == ValuationBasis.PROVISIONAL
    assert_close(report["cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "cost_to_charge_ratio")

    small = post_charge_based(api, report["id"], 1005, category=Category.FINANCIAL_ASSISTANCE)
    large = post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)

    for posting in (small, large):
        assert_close(posting["ratio_applied"], C.PRIOR_YEAR_RATIO, "ratio_applied")
        assert posting["valuation_basis_at_posting"] == ValuationBasis.PROVISIONAL
        assert posting["direct_cost_cents"] == 0

    stored = validate_success(api.get_report(report["id"]))
    assert stored["valuation_basis"] == ValuationBasis.PROVISIONAL
    assert_close(stored["cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "cost_to_charge_ratio")


def test_a_cost_based_posting_is_valued_at_its_direct_cost_with_no_ratio_at_all(api):
    """PRD §3.9: "For a cost-based posting, `valued_cents` is simply the posting's
    `direct_cost_cents` unchanged, and `ratio_applied` is null — no ratio was
    involved and none is recorded."

    Design: Corner/calculations/cost_based_posting_bypasses_ratio_valuation_entirely
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])

    posting = post_cost_based(
        api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT
    )
    assert posting["valued_cents"] == 850000
    assert posting["direct_cost_cents"] == 850000
    assert posting["charges_cents"] == 0
    assert posting["ratio_applied"] is None
    assert posting["valuation_basis_at_posting"] == ValuationBasis.PROVISIONAL

    stored = validate_success(api.get_report(report["id"]))
    assert stored["community_health_improvement_cents"] == 850000
    assert stored["total_valued_cents"] == 850000
    # A base of 850,000 is in the lowest tier, so 0.05 * 850000 = 42500.
    assert_close(stored["overhead_rate"], 0.05, "overhead_rate")
    assert stored["indirect_allocation_cents"] == 42500
    assert stored["grand_total_cents"] == 892500
    # 892500 / 120000000 * 100 = 0.74375 -> 0.74.
    assert_close(stored["benefit_pct_of_expense"], 0.74, "benefit_pct_of_expense")


def test_finalization_cannot_move_a_cost_based_posting_or_its_totals(api):
    """PRD §3.9: "cost-based postings are unaffected, since no ratio ever entered
    their valuation."

    Design: Corner/calculations/cost_based_posting_bypasses_ratio_valuation_entirely
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    posting = post_cost_based(
        api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT
    )

    locked = finalize_report(api, report["id"], C.AUDITED_RATIO)
    assert locked["status"] == ReportStatus.LOCKED
    assert locked["valuation_basis"] == ValuationBasis.FINAL
    assert_close(locked["cost_to_charge_ratio"], C.AUDITED_RATIO, "cost_to_charge_ratio")

    after = validate_success(api.get_posting(posting["id"], headers=COMPLIANCE))
    assert after["valued_cents"] == 850000
    assert after["ratio_applied"] is None

    # Every total the provisional run produced is still exactly where it was.
    assert locked["community_health_improvement_cents"] == 850000
    assert locked["total_valued_cents"] == 850000
    assert locked["indirect_allocation_cents"] == 42500
    assert locked["grand_total_cents"] == 892500
    assert_close(locked["benefit_pct_of_expense"], 0.74, "benefit_pct_of_expense")
