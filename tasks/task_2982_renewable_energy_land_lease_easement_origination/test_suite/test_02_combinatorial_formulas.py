"""Formulas whose pinned rounding and keying order changes the answer."""

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_score_equals,
    assert_status,
)
from test_helpers.fixtures import (
    advance_option_to_executed,
    draft_option,
    exercise_option,
    publish_setback_rule,
    read_lease,
    read_option,
    register_landowner,
    register_parcel,
)


def _llano_uplands_parcel():
    """An owner in a two-ordinance county with one small deeded tract."""
    landowner = register_landowner(
        legal_name="Llano Uplands Partnership", entity_type="PARTNERSHIP"
    )
    publish_setback_rule(
        jurisdiction_code="48027",
        rule_type="PROPERTY_LINE",
        setback_feet=125,
        encumbrance_rate_per_acre=0.0550,
        consent_waivable=True,
    )
    publish_setback_rule(
        jurisdiction_code="48027",
        rule_type="PUBLIC_ROAD",
        setback_feet=80,
        encumbrance_rate_per_acre=0.0750,
        consent_waivable=False,
    )
    parcel = register_parcel(
        landowner["id"],
        apn="R-2027-118",
        county_fips="48027",
        gross_acres=15.00,
        interconnection_distance_km=2.00,
        resource_capacity_factor=0.36,
        slope_pct=3.0,
        title_condition_grade="A",
        zoning_code="AG1",
    )
    return landowner, parcel


def _pecos_bend_parcel():
    """An owner in a single-ordinance county with a tract just under the tier edge."""
    landowner = register_landowner(
        legal_name="Pecos Bend Land Company LLC", entity_type="LLC"
    )
    publish_setback_rule(
        jurisdiction_code="48491",
        rule_type="PROPERTY_LINE",
        setback_feet=130,
        encumbrance_rate_per_acre=0.0500,
        consent_waivable=True,
    )
    parcel = register_parcel(
        landowner["id"],
        apn="R-2491-770",
        county_fips="48491",
        gross_acres=105.25,
        interconnection_distance_km=3.50,
        resource_capacity_factor=0.38,
        slope_pct=3.0,
        title_condition_grade="B",
        zoning_code="AG2",
    )
    return landowner, parcel


def test_setback_acreage_rounds_per_rule_before_the_rules_are_summed():
    """
    Fifteen deeded acres against two ordinance rates accumulate to 1.96 encumbered
    acres because each rule's product is rounded before the sum is taken. Summing
    the rates first would have produced 1.95.

    PRD: "Summing the rates and rounding once at the end is wrong and yields a
    different answer: fifteen deeded acres against rates of 0.0550 and 0.0750
    give 1.96 acres under the pinned order and 1.95 under the sum-then-round
    order."

    Design: Difficulty/combinatorial_formula/setback_rounding_order_per_rule_then_sum
    """
    _landowner, parcel = _llano_uplands_parcel()

    assert_acres_equals(parcel["raw_setback_acres"], 1.96, "raw_setback_acres")
    assert_acres_equals(parcel["consent_released_acres"], 0.00, "consent_released_acres")
    assert_acres_equals(
        parcel["setback_encumbered_acres"], 1.96, "setback_encumbered_acres"
    )
    assert_acres_equals(parcel["buildable_acres"], 13.04, "buildable_acres")
    assert_acres_equals(parcel["slope_excluded_acres"], 0.00, "slope_excluded_acres")


def test_a_top_tier_score_still_fails_the_eighty_acre_qualification_floor():
    """
    The same small tract screens into the top tier and still stays in screening,
    because qualification demands the acreage floor as well as the tier.

    PRD: "A parcel sitting in `SCREENING` is promoted `SCREENING → QUALIFIED`
    when its `buildable_acres` is at least 80.00 acres, its `screening_tier` is
    `PRIORITY` or `STANDARD`, and its `blocking_curative_open_count` is zero."

    Design: Difficulty/combinatorial_formula/setback_rounding_order_per_rule_then_sum
    """
    _landowner, parcel = _llano_uplands_parcel()

    assert_score_equals(parcel["screening_score"], 90.30, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY"
    assert_acres_equals(parcel["buildable_acres"], 13.04, "buildable_acres")
    assert_status(parcel, "SCREENING", "parcel")


def test_the_three_acreage_figures_conserve_the_deed_exactly():
    """
    Whatever the rounding order does to the individual terms, the derived
    breakdown adds back up to the deeded figure.

    PRD: "Whenever `buildable_acres` comes out greater than zero, the three
    figures conserve the deed exactly: `gross_acres` equals `buildable_acres`
    plus `slope_excluded_acres` plus `setback_encumbered_acres`."

    Design: Difficulty/combinatorial_formula/setback_rounding_order_per_rule_then_sum
    """
    _landowner, parcel = _llano_uplands_parcel()

    total = (
        parcel["buildable_acres"]
        + parcel["slope_excluded_acres"]
        + parcel["setback_encumbered_acres"]
    )
    assert_acres_equals(total, 15.00, "conserved deeded acreage")
    assert_acres_equals(parcel["gross_acres"], 15.00, "gross_acres")


def test_security_band_is_read_off_the_gross_never_off_the_total():
    """
    A lease snapshotted at 99.99 buildable acres sits just under the first band
    boundary on its gross figure, so it carries the dearest administrative rate
    and a total that exceeds what a whole hundred acres would have required.

    PRD: "Because the rate falls as the gross rises, the total is **not**
    monotonic in acreage across a band boundary: 99.99 buildable acres require
    5,299,470 cents of security while 100.00 buildable acres require only
    5,225,000 cents."

    Design: Difficulty/combinatorial_formula/security_tier_keyed_on_gross_not_total
    """
    landowner, parcel = _pecos_bend_parcel()
    assert_acres_equals(parcel["raw_setback_acres"], 5.26, "raw_setback_acres")
    assert_acres_equals(parcel["buildable_acres"], 99.99, "buildable_acres")
    assert_score_equals(parcel["screening_score"], 82.95, "screening_score")
    assert parcel["screening_tier"] == "PRIORITY"
    assert_status(parcel, "QUALIFIED", "parcel")

    option = draft_option(parcel["id"], landowner["id"], escalator_mode="SIMPLE")
    advance_option_to_executed(option["id"], landowner["id"])
    lease = exercise_option(option["id"], "NOL-2982-0002")

    assert_acres_equals(lease["acre_basis_at_exercise"], 99.99, "acre_basis_at_exercise")
    assert_cents_equals(lease["gross_security_cents"], 4999500, "gross_security_cents")
    assert lease["admin_rate_bps"] == 600, f"admin_rate_bps: got {lease['admin_rate_bps']}"
    assert_cents_equals(lease["admin_loading_cents"], 299970, "admin_loading_cents")
    assert_cents_equals(
        lease["total_security_required_cents"], 5299470, "total_security_required_cents"
    )


def test_option_consideration_is_priced_on_deeded_not_buildable_acreage():
    """
    The initial option fee on the same tract is charged over all 105.25 deeded
    acres, not over the 99.99 acres the setback ordinance leaves buildable.

    PRD: "**Option fees are always priced on deeded acreage, never on buildable
    acreage** — that is the commercial convention, and it does not change when
    consents or setbacks move the buildable figure."

    Design: Difficulty/combinatorial_formula/security_tier_keyed_on_gross_not_total
    """
    landowner, parcel = _pecos_bend_parcel()
    option = draft_option(parcel["id"], landowner["id"], escalator_mode="SIMPLE")
    advance_option_to_executed(option["id"], landowner["id"])
    lease = exercise_option(option["id"], "NOL-2982-0002")

    exercised = read_option(option["id"])
    assert_status(exercised, "EXERCISED", "option")
    assert_cents_equals(
        exercised["total_option_paid_cents"], 263125, "total_option_paid_cents"
    )

    fresh_lease = read_lease(lease["id"])
    assert_cents_equals(fresh_lease["security_posted_cents"], 0, "security_posted_cents")
    assert fresh_lease["rent_status"] == "PENDING_FIRST_RENT"
