"""Boundary precision: the exact value on each side of a declared comparison.

The three boundaries exercised here are the small-producer revenue threshold at
registration submission, the half-open rate band on a fee assessment, and the
difference between an empty line set and a line of exactly zero units.
"""

from test_helpers import (
    ApiErrorId,
    EcoModPolicy,
    ExemptionStatus,
    FeeRoundingOrder,
    FeeVariant,
    ObligationBasis,
    ProducerStatus,
    REGULATOR_HEADERS,
    RegistrationStatus,
    ReportFeeStatus,
    SubmissionStatus,
    assert_cents,
    assert_exact_cents,
    assert_producer,
    assert_registration,
    assert_report,
    assert_report_line,
    assert_weight,
    expected_membership_fee_cents,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# The small-producer revenue threshold is a strict comparison
# ---------------------------------------------------------------------------
def _group_summing_to_the_threshold(api):
    """A parent and one affiliate whose revenues total exactly five million."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    ca_program = fx.make_deep_ca_program(api)
    or_program = fx.make_deep_ca_program(
        api,
        state_code="OR",
        eco_mod_policy=EcoModPolicy.DISCOUNT_ONLY,
        fee_rounding_order=FeeRoundingOrder.SUM_THEN_ROUND,
        exempt_product_categories=[],
    )

    parent = fx.make_producer(
        api,
        legal_name="Boundary Parent Co",
        annual_gross_revenue_usd=3000000,
        contact_email="pp@x.com",
    )
    fx.glass_mini_sku(api, parent, name="Parent Jar", product_category="HOUSEHOLD_CHEM")
    parent = fx.determine_obligation(api, parent)
    assert_producer(parent, annual_packaging_weight_kg=5.500)

    child = fx.make_producer(
        api,
        legal_name="Boundary Child Co",
        parent_producer_id=parent["id"],
        annual_gross_revenue_usd=2000000,
        contact_email="pq@x.com",
    )
    fx.make_sku_with_components(
        api,
        child,
        components=[f.component_payload(material_type="GLASS", unit_weight_grams=50)],
        name="Child Jar",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=100,
    )
    child = fx.determine_obligation(api, child)
    assert_producer(child, annual_packaging_weight_kg=5.000)

    return {
        "parent": parent,
        "child": child,
        "ca_registration": fx.make_registration(api, parent, ca_program["id"]),
        "or_registration": fx.make_registration(api, parent, or_program["id"]),
        "headers": fx.officer(parent),
    }


def test_a_group_revenue_exactly_at_the_threshold_is_obligated(api):
    """Five million exactly clears the threshold because the test is strict.

    The parent's three million and the affiliate's two million sum to exactly the
    program's five million threshold, and the group weight of 10.500 kg is far
    below the tonnage threshold, so revenue alone decides and the registration is
    obligated.

    Design: Difficulty/boundary_precision_check/group_revenue_exactly_at_small_producer_threshold
    """
    built = _group_summing_to_the_threshold(api)

    submitted = validate_success(
        api.submit_registration(built["ca_registration"]["id"], None, built["headers"])
    )

    assert_registration(
        submitted,
        exemption_status=ExemptionStatus.OBLIGATED,
        exemption_basis_applied=ObligationBasis.GROUP_LEVEL,
        assessed_group_revenue_usd=5000000,
    )
    assert_weight(submitted["assessed_group_weight_kg"], 10.500, "assessed_group_weight_kg")


def test_one_dollar_below_the_threshold_is_exempt(api):
    """A single dollar less in the group makes the same parent a small producer.

    Restating the affiliate one dollar downwards puts the group at 4999999, and
    the second registration of the very same parent is assessed on that figure and
    comes out exempt while the group weight is unchanged at 10.500 kg.

    Design: Difficulty/boundary_precision_check/group_revenue_exactly_at_small_producer_threshold
    """
    built = _group_summing_to_the_threshold(api)
    validate_success(
        api.submit_registration(built["ca_registration"]["id"], None, built["headers"])
    )

    restated = validate_success(
        api.restate_revenue(
            built["child"]["id"],
            f.restate_revenue_payload(
                1999999, "One dollar of intercompany revenue reclassified"
            ),
            REGULATOR_HEADERS,
        )
    )
    assert_producer(
        restated, status=ProducerStatus.DRAFT, annual_gross_revenue_usd=1999999
    )

    submitted = validate_success(
        api.submit_registration(built["or_registration"]["id"], None, built["headers"])
    )

    assert_registration(
        submitted,
        exemption_status=ExemptionStatus.EXEMPT_SMALL_PRODUCER,
        exemption_basis_applied=ObligationBasis.GROUP_LEVEL,
        assessed_group_revenue_usd=4999999,
    )
    assert_weight(submitted["assessed_group_weight_kg"], 10.500, "assessed_group_weight_kg")


def test_the_exemption_verdict_is_frozen_at_submission_and_gates_reporting(api):
    """The earlier verdict survives the restatement and the exempt one blocks reports.

    The obligated registration keeps that verdict even though the group has since
    fallen below the threshold, and once each registration is accepted only the
    obligated one may open a report.

    Design: Difficulty/boundary_precision_check/group_revenue_exactly_at_small_producer_threshold
    """
    built = _group_summing_to_the_threshold(api)
    ca = built["ca_registration"]
    validate_success(api.submit_registration(ca["id"], None, built["headers"]))
    validate_success(
        api.restate_revenue(
            built["child"]["id"], f.restate_revenue_payload(1999999), REGULATOR_HEADERS
        )
    )
    or_submitted = validate_success(
        api.submit_registration(built["or_registration"]["id"], None, built["headers"])
    )
    assert_registration(or_submitted, exemption_status=ExemptionStatus.EXEMPT_SMALL_PRODUCER)

    ca_reread = validate_success(api.get_registration(ca["id"], built["headers"]))
    assert_registration(
        ca_reread,
        exemption_status=ExemptionStatus.OBLIGATED,
        assessed_group_revenue_usd=5000000,
        status=RegistrationStatus.SUBMITTED,
    )

    ca_active = fx.accept_registration(api, ca)
    or_active = fx.accept_registration(api, or_submitted)
    ca_period = fx.make_reporting_period(
        api,
        ca_active["state_program_id"],
        period_label="CA-2026-H2",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )
    or_period = fx.make_reporting_period(
        api,
        or_active["state_program_id"],
        period_label="OR-2026-H2",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )

    validate_error(
        api.create_report(
            f.report_payload(or_active["id"], or_period["id"]), built["headers"]
        ),
        ApiErrorId.EXEMPT_REGISTRATION_CANNOT_REPORT,
        422,
    )
    allowed = validate_success(
        api.create_report(
            f.report_payload(ca_active["id"], ca_period["id"]), built["headers"]
        ),
        201,
    )
    assert_report(allowed, submission_status=SubmissionStatus.DRAFT, line_count=0)


# ---------------------------------------------------------------------------
# Rate bands are half-open, so the basis at the floor selects the upper band
# ---------------------------------------------------------------------------
def _two_periods_priced_across_the_band_floor(api):
    """A 999.900 kg first report and a 0.100 kg second one on banded PLASTIC."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    program = fx.make_deep_ca_program(api)
    period_h1 = fx.make_reporting_period(
        api,
        program["id"],
        period_label="CA-2026-H1",
        data_start="2026-01-01",
        data_end="2026-07-01",
        submission_open="2026-08-01T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )
    period_h2 = fx.make_reporting_period(
        api,
        program["id"],
        period_label="CA-2026-H2",
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-08-01T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
    )
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    built = fx.determined_producer(
        api,
        components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100,
                recyclability_class="READILY_RECYCLABLE",
                pcr_content_pct=0,
            )
        ],
        sku_kwargs=dict(
            name="Neutral Pouch",
            product_category="FOOD_DRY",
            units_sold_annual_estimate=10000,
        ),
        legal_name="Boundary Fee Co",
        annual_gross_revenue_usd=20000000,
        contact_email="pe@x.com",
    )
    producer, sku = built["producer"], built["sku"]
    assert_producer(producer, annual_packaging_weight_kg=1000.000)

    schedule = fx.published_fee_schedule(
        api,
        pro,
        program["id"],
        effective_from="2026-01-01",
        effective_to=None,
        membership_fee_cents=300000,
        admin_fee_bps_high=300,
        material_rates=[
            f.material_rate("PLASTIC", 0, 1000, 42),
            f.material_rate("PLASTIC", 1000, 5000, 33),
            f.material_rate("PLASTIC", 5000, None, 21),
        ],
    )
    registration = fx.active_registration(api, producer, program["id"])
    membership = fx.paid_membership(api, producer, registration, pro, schedule)
    assert_cents(
        membership["membership_fee_cents"],
        expected_membership_fee_cents(300000, 1000.000),
        "membership_fee_cents",
    )

    report_h1 = fx.make_report(api, producer, registration, period_h1)
    line_h1 = fx.add_line(api, producer, report_h1, sku, 9999)
    assert_report_line(line_h1, units_sold=9999, line_weight_kg=999.900)
    report_h1 = fx.submit_report(api, producer, report_h1)
    assert_report(report_h1, total_weight_kg=999.900, verification_required=False)

    report_h2 = fx.make_report(api, producer, registration, period_h2)
    line_h2 = fx.add_line(api, producer, report_h2, sku, 1)
    assert_report_line(line_h2, units_sold=1, line_weight_kg=0.100)

    return {
        "producer": producer,
        "registration": registration,
        "pro": pro,
        "report_h1": report_h1,
        "line_h1": line_h1,
        "report_h2": report_h2,
        "line_h2": line_h2,
        "officer_headers": fx.officer(producer),
        "admin_headers": fx.admin(pro),
    }


def test_a_tier_basis_just_below_the_band_floor_prices_at_the_lower_band(api):
    """A basis of 999.900 kg stays inside the first band at 42 cents.

    The first report is the only tonnage of the year, so its final basis is its own
    999.900 kg, one thousandth of a kilogram short of the band floor, and the line
    prices at 41995.8000 exact cents, rounded to 41996.

    Design: Difficulty/boundary_precision_check/tier_basis_exactly_at_band_minimum_selects_upper_band
    """
    built = _two_periods_priced_across_the_band_floor(api)
    registration = validate_success(
        api.get_registration(built["registration"]["id"], built["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 999.900, "reported_weight_kg_ytd")

    assessed = validate_success(
        api.assess_report(
            built["report_h1"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        )
    )

    assert_report(
        assessed,
        tier_basis_kg=999.900,
        fee_subtotal_cents=41996,
        fee_variant_applied=FeeVariant.FINAL,
        fee_status=ReportFeeStatus.FINAL,
    )
    line = validate_success(
        api.get_report_line(built["line_h1"]["id"], built["officer_headers"])
    )
    assert_exact_cents(line["line_fee_exact_cents"], 41995.8000, "line_fee_exact_cents")
    assert_report_line(line, line_fee_cents=41996)


def test_a_tier_basis_exactly_at_the_band_floor_prices_at_the_upper_band(api):
    """A basis of exactly 1000.000 kg moves into the second band at 33 cents.

    Submitting the 0.100 kg second report lifts the year to the band floor, and its
    own final basis is that whole 1000.000 kg, so the line prices at 3.3000 exact
    cents rather than the 4.2000 the lower band would have produced.

    Design: Difficulty/boundary_precision_check/tier_basis_exactly_at_band_minimum_selects_upper_band
    """
    built = _two_periods_priced_across_the_band_floor(api)
    submitted = fx.submit_report(api, built["producer"], built["report_h2"])
    assert_report(submitted, total_weight_kg=0.100, verification_required=False)
    registration = validate_success(
        api.get_registration(built["registration"]["id"], built["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 1000.000, "reported_weight_kg_ytd")

    assessed = validate_success(
        api.assess_report(
            built["report_h2"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        )
    )

    assert_report(
        assessed,
        tier_basis_kg=1000.000,
        fee_subtotal_cents=3,
        fee_variant_applied=FeeVariant.FINAL,
        fee_status=ReportFeeStatus.FINAL,
    )
    line = validate_success(
        api.get_report_line(built["line_h2"]["id"], built["officer_headers"])
    )
    assert_exact_cents(line["line_fee_exact_cents"], 3.3000, "line_fee_exact_cents")
    assert_report_line(line, line_fee_cents=3)
    assert line["line_fee_cents"] != 4, "the line must not be priced at the 42 cent band"


# ---------------------------------------------------------------------------
# An empty line set and a line of zero units are different things
# ---------------------------------------------------------------------------
def _report_with_no_lines(api):
    """A DRAFT report on a paid-up registration that carries no lines at all."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Zero Line Co",
            annual_gross_revenue_usd=8000000,
            contact_email="pz@x.com",
        ),
        sku_overrides=dict(name="Zero Jar", product_category="HOUSEHOLD_CHEM"),
        line_units=None,
        submit=False,
    )
    assert_report(chain["report"], submission_status=SubmissionStatus.DRAFT, line_count=0)
    return chain


def test_an_empty_line_set_cannot_be_submitted(api):
    """A report with no lines is refused and stays in DRAFT.

    Every other admission condition is satisfied — the registration is active, the
    membership is paid and the clock is inside the window — so the structural rule
    about lines is the only one left to fail.

    Design: Difficulty/boundary_precision_check/zero_quantity_and_empty_line_set_boundary_on_submit
    """
    chain = _report_with_no_lines(api)

    validate_error(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"]),
        ApiErrorId.REPORT_HAS_NO_LINES,
        422,
    )

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(
        report,
        submission_status=SubmissionStatus.DRAFT,
        line_count=0,
        total_weight_kg=0.000,
    )


def test_a_line_of_exactly_zero_units_submits_and_prices_to_nothing(api):
    """One line of zero units is a legal filing that weighs and costs nothing.

    The line is accepted, the report submits with a total of 0.000 kg and no
    verification requirement, the year-to-date rollup does not move, and the final
    assessment prices the line at zero on a basis of 0.000 kg.

    Design: Difficulty/boundary_precision_check/zero_quantity_and_empty_line_set_boundary_on_submit
    """
    chain = _report_with_no_lines(api)

    line = validate_success(
        api.add_report_line(
            chain["report"]["id"],
            f.report_line_payload(chain["sku"]["id"], 0),
            chain["officer_headers"],
        ),
        201,
    )
    assert_report_line(line, units_sold=0, line_weight_kg=0.000, fee_exempt=False)

    submitted = validate_success(
        api.submit_report(chain["report"]["id"], None, chain["officer_headers"])
    )
    assert_report(
        submitted,
        submission_status=SubmissionStatus.SUBMITTED,
        total_weight_kg=0.000,
        verification_required=False,
        line_count=1,
    )
    registration = validate_success(
        api.get_registration(chain["registration"]["id"], chain["officer_headers"])
    )
    assert_weight(registration["reported_weight_kg_ytd"], 0.000, "reported_weight_kg_ytd")

    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    assert_report(
        assessed,
        tier_basis_kg=0.000,
        fee_subtotal_cents=0,
        fee_status=ReportFeeStatus.FINAL,
        fee_variant_applied=FeeVariant.FINAL,
    )
    priced = validate_success(api.get_report_line(line["id"], chain["officer_headers"]))
    assert_exact_cents(priced["line_fee_exact_cents"], 0.0000, "line_fee_exact_cents")
    assert_report_line(priced, line_fee_cents=0)
