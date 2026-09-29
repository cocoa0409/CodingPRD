"""Zone risk scoring: the two assessment bases and the tier band boundary."""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_append_only_record,
    assert_four_dp,
    assert_number_equals,
    assert_two_dp,
)
from test_helpers.constants import AssessmentBasis, PriorityBand, RiskTier
from test_helpers.factories import assessment_payload
from test_helpers.fixtures import (
    assess_zone,
    create_zone,
    pin_clock,
    read_household,
    read_zone,
    survey_one_unit,
)
from test_helpers.test_users import ANALYST

# A leaf zone whose demographic inputs place it exactly on the TIER_1 boundary:
# 40.00 incident + 10.00 injury + 9.00 building + 4.40 vulnerability points,
# leaving the alarm component to decide the tier.
ASHFIELD = {
    "zone_code": "Z-A70",
    "name": "Ashfield Leaf",
    "occupied_units": 2000,
    "structure_fire_count_5yr": 20,
    "fire_injury_count_5yr": 2,
    "pre_1980_unit_pct": 60.0,
    "senior_household_pct": 25.0,
    "under5_household_pct": 10.0,
    "disability_household_pct": 5.0,
    "assumed_alarm_absence_pct": 66.0,
    "daily_visit_cap": 12,
}


def _provisionally_scored_zone(api) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A freshly scored Ashfield zone plus its first assessment row."""
    pin_clock(api)
    zone = create_zone(api, **ASHFIELD)
    first = assess_zone(api, zone["id"], zone["version"])
    return zone, first


def test_01_provisional_basis_scores_the_zone_on_the_assumed_alarm_absence(api):
    """The provisional basis takes its alarm gap straight from the census estimate.

    PRD: "Under the **provisional** basis the alarm gap is simply the zone's
    `assumed_alarm_absence_pct` - the census or pre-survey estimate - and
    `surveyed_units` is ignored entirely."

    Design: Difficulty/dual_variant_calc/zone_risk_score_provisional_demographic_vs_validated_field_diverges
    """
    zone, first = _provisionally_scored_zone(api)

    assert first["basis"] == AssessmentBasis.PROVISIONAL
    assert_number_equals(first["alarm_gap_pct"], 66.00, "alarm_gap_pct")
    assert_number_equals(first["alarm_points"], 6.60, "alarm_points")
    assert_number_equals(first["incident_points"], 40.00, "incident_points")
    assert_number_equals(first["injury_points"], 10.00, "injury_points")
    assert_number_equals(first["building_points"], 9.00, "building_points")
    assert_number_equals(first["vulnerability_points"], 4.40, "vulnerability_points")
    assert_number_equals(first["risk_score"], 70.00, "risk_score")
    assert first["risk_tier"] == RiskTier.TIER_1
    assert_four_dp(first["incident_density_per_1000"], "incident_density_per_1000")
    assert_four_dp(first["injury_density_per_1000"], "injury_density_per_1000")
    assert_two_dp(first["risk_score"], "risk_score")
    assert_append_only_record(first)
    assert first["surveyed_units_at_assessment"] == 0
    assert first["sequence_no"] == 1


def test_02_validated_basis_on_the_same_zone_row_diverges_to_the_lower_tier(api):
    """The same row scores lower once the alarm gap comes from field data.

    PRD: "The single field that differs between the two bases is `alarm_gap_pct`,
    and the difference is material enough that the same zone row, on the same
    logical clock instant, can produce two different scores and even two different
    tiers depending on which basis was requested."

    Design: Difficulty/dual_variant_calc/zone_risk_score_provisional_demographic_vs_validated_field_diverges
    """
    zone, first = _provisionally_scored_zone(api)
    survey_one_unit(
        api,
        zone["id"],
        pre_existing_working_smoke_alarms=2,
        sleeping_areas_count=2,
        storeys=1,
    )

    current = read_zone(api, zone["id"])
    assert current["surveyed_units"] == 1
    assert current["surveyed_units_without_alarm"] == 0

    second = validate_success(
        api.create_assessment(
            zone["id"],
            assessment_payload(current["version"], basis=AssessmentBasis.VALIDATED),
            ANALYST,
        ),
        201,
    )

    assert second["basis"] == AssessmentBasis.VALIDATED
    assert_number_equals(second["alarm_gap_pct"], 0.00, "alarm_gap_pct")
    assert_number_equals(second["alarm_points"], 0.00, "alarm_points")
    assert_number_equals(second["risk_score"], 63.40, "risk_score")
    assert second["risk_tier"] == RiskTier.TIER_2
    assert_number_equals(first["risk_score"], 70.00, "first risk_score")
    assert first["risk_tier"] == RiskTier.TIER_1


def test_03_validated_run_snapshots_its_sequence_and_surveyed_units(api):
    """The second run numbers itself 2 and freezes the surveyed-unit count it used.

    PRD: "The run writes a new assessment row whose `sequence_no` is the count of
    that zone's pre-existing assessment rows plus 1, records the acting analyst's
    opaque identifier as `assessed_by_user_id`, and snapshots the zone's
    `surveyed_units` at the moment of execution into `surveyed_units_at_assessment`."

    Design: Difficulty/dual_variant_calc/zone_risk_score_provisional_demographic_vs_validated_field_diverges
    """
    zone, _first = _provisionally_scored_zone(api)
    survey_one_unit(
        api,
        zone["id"],
        pre_existing_working_smoke_alarms=2,
        sleeping_areas_count=2,
        storeys=1,
    )
    current = read_zone(api, zone["id"])

    second = validate_success(
        api.create_assessment(
            zone["id"],
            assessment_payload(current["version"], basis=AssessmentBasis.VALIDATED),
            ANALYST,
        ),
        201,
    )

    assert second["sequence_no"] == 2
    assert second["surveyed_units_at_assessment"] == 1
    assert second["zone_id"] == zone["id"]
    assert isinstance(second["assessed_by_user_id"], str)
    assert second["assessed_by_user_id"] != ""


def test_04_validated_writeback_repropagates_the_household_priority_band(api):
    """The write-back lands on the zone and re-bands every household in it.

    PRD: "A completed run writes `risk_score`, `risk_tier` and `assessment_basis`
    back onto the zone, points `current_assessment_id` at the new row, recomputes
    the priority band of every household in the zone (§3.3), and increments the
    zone's `version` by 1."

    Design: Difficulty/dual_variant_calc/zone_risk_score_provisional_demographic_vs_validated_field_diverges
    """
    zone, _first = _provisionally_scored_zone(api)
    surveyed = survey_one_unit(
        api,
        zone["id"],
        pre_existing_working_smoke_alarms=2,
        sleeping_areas_count=2,
        storeys=1,
    )
    before = read_zone(api, zone["id"])
    assert before["risk_tier"] == RiskTier.TIER_1

    second = validate_success(
        api.create_assessment(
            zone["id"],
            assessment_payload(before["version"], basis=AssessmentBasis.VALIDATED),
            ANALYST,
        ),
        201,
    )

    after = read_zone(api, zone["id"])
    assert_number_equals(after["risk_score"], 63.40, "zone risk_score")
    assert after["risk_tier"] == RiskTier.TIER_2
    assert after["assessment_basis"] == AssessmentBasis.VALIDATED
    assert after["current_assessment_id"] == second["id"]
    assert after["version"] == before["version"] + 1

    household = read_household(api, surveyed["household"]["id"])
    assert household["priority_band"] == PriorityBand.P3_STANDARD


def test_05_a_score_of_exactly_seventy_points_lands_in_the_top_tier(api):
    """The TIER_1 lower bound is inclusive, so exactly 70.00 is TIER_1.

    PRD: "A score of 70.00 or more is `TIER_1`. A score of at least 45.00 but
    strictly below 70.00 is `TIER_2`. A score strictly below 45.00 is `TIER_3`. A
    zone scoring exactly 70.00 is therefore `TIER_1`, and one scoring exactly 45.00
    is `TIER_2`."

    Design: Difficulty/boundary_precision_check/risk_tier_boundary_at_exactly_seventy_points_is_tier_1
    """
    pin_clock(api)
    zone = create_zone(api, **{**ASHFIELD, "zone_code": "Z-EDGE-HI", "name": "Edge High"})

    assessment = assess_zone(api, zone["id"], zone["version"])

    assert_number_equals(assessment["alarm_points"], 6.60, "alarm_points")
    assert_number_equals(assessment["risk_score"], 70.00, "risk_score")
    assert assessment["risk_tier"] == RiskTier.TIER_1
    assert read_zone(api, zone["id"])["risk_tier"] == RiskTier.TIER_1


def test_06_one_hundredth_of_a_point_below_the_bound_falls_to_the_middle_tier(api):
    """69.99 is strictly below the bound and therefore TIER_2, not TIER_1.

    PRD: "`alarm_points` is `alarm_gap_pct` multiplied by 0.10, rounded half up to
    two decimal places, then held to a ceiling of 10.00."

    Design: Difficulty/boundary_precision_check/risk_tier_boundary_at_exactly_seventy_points_is_tier_1
    """
    pin_clock(api)
    zone = create_zone(
        api,
        **{
            **ASHFIELD,
            "zone_code": "Z-EDGE-LO",
            "name": "Edge Low",
            "assumed_alarm_absence_pct": 65.9,
        },
    )

    assessment = assess_zone(api, zone["id"], zone["version"])

    assert_number_equals(assessment["alarm_points"], 6.59, "alarm_points")
    assert_number_equals(assessment["risk_score"], 69.99, "risk_score")
    assert assessment["risk_tier"] == RiskTier.TIER_2
    assert read_zone(api, zone["id"])["risk_tier"] == RiskTier.TIER_2
