"""Formula claims: the occupancy surcharge, the rule input set, tiers and weights."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_score_equals,
    assert_status,
)
from test_helpers.factories import crossing_payload
from test_helpers.fixtures import (
    client,
    plan_corridor,
    publish_setback_rule,
    read_corridor,
    read_parcel,
    register_landowner,
    register_parcel,
)
from test_helpers.test_users import LAND_AGENT

SANDHILL = {
    "legal_name": "Sandhill Prairie LLC",
    "entity_type": "LLC",
    "mailing_state": "TX",
    "contact_email": "ops@sandhill.example",
    "w9_on_file": True,
    "payment_hold": False,
}

CLEAN_COUNTY = "48451"


def _tract(landowner_id: str, apn: str = "R-9001-001", **overrides):
    """One two-hundred-acre tract of a known owner, with any input overridden."""
    inputs = {
        "apn": apn,
        "county_fips": CLEAN_COUNTY,
        "gross_acres": 200.00,
        "interconnection_distance_km": 3.50,
        "resource_capacity_factor": 0.38,
        "slope_pct": 4.0,
        "title_condition_grade": "B",
        "zoning_code": "AG2",
    }
    inputs.update(overrides)
    return register_parcel(landowner_id, **inputs)


def _corridor_over_a_clean_parcel():
    """A five-kilometre planned route and one unencumbered tract to cross."""
    parcel = _tract(register_landowner(**SANDHILL)["id"])
    corridor = plan_corridor(
        route_name="Sandhill Collection A",
        total_length_m=5000,
        voltage_class="COLLECTION_34_5KV",
        buffer_m=50,
    )
    assert_status(corridor, "PLANNED", "corridor")
    return corridor["id"], parcel["id"]


def test_the_surcharge_counts_only_the_days_past_the_thirtieth():
    """
    Forty days of occupancy buys ten surcharged days at fifty basis points each.
    Charging all forty, or none, gives a different price.

    PRD: "`long_occupancy_surcharge_bps` is zero for the first thirty days: when
    `duration_days` is 30 or less the surcharge is 0 basis points, and otherwise it is
    fifty basis points for each day beyond the thirtieth, capped at 2500 basis points
    — a twenty-five-percent ceiling, reached at eighty days of occupancy and never
    exceeded however long the window runs."

    Design: Corner/calculations/crossing_surcharge_applies_only_above_thirty_free_days
    """
    corridor_id, parcel_id = _corridor_over_a_clean_parcel()

    response = client().create_crossing_agreement(
        crossing_payload(
            corridor_id,
            parcel_id,
            crossing_kind="COLLECTION_LINE",
            station_start_m=1000,
            station_end_m=1600,
            occupancy_window_start="2026-08-05T00:00:00Z",
            occupancy_window_end="2026-09-14T00:00:00Z",
        ),
        LAND_AGENT,
    )

    crossing = validate_success(response, 201)
    assert crossing["occupied_m"] == 600, crossing["occupied_m"]
    assert crossing["duration_days"] == 40, crossing["duration_days"]
    assert crossing["long_occupancy_surcharge_bps"] == 500, (
        crossing["long_occupancy_surcharge_bps"]
    )
    assert_cents_equals(crossing["compensation_cents"], 1134000, "compensation_cents")
    assert_status(crossing, "PROPOSED", "crossing")
    assert read_corridor(corridor_id)["granted_crossing_count"] == 0


def test_the_surcharge_is_clamped_at_twenty_five_hundred_basis_points():
    """
    A hundred-and-two-day occupancy would earn thirty-six hundred basis points on
    the linear reading. The declared ceiling holds it at twenty-five hundred, so the
    price stops rising well before the window does.

    PRD: "`compensation_cents` is the base amount plus the base amount multiplied by
    `long_occupancy_surcharge_bps` divided by ten thousand, with that surcharge term
    rounded half up to whole cents once."

    Design: Corner/calculations/crossing_surcharge_is_capped_at_twenty_five_hundred_bps
    """
    corridor_id, parcel_id = _corridor_over_a_clean_parcel()

    response = client().create_crossing_agreement(
        crossing_payload(
            corridor_id,
            parcel_id,
            crossing_kind="COLLECTION_LINE",
            station_start_m=1000,
            station_end_m=1600,
            occupancy_window_start="2026-08-05T00:00:00Z",
            occupancy_window_end="2026-11-15T00:00:00Z",
        ),
        LAND_AGENT,
    )

    crossing = validate_success(response, 201)
    assert crossing["duration_days"] == 102, crossing["duration_days"]
    assert crossing["long_occupancy_surcharge_bps"] == 2500, (
        crossing["long_occupancy_surcharge_bps"]
    )
    assert_cents_equals(crossing["compensation_cents"], 1350000, "compensation_cents")
    assert crossing["compensation_cents"] != 1468800, (
        "the surcharge was applied linearly instead of being clamped"
    )


def test_the_surcharge_term_rounds_a_half_cent_upward():
    """
    A single metre of access road held thirty-one days puts the surcharge term on
    exactly four and a half cents — the one tie this formula can produce. It must
    round up to five, so the total is nine hundred and five cents.

    PRD: "A base amount is `occupied_m` multiplied by the per-metre rate for the
    `crossing_kind`: eighteen dollars per metre for a `COLLECTION_LINE`, thirty-four
    dollars per metre for an `INTERCONNECTION_ROUTE`, and nine dollars per metre for
    an `ACCESS_ROAD`."

    Design: Corner/calculations/crossing_surcharge_rounds_half_up_to_a_whole_cent
    """
    corridor_id, parcel_id = _corridor_over_a_clean_parcel()

    response = client().create_crossing_agreement(
        crossing_payload(
            corridor_id,
            parcel_id,
            crossing_kind="ACCESS_ROAD",
            station_start_m=2000,
            station_end_m=2001,
            occupancy_window_start="2026-08-05T00:00:00Z",
            occupancy_window_end="2026-09-05T00:00:00Z",
        ),
        LAND_AGENT,
    )

    crossing = validate_success(response, 201)
    assert crossing["occupied_m"] == 1, crossing["occupied_m"]
    assert crossing["duration_days"] == 31, crossing["duration_days"]
    assert crossing["long_occupancy_surcharge_bps"] == 50, (
        crossing["long_occupancy_surcharge_bps"]
    )
    assert_cents_equals(crossing["compensation_cents"], 905, "compensation_cents")
    assert crossing["compensation_cents"] != 904, (
        "the half-cent surcharge term was truncated instead of rounded half up"
    )


def test_a_heavier_ordinance_in_another_county_encumbers_nothing():
    """
    Two ordinances are on the books before the tract is registered, and only the one
    naming this county is in the input set. Reading both would have taken sixty
    percent of the deed instead of ten.

    PRD: "The applicable rules are every setback rule whose `jurisdiction_code` equals
    this parcel's `county_fips` — setback rules have no lifecycle, so there is no
    status filter — taken in `created_at` ascending order."

    Design: Corner/calculations/buildable_acres_ignores_setback_rules_of_other_jurisdictions
    """
    landowner_id = register_landowner(**SANDHILL)["id"]
    publish_setback_rule(
        jurisdiction_code=CLEAN_COUNTY,
        rule_type="PROPERTY_LINE",
        setback_feet=150,
        encumbrance_rate_per_acre=0.1000,
        consent_waivable=False,
    )
    publish_setback_rule(
        jurisdiction_code="48029",
        rule_type="WETLAND",
        setback_feet=300,
        encumbrance_rate_per_acre=0.5000,
        consent_waivable=False,
    )

    parcel = _tract(landowner_id)

    assert_acres_equals(parcel["raw_setback_acres"], 20.00, "raw_setback_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 20.00, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(parcel["buildable_acres"], 180.00, "buildable_acres")
    assert_status(parcel, "QUALIFIED", "parcel")
    assert parcel["screening_tier"] == "PRIORITY", parcel["screening_tier"]


def test_a_slope_of_exactly_five_percent_excludes_no_ground():
    """
    The first tier boundary is written inclusive, so a tract sitting exactly on it
    keeps every deeded acre. A strict reading of the same ladder would take a tenth
    of the parcel.

    PRD: "A slope tier is read off `slope_pct` against three breakpoints: a slope of
    5.0 percent or less excludes nothing, so the rate is zero; a slope greater than
    5.0 and at most 10.0 percent carries a rate of one tenth; a slope greater than
    10.0 and at most 15.0 percent carries a rate of one quarter; and a slope greater
    than 15.0 percent carries a rate of one half."

    Design: Corner/calculations/slope_exclusion_tier_break_is_upper_inclusive_at_five_percent
    """
    landowner_id = register_landowner(**SANDHILL)["id"]

    parcel = _tract(landowner_id, apn="R-9003-050", slope_pct=5.0)

    assert_acres_equals(parcel["slope_excluded_acres"], 0.00, "slope_excluded_acres")
    assert_acres_equals(parcel["buildable_acres"], 200.00, "buildable_acres")
    assert_score_equals(parcel["screening_score"], 81.35, "screening_score")
    assert parcel["screening_tier"] == "STANDARD", parcel["screening_tier"]
    assert_status(parcel, "QUALIFIED", "parcel")


def test_a_tenth_of_a_point_past_the_break_costs_a_tenth_of_the_parcel():
    """
    The neighbouring tract differs by one tenth of a percentage point of slope and
    loses twenty acres for it, while its buildability sub-score slips by four tenths
    of a point — eight hundredths of a point on the blended score.

    PRD: "The buildability sub-score is one hundred less four points per percentage
    point of `slope_pct`, clamped into the range from 0 to 100."

    Design: Corner/calculations/slope_exclusion_tier_break_is_upper_inclusive_at_five_percent
    """
    landowner_id = register_landowner(**SANDHILL)["id"]
    on_the_break = _tract(landowner_id, apn="R-9003-050", slope_pct=5.0)

    past_the_break = _tract(landowner_id, apn="R-9003-051", slope_pct=5.1)

    assert_acres_equals(
        past_the_break["slope_excluded_acres"], 20.00, "slope_excluded_acres"
    )
    assert_acres_equals(past_the_break["buildable_acres"], 180.00, "buildable_acres")
    assert_score_equals(past_the_break["screening_score"], 81.27, "screening_score")
    assert past_the_break["screening_tier"] == "STANDARD", (
        past_the_break["screening_tier"]
    )
    assert_status(past_the_break, "QUALIFIED", "parcel")
    assert_score_equals(
        read_parcel(on_the_break["id"])["screening_score"], 81.35, "screening_score"
    )


def test_four_saturated_sub_scores_blend_to_exactly_one_hundred():
    """
    Zero distance, the capacity factor that maxes the resource term, no slope and a
    clean title report each score one hundred, so the four weights are observable on
    their own: they must sum to one, giving exactly one hundred and nothing near it.

    PRD: "`screening_score` is the weighted sum of the four sub-scores — three tenths
    of the interconnection sub-score, one quarter of the resource sub-score, one fifth
    of the buildability sub-score and one quarter of the title sub-score — rounded
    half up to two decimals **once**, at the end."

    Design: Corner/calculations/screening_score_reaches_one_hundred_when_every_sub_score_is_maximal
    """
    landowner_id = register_landowner(**SANDHILL)["id"]

    parcel = _tract(
        landowner_id,
        apn="R-9100-777",
        interconnection_distance_km=0.00,
        resource_capacity_factor=0.4000,
        slope_pct=0.0,
        title_condition_grade="A",
    )

    assert_score_equals(parcel["screening_score"], 100.00, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY", parcel["screening_tier"]
    assert_acres_equals(parcel["buildable_acres"], 200.00, "buildable_acres")
    assert_acres_equals(parcel["slope_excluded_acres"], 0.00, "slope_excluded_acres")
