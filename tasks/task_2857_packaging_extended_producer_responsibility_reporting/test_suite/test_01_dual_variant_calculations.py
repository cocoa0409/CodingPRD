"""Dual-variant calculations: the same inputs priced under two declared variants.

Each test drives one variant pair end to end through the public endpoints and
pins the divergence to the single switch that causes it — the program's
`obligation_basis`, the assessment `variant`, or the projection `units_basis`.
"""

from test_helpers import (
    ExemptionStatus,
    FeeVariant,
    ObligationBasis,
    ReportFeeStatus,
    SubmissionStatus,
    UnitsBasis,
    VERIFIER_HEADERS,
    VERIFIER_USER_ID,
    assert_cents,
    assert_producer,
    assert_registration,
    assert_report,
    assert_report_line,
    assert_sku,
    assert_weight,
    expected_membership_fee_cents,
    factories as f,
    fixtures as fx,
    validate_success,
)


# ---------------------------------------------------------------------------
# Variant one: eligibility. Only GROUP_LEVEL adds the parent's revenue.
# ---------------------------------------------------------------------------
def _affiliate_in_two_programs(api):
    """A parent plus an affiliate holding one DRAFT registration in each program."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    group_program = fx.make_deep_ca_program(api)
    entity_program = fx.make_deep_or_program(api)

    parent = fx.make_producer(
        api,
        legal_name="Parent Brands Inc",
        annual_gross_revenue_usd=3000000,
        brand_owner_flag=True,
        contact_email="par@x.com",
    )
    fx.make_sku_with_components(
        api,
        parent,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        name="Par Jar",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=110,
    )
    parent = fx.determine_obligation(api, parent)
    assert_producer(parent, annual_packaging_weight_kg=5.500)

    affiliate = fx.make_producer(
        api,
        legal_name="Sub Brands LLC",
        parent_producer_id=parent["id"],
        annual_gross_revenue_usd=4000000,
        brand_owner_flag=True,
        contact_email="sub@x.com",
    )
    fx.make_sku_with_components(
        api,
        affiliate,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        name="Sub Jar",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=210,
    )
    affiliate = fx.determine_obligation(api, affiliate)
    assert_producer(affiliate, annual_packaging_weight_kg=10.500)

    return {
        "affiliate": affiliate,
        "group_registration": fx.make_registration(api, affiliate, group_program["id"]),
        "entity_registration": fx.make_registration(api, affiliate, entity_program["id"]),
    }


def test_group_level_submission_adds_the_parent_revenue_and_obligates(api):
    """A GROUP_LEVEL program assesses the affiliate's family, so it is obligated.

    The affiliate alone earns 4000000 USD, under the 5000000 threshold, but the
    group total of 7000000 is over it and the group weight is 16.000 kg.

    Design: Difficulty/dual_variant_calc/exemption_variant_divergence_entity_level_vs_group_level
    """
    built = _affiliate_in_two_programs(api)
    affiliate = built["affiliate"]

    submitted = validate_success(
        api.submit_registration(
            built["group_registration"]["id"], None, fx.officer(affiliate)
        )
    )

    assert_registration(
        submitted,
        producer_id=affiliate["id"],
        exemption_basis_applied=ObligationBasis.GROUP_LEVEL,
        assessed_group_revenue_usd=7000000,
        exemption_status=ExemptionStatus.OBLIGATED,
    )
    assert_weight(submitted["assessed_group_weight_kg"], 16.000, "assessed_group_weight_kg")


def test_entity_level_submission_ignores_the_parent_and_exempts(api):
    """An ENTITY_LEVEL program assesses the affiliate alone, so it is exempt.

    The identical producer and the identical stock keeping unit yield an
    assessed revenue of 4000000 and an assessed weight of 10.500 kg, both under
    the program thresholds, so the small-producer exemption applies.

    Design: Difficulty/dual_variant_calc/exemption_variant_divergence_entity_level_vs_group_level
    """
    built = _affiliate_in_two_programs(api)
    affiliate = built["affiliate"]

    submitted = validate_success(
        api.submit_registration(
            built["entity_registration"]["id"], None, fx.officer(affiliate)
        )
    )

    assert_registration(
        submitted,
        producer_id=affiliate["id"],
        exemption_basis_applied=ObligationBasis.ENTITY_LEVEL,
        assessed_group_revenue_usd=4000000,
        exemption_status=ExemptionStatus.EXEMPT_SMALL_PRODUCER,
    )
    assert_weight(submitted["assessed_group_weight_kg"], 10.500, "assessed_group_weight_kg")


# ---------------------------------------------------------------------------
# Variant two: money. Only FINAL counts the report's own tonnage in the tier.
# ---------------------------------------------------------------------------
def _plastic_paper_report(api):
    """A submitted 3300.000 kg report against a banded PLASTIC and PAPER schedule."""
    rates = [
        f.material_rate("PLASTIC", 0, 1000, 42),
        f.material_rate("PLASTIC", 1000, 5000, 33),
        f.material_rate("PLASTIC", 5000, None, 25),
        f.material_rate("PAPER", 0, 1000, 18),
        f.material_rate("PAPER", 1000, None, 12),
    ]
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Big Brand Co",
            annual_gross_revenue_usd=40000000,
            contact_email="p1@x.com",
        ),
        sku_components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=25,
                recyclability_class="READILY_RECYCLABLE",
                pcr_content_pct=30,
            ),
            f.component_payload(
                material_type="PAPER",
                unit_weight_grams=8,
                recyclability_class="LIMITED",
                pcr_content_pct=0,
            ),
        ],
        sku_overrides=dict(name="Bottle 500ml", units_sold_annual_estimate=100000),
        schedule_overrides=dict(material_rates=rates),
        line_units=100000,
    )
    assert_cents(
        chain["membership"]["membership_fee_cents"],
        expected_membership_fee_cents(250000, 3300.000),
        "membership_fee_cents",
    )
    assert_report(
        chain["report"],
        submission_status=SubmissionStatus.SUBMITTED,
        fee_status=ReportFeeStatus.UNASSESSED,
        verification_required=True,
        total_weight_kg=3300.000,
    )
    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 3300.000, "reported_weight_kg_ytd")
    return chain


def test_provisional_assessment_excludes_the_reports_own_tonnage(api):
    """PROVISIONAL prices a first report at a tier basis of zero.

    The year-to-date tonnage minus this report's own 3300.000 kg leaves 0.000,
    which selects the lowest PLASTIC and PAPER bands at 42 and 18 cents, so the
    single line costs 106530 cents.

    Design: Difficulty/dual_variant_calc/report_fee_variant_divergence_provisional_vs_final
    """
    chain = _plastic_paper_report(api)

    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.PROVISIONAL), chain["admin_headers"]
        )
    )

    assert_report(
        assessed,
        tier_basis_kg=0.000,
        fee_subtotal_cents=106530,
        fee_variant_applied=FeeVariant.PROVISIONAL,
        fee_status=ReportFeeStatus.PROVISIONAL,
        submission_status=SubmissionStatus.SUBMITTED,
    )
    line = validate_success(
        api.get_report_line(chain["line"]["id"], chain["officer_headers"])
    )
    assert_report_line(line, line_fee_cents=106530)


def test_final_assessment_includes_the_reports_own_tonnage(api):
    """FINAL reprices the identical line at a tier basis of 3300.000 kg.

    Verification is required at this weight, so an unqualified opinion is issued
    first; the higher tier basis selects the 33 and 12 cent bands and the same
    line now costs 81645 cents, overwriting the provisional figure.

    Design: Difficulty/dual_variant_calc/report_fee_variant_divergence_provisional_vs_final
    """
    chain = _plastic_paper_report(api)
    provisional = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.PROVISIONAL), chain["admin_headers"]
        )
    )
    assert_cents(provisional["fee_subtotal_cents"], 106530, "provisional subtotal")

    verified = fx.verify_report(
        api,
        chain["report"],
        VERIFIER_USER_ID,
        VERIFIER_HEADERS,
        fieldwork_start="2026-09-10",
        fieldwork_end="2026-09-12",
    )
    assert verified["opinion"] == "UNQUALIFIED"

    final = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )

    assert_report(
        final,
        tier_basis_kg=3300.000,
        fee_subtotal_cents=81645,
        fee_variant_applied=FeeVariant.FINAL,
        fee_status=ReportFeeStatus.FINAL,
        submission_status=SubmissionStatus.VERIFIED,
    )
    line = validate_success(
        api.get_report_line(chain["line"]["id"], chain["officer_headers"])
    )
    assert_report_line(line, line_fee_cents=81645)


# ---------------------------------------------------------------------------
# Variant three: modelling. Only PROJECTED_UNITS reads the body's unit count.
# ---------------------------------------------------------------------------
def _redesign_context(api):
    """One ACTIVE 100 g NOT_RECYCLABLE PLASTIC unit and a published banded schedule."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    program = fx.make_deep_ca_program(api)
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    producer = fx.make_producer(
        api,
        legal_name="Redesign Co",
        annual_gross_revenue_usd=9000000,
        brand_owner_flag=True,
        contact_email="p7@x.com",
    )
    sku = fx.make_sku_with_components(
        api,
        producer,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100,
                recyclability_class="NOT_RECYCLABLE",
                pcr_content_pct=0,
            )
        ],
        name="Tub 1L",
        product_category="PERSONAL_CARE",
        units_sold_annual_estimate=10000,
    )
    schedule = fx.published_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-07-01",
        effective_to=None,
        admin_fee_bps_high=300,
        material_rates=[
            f.material_rate("PLASTIC", 0, 1000, 42),
            f.material_rate("PLASTIC", 1000, 5000, 33),
            f.material_rate("PLASTIC", 5000, None, 25),
        ],
    )
    candidate = [
        f.component_payload(
            material_type="PLASTIC",
            unit_weight_grams=100,
            recyclability_class="READILY_RECYCLABLE",
            pcr_content_pct=100,
            is_reusable=True,
        )
    ]
    return {
        "program": program,
        "producer": producer,
        "sku": sku,
        "schedule": schedule,
        "candidate": candidate,
        "headers": fx.officer(producer),
    }


def test_baseline_units_projection_prices_the_units_own_estimate(api):
    """BASELINE_UNITS prices the candidate set at the unit's own annual estimate.

    Ten thousand units of a 100 g component weigh 1000.000 kg; at the supplied
    tier basis of 1000 the 33 cent band applies, the surcharged baseline costs
    52800 cents and the fully recycled reusable candidate is clamped to a thirty
    percent discount at 23100 cents, a saving of 29700 cents.

    Design: Difficulty/dual_variant_calc/redesign_projection_baseline_units_vs_projected_units
    """
    ctx = _redesign_context(api)

    projection = validate_success(
        api.redesign_projection(
            ctx["sku"]["id"],
            f.redesign_projection_payload(
                ctx["program"]["id"],
                ctx["schedule"]["id"],
                1000,
                UnitsBasis.BASELINE_UNITS,
                ctx["candidate"],
            ),
            ctx["headers"],
        )
    )

    assert projection["projected_units"] == 10000
    assert_weight(projection["projected_line_weight_kg"], 1000.000, "projected_line_weight_kg")
    assert_cents(projection["baseline_line_fee_cents"], 52800, "baseline_line_fee_cents")
    assert_cents(projection["projected_line_fee_cents"], 23100, "projected_line_fee_cents")
    assert_cents(projection["fee_delta_cents"], -29700, "fee_delta_cents")

    sku = validate_success(api.get_sku(ctx["sku"]["id"], ctx["headers"]))
    assert_sku(sku, revision_count=0, unit_packaging_weight_grams=100.00)
    producer = validate_success(api.get_producer(ctx["producer"]["id"], ctx["headers"]))
    assert_producer(producer, annual_packaging_weight_kg=1000.000)


def test_projected_units_projection_prices_the_body_unit_count(api):
    """PROJECTED_UNITS prices the same candidate set at the body's twenty thousand.

    The tier basis is held at 1000 so the same 33 cent band applies, and both
    sides of the comparison simply double: 105600 against 46200, a saving of
    59400 cents, while the stock keeping unit is still untouched.

    Design: Difficulty/dual_variant_calc/redesign_projection_baseline_units_vs_projected_units
    """
    ctx = _redesign_context(api)

    projection = validate_success(
        api.redesign_projection(
            ctx["sku"]["id"],
            f.redesign_projection_payload(
                ctx["program"]["id"],
                ctx["schedule"]["id"],
                1000,
                UnitsBasis.PROJECTED_UNITS,
                ctx["candidate"],
                projected_units=20000,
            ),
            ctx["headers"],
        )
    )

    assert projection["projected_units"] == 20000
    assert_weight(projection["projected_line_weight_kg"], 2000.000, "projected_line_weight_kg")
    assert_cents(projection["baseline_line_fee_cents"], 105600, "baseline_line_fee_cents")
    assert_cents(projection["projected_line_fee_cents"], 46200, "projected_line_fee_cents")
    assert_cents(projection["fee_delta_cents"], -59400, "fee_delta_cents")

    sku = validate_success(api.get_sku(ctx["sku"]["id"], ctx["headers"]))
    assert_sku(sku, revision_count=0, unit_packaging_weight_grams=100.00)
    producer = validate_success(api.get_producer(ctx["producer"]["id"], ctx["headers"]))
    assert_producer(producer, annual_packaging_weight_kg=1000.000)
