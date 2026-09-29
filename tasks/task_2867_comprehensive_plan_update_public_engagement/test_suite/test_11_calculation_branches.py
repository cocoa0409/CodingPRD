"""Arithmetic branches of the projection, equity and impact formulas.

Each test pins one branch of one formula to literal figures the PRD's own arithmetic
produces, and cross-checks the same figures against the reference calculators, so a
failure says which branch was taken rather than merely that a number is wrong.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import CONSULTANT, DIRECTOR, STAFF

# The reference land-use row, restated here because both capacity figures are asserted
# against it: 400 vacant, 250 underutilized, 60 constrained acres at 18 units per acre.
REF_VACANT = 400
REF_UNDERUTILIZED = 250
REF_CONSTRAINED = 60
REF_DENSITY = 18

# The projection inputs of this scenario, kept apart from the factory defaults.
SCENARIO_BASE_HOUSEHOLDS = 20000
SCENARIO_GROWTH_RATE = 0.012
SCENARIO_JOB_GROWTH = 12000
SCENARIO_DEMOLITION_REPLACEMENT = 500


def _trend_scenario(api):
    """A plan, a certified reference land-use dataset and one TREND scenario on it."""
    plan = fx.create_plan(api)
    inventory = fx.create_land_use_inventory(
        api,
        plan["id"],
        vacant_acres=REF_VACANT,
        underutilized_acres=REF_UNDERUTILIZED,
        infrastructure_constrained_acres=REF_CONSTRAINED,
        allowed_density_units_per_acre=REF_DENSITY,
    )
    certified = fx.certify_inventory(api, inventory["id"])
    scenario = validate_success(
        api.create_growth_scenario(
            f.growth_scenario_payload(
                plan["id"],
                certified["id"],
                certified["version"],
                method=C.METHOD_TREND,
                label="Trend continuation",
                base_households=SCENARIO_BASE_HOUSEHOLDS,
                annual_household_growth_rate=SCENARIO_GROWTH_RATE,
                job_growth_total=SCENARIO_JOB_GROWTH,
                demolition_replacement_units=SCENARIO_DEMOLITION_REPLACEMENT,
            ),
            STAFF,
        ),
        201,
    )
    return plan, scenario


def test_trend_scenario_takes_the_gross_capacity_variant(api):
    """A TREND scenario reads capacity optimistically: (400 + 250) * 18 == 11700 units.

    "Under `GROSS_CAPACITY`, `land_capacity_units` is the vacant acreage plus the
    underutilized acreage, multiplied by the allowed density per acre, and that single
    product is rounded half up to whole units."

    Design: Corner/calculations/trend_scenario_capacity_and_demand_correct_result
    """
    _plan, scenario = _trend_scenario(api)

    # "a TREND scenario is GROSS_CAPACITY, a POLICY scenario is NET_CAPACITY".
    assert scenario["capacity_variant"] == C.CAPACITY_VARIANT_GROSS
    assert scenario["land_capacity_units"] == 11700
    assert scenario["land_capacity_units"] == A.expected_gross_capacity(
        REF_VACANT, REF_UNDERUTILIZED, REF_DENSITY
    )
    A.assert_whole_units(scenario["land_capacity_units"], "land_capacity_units")
    # The 60 constrained acres and the market-softness discount belong to the other
    # variant, so the net figure of 7115 must not appear here.
    assert scenario["land_capacity_units"] != A.expected_net_capacity(
        REF_VACANT, REF_UNDERUTILIZED, REF_CONSTRAINED, REF_DENSITY
    )


def test_trend_projected_demand_ignores_the_job_pressure_and_rounds_once(api):
    """Household growth alone drives demand: round_half_up((5388.687... + 500) * 1.05) == 6183.

    "The chosen driver is then added to `demolition_replacement_units`, the sum is
    multiplied by 1.05 to allow a five percent vacancy margin, and only that final figure
    is rounded half up to whole units."

    Design: Corner/calculations/trend_scenario_capacity_and_demand_correct_result
    """
    _plan, scenario = _trend_scenario(api)

    expected_demand = A.expected_projected_demand(
        C.METHOD_TREND,
        SCENARIO_BASE_HOUSEHOLDS,
        SCENARIO_GROWTH_RATE,
        f.REF_HORIZON_YEAR,
        f.REF_BASE_YEAR,
        SCENARIO_JOB_GROWTH,
        SCENARIO_DEMOLITION_REPLACEMENT,
    )
    assert expected_demand == 6183
    assert scenario["projected_demand_units"] == 6183
    A.assert_whole_units(scenario["projected_demand_units"], "projected_demand_units")

    # The job pressure of 12000 / 1.45 households is the larger of the two drivers and is
    # nonetheless discarded under TREND.
    policy_demand = A.expected_projected_demand(
        C.METHOD_POLICY,
        SCENARIO_BASE_HOUSEHOLDS,
        SCENARIO_GROWTH_RATE,
        f.REF_HORIZON_YEAR,
        f.REF_BASE_YEAR,
        SCENARIO_JOB_GROWTH,
        SCENARIO_DEMOLITION_REPLACEMENT,
    )
    assert policy_demand > expected_demand
    assert scenario["projected_demand_units"] != policy_demand

    # "the projected demand less the land capacity, floored at zero so it is never
    #  negative".
    assert scenario["capacity_gap_units"] == 0
    assert scenario["capacity_gap_units"] == A.expected_capacity_gap(
        scenario["projected_demand_units"], scenario["land_capacity_units"]
    )
    assert scenario["status"] == C.SCENARIO_STATUS_DRAFT

    # The figures are computed once at creation and stored, not recomputed per read.
    reread = validate_success(api.get_growth_scenario(scenario["id"], DIRECTOR))
    assert reread["land_capacity_units"] == scenario["land_capacity_units"]
    assert reread["projected_demand_units"] == scenario["projected_demand_units"]
    assert reread["capacity_gap_units"] == scenario["capacity_gap_units"]
    assert reread["status"] == C.SCENARIO_STATUS_DRAFT


# Five respondents at one workshop: three from the closed underrepresented list, two not,
# and three of them speaking through an interpreter.
STANDARD_ROSTER = [
    {
        "respondent_ref": "R-001",
        "demographic_group": C.GROUP_RENTER,
        "interpreter_used": True,
    },
    {"respondent_ref": "R-002", "demographic_group": C.GROUP_DISABILITY},
    {
        "respondent_ref": "R-003",
        "demographic_group": C.GROUP_LIMITED_ENGLISH,
        "interpreter_used": True,
    },
    {
        "respondent_ref": "R-004",
        "demographic_group": C.GROUP_SENIOR,
        "interpreter_used": True,
    },
    {"respondent_ref": "R-005", "demographic_group": C.GROUP_GENERAL},
]


def _standard_workshop(api):
    """A workshop, whose weighting variant is fixed at STANDARD by its activity type."""
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api, turnover_buffer_minutes=0)
    activity = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="Eastside Workshop",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_START,
        end_at=fx.T_ACTIVITY_END,
        interpretation_offered=True,
    )
    assert activity["weighting_variant"] == C.VARIANT_STANDARD
    return plan, activity


def test_standard_weighting_ignores_the_interpreter_flag(api):
    """At a workshop every respondent weighs 1.0, interpreter or not.

    "The record's `weight` is 2.0 when the parent activity's `weighting_variant` is
    `OUTREACH_WEIGHTED` and the respondent's `interpreter_used` is true, and 1.0 in every
    other case — an interpreter changes nothing at a workshop or a survey."

    Design: Corner/calculations/standard_weighting_ignores_interpreter_and_the_group_list_is_closed
    """
    _plan, activity = _standard_workshop(api)

    for entry in STANDARD_ROSTER:
        record = validate_success(
            api.create_participation_record(
                f.participation_record_payload(activity["id"], **entry), STAFF
            ),
            201,
        )
        assert record["weight"] == C.WEIGHT_STANDARD
        assert record["weight"] == A.expected_weight(
            C.VARIANT_STANDARD, entry.get("interpreter_used", False)
        )
        # "it is true when the respondent's demographic_group is LOW_INCOME,
        #  LIMITED_ENGLISH, YOUTH, DISABILITY or RENTER. GENERAL and SENIOR are
        #  deliberately not underrepresented groups."
        assert record["is_underrepresented"] == A.expected_is_underrepresented(
            entry["demographic_group"]
        )

    assert validate_success(api.get_engagement_activity(activity["id"], STAFF))[
        "record_count"
    ] == len(STANDARD_ROSTER)


def test_standard_workshop_totals_count_three_of_five_as_underrepresented(api):
    """The closed group list gives 3.0 of 5.0 weighted units, or 60.0 percent.

    "the activity's own `equity_share_pct` is computed as one hundred times its
    `underrepresented_weighted_count` divided by its `total_weighted_count`, rounded half
    up to one decimal place"

    Design: Corner/calculations/standard_weighting_ignores_interpreter_and_the_group_list_is_closed
    """
    _plan, activity = _standard_workshop(api)
    fx.add_roster(api, activity["id"], STANDARD_ROSTER)

    completed = validate_success(
        api.complete_engagement_activity(activity["id"], {}, STAFF)
    )
    assert completed["record_count"] == 5
    assert completed["underrepresented_record_count"] == 3
    assert completed["total_weighted_count"] == 5.0
    assert completed["underrepresented_weighted_count"] == 3.0
    assert completed["equity_share_pct"] == 60.0
    A.assert_one_decimal(completed["total_weighted_count"], "total_weighted_count")
    A.assert_one_decimal(completed["equity_share_pct"], "equity_share_pct")

    expected = A.expected_activity_totals(STANDARD_ROSTER, C.VARIANT_STANDARD)
    A.assert_fields_equal(completed, expected)


# Workshop A already happened and mixes two underrepresented respondents into five;
# workshop B is still ahead of the clock and is entirely GENERAL.
ROSTER_HELD = [
    {"respondent_ref": "A-001", "demographic_group": C.GROUP_LOW_INCOME},
    {"respondent_ref": "A-002", "demographic_group": C.GROUP_YOUTH},
    {"respondent_ref": "A-003", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "A-004", "demographic_group": C.GROUP_GENERAL},
    {"respondent_ref": "A-005", "demographic_group": C.GROUP_SENIOR},
]
ROSTER_UPCOMING = [
    {"respondent_ref": f"B-00{n}", "demographic_group": C.GROUP_GENERAL}
    for n in range(1, 6)
]
UPCOMING_START = "2026-09-10T18:00:00.000Z"
UPCOMING_END = "2026-09-10T20:00:00.000Z"


def test_plan_equity_counts_only_completed_activities(api):
    """Five scheduled GENERAL respondents do not dilute the plan's 40.0 percent share.

    "The plan's `participation_weight_total` is the sum of `total_weighted_count` across
    the plan's activities in status `COMPLETED`, its `underrepresented_weight_total` the
    corresponding sum of `underrepresented_weighted_count`, and its `equity_share_pct` is
    one hundred times the second divided by the first, rounded half up to one decimal
    place, or 0.0 when the denominator is zero."

    Design: Corner/calculations/plan_equity_counts_only_completed_activities
    """
    plan = fx.create_plan(api)
    venue = fx.create_equity_venue(api, turnover_buffer_minutes=0)

    held = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="July Workshop",
        venue_id=venue["id"],
        start_at=fx.T_ACTIVITY_START,
        end_at=fx.T_ACTIVITY_END,
    )
    fx.add_roster(api, held["id"], ROSTER_HELD)

    upcoming = fx.create_activity(
        api,
        plan["id"],
        activity_type=C.ACTIVITY_WORKSHOP,
        title="September Workshop",
        venue_id=venue["id"],
        start_at=UPCOMING_START,
        end_at=UPCOMING_END,
    )
    fx.add_roster(api, upcoming["id"], ROSTER_UPCOMING)

    completed = validate_success(api.complete_engagement_activity(held["id"], {}, STAFF))
    assert completed["total_weighted_count"] == 5.0
    assert completed["underrepresented_weighted_count"] == 2.0
    assert completed["equity_share_pct"] == 40.0

    # "Activities still SCHEDULED have not been held and are excluded" — even though
    # their records exist and were weighted as they were captured.
    still_scheduled = validate_success(api.get_engagement_activity(upcoming["id"], STAFF))
    assert still_scheduled["status"] == C.ACTIVITY_STATUS_SCHEDULED
    assert still_scheduled["total_weighted_count"] == 5.0

    plan_after = validate_success(api.get_plan_update(plan["id"], STAFF))
    assert plan_after["participation_weight_total"] == 5.0
    assert plan_after["underrepresented_weight_total"] == 2.0
    assert plan_after["equity_share_pct"] == 40.0
    assert plan_after["equity_share_pct"] == A.expected_equity_share_pct(2.0, 5.0)


# Two alternatives that straddle the credit threshold. The first sits exactly on 50,
# the second a tenth of a traffic point below it.
AT_THRESHOLD_INDICES = {
    "traffic_vmt_index": 50,
    "ghg_index": 50,
    "habitat_index": 50,
    "water_index": 50,
}
BELOW_THRESHOLD_INDICES = {
    "traffic_vmt_index": 49.9,
    "ghg_index": 50,
    "habitat_index": 50,
    "water_index": 50,
}


def _two_alternatives(api):
    """One draft review holding the on-threshold and the just-below alternative."""
    plan = fx.create_plan(api)
    review = fx.create_review(api, plan["id"])
    assert review["status"] == C.REVIEW_STATUS_DRAFT
    at_threshold = fx.add_alternative(
        api, review["id"], label="Balanced Growth", **AT_THRESHOLD_INDICES
    )
    below_threshold = fx.add_alternative(
        api, review["id"], label="Slightly Lighter Traffic", **BELOW_THRESHOLD_INDICES
    )
    return review, at_threshold, below_threshold


def test_mitigation_credit_starts_exactly_at_a_raw_score_of_fifty(api):
    """Raw 50.00 earns 5.00 of credit; raw 49.97 earns none at all.

    "a raw score of 70 or more earns a credit of 15 percent of the raw score, a raw score
    of at least 50 but below 70 earns 10 percent of the raw score, and anything below 50
    earns no credit at all, that is, 0.00"

    Design: Corner/calculations/mitigation_tier_boundary_at_exactly_fifty
    """
    _review, at_threshold, below_threshold = _two_alternatives(api)

    # 0.35*50 + 0.25*50 + 0.20*50 + 0.20*50 == 50.00, which is inside the middle tier.
    assert at_threshold["raw_impact_score"] == 50.00
    assert at_threshold["mitigation_credit"] == 5.00
    assert at_threshold["net_impact_score"] == 45.00
    A.assert_two_decimals(at_threshold["raw_impact_score"], "raw_impact_score")
    A.assert_two_decimals(at_threshold["mitigation_credit"], "mitigation_credit")
    A.assert_two_decimals(at_threshold["net_impact_score"], "net_impact_score")
    A.assert_alternative_scores(at_threshold)

    # 0.35*49.9 + 0.25*50 + 0.20*50 + 0.20*50 == 49.965, rounded half up to 49.97,
    # a tenth of a point short of the tier and therefore uncredited.
    assert below_threshold["raw_impact_score"] == 49.97
    assert below_threshold["mitigation_credit"] == 0.00
    # "net_impact_score is the raw score less the credit" — with no credit the net score
    # equals the raw score exactly.
    assert below_threshold["net_impact_score"] == 49.97
    A.assert_alternative_scores(below_threshold)

    # The lighter-traffic alternative scores lower before mitigation yet ends up worse
    # after it, because the credit is keyed on the raw score.
    assert below_threshold["raw_impact_score"] < at_threshold["raw_impact_score"]
    assert below_threshold["net_impact_score"] > at_threshold["net_impact_score"]


def test_both_threshold_alternatives_are_evaluated_and_counted(api):
    """Each alternative added to the draft review enters EVALUATED and bumps its count.

    "Adding an alternative increments the parent review's `alternative_count` by one and
    its `version` by one, and the new alternative enters `EVALUATED`."

    Design: Corner/calculations/mitigation_tier_boundary_at_exactly_fifty
    """
    review, at_threshold, below_threshold = _two_alternatives(api)

    assert at_threshold["status"] == C.ALTERNATIVE_STATUS_EVALUATED
    assert below_threshold["status"] == C.ALTERNATIVE_STATUS_EVALUATED

    parent = validate_success(api.get_environmental_review(review["id"], CONSULTANT))
    assert parent["alternative_count"] == 2
    assert parent["version"] == review["version"] + 2
    assert parent["preferred_alternative_id"] is None

    rows, meta = validate_paginated(
        api.list_review_alternatives(review["id"], CONSULTANT)
    )
    assert meta["total_count"] == 2
    assert sorted(A.ids_of(rows)) == sorted([at_threshold["id"], below_threshold["id"]])
    assert [row["status"] for row in rows] == [
        C.ALTERNATIVE_STATUS_EVALUATED,
        C.ALTERNATIVE_STATUS_EVALUATED,
    ]
    for row in rows:
        A.assert_alternative_scores(row)
