"""Probes taken on both sides of, and exactly on, two pinned edges."""

from test_helpers.assertions import (
    assert_acres_equals,
    assert_cents_equals,
    assert_lease_dimensions,
    assert_status,
)
from test_helpers.fixtures import (
    advance_option_to_executed,
    caprock_recorded_lease,
    draft_option,
    exercise_option,
    publish_caprock_setback_rules,
    publish_setback_rule,
    raise_invoice,
    read_invoice,
    register_landowner,
    register_parcel,
    void_invoice,
)


def _security_probe_leases():
    """
    Three leases whose gross security sits below, exactly on, and above the first
    band edge of the administrative ladder.
    """
    landowner = register_landowner(legal_name="Ridgeline Solar Land Co", entity_type="LLC")
    landowner_id = landowner["id"]
    publish_caprock_setback_rules()
    publish_setback_rule(
        jurisdiction_code="48491",
        rule_type="PROPERTY_LINE",
        setback_feet=130,
        encumbrance_rate_per_acre=0.0500,
        consent_waivable=True,
    )

    probes = {}
    specs = (
        ("below", "R-2491-770", "48491", 105.25, 3.0, 99.99, "NOL-2982-B01"),
        ("at", "R-1188-004", "48453", 125.00, 4.0, 100.00, "NOL-2982-B02"),
        ("above", "R-2451-330", "48451", 106.00, 4.0, 106.00, "NOL-2982-B03"),
    )
    for label, apn, county, gross, slope, buildable, notice in specs:
        parcel = register_parcel(
            landowner_id,
            apn=apn,
            county_fips=county,
            gross_acres=gross,
            interconnection_distance_km=3.50,
            resource_capacity_factor=0.38,
            slope_pct=slope,
            title_condition_grade="B",
            zoning_code="AG2",
        )
        assert_acres_equals(parcel["buildable_acres"], buildable, f"{label} buildable_acres")
        assert_status(parcel, "QUALIFIED", f"{label} parcel")
        option = draft_option(
            parcel["id"],
            landowner_id,
            option_term_days=365,
            extension_count_allowed=0,
            base_rent_per_acre_cents=118000,
        )
        advance_option_to_executed(option["id"], landowner_id)
        probes[label] = exercise_option(option["id"], notice)
    return probes


def _crossover_lease():
    """A recorded royalty-hybrid lease tuned so the two rent legs can tie exactly."""
    setup = caprock_recorded_lease(
        recording_instrument_no="2026-0044822",
        exercise_notice_reference="NOL-2982-0005",
        royalty_hybrid=True,
        extension_count_allowed=0,
        base_rent_per_acre_cents=117600,
        royalty_rate_bps=350,
        escalator_mode="COMPOUND",
    )
    assert setup["lease"]["recording_status"] == "RECORDED"
    return setup["lease"]["id"]


def test_the_admin_rate_band_is_inclusive_at_its_lower_edge():
    """
    A gross of exactly fifty thousand dollars draws the middle band's 450 basis
    points, not the cheaper-acreage band's 600. One cent-band below it still draws
    600, and well above it still draws 450.

    PRD: "Step two reads `admin_rate_bps` off a three-band ladder against that
    gross figure: a gross below fifty thousand dollars carries 600 basis points, a
    gross of fifty thousand dollars or more but below one hundred and fifty
    thousand dollars carries 450 basis points, and a gross of one hundred and
    fifty thousand dollars or more carries 300 basis points."

    Design: Difficulty/boundary_precision_check/security_gross_exactly_at_five_million_tier_edge
    """
    probes = _security_probe_leases()

    below = probes["below"]
    assert_cents_equals(below["gross_security_cents"], 4999500, "below gross_security_cents")
    assert below["admin_rate_bps"] == 600, f"below admin_rate_bps: {below['admin_rate_bps']}"
    assert_cents_equals(below["admin_loading_cents"], 299970, "below admin_loading_cents")
    assert_cents_equals(
        below["total_security_required_cents"], 5299470, "below total security"
    )

    at = probes["at"]
    assert_cents_equals(at["gross_security_cents"], 5000000, "at gross_security_cents")
    assert at["admin_rate_bps"] == 450, f"at admin_rate_bps: {at['admin_rate_bps']}"
    assert_cents_equals(at["admin_loading_cents"], 225000, "at admin_loading_cents")
    assert_cents_equals(at["total_security_required_cents"], 5225000, "at total security")

    above = probes["above"]
    assert_cents_equals(above["gross_security_cents"], 5300000, "above gross_security_cents")
    assert above["admin_rate_bps"] == 450, f"above admin_rate_bps: {above['admin_rate_bps']}"
    assert_cents_equals(above["admin_loading_cents"], 238500, "above admin_loading_cents")
    assert_cents_equals(
        above["total_security_required_cents"], 5538500, "above total security"
    )


def test_the_required_security_is_not_monotonic_across_the_band_edge():
    """
    The smaller parcel owes more security than the larger one, because the rate it
    draws is dearer than the acreage it saves.

    PRD: "Because the rate falls as the gross rises, the total is **not**
    monotonic in acreage across a band boundary: 99.99 buildable acres require
    5,299,470 cents of security while 100.00 buildable acres require only
    5,225,000 cents."

    Design: Difficulty/boundary_precision_check/security_gross_exactly_at_five_million_tier_edge
    """
    probes = _security_probe_leases()
    below, at = probes["below"], probes["at"]

    assert below["gross_security_cents"] < at["gross_security_cents"], (
        "the below-edge lease should carry the smaller gross"
    )
    assert below["total_security_required_cents"] > at["total_security_required_cents"], (
        "the below-edge lease should nevertheless owe the larger total"
    )
    assert_acres_equals(below["acre_basis_at_exercise"], 99.99, "below acre_basis_at_exercise")
    assert_acres_equals(at["acre_basis_at_exercise"], 100.00, "at acre_basis_at_exercise")
    for label, lease in probes.items():
        assert_cents_equals(lease["security_posted_cents"], 0, f"{label} security_posted_cents")
        assert_lease_dimensions(lease, "PENDING_FIRST_RENT", "UNRECORDED")


def test_the_greater_of_returns_the_shared_value_once_at_the_crossover():
    """
    At exactly eighty thousand megawatt-hours the royalty leg equals the per-acre
    leg to the cent. The greater-of returns that one figure; summing the legs
    would have doubled the rent.

    PRD: "Under `ROYALTY_HYBRID` it is the greater of `per_acre_component_cents`
    and `royalty_component_cents`."

    Design: Difficulty/boundary_precision_check/royalty_versus_per_acre_greater_of_exact_tie
    """
    lease_id = _crossover_lease()

    invoice = raise_invoice(lease_id, period_year=1, production_mwh=80000)

    assert invoice["rent_variant"] == "FINAL_AS_BUILT"
    assert_acres_equals(invoice["acre_basis"], 100.00, "acre_basis")
    assert_cents_equals(invoice["per_acre_component_cents"], 11760000, "per-acre component")
    assert_cents_equals(invoice["royalty_component_cents"], 11760000, "royalty component")
    assert_cents_equals(invoice["gross_rent_cents"], 11760000, "gross rent at the tie")
    assert invoice["gross_rent_cents"] != 23520000, "the legs were summed, not compared"


def test_one_megawatt_hour_either_side_of_the_crossover_flips_the_winner():
    """
    One unit of production below the crossover the per-acre leg wins by a
    hundred and forty-seven cents; one unit above, the royalty leg wins by the
    same margin. Each probe reuses period one after the previous one is voided.

    PRD: "**Both components are rounded to whole cents before that comparison is
    made**; comparing the unrounded real numbers and rounding the winner
    afterwards is wrong and can produce a different total by a cent."

    Design: Difficulty/boundary_precision_check/royalty_versus_per_acre_greater_of_exact_tie
    """
    lease_id = _crossover_lease()

    low = raise_invoice(lease_id, period_year=1, production_mwh=79999)
    assert_cents_equals(low["royalty_component_cents"], 11759853, "low royalty component")
    assert_cents_equals(low["per_acre_component_cents"], 11760000, "low per-acre component")
    assert_cents_equals(low["gross_rent_cents"], 11760000, "low gross rent")
    void_invoice(low["id"])

    tie = raise_invoice(lease_id, period_year=1, production_mwh=80000)
    assert_cents_equals(tie["gross_rent_cents"], 11760000, "tie gross rent")
    void_invoice(tie["id"])

    high = raise_invoice(lease_id, period_year=1, production_mwh=80001)
    assert_cents_equals(high["royalty_component_cents"], 11760147, "high royalty component")
    assert_cents_equals(high["per_acre_component_cents"], 11760000, "high per-acre component")
    assert_cents_equals(high["gross_rent_cents"], 11760147, "high gross rent")

    assert high["gross_rent_cents"] - tie["gross_rent_cents"] == 147
    assert tie["gross_rent_cents"] - low["gross_rent_cents"] == 0
    assert_status(read_invoice(low["id"]), "VOID", "low invoice")
    assert_status(read_invoice(tie["id"]), "VOID", "tie invoice")
    assert_status(read_invoice(high["id"]), "DRAFT", "high invoice")
