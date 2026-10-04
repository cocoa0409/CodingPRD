"""Corner coverage — PRD-pinned calculations: waitlist promotion head-of-line
blocking (§3.6), subscription invoice shipping tiers (§3.7), bullion premium
size brackets (§3.8), the denomination error-rate quality gate (§3.3), the
seigniorage report's fiscal-year filter (§2.9), and the surcharge
disbursement min() boundary (§3.5)."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_created,
    validate_error,
    validate_success,
)
from test_helpers.assertions import (
    assert_report_envelope,
    bullion_total_price_cents,
    subscription_invoice_amount_cents,
    surcharge_disbursement_cents,
)
from test_helpers.constants import DEFAULT_GOLD_SPOT_CENTS_PER_OZ
from test_helpers.factories import create_error_coin_case_payload
from test_helpers.fixtures import (
    confirm_allocation,
    create_allocation_offer,
    create_authorized_purchaser,
    create_collector,
    create_denomination,
    create_fed_order,
    create_run,
    disburse_surcharges,
    get_order,
    get_product,
    inspect_run,
    place_order,
    run_billing_cycle,
    set_clock,
    setup_bullion_issue,
    setup_circulating_base,
    setup_on_sale_product,
    setup_program_with_paid_sales,
    setup_subscription,
    start_run,
)
from test_helpers.test_users import make_collector_headers

PLANNER = TEST_USERS["production_planner_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
INSPECTOR = TEST_USERS["quality_inspector_headers"]


def _setup_case_with_pending_run(api, *, error_pieces, planned_quantity=10000,
                                 good_pieces=9800, run2_quantity=5000,
                                 run2_start="2026-10-05T13:00:00Z",
                                 run2_end="2026-10-05T15:00:00Z"):
    """Circulating chain ending in a QUARANTINED case against a COMPLETED run1
    while a second run is still PLANNED. run2 must be scheduled BEFORE run1's
    inspection resolves: otherwise run1's completion leaves every linked run
    terminal with the fulfilled count short of the ordered quantity and the
    order auto-transitions to SHORTFALL_RECORDED (PRD §3.1), after which any
    run start fails the ERR_RUN_NOT_STARTABLE state gate (PRD §3.3) and the
    quality gate these tests exercise is never evaluated. run2's press window
    defaults to 13:00-15:00 so it cannot overlap run1's 08:00-12:00 window on
    the same press line while run1 is non-terminal. Returns
    (case, run1, run2, fed_order)."""
    _, _, fed_order = setup_circulating_base(api)
    run1 = create_run(api, fed_order["id"], planned_quantity=planned_quantity)
    run2 = create_run(api, fed_order["id"], planned_quantity=run2_quantity,
                      planned_start=run2_start, planned_end=run2_end)
    start_run(api, run1["id"])
    inspect_run(api, run1["id"], good_pieces=good_pieces)
    case = validate_created(api.create_error_coin_case(
        create_error_coin_case_payload(
            production_run_id=run1["id"], error_pieces=error_pieces,
            description="off-center strikes"),
        INSPECTOR))
    return case, run1, run2, fed_order


def test_waitlist_promotion_head_of_line_blocking(api):
    """PRD §3.6: "Released units immediately trigger waitlist promotion: the
    platform scans the product's `WAITLISTED` orders oldest first by
    `created_at`, ties broken by server receipt order, under strict
    head-of-line blocking — the earliest waiting order is promoted to
    `ALLOCATED` if its `quantity` fits the remaining units, growing
    `allocated_units` and possibly closing the product at `SOLD_OUT` again,
    and the scan repeats with the new earliest; the moment the earliest
    waiting order does not fit, promotion stops and no later order is
    considered, even one that would fit."
    PRD §3.6: "A sold-out product still accepts orders — they join its
    waitlist."
    PRD §3.6: "Thereafter allocation drives the lifecycle: when
    `allocated_units` reaches `mintage_limit` exactly, whether through a new
    allocation or a waitlist promotion, the product auto-transitions `ON_SALE →
    SOLD_OUT`; when a cancellation pulls `allocated_units` back below the
    limit, the product returns `SOLD_OUT → ON_SALE`."

    Design: Corner/calculations/waitlist_promotion_head_of_line_blocking
    """
    product = setup_on_sale_product(
        api, product_code="HOL-1", product_family="HFAM",
        product_type="PROOF_SET", price_cents=2000, mintage_limit=5,
        household_order_limit=9)
    c1 = create_collector(api, full_name="H1", email="h1@example.com", household_id="HH-H1")
    c2 = create_collector(api, full_name="H2", email="h2@example.com", household_id="HH-H2")
    c3 = create_collector(api, full_name="H3", email="h3@example.com", household_id="HH-H3")
    c4 = create_collector(api, full_name="H4", email="h4@example.com", household_id="HH-H4")

    a1 = place_order(api, product["id"], c1, 3)
    a2 = place_order(api, product["id"], c2, 2)
    b = place_order(api, product["id"], c3, 4)
    c = place_order(api, product["id"], c4, 1)
    assert a1["allocation_status"] == "ALLOCATED"
    assert a2["allocation_status"] == "ALLOCATED"
    # 3 + 2 == mintage_limit 5: the product closed, so both later orders waitlist.
    assert b["allocation_status"] == "WAITLISTED"
    assert c["allocation_status"] == "WAITLISTED"
    mid = get_product(api, product["id"])
    assert mid["status"] == "SOLD_OUT" and mid["allocated_units"] == 5

    cancelled = validate_success(api.cancel_order(a1["id"], make_collector_headers(c1["id"])))
    assert cancelled["allocation_status"] == "RELEASED"

    # Cancelling a1 releases 3 units (allocated 5 -> 2, remaining 3). The head
    # of the line is b (qty 4): 4 > 3 does not fit, so the scan STOPS and c
    # (qty 1, which would fit) is never considered.
    b_after = get_order(api, b["id"])
    c_after = get_order(api, c["id"])
    assert b_after["allocation_status"] == "WAITLISTED", (
        f"head-of-line order (qty 4 > 3 released) must stay WAITLISTED, got "
        f"{b_after['allocation_status']}")
    assert c_after["allocation_status"] == "WAITLISTED", (
        f"scan stops at the blocking head; the fitting 1-unit order must not be "
        f"promoted, got {c_after['allocation_status']}")
    product_after = get_product(api, product["id"])
    assert product_after["allocated_units"] == 2
    assert product_after["status"] == "ON_SALE"


def test_shipping_tier_boundary_three_vs_four_units(api):
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

    Design: Corner/calculations/shipping_tier_boundary_three_vs_four_units
    """
    # 9995 x 0.90 = 8995.5 -> round half-up per unit -> 8996.
    _, _, sub3 = setup_subscription(
        api, units_per_cycle=3, frequency="MONTHLY", price_cents=9995)
    _, _, sub4 = setup_subscription(
        api, units_per_cycle=4, frequency="MONTHLY", price_cents=9995)

    inv3, _ = run_billing_cycle(api, sub3)
    inv4, _ = run_billing_cycle(api, sub4)

    expected3 = subscription_invoice_amount_cents(9995, 3)
    expected4 = subscription_invoice_amount_cents(9995, 4)
    assert expected3 == 27483   # 8996 x 3 + 495 (tier 1: at most 3 units)
    assert expected4 == 36879   # 8996 x 4 + 895 (tier 2 starts at 4 units)
    assert inv3["amount_cents"] == expected3, (
        f"3 units must land in the 495c shipping tier: expected {expected3}, "
        f"got {inv3['amount_cents']}")
    assert inv4["amount_cents"] == expected4, (
        f"4 units must land in the 895c shipping tier: expected {expected4}, "
        f"got {inv4['amount_cents']}")
    assert inv3["status"] == "PENDING" and inv4["status"] == "PENDING"


def test_bullion_bracket_boundary_99_vs_100_oz(api):
    """PRD §3.8: "The premium in basis points combines a tier component — 300
    basis points for `T1`, 450 for `T2`, and 625 for `T3` — with a size bracket:
    200 basis points when the total weight is under 100 troy ounces, 100 basis
    points from 100 up to but not including 500 troy ounces, and zero at 500
    troy ounces or more."
    PRD §3.8: "The `total_price_cents` is then the total weight multiplied by
    the metal's current spot price in cents per troy ounce, multiplied by one
    plus the premium fraction (the premium basis points divided by ten
    thousand), with a single round-half-up to whole cents at the very end."

    Design: Corner/calculations/bullion_bracket_boundary_99_vs_100_oz
    """
    issue = setup_bullion_issue(
        api, clock_ts="2026-09-10T00:00:00Z", name="AGE 2026",
        total_pool_units=200, offer_window_hours=72)
    ap = create_authorized_purchaser(api, name="Dealer", tier="T1")

    alloc99, issue = create_allocation_offer(api, issue, ap, 99)
    alloc100, issue = create_allocation_offer(api, issue, ap, 100)
    alloc99 = confirm_allocation(api, alloc99, ap)
    alloc100 = confirm_allocation(api, alloc100, ap)

    # 99oz: 300 (T1) + 200 (under 100oz) = 500bps -> 99 x 250000 x 1.05.
    # 100oz: bracket flips to +100bps -> 400bps -> 100 x 250000 x 1.04.
    expected99 = bullion_total_price_cents(
        99, 1.0, DEFAULT_GOLD_SPOT_CENTS_PER_OZ, "T1")
    expected100 = bullion_total_price_cents(
        100, 1.0, DEFAULT_GOLD_SPOT_CENTS_PER_OZ, "T1")
    assert expected99 == 25987500
    assert expected100 == 26000000
    assert alloc99["total_price_cents"] == expected99, (
        f"99oz must carry the under-100oz bracket premium: expected "
        f"{expected99}, got {alloc99['total_price_cents']}")
    assert alloc100["total_price_cents"] == expected100, (
        f"exactly 100oz must drop to the 100-499oz bracket: expected "
        f"{expected100}, got {alloc100['total_price_cents']}")


def test_error_rate_exactly_two_percent_breaches(api):
    """PRD §3.3: "And the denomination's trailing quality record must be clean:
    over the window from 30 days before the current logical-clock instant up to
    that instant, the platform sums the `error_pieces` of every error-coin case
    raised against runs of this denomination whose case was created inside the
    window, and sums the `produced_pieces` plus `scrapped_pieces` of every run
    of this denomination whose inspection completed inside the window; if any
    pieces were struck at all and the ratio of error pieces to struck pieces is
    at least 0.02 — exactly 0.02 breaches the gate, while anything strictly
    below it passes — the start is rejected with
    `ERR_QUALITY_THRESHOLD_BREACH` (422)."

    Design: Corner/calculations/error_rate_exactly_two_percent_breaches
    """
    _, _, run2, _ = _setup_case_with_pending_run(
        api, error_pieces=200, planned_quantity=10000, good_pieces=9800)
    # 200 error pieces over (9800 produced + 200 scrapped) == 200/10000 == 0.02
    # exactly, and >= breaches.
    resp = api.start_production_run(run2["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_QUALITY_THRESHOLD_BREACH)
    run2_after = validate_success(api.get_production_run(run2["id"], PLANNER))
    assert run2_after["status"] == "PLANNED", (
        f"a rejected start must leave the run PLANNED, got {run2_after['status']}")


def test_error_rate_just_below_threshold_passes(api):
    """PRD §3.3: "if any pieces were struck at all and the ratio of error pieces
    to struck pieces is at least 0.02 — exactly 0.02 breaches the gate, while
    anything strictly below it passes — the start is rejected with
    `ERR_QUALITY_THRESHOLD_BREACH` (422)."
    PRD §2.8: "Ratios such as the denomination error rate are compared exactly
    as rational numbers over integers, never through a rounded decimal
    approximation."

    Design: Corner/calculations/error_rate_just_below_threshold_passes
    """
    _, _, run2, _ = _setup_case_with_pending_run(
        api, error_pieces=199, planned_quantity=10000, good_pieces=9800)
    # 199 / (9800 + 200) == 0.0199 < 0.02: one piece under the boundary passes.
    started = validate_success(api.start_production_run(run2["id"], PLANNER))
    assert started["status"] == "STRIKING", (
        f"0.0199 < 0.02 must pass the quality gate, got {started['status']}")


def test_error_rate_rolling_window_excludes_old_cases(api):
    """PRD §3.3: "And the denomination's trailing quality record must be clean:
    over the window from 30 days before the current logical-clock instant up to
    that instant, the platform sums the `error_pieces` of every error-coin case
    raised against runs of this denomination whose case was created inside the
    window, and sums the `produced_pieces` plus `scrapped_pieces` of every run
    of this denomination whose inspection completed inside the window; if any
    pieces were struck at all and the ratio of error pieces to struck pieces is
    at least 0.02 — exactly 0.02 breaches the gate, while anything strictly
    below it passes — the start is rejected with
    `ERR_QUALITY_THRESHOLD_BREACH` (422)."

    Design: Corner/calculations/error_rate_rolling_window_excludes_old_cases
    """
    # Breach-shaped data (200/10000) recorded entirely at 2026-09-01, with
    # run2 scheduled before run1's inspection so the order stays FULFILLING.
    _, _, run2, _ = _setup_case_with_pending_run(
        api, error_pieces=200, planned_quantity=10000, good_pieces=9800,
        run2_start="2026-10-16T08:00:00Z", run2_end="2026-10-16T10:00:00Z")
    # 44 days later the window [2026-09-15, 2026-10-15] excludes BOTH the old
    # error case (numerator) and run1's inspection (denominator): in-window
    # struck pieces == 0, so the "if any pieces were struck at all" condition
    # is false and the gate stays open.
    set_clock(api, "2026-10-15T00:00:00Z")
    started = validate_success(api.start_production_run(run2["id"], PLANNER))
    assert started["status"] == "STRIKING", (
        f"out-of-window quality data must not block the start, got {started['status']}")


def test_seigniorage_report_filters_by_fiscal_year(api):
    """PRD §2.9: "The seigniorage report carries one row per denomination with
    `budgeted_seigniorage_cents` summed over non-cancelled orders' creation-time
    snapshots, `realized_seigniorage_cents` summed over `FULFILLED` orders, and
    the reconciliation figures `blanks_on_hand_pieces`, `blanks_reserved_pieces`,
    `blanks_produced_pieces`, `blanks_scrapped_pieces`, and
    `blanks_delivered_pieces`; optional `fiscal_year` and `denomination_code`
    query parameters narrow the rows."
    PRD §3.1: "Newly submitted orders sit in `SUBMITTED`, and at creation the
    platform snapshots `budgeted_seigniorage_cents` as `quantity_ordered_pieces`
    multiplied by the denomination's current `budgeted_unit_seigniorage_cents`."

    Design: Corner/calculations/seigniorage_report_filters_by_fiscal_year
    """
    create_denomination(api)  # QUARTER: 25 - 4.0 - 2.0 -> 19.0c per piece
    create_fed_order(api, fiscal_year=2026, quantity_ordered_pieces=100000)
    create_fed_order(api, fiscal_year=2027, quantity_ordered_pieces=50000,
                     due_date="2027-12-31")

    data = validate_success(api.get_report(
        "seigniorage", FINANCE,
        params={"fiscal_year": 2026, "denomination_code": "QUARTER"}))
    assert_report_envelope(data, "seigniorage")
    rows = data["rows"]
    assert len(rows) == 1, f"denomination_code filter must yield one row, got {len(rows)}"
    # FY2026: 100000 x 19.0 == 1900000.0; the FY2027 order's 950000.0 is excluded.
    assert rows[0]["budgeted_seigniorage_cents"] == 1900000, (
        f"fiscal_year=2026 must include only that year's snapshots: expected "
        f"1900000, got {rows[0]['budgeted_seigniorage_cents']}")


def test_surcharge_disbursement_cap_binds(api):
    """PRD §3.5: "`surcharge_accrued_cents` multiplies the total paid units
    across those products by `surcharge_cents_per_unit`; it is computed
    separately and is not net of the administrative fee."
    PRD §3.5: "The disbursed amount is the smaller of `beneficiary_cap_cents`
    and `surcharge_accrued_cents` — when the two are equal, the cap is paid
    exactly — and is recorded in `disbursed_cents` as the program moves to its
    terminal `SURCHARGE_DISBURSED` state, incrementing `version` one last time."
    PRD §3.5: "Disbursement requires the program to be in `SALES_CLOSED` — any
    other state is rejected with `ERR_PROGRAM_NOT_DISBURSABLE` (422) — and the
    officer's `X-User-ID` must differ from the program's `created_by_user_id`
    (`ERR_SEGREGATION_OF_DUTIES`, 422, per §2.10)."

    Design: Corner/calculations/surcharge_disbursement_cap_binds
    """
    program, _, _, order = setup_program_with_paid_sales(
        api, units=400, price_cents=5000,
        program_overrides={
            "name": "Cap Program",
            "statute_reference": "PL 119-30",
            "max_mintage_legal": 1000,
            "surcharge_cents_per_unit": 1000,
            "beneficiary_name": "Cap Fund",
            "beneficiary_cap_cents": 350000,
            "direct_costs_cents": 1000,
        },
        product_overrides={
            "product_code": "CX-CAP",
            "product_family": "CXCF",
            "product_type": "COMMEMORATIVE",
        })
    assert order["payment_status"] == "PAID"
    # 400 paid units x 1000c surcharge: accrual exceeds the 350000c statutory cap.
    assert program["surcharge_accrued_cents"] == 400000

    set_clock(api, "2027-01-01T00:00:00Z")  # past sales_window_end -> SALES_CLOSED
    disbursed = disburse_surcharges(api, program["id"])

    expected = surcharge_disbursement_cents(400000, 350000)
    assert expected == 350000
    assert disbursed["surcharge_accrued_cents"] == 400000
    assert disbursed["disbursed_cents"] == expected, (
        f"the cap must bind over the larger accrual: expected {expected}, got "
        f"{disbursed['disbursed_cents']}")
    assert disbursed["status"] == "SURCHARGE_DISBURSED"


def test_surcharge_disbursement_accrued_binds(api):
    """PRD §3.5: "The disbursed amount is the smaller of `beneficiary_cap_cents`
    and `surcharge_accrued_cents` — when the two are equal, the cap is paid
    exactly — and is recorded in `disbursed_cents` as the program moves to its
    terminal `SURCHARGE_DISBURSED` state, incrementing `version` one last time."
    PRD §3.5: "`surcharge_accrued_cents` multiplies the total paid units across
    those products by `surcharge_cents_per_unit`; it is computed separately and
    is not net of the administrative fee."

    Design: Corner/calculations/surcharge_disbursement_accrued_binds
    """
    program, _, _, order = setup_program_with_paid_sales(
        api, units=300, price_cents=5000,
        program_overrides={
            "name": "Accrual Program",
            "statute_reference": "PL 119-31",
            "max_mintage_legal": 1000,
            "surcharge_cents_per_unit": 1000,
            "beneficiary_name": "Accrual Fund",
            "beneficiary_cap_cents": 350000,
            "direct_costs_cents": 1000,
        },
        product_overrides={
            "product_code": "CX-ACC",
            "product_family": "CXAF",
            "product_type": "COMMEMORATIVE",
        })
    assert order["payment_status"] == "PAID"
    # 300 paid units x 1000c == 300000c accrued, under the 350000c cap.
    assert program["surcharge_accrued_cents"] == 300000

    set_clock(api, "2027-01-01T00:00:00Z")  # past sales_window_end -> SALES_CLOSED
    disbursed = disburse_surcharges(api, program["id"])

    expected = surcharge_disbursement_cents(300000, 350000)
    assert expected == 300000
    assert disbursed["disbursed_cents"] == expected, (
        f"the smaller accrual must pass through whole: expected {expected}, got "
        f"{disbursed['disbursed_cents']}")
    assert disbursed["status"] == "SURCHARGE_DISBURSED"
