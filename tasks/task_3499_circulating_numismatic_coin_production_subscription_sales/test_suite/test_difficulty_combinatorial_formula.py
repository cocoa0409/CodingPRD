"""Difficulty rule combinatorial_formula (PRD §3.5, §3.7, §3.8): multi-input
formulas whose input combination and pinned evaluation/rounding order decide
the result — bullion settlement premium composition (tier x size bracket),
subscription invoice per-unit rounding before multiplication, and program net
proceeds computed on (gross - direct costs), not on gross."""

from test_helpers.assertions import (
    bullion_total_price_cents,
    program_net_proceeds_cents,
    subscription_invoice_amount_cents,
)
from test_helpers.constants import DEFAULT_GOLD_SPOT_CENTS_PER_OZ
from test_helpers.fixtures import (
    add_months,
    confirm_allocation,
    create_allocation_offer,
    create_authorized_purchaser,
    run_billing_cycle,
    setup_bullion_issue,
    setup_program_with_paid_sales,
    setup_subscription,
)


def test_bullion_price_tier_plus_bracket_composition(api):
    """PRD §3.8: "The premium in basis points combines a tier component — 300
    basis points for `T1`, 450 for `T2`, and 625 for `T3` — with a size bracket:
    200 basis points when the total weight is under 100 troy ounces, 100 basis
    points from 100 up to but not including 500 troy ounces, and zero at 500
    troy ounces or more."
    PRD §3.8: "The `total_price_cents` is then the total weight multiplied by
    the metal's current spot price in cents per troy ounce, multiplied by one
    plus the premium fraction (the premium basis points divided by ten
    thousand), with a single round-half-up to whole cents at the very end."
    PRD §3.8: "Issues begin `ACTIVE` with `remaining_pool_units` equal to the
    full pool, and the remaining pool excludes every unit held in an `OFFERED`,
    `CONFIRMED`, or `SETTLED` allocation."

    Design: Difficulty/combinatorial_formula/bullion_price_tier_plus_bracket_composition
    """
    issue = setup_bullion_issue(
        api, name="American Gold Eagle 2026", total_pool_units=1000,
        offer_window_hours=48)
    ap_t2 = create_authorized_purchaser(api, name="Dealer Tier Two", tier="T2")
    ap_t1 = create_authorized_purchaser(api, name="Dealer Tier One", tier="T1")

    alloc_t2, issue = create_allocation_offer(api, issue, ap_t2, 50)
    alloc_t1, issue = create_allocation_offer(api, issue, ap_t1, 500)

    alloc_t2 = confirm_allocation(api, alloc_t2, ap_t2)
    alloc_t1 = confirm_allocation(api, alloc_t1, ap_t1)

    # T2 x 50oz -> 450 + 200 = 650 bps; T1 x 500oz -> 300 + 0 = 300 bps
    # (the bracket flips to 0 at exactly 500oz).
    expected_t2 = bullion_total_price_cents(
        50, 1.0, DEFAULT_GOLD_SPOT_CENTS_PER_OZ, "T2")
    assert expected_t2 == 13312500
    expected_t1 = bullion_total_price_cents(
        500, 1.0, DEFAULT_GOLD_SPOT_CENTS_PER_OZ, "T1")
    assert expected_t1 == 128750000
    assert alloc_t2["total_price_cents"] == expected_t2
    assert alloc_t1["total_price_cents"] == expected_t1
    assert issue["remaining_pool_units"] == 450


def test_subscription_invoice_per_unit_rounding_before_multiplication(api):
    """PRD §3.7: "A successful run creates a new invoice in `PENDING` whose
    `subscription_id` ties it to the billed subscription, whose `period_index`
    is `cycles_billed` plus one, and whose `amount_cents` prices the cycle: the
    product's `price_cents` is discounted by the ten-percent subscriber discount
    and rounded half-up to whole cents per unit first, that per-unit net is then
    multiplied by `units_per_cycle`, and finally a shipping tier is added — 495
    cents when the cycle ships at most 3 units, 895 cents when it ships 4 to 10
    units, and free shipping at 11 units or more."
    PRD §3.7: "The rounding order is pinned: the discount is applied and rounded
    per unit before multiplication, and rounding after multiplication is a
    rejected order of operations."
    PRD §3.7: "The cycle then advances `next_billing_date` by one month for
    `MONTHLY` or three months for `QUARTERLY`, increments `cycles_billed` by
    one, increments the subscription's `version`, and returns the created
    invoice."

    Design: Difficulty/combinatorial_formula/subscription_invoice_per_unit_rounding_before_multiplication
    """
    product, collector, subscription = setup_subscription(
        api, units_per_cycle=2, frequency="MONTHLY", price_cents=9995)
    invoice, subscription = run_billing_cycle(api, subscription)

    # 9995 x 0.90 = 8995.5 -> round half-up per unit -> 8996; 8996 x 2 = 17992;
    # + 495 shipping (<= 3 units). Round-after-multiply would give 18486.
    expected_amount = subscription_invoice_amount_cents(9995, 2)
    assert expected_amount == 18487
    assert invoice["amount_cents"] == expected_amount
    assert invoice["status"] == "PENDING"
    assert invoice["period_index"] == 1

    expected_next_billing = add_months("2026-09-01", 1)
    assert expected_next_billing == "2026-10-01"
    assert subscription["next_billing_date"] == expected_next_billing
    assert subscription["cycles_billed"] == 1


def test_program_net_proceeds_pinned_evaluation_order(api):
    """PRD §3.5: "`gross_receipts_cents` sums, over all `PAID` orders of
    products belonging to the program, each order's quantity multiplied by its
    product's `price_cents`."
    PRD §3.5: "`surcharge_accrued_cents` multiplies the total paid units across
    those products by `surcharge_cents_per_unit`; it is computed separately and
    is not net of the administrative fee."
    PRD §3.5: "`net_proceeds_cents` follows a pinned evaluation order: first the
    base is `gross_receipts_cents` minus `direct_costs_cents`; then the
    administrative fee is that base multiplied by five percent, rounded half-up
    to whole cents; then net proceeds are the base minus the fee."

    Design: Difficulty/combinatorial_formula/program_net_proceeds_pinned_evaluation_order
    """
    program, product, collector, order = setup_program_with_paid_sales(
        api, units=400, price_cents=5000,
        program_overrides={
            "name": "Harbor Centennial",
            "statute_reference": "PL 119-10",
            "max_mintage_legal": 1000,
            "surcharge_cents_per_unit": 1000,
            "beneficiary_name": "Harbor Foundation",
            "beneficiary_cap_cents": 350000,
            "direct_costs_cents": 1200000,
        },
        product_overrides={
            "product_code": "CX-1",
            "product_family": "CXF",
            "product_type": "COMMEMORATIVE",
            "household_order_limit": 500,
        })

    assert order["payment_status"] == "PAID"
    assert program["gross_receipts_cents"] == 2000000
    # base 800000 = 2000000 - 1200000; fee 40000 = round_half_up(800000 x 0.05);
    # net 760000. A fee-on-gross reading would wrongly give net 700000.
    expected_net = program_net_proceeds_cents(2000000, 1200000)
    assert expected_net == 760000
    assert program["net_proceeds_cents"] == expected_net
    assert program["surcharge_accrued_cents"] == 400000  # 400 paid units x 1000c
