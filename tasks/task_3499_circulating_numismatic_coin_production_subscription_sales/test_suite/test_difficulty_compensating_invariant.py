"""Difficulty rule compensating_invariant (PRD §2.9, §3.6, §3.8): forward
actions and their compensating actions conserve a domain quantity exactly —
blank pieces across reserve/strike/scrap, bullion pool units across
offer/settle/expire, and sellable product units across order/cancel/promote."""

from test_helpers import (
    TEST_USERS,
    get_success_data,
    make_collector_headers,
    validate_success,
)
from test_helpers.assertions import assert_blank_conservation, assert_report_envelope
from test_helpers.fixtures import (
    confirm_allocation,
    create_allocation_offer,
    create_authorized_purchaser,
    create_collector,
    create_run,
    get_bullion_issue,
    get_order,
    get_product,
    inspect_run,
    place_order,
    set_clock,
    settle_allocation,
    setup_bullion_issue,
    setup_circulating_base,
    setup_on_sale_product,
    start_run,
)

FINANCE = TEST_USERS["finance_officer_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
MANAGER_ALT = TEST_USERS["program_manager_alt_headers"]
FINANCE_ALT = TEST_USERS["finance_officer_alt_headers"]


def test_blank_pieces_conserved_across_reserve_strike_scrap(api):
    """PRD §2.9: "Blank stock is reconciled as an invariant on every
    blank-affecting transition — lot receipt, run start, inspection resolution,
    and run cancellation. For each denomination, the pieces on hand
    (`blank_stock_pieces`), plus the pieces reserved by runs currently in
    `STRIKING` or `INSPECTION`, plus all pieces produced across its runs, plus
    all pieces scrapped across its runs, must equal the total pieces delivered
    by its `DELIVERED` lots."
    PRD §3.3: "On `outcome=PASS` the inspector supplies `good_pieces` between 0
    and the run's `reserved_blanks` inclusive — any other value is rejected with
    `ERR_INVALID_REQUEST` (400) — and the run's `produced_pieces` becomes
    `good_pieces`, its `scrapped_pieces` becomes the reserved count minus the
    good pieces, `reserved_blanks` zeroes out, and the run lands in
    `COMPLETED`."
    PRD §3.3: "On `outcome=FAIL` the entire reservation is lost:
    `scrapped_pieces` grows by the reserved count, `reserved_blanks` zeroes out,
    `rework_count` increments by one, and the run returns to `REWORK`, from
    which a planner may start it again with a fresh reservation once stock and
    quality gates permit."

    Design: Difficulty/compensating_invariant/blank_pieces_conserved_across_reserve_strike_scrap
    """
    # QUARTER; 10t lot DELIVERED -> 1760000 blanks; FY2026 order for 300000.
    denomination, lot, fed_order = setup_circulating_base(
        api, quantity_ordered_pieces=300000)
    run1 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P1",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T12:00:00Z",
        planned_quantity=100000)
    run2 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P2",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T12:00:00Z",
        planned_quantity=100000)

    # run1: reserve 100000, then PASS with a partial scrap of 2000.
    start_run(api, run1["id"])
    inspect_run(api, run1["id"], outcome="PASS", good_pieces=98000)
    # run2: reserve 100000, then FAIL — the entire reservation is scrapped.
    start_run(api, run2["id"])
    run2 = inspect_run(api, run2["id"], outcome="FAIL")
    assert run2["status"] == "REWORK"

    resp = api.get_report("seigniorage", FINANCE,
                          params={"denomination_code": "QUARTER"})
    report = validate_success(resp)
    assert_report_envelope(report, "seigniorage")
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["blanks_delivered_pieces"] == 1760000
    assert row["blanks_on_hand_pieces"] == 1560000
    assert row["blanks_reserved_pieces"] == 0
    assert row["blanks_produced_pieces"] == 98000
    assert row["blanks_scrapped_pieces"] == 102000
    # Conservation: 1560000 + 0 + 98000 + 102000 == 1760000.
    assert_blank_conservation(row)


def test_bullion_pool_conserved_across_offer_settle_expire(api):
    """PRD §3.8: "Issues begin `ACTIVE` with `remaining_pool_units` equal to the
    full pool, and the remaining pool excludes every unit held in an `OFFERED`,
    `CONFIRMED`, or `SETTLED` allocation."
    PRD §3.8: "A created offer decrements the issue's `remaining_pool_units` by
    the offered quantity, increments the issue's `version`, records
    `offered_by_user_id` from the manager's `X-User-ID`, fixes
    `offer_expires_at` as the current logical-clock instant plus the issue's
    `offer_window_hours`, and sits in `OFFERED` with `total_price_cents` still
    null."
    PRD §3.8: "When a clock-set sweep finds the logical clock at or past an
    `OFFERED` allocation's `offer_expires_at`, the allocation becomes `EXPIRED`
    — terminal — its `quantity_units` return to the issue's
    `remaining_pool_units`, an issue that had sold out returns to `ACTIVE`, and
    the issue's `version` increments."

    Design: Difficulty/compensating_invariant/bullion_pool_conserved_across_offer_settle_expire
    """
    issue = setup_bullion_issue(
        api, clock_ts="2026-09-10T00:00:00Z", name="AGE 2026",
        total_pool_units=1000, offer_window_hours=48,
        creator_headers=MANAGER_ALT)
    ap = create_authorized_purchaser(api, name="Dealer", tier="T1")
    alloc1, issue = create_allocation_offer(
        api, issue, ap, 50, offerer_headers=MANAGER_ALT)
    alloc2, issue = create_allocation_offer(
        api, issue, ap, 100, offerer_headers=MANAGER_ALT)
    assert issue["remaining_pool_units"] == 850

    # alloc1 settles (its 50 units stay out of the pool); alloc2 lapses.
    alloc1 = confirm_allocation(api, alloc1, ap)
    alloc1 = settle_allocation(api, alloc1, settler_headers=FINANCE_ALT)
    assert alloc1["status"] == "SETTLED"

    # alloc2 was offered at 2026-09-10T00:00:00Z with a 48h window; the sweep
    # at exactly offer_expires_at expires it and restores its 100 units.
    set_clock(api, "2026-09-12T00:00:00Z")
    alloc2 = get_success_data(api.get_allocation(alloc2["id"], MANAGER))
    assert alloc2["status"] == "EXPIRED"

    issue = get_bullion_issue(api, issue["id"])
    assert issue["remaining_pool_units"] == 950
    # Conservation: remaining 950 + SETTLED 50 == total_pool_units 1000.
    assert issue["remaining_pool_units"] + alloc1["quantity_units"] == 1000
    assert issue["total_pool_units"] == 1000


def test_product_mintage_units_conserved_across_cancel_promote(api):
    """PRD §3.6: "`SOLD_OUT` is therefore a reversible state, and
    `remaining_units` is always the limit minus the allocated count."
    PRD §3.6: "Finally the allocation waterfall runs against the product's
    current `allocated_units`: if the allocated count plus the order's quantity
    stays at or below `mintage_limit`, the whole order becomes `ALLOCATED` and
    `allocated_units` grows by the quantity — flipping the product to `SOLD_OUT`
    when the limit is met exactly — and otherwise the whole order becomes
    `WAITLISTED`, because partial fills are never performed."
    PRD §3.6: "Released units immediately trigger waitlist promotion: the
    platform scans the product's `WAITLISTED` orders oldest first by
    `created_at`, ties broken by server receipt order, under strict
    head-of-line blocking — the earliest waiting order is promoted to
    `ALLOCATED` if its `quantity` fits the remaining units, growing
    `allocated_units` and possibly closing the product at `SOLD_OUT` again, and
    the scan repeats with the new earliest; the moment the earliest waiting
    order does not fit, promotion stops and no later order is considered, even
    one that would fit."

    Design: Difficulty/compensating_invariant/product_mintage_units_conserved_across_cancel_promote
    """
    product = setup_on_sale_product(
        api, product_code="CONS-1", product_family="CONSF", price_cents=3000,
        mintage_limit=5, household_order_limit=99)
    c1 = create_collector(api, full_name="K1", email="k1@example.com",
                          household_id="HH-K1")
    c2 = create_collector(api, full_name="K2", email="k2@example.com",
                          household_id="HH-K2")
    c3 = create_collector(api, full_name="K3", email="k3@example.com",
                          household_id="HH-K3")

    o1 = place_order(api, product["id"], c1, 2)  # 2 + 3 == 5
    o2 = place_order(api, product["id"], c2, 3)  # 5 + 0 == 5, SOLD_OUT
    o3 = place_order(api, product["id"], c3, 2)
    assert o1["allocation_status"] == "ALLOCATED"
    assert o2["allocation_status"] == "ALLOCATED"
    assert o3["allocation_status"] == "WAITLISTED"

    product = get_product(api, product["id"])
    assert product["allocated_units"] == 5
    assert product["remaining_units"] == 0
    assert product["status"] == "SOLD_OUT"
    assert product["allocated_units"] + product["remaining_units"] == product["mintage_limit"]

    # Cancel releases 2 units; the promotion re-consumes exactly them (o3's
    # quantity 2 fits), so the invariant holds at every step.
    resp = api.cancel_order(o1["id"], make_collector_headers(c1["id"]))
    o1 = validate_success(resp)
    assert o1["allocation_status"] == "RELEASED"

    o3 = get_order(api, o3["id"])
    assert o3["allocation_status"] == "ALLOCATED"
    product = get_product(api, product["id"])
    assert product["allocated_units"] == 5
    assert product["remaining_units"] == 0
    assert product["status"] == "SOLD_OUT"
    assert product["allocated_units"] + product["remaining_units"] == product["mintage_limit"]
