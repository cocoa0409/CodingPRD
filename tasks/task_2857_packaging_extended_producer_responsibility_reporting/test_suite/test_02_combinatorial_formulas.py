"""Combinatorial fee formulas: nested clamps, keyed brackets and rounding orders.

The three formulas exercised here each combine several independent inputs in a
pinned order, and each has a naive reading that produces a different number.
Every expected figure below is the PRD formula worked through by hand.
"""

from test_helpers import (
    ADMIN_TIER_BREAK_CENTS,
    FeeVariant,
    ReportFeeStatus,
    assert_cents,
    assert_eco_mod_row,
    assert_exact_cents,
    assert_invoice,
    assert_producer,
    assert_report,
    assert_report_line,
    expected_membership_fee_cents,
    factories as f,
    fixtures as fx,
    validate_success,
)

PLASTIC_BANDS = [
    ("PLASTIC", 0, 1000, 42),
    ("PLASTIC", 1000, 5000, 33),
    ("PLASTIC", 5000, None, 25),
]


# ---------------------------------------------------------------------------
# Mode (a): eco-modulation, a floored and capped bonus inside a clamp
# ---------------------------------------------------------------------------
def _two_component_report(api):
    """One report with a surcharged line and a fully-bonused line, both 1000 kg."""
    rates = [f.material_rate(*band) for band in PLASTIC_BANDS]
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="EcoMod Co",
            annual_gross_revenue_usd=20000000,
            contact_email="p4@x.com",
        ),
        sku_components=[
            f.component_payload(
                material_type="PLASTIC",
                unit_weight_grams=100,
                recyclability_class="NOT_RECYCLABLE",
                pcr_content_pct=62,
                is_reusable=True,
            )
        ],
        sku_overrides=dict(
            name="Pouch E", product_category="FOOD_DRY", units_sold_annual_estimate=10000
        ),
        extra_skus=[
            dict(
                components=[
                    f.component_payload(
                        material_type="PLASTIC",
                        unit_weight_grams=100,
                        recyclability_class="READILY_RECYCLABLE",
                        pcr_content_pct=100,
                        is_reusable=True,
                    )
                ],
                name="Pouch F",
                product_category="FOOD_DRY",
                units_sold_annual_estimate=10000,
            )
        ],
        schedule_overrides=dict(material_rates=rates),
        with_membership=False,
        with_report=False,
    )
    producer = chain["producer"]
    bonused_sku = chain["extra_skus"][0]
    assert_producer(producer, annual_packaging_weight_kg=2000.000)

    membership = fx.paid_membership(
        api, producer, chain["registration"], chain["pro"], chain["schedule"]
    )
    assert_cents(
        membership["membership_fee_cents"],
        expected_membership_fee_cents(250000, 2000.000),
        "membership_fee_cents",
    )
    report = fx.make_report(api, producer, chain["registration"], chain["period"])
    surcharged_line = fx.add_line(api, producer, report, chain["sku"], 10000)
    bonused_line = fx.add_line(api, producer, report, bonused_sku, 10000)
    report = fx.submit_report(api, producer, report)
    assert_report(report, total_weight_kg=2000.000, verification_required=False)

    assessed = validate_success(
        api.assess_report(
            report["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    assert_report(assessed, tier_basis_kg=2000.000, fee_status=ReportFeeStatus.FINAL)
    return {
        "chain": chain,
        "report": assessed,
        "surcharged_line": surcharged_line,
        "bonused_line": bonused_line,
        "officer_headers": chain["officer_headers"],
    }


def test_capped_recycled_bonus_leaves_a_net_surcharge_on_a_non_recyclable_line(api):
    """A 62 percent recycled reusable non-recyclable component nets plus twenty.

    The recycled bonus is floored to six complete ten-point steps worth thirty
    points and then capped at twenty-five, so the combined bonus is forty rather
    than thirty-one or forty-five, and sixty minus forty leaves twenty: the line
    costs 39600 cents at the 33 cent band.

    Design: Difficulty/combinatorial_formula/eco_modulation_mode_a_nested_min_max_clamp
    """
    built = _two_component_report(api)

    line = validate_success(
        api.get_report_line(built["surcharged_line"]["id"], built["officer_headers"])
    )

    assert_report_line(line, line_fee_cents=39600)
    assert len(line["eco_mod_detail"]) == 1
    row = line["eco_mod_detail"][0]
    assert row["malus_pct"] == 60
    assert row["bonus_pct"] == 40
    assert_eco_mod_row(
        row, material_type="PLASTIC", comp_weight_kg=1000.000, rate_cents_per_kg=33, net_pct=20
    )


def test_the_net_discount_is_clamped_at_thirty_percent_and_the_subtotal_sums_both_lines(api):
    """A fully recycled reusable recyclable component is clamped up to minus thirty.

    Its raw net is minus forty, which would price the line at 19800 cents; the
    clamp floor holds it at minus thirty and 23100 cents, and the report's
    subtotal is the sum of the two rounded line values.

    Design: Difficulty/combinatorial_formula/eco_modulation_mode_a_nested_min_max_clamp
    """
    built = _two_component_report(api)

    line = validate_success(
        api.get_report_line(built["bonused_line"]["id"], built["officer_headers"])
    )

    assert_report_line(line, line_fee_cents=23100)
    assert line["line_fee_cents"] != 19800
    row = line["eco_mod_detail"][0]
    assert row["malus_pct"] == 0
    assert row["bonus_pct"] == 40
    assert_eco_mod_row(row, rate_cents_per_kg=33, net_pct=-30)
    assert_report(built["report"], fee_subtotal_cents=62700)


# ---------------------------------------------------------------------------
# Mode (c): the administrative bracket is keyed on the subtotal, never the total
# ---------------------------------------------------------------------------
def _invoiced_metal_report(api):
    """A 39000 cent report, one thousand cents below the administrative break."""
    chain = fx.deep_ca_chain(
        api,
        producer_overrides=dict(
            legal_name="Tin Co",
            annual_gross_revenue_usd=12000000,
            brand_owner_flag=False,
            importer_of_record_flag=True,
            contact_email="p5@x.com",
        ),
        sku_components=[
            f.component_payload(material_type="METAL", unit_weight_grams=40)
        ],
        sku_overrides=dict(name="Can 330ml", units_sold_annual_estimate=65000),
        schedule_overrides=dict(
            material_rates=[f.material_rate("METAL", 0, None, 15)]
        ),
        line_units=65000,
    )
    assert_cents(
        chain["membership"]["membership_fee_cents"],
        expected_membership_fee_cents(250000, 2600.000),
        "membership_fee_cents",
    )
    assert_report(chain["report"], total_weight_kg=2600.000, verification_required=False)
    assessed = validate_success(
        api.assess_report(
            chain["report"]["id"], f.assess_payload(FeeVariant.FINAL), chain["admin_headers"]
        )
    )
    assert_report(assessed, fee_subtotal_cents=39000, fee_status=ReportFeeStatus.FINAL)
    chain["report"] = assessed
    return chain


def test_administrative_bracket_is_selected_from_the_report_subtotal(api):
    """A subtotal of 39000 cents sits below the break, so the low bracket applies.

    Five hundred basis points of 39000 is 1950 cents and the total is 40950.

    Design: Difficulty/combinatorial_formula/invoice_admin_fee_mode_c_bracket_keyed_on_subtotal
    """
    chain = _invoiced_metal_report(api)

    invoice = validate_success(
        api.create_invoice(
            f.invoice_payload(chain["report"]["id"], chain["membership"]["id"]),
            chain["admin_headers"],
        ),
        201,
    )

    assert_invoice(
        invoice,
        packaging_report_id=chain["report"]["id"],
        membership_id=chain["membership"]["id"],
        fee_subtotal_cents=39000,
        admin_fee_bps_applied=500,
        admin_fee_cents=1950,
        total_cents=40950,
    )


def test_the_bracket_is_not_re_derived_once_the_total_crosses_the_break(api):
    """The total of 40950 cents is above the break yet the bracket stays low.

    A total-keyed reading would apply three hundred basis points and produce
    1170 cents on a total of 40170; the stored figures are the subtotal-keyed
    ones, the report moves to INVOICED and the producer's balance rises by the
    invoice total.

    Design: Difficulty/combinatorial_formula/invoice_admin_fee_mode_c_bracket_keyed_on_subtotal
    """
    chain = _invoiced_metal_report(api)

    invoice = validate_success(
        api.create_invoice(
            f.invoice_payload(chain["report"]["id"], chain["membership"]["id"]),
            chain["admin_headers"],
        ),
        201,
    )

    assert invoice["total_cents"] > ADMIN_TIER_BREAK_CENTS
    assert invoice["admin_fee_bps_applied"] != 300
    assert invoice["admin_fee_cents"] != 1170
    assert invoice["total_cents"] != 40170

    report = validate_success(api.get_report(chain["report"]["id"], chain["officer_headers"]))
    assert_report(report, fee_status=ReportFeeStatus.INVOICED, fee_subtotal_cents=39000)
    producer = validate_success(
        api.get_producer(chain["producer"]["id"], chain["officer_headers"])
    )
    assert_producer(producer, assessed_fee_balance_cents=40950)


# ---------------------------------------------------------------------------
# Mode (b): the rounding order the state program declares
# ---------------------------------------------------------------------------
def _same_lines_in_two_states(api):
    """Identical two-line reports in a per-line state and a sum-first state."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    per_line_program = fx.make_deep_ca_program(api)
    sum_first_program = fx.make_deep_or_program(api)
    period_kwargs = dict(
        data_start="2026-07-01",
        data_end="2027-01-01",
        submission_open="2026-08-15T00:00:00Z",
        submission_deadline="2026-09-30T23:59:59Z",
        correction_window_days=30,
    )
    per_line_period = fx.make_reporting_period(
        api, per_line_program["id"], period_label="CA-2026-H2", **period_kwargs
    )
    sum_first_period = fx.make_reporting_period(
        api, sum_first_program["id"], period_label="OR-2026-H2", **period_kwargs
    )
    pro = fx.make_pro(api, name="PRO West", contact_email="pro@x.com")
    producer = fx.make_producer(
        api,
        legal_name="Glass Goods Co",
        annual_gross_revenue_usd=8000000,
        brand_owner_flag=True,
        contact_email="p2@x.com",
    )
    glass = [f.component_payload(material_type="GLASS", unit_weight_grams=50)]
    small_sku = fx.make_sku_with_components(
        api,
        producer,
        components=list(glass),
        name="Jar S",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=110,
    )
    large_sku = fx.make_sku_with_components(
        api,
        producer,
        components=list(glass),
        name="Jar L",
        product_category="HOUSEHOLD_CHEM",
        units_sold_annual_estimate=210,
    )
    producer = fx.determine_obligation(api, producer)
    assert_producer(producer, annual_packaging_weight_kg=16.000)

    built = {}
    for key, program, period in (
        ("per_line", per_line_program, per_line_period),
        ("sum_first", sum_first_program, sum_first_period),
    ):
        schedule = fx.published_fee_schedule(
            api,
            pro,
            program["id"],
            effective_from="2026-07-01",
            effective_to=None,
            admin_fee_bps_high=300,
            material_rates=[f.material_rate("GLASS", 0, None, 9)],
        )
        registration = fx.active_registration(api, producer, program["id"])
        membership = fx.paid_membership(api, producer, registration, pro, schedule)
        assert_cents(membership["membership_fee_cents"], 250000, "membership_fee_cents")
        report = fx.make_report(api, producer, registration, period)
        small_line = fx.add_line(api, producer, report, small_sku, 110)
        large_line = fx.add_line(api, producer, report, large_sku, 210)
        report = fx.submit_report(api, producer, report)
        assert_report(report, total_weight_kg=16.000, verification_required=False)
        built[key] = {
            "report": report,
            "small_line": small_line,
            "large_line": large_line,
        }
    built["producer"] = producer
    built["pro"] = pro
    built["officer_headers"] = fx.officer(producer)
    built["admin_headers"] = fx.admin(pro)
    return built


def _read_lines(api, built, key):
    headers = built["officer_headers"]
    small = validate_success(api.get_report_line(built[key]["small_line"]["id"], headers))
    large = validate_success(api.get_report_line(built[key]["large_line"]["id"], headers))
    return small, large


def test_per_line_then_sum_rounds_each_line_before_adding(api):
    """The per-line state rounds 49.5000 and 94.5000 up first, giving 145 cents.

    Both lines are priced at the single GLASS band of 9 cents per kilogram with a
    net adjustment of zero, so the exact values are unambiguous.

    Design: Difficulty/combinatorial_formula/fee_rounding_order_mode_b_per_line_then_sum_vs_sum_then_round
    """
    built = _same_lines_in_two_states(api)

    assessed = validate_success(
        api.assess_report(
            built["per_line"]["report"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        )
    )

    small, large = _read_lines(api, built, "per_line")
    assert_exact_cents(small["line_fee_exact_cents"], 49.5000, "small line_fee_exact_cents")
    assert_exact_cents(large["line_fee_exact_cents"], 94.5000, "large line_fee_exact_cents")
    assert_report_line(small, line_fee_cents=50)
    assert_report_line(large, line_fee_cents=95)
    assert_report(assessed, fee_subtotal_cents=145, tier_basis_kg=16.000)


def test_sum_then_round_adds_the_exact_values_before_rounding(api):
    """The sum-first state adds 49.5000 and 94.5000 to 144.0000, giving 144 cents.

    The stored per-line values are still the individually rounded 50 and 95, so
    their sum exceeds the report subtotal by exactly one cent — the reconciliation
    gap this rounding order is meant to expose.

    Design: Difficulty/combinatorial_formula/fee_rounding_order_mode_b_per_line_then_sum_vs_sum_then_round
    """
    built = _same_lines_in_two_states(api)

    assessed = validate_success(
        api.assess_report(
            built["sum_first"]["report"]["id"],
            f.assess_payload(FeeVariant.FINAL),
            built["admin_headers"],
        )
    )

    small, large = _read_lines(api, built, "sum_first")
    assert_exact_cents(small["line_fee_exact_cents"], 49.5000, "small line_fee_exact_cents")
    assert_exact_cents(large["line_fee_exact_cents"], 94.5000, "large line_fee_exact_cents")
    assert_report_line(small, line_fee_cents=50)
    assert_report_line(large, line_fee_cents=95)
    assert_report(assessed, fee_subtotal_cents=144, total_weight_kg=16.000)
    assert small["line_fee_cents"] + large["line_fee_cents"] == assessed["fee_subtotal_cents"] + 1
