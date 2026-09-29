"""A settlement engineered to land exactly on the 15000-cent rebate tier edge, so
that the tier lookup can only be satisfied by keying on the pre-rebate cumulative
basis with an inclusive lower bound."""

from test_helpers import (
    assert_certificate,
    assert_kit,
    assert_program_balances,
    certify_destruction_for,
    read_kit,
    read_program,
    setup_certifiable_shipment,
)

# A high-volume syringe patient on a manufacturer program whose allowance is
# deliberately generous, shipped in an EIGHT_GALLON-only packaging specification.
_RMW_SPEC = {
    "spec_code": "PS-B",
    "un_specification_code": "UN 4H2/Y30/S/26",
    "postal_service": "UPS_GROUND_MEDICAL",
    "hazard_class": "UN3291_REGULATED_MEDICAL_WASTE",
    "max_gross_weight_grams": 31700,
    "allowed_container_sizes": ["EIGHT_GALLON"],
    "requires_absorbent": False,
    "status": "ACTIVE",
}
_LARGE_FACILITY = {
    "name": "Central Valley Sharps Treatment",
    "permit_number": "CA-TF-0002",
    "daily_intake_capacity_units": 5000,
}
_GLUCOCARE = {
    "legal_name": "GlucoCare Devices LLC",
    "contact_email": "stewardship@glucocare.example",
}
_GENEROUS_PROGRAM = {
    "program_code": "GCM-2026",
    "funding_ceiling_cents": 500000,
    "per_kit_allowance_cents": 30000,
}
_SYRINGE_PATIENT = {
    "full_name": "Milo Chen",
    "therapy_type": "INSULIN_SYRINGES",
    "weekly_sharps_count": 140,
    "contact_email": "milo@example.com",
}


def _settled_syringe_kit(api):
    """Drive one 2400-unit, 23684 g syringe kit all the way to a conforming screening
    on a brand-new manufacturer program with no prior commitments."""
    return setup_certifiable_shipment(
        api,
        packaging_spec_overrides=_RMW_SPEC,
        facility_overrides=_LARGE_FACILITY,
        sponsor_overrides=_GLUCOCARE,
        program_overrides=_GENEROUS_PROGRAM,
        patient_overrides=_SYRINGE_PATIENT,
        enrollment_overrides={"cadence_days": 30, "kits_authorized": 3},
        fill_units=2400,
        sealed_gross_weight_grams=23684,
        declared_gross_weight_grams=23684,
        scheduled_intake_date="2026-08-12",
        observed_gross_weight_grams=23684,
    )


def test_01_syringe_demand_pushes_sizing_past_three_gallon_to_eight_gallon(api):
    """140 syringes a week at 2 units each over a 30-day cadence with the safety
    margin gives 1380 required units, which no container below EIGHT_GALLON can hold.

    PRD 3.4: "The computation multiplies the weekly count by that factor, then by the number of cadence days, then by 115, divides the product by 700, and rounds the single resulting quotient up to the next whole number."
    PRD 3.4: "A catalogue row is a **candidate** for this kit when four conditions all hold: its volume is at most the patient's state cap `max_container_volume_liters`, inclusively; its capacity is at least `required_units`, inclusively; if the patient's therapy is `INFUSION_SETS`, its volume is at least 7.6 litres; and if the patient's therapy is `LANCETS_ONLY`, its volume is at most 11.4 litres."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)

    assert_kit(
        read_kit(api, ctx["kit"]["id"]),
        container_size="EIGHT_GALLON",
        required_units=1380,
        capacity_units=3600,
        volume_liters=30.3,
    )


def test_02_the_eight_gallon_reservation_prices_its_own_capacity(api):
    """The reservation is the 6900-cent EIGHT_GALLON base plus 3600 capacity units at
    4 g each priced at 38 cents/kg, which is 547.2 cents rounded half up to 547.

    PRD 3.4: "The base component is the catalogue's `unit_cost_cents` for the selected size."
    PRD 3.4: "`provisional_cost_cents` is the base component plus that rounded transport component."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)

    assert_kit(read_kit(api, ctx["kit"]["id"]), provisional_cost_cents=7447)


def test_03_the_tier_is_keyed_on_the_pre_rebate_cumulative_basis(api):
    """The four rounded components sum to exactly 15000 cents, and the basis is the
    program's committed_cents before these appends (0) plus that figure, landing on the
    inclusive lower edge of the three-percent tier. Keying on the post-rebate total
    would read a basis of 0 and select no rebate at all.

    PRD 3.8: "For a `MANUFACTURER` sponsor the percentage is selected from a tier table keyed on a cumulative basis figure, and that basis is the program's `committed_cents` **as it stands before this certificate's ledger appends** plus this kit's capped pre-rebate amount."
    PRD 3.8: "The tiers are: a basis from 0 through 14999 cents inclusive gives 0; a basis from 15000 through 29999 cents inclusive gives 0.03; and a basis from 30000 through 100000000 cents inclusive gives 0.06."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)

    certificate = certify_destruction_for(api, ctx, destroyed_units=2400)

    assert certificate["rebate_pct_applied"] == 0.03


def test_04_the_three_percent_rebate_is_deducted_from_the_capped_amount(api):
    """15000 cents less three percent of 15000 leaves 14550, and the 30000-cent
    allowance never binds.

    PRD 3.8: "The rebate amount is the capped amount multiplied by that percentage, rounded half up to a whole cent, and `final_kit_cost_cents` is the capped amount less that rebate amount."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)

    certificate = certify_destruction_for(api, ctx, destroyed_units=2400)

    assert_certificate(
        certificate,
        destroyed_units=2400,
        final_kit_cost_cents=14550,
        rebate_pct_applied=0.03,
        status="ISSUED",
    )


def test_05_the_certificate_number_prefixes_the_facility_permit(api):
    """The facility has never minted a certificate, so the sequence number is 1,
    zero-padded to five digits behind the permit number.

    PRD 3.8: "Its `certificate_number` is the literal text `CERT-`, then the facility's `permit_number`, then a hyphen, then a sequence number zero-padded to five digits, where the sequence number is the facility's `certificates_issued_count` plus one."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)

    certificate = certify_destruction_for(api, ctx, destroyed_units=2400)

    assert certificate["certificate_number"] == "CERT-CA-TF-0002-00001"


def test_06_the_rebated_figure_is_what_the_program_commits(api):
    """It is the post-rebate amount that reaches the ledger and the program totals, so
    committed_cents and final_total_cents both read 14550 and 485450 remains available.

    PRD 3.2: "`final_total_cents`, the sum of `final_kit_cost_cents` over this program's `ISSUED` certificates."

    Design: Difficulty/combinatorial_formula/rebate_tier_keyed_on_pre_rebate_cumulative_total
    """
    ctx = _settled_syringe_kit(api)
    certify_destruction_for(api, ctx, destroyed_units=2400)

    program = read_program(api, ctx["sponsorship_program"]["id"])
    assert program["final_total_cents"] == 14550
    assert_program_balances(
        program,
        reserved_cents=0,
        committed_cents=14550,
        available_cents=485450,
        status="ACTIVE",
    )
