"""Invoice assembly: per-line rounding against sum-then-round, and the two
totals-keyed decisions that both read the pre-discount figure.
"""

from test_helpers.assertions import (
    assert_invoice,
    assert_invoice_line,
    assert_invoice_total,
    assert_product_line_amount,
)
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    CATALOG_SPEC_THREE_ALLIED,
    CATALOG_SPEC_WITH_TWO_PANTRY,
    assemble_invoice_for,
    complete_stop,
    create_asset,
    lines_by_type,
    place_asset_at_site,
    schedule_stop_with_lines,
    set_clock,
    setup_planned_site,
    setup_second_site,
)

PERIOD_START = "2026-08-01T00:00:00Z"
PERIOD_END = "2026-08-31T23:59:59Z"
BILLING_INSTANT = "2026-09-01T00:00:00Z"


def _two_sites_with_fractional_cent_deliveries():
    """Two break rooms of one consolidated customer, each on rental terms, each
    served once with two pantry products whose unit prices are a half cent.

    Stirrers at 25000 micro-dollars and cups at 15000 micro-dollars both price a
    three-unit line at a half cent, so the invoice cannot avoid deciding where
    the rounding happens.
    """
    base = setup_planned_site(
        clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_WITH_TWO_PANTRY
    )
    site_two = setup_second_site(base)
    base["site_two"] = site_two

    for site, serial in ((base["site"], "SN-RENT-1"), (site_two, "SN-RENT-2")):
        asset = create_asset(base["model"]["id"], serial_number=serial)
        place_asset_at_site(
            site,
            asset["id"],
            terms_type="RENTAL",
            minimum_purchase_cents=60000,
        )

    first = schedule_stop_with_lines(
        base,
        {"COFFEE": 20, "CREAMER": 4, "TEA": 2, "PANTRY": 3, "PANTRY_CUP": 3},
        site=base["site"],
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T09:45:00Z",
    )
    second = schedule_stop_with_lines(
        base,
        {"COFFEE": 15, "WATER": 6, "PANTRY": 3, "PANTRY_CUP": 3},
        site=site_two,
        window_start="2026-08-03T10:30:00Z",
        window_end="2026-08-03T11:15:00Z",
    )
    complete_stop(
        base,
        first,
        {"COFFEE": 20, "CREAMER": 4, "TEA": 2, "PANTRY": 3, "PANTRY_CUP": 3},
        complete_at="2026-08-03T11:15:00Z",
    )
    complete_stop(
        base,
        second,
        {"COFFEE": 15, "WATER": 6, "PANTRY": 3, "PANTRY_CUP": 3},
        complete_at="2026-08-03T11:15:00Z",
    )

    set_clock(BILLING_INSTANT)
    base["invoice"] = assemble_invoice_for(
        base["account"]["id"], PERIOD_START, PERIOD_END
    )
    return base


def test_per_line_rounding_beats_rounding_the_micro_dollar_sum():
    """Four half-cent product lines round up individually, so the invoice total
    lands two cents above what a single rounding of the micro-dollar sum would
    have produced.

    "A `PRODUCT` line's `amount_cents` is its `qty_units` multiplied by its
    `unit_price_micros`, divided by 10000, rounded half up — **individually, per
    line**."

    "Summing micro-dollar products across a site and rounding once at the end is
    explicitly forbidden: it differs by cents whenever two or more lines of a
    site carry a fractional-cent unit price."

    "`pre_freight_total_cents` is the sum of all of those line amounts, across
    all sites and all four line types, before any discount and before any
    freight."

    "`total_cents` is `pre_freight_total_cents` less `allied_discount_cents` plus
    `freight_cents`."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_per_line_beats_sum_then_round
    """
    base = _two_sites_with_fractional_cent_deliveries()
    invoice = base["invoice"]
    assert_invoice(invoice)
    assert invoice["invoice_status"] == "DRAFT"
    assert invoice["issued_at"] is None

    # 9913 at the first break room, 12013 at the second, plus 4200 of prorated
    # rent at each.
    assert invoice["pre_freight_total_cents"] == 30326
    # Four allied categories appear but the pre-freight total is under 50000,
    # so no breadth tier is reachable.
    assert invoice["allied_discount_bps"] == 0
    assert invoice["allied_discount_cents"] == 0
    assert invoice["freight_cents"] == 2500
    assert invoice["total_cents"] == 32826
    # Rounding the micro-dollar sums once per site would have given 32824.
    assert invoice["total_cents"] != 32824
    assert_invoice_total(invoice)

    # Nine product lines, two rent lines, one freight line.
    assert invoice["line_count"] == 12
    grouped = lines_by_type(invoice["id"])
    assert len(grouped["PRODUCT"]) == 9
    assert len(grouped["RENT"]) == 2
    assert len(grouped["FREIGHT"]) == 1
    assert "SHORTFALL" not in grouped
    assert "UNRETURNED_ASSET" not in grouped
    assert "ALLIED_DISCOUNT" not in grouped


def test_each_half_cent_line_rounds_up_and_the_site_subtotals_follow():
    """The individual half-cent lines are stored at 8 and 5 cents, the rent
    lines at the prorated 4200, and each site's product subtotal is the sum of
    its already-rounded lines.

    "Only after each line has been rounded are the rounded amounts summed to
    form a site's product subtotal, and the site's discount is then rounded once
    against that subtotal."

    "Each such line carries the `product_id`, a `qty_units` equal to the
    delivered quantity, and a `unit_price_micros` copied straight from the
    `effective_unit_price_micros` snapshotted on the visit line at completion —
    never recomputed at invoice time."

    "Rent is prorated: it is the model's `monthly_rent_cents` multiplied by the
    number of days the placement was active in the billed period — capped at 30,
    the proration denominator — divided by 30, rounded half up."

    Design: Difficulty/combinatorial_formula/invoice_line_rounding_per_line_beats_sum_then_round
    """
    base = _two_sites_with_fractional_cent_deliveries()
    grouped = lines_by_type(base["invoice"]["id"])

    by_site = {}
    for line in grouped["PRODUCT"]:
        assert_invoice_line(line)
        assert_product_line_amount(line)
        by_site.setdefault(line["site_id"], []).append(line)

    site_one_lines = by_site[base["site"]["id"]]
    site_two_lines = by_site[base["site_two"]["id"]]
    assert len(site_one_lines) == 5
    assert len(site_two_lines) == 4

    stirrer_id = base["products"]["PANTRY"]["id"]
    cup_id = base["products"]["PANTRY_CUP"]["id"]
    for lines in (site_one_lines, site_two_lines):
        amounts = {line["product_id"]: line["amount_cents"] for line in lines}
        # Three units at 25000 micro-dollars is 7.5 cents, rounded half up.
        assert amounts[stirrer_id] == 8
        # Three units at 15000 micro-dollars is 4.5 cents, rounded half up.
        assert amounts[cup_id] == 5

    assert sum(line["amount_cents"] for line in site_one_lines) == 9913
    assert sum(line["amount_cents"] for line in site_two_lines) == 12013

    # The green-linked coffee price snapshotted at an unmodified factor.
    coffee_id = base["products"]["COFFEE"]["id"]
    coffee_lines = [line for line in grouped["PRODUCT"] if line["product_id"] == coffee_id]
    assert {line["unit_price_micros"] for line in coffee_lines} == {4500000}
    assert {line["qty_units"] for line in coffee_lines} == {20, 15}

    for rent in grouped["RENT"]:
        assert_invoice_line(rent)
        # 4500 cents of monthly rent over 28 of the 30 proration days.
        assert rent["amount_cents"] == 4200
        assert rent["product_id"] is None
        assert rent["qty_units"] == 0
        assert rent["unit_price_micros"] == 0
    assert {rent["site_id"] for rent in grouped["RENT"]} == {
        base["site"]["id"],
        base["site_two"]["id"],
    }


def _one_site_at_exactly_fifty_thousand_cents():
    """One break room whose single stop prices out at exactly 50000 cents across
    coffee and three allied categories, with no equipment rent to muddy it."""
    base = setup_planned_site(clock=ANCHOR_MONDAY, catalog_spec=CATALOG_SPEC_THREE_ALLIED)
    visit = schedule_stop_with_lines(
        base, {"COFFEE": 100, "CREAMER": 20, "TEA": 10, "PANTRY": 200}
    )
    complete_stop(
        base,
        visit,
        {"COFFEE": 100, "CREAMER": 20, "TEA": 10, "PANTRY": 200},
        complete_at="2026-08-03T09:30:00Z",
    )
    set_clock(BILLING_INSTANT)
    base["invoice"] = assemble_invoice_for(base["account"]["id"], PERIOD_START, PERIOD_END)
    return base


def test_breadth_tier_and_freight_waiver_both_read_the_pre_discount_total():
    """A pre-freight total sitting exactly on 50000 cents with three allied
    categories earns the middle discount tier and free freight at the same time.

    "`allied_discount_bps` is selected from that count and from the step-2 total,
    in this precedence: 500 basis points when the allied category count is at
    least 3 **and** the pre-freight total is at least 100000 cents; otherwise 300
    basis points when the allied category count is at least 3 **and** the
    pre-freight total is at least 50000 cents; otherwise 100 basis points when
    the allied category count is exactly 2; otherwise 0."

    "`allied_category_count` is the number of **distinct** product categories
    other than `COFFEE` appearing among this invoice's `PRODUCT` lines."

    "`freight_cents` is 0 when `pre_freight_total_cents` is at or above 50000,
    and otherwise a flat 2500 cents."

    Design: Difficulty/combinatorial_formula/freight_waiver_and_breadth_tier_both_key_on_pre_discount_total
    """
    base = _one_site_at_exactly_fifty_thousand_cents()
    invoice = base["invoice"]
    assert_invoice(invoice)

    # 45000 of coffee, 2500 of creamer, 2000 of tea and 500 of pantry.
    assert invoice["pre_freight_total_cents"] == 50000
    # Creamer, tea and pantry are three distinct allied categories, and the
    # pre-freight total reaches the middle threshold but not the top one.
    assert invoice["allied_discount_bps"] == 300
    assert invoice["allied_discount_cents"] == 1500
    assert invoice["freight_cents"] == 0
    assert invoice["total_cents"] == 48500
    assert_invoice_total(invoice)
    # Four product lines plus the discount line.
    assert invoice["line_count"] == 5


def test_free_freight_survives_a_discount_that_drops_the_total_below_the_threshold():
    """The discount pushes the final total under 50000 cents, yet freight stays
    waived because the waiver was decided on the pre-discount figure — and no
    freight line is written at all.

    "This too is keyed on the step-2 value, which has an observable consequence:
    an invoice that clears the free-freight threshold **before** the discount
    keeps its free freight even when the discount drops the final total below the
    threshold."

    "A `FREIGHT` line is written only when the freight is above 0."

    "One negative `ALLIED_DISCOUNT` line is written per site whose result is
    non-zero, and the stored `allied_discount_cents` is the absolute value of the
    sum of those lines."

    Design: Difficulty/combinatorial_formula/freight_waiver_and_breadth_tier_both_key_on_pre_discount_total
    """
    base = _one_site_at_exactly_fifty_thousand_cents()
    invoice = base["invoice"]

    # The final total is under the free-freight threshold the invoice cleared.
    assert invoice["total_cents"] == 48500
    assert invoice["total_cents"] < 50000
    assert invoice["freight_cents"] == 0

    grouped = lines_by_type(invoice["id"])
    assert "FREIGHT" not in grouped
    assert len(grouped["PRODUCT"]) == 4
    assert len(grouped["ALLIED_DISCOUNT"]) == 1

    discount = grouped["ALLIED_DISCOUNT"][0]
    assert_invoice_line(discount)
    # The line itself is signed negative; the header carries its magnitude.
    assert discount["amount_cents"] == -1500
    assert invoice["allied_discount_cents"] == 1500
    assert discount["site_id"] == base["site"]["id"]
    assert discount["product_id"] is None
    assert discount["qty_units"] == 0
    assert discount["unit_price_micros"] == 0
    assert discount["target_line_id"] is None
    assert discount["credit_reason"] is None
    assert discount["credits_applied_cents"] == 0
