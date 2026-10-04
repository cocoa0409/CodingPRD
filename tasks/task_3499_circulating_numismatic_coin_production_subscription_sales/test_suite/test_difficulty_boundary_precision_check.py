"""Difficulty rule boundary_precision_check (PRD §3.2, §3.6, §3.8): numeric
limits accept at exact equality and reject one unit beyond — household order
limit on POST /mint/orders, bullion remaining pool on allocation offers, and
the 50-tonne same-day vault receiving cap."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_collector_headers,
    validate_error,
)
from test_helpers.factories import create_allocation_payload, create_order_payload
from test_helpers.fixtures import (
    create_authorized_purchaser,
    create_allocation_offer,
    create_collector,
    create_denomination,
    create_metal_lot,
    place_order,
    receive_metal_lot,
    set_clock,
    setup_bullion_issue,
    setup_on_sale_product,
)

MANAGER = TEST_USERS["program_manager_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]


def test_household_limit_exact_equality_accepted(api):
    """PRD §3.6: "The household limit then aggregates: the platform sums the
    quantities of every non-`CANCELLED` order for this product placed by any
    collector sharing the caller's `household_id`, adds the new quantity, and
    accepts only while the total stays at or below the product's
    `household_order_limit` — reaching exactly the limit succeeds, while one
    unit beyond it fails with `ERR_HOUSEHOLD_LIMIT_EXCEEDED` (422)."

    Design: Difficulty/boundary_precision_check/household_limit_exact_equality_accepted
    """
    product = setup_on_sale_product(
        api, product_code="HL-1", product_family="HLF", price_cents=2000,
        mintage_limit=100, household_order_limit=2)
    c1 = create_collector(api, full_name="Shared One", email="s1@example.com",
                          household_id="HH-SHARED")
    c2 = create_collector(api, full_name="Shared Two", email="s2@example.com",
                          household_id="HH-SHARED")

    o1 = place_order(api, product["id"], c1, 1)
    assert o1["allocation_status"] == "ALLOCATED"  # household total 1 <= 2
    # The household aggregate spans both collectors: 1 (c1) + 1 (c2) == 2, the
    # exact limit — accepted.
    o2 = place_order(api, product["id"], c2, 1)
    assert o2["allocation_status"] == "ALLOCATED"

    # One unit beyond the limit (2 + 1 > 2) is rejected.
    resp = api.create_order(
        create_order_payload(product_id=product["id"], quantity=1),
        make_collector_headers(c1["id"]))
    validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_LIMIT_EXCEEDED)


def test_bullion_pool_exact_equality_accepted(api):
    """PRD §3.8: "The request names an `authorized_purchaser_id` — the firm must
    exist and be in `APPROVED`, otherwise `ERR_AP_NOT_APPROVED` (422) — a
    `quantity_units` of at least 1 (`ERR_QUANTITY_INVALID`, 400) that does not
    exceed the issue's `remaining_pool_units` (`ERR_POOL_INSUFFICIENT`, 422),
    and the OCC field `expected_bullion_issue_version` described in §2.6."
    PRD §3.8: "A created offer decrements the issue's `remaining_pool_units` by
    the offered quantity, increments the issue's `version`, records
    `offered_by_user_id` from the manager's `X-User-ID`, fixes
    `offer_expires_at` as the current logical-clock instant plus the issue's
    `offer_window_hours`, and sits in `OFFERED` with `total_price_cents` still
    null."

    Design: Difficulty/boundary_precision_check/bullion_pool_exact_equality_accepted
    """
    issue = setup_bullion_issue(api, name="AGE 2026", total_pool_units=100)
    ap = create_authorized_purchaser(api, name="Dealer", tier="T1")

    # An offer of exactly the remaining 100 units does not exceed the pool.
    alloc, issue = create_allocation_offer(api, issue, ap, 100)
    assert alloc["status"] == "OFFERED"
    assert issue["remaining_pool_units"] == 0

    # One unit beyond the remaining pool (0) is rejected.
    resp = api.create_allocation(
        issue["id"],
        create_allocation_payload(
            authorized_purchaser_id=ap["id"], quantity_units=1,
            expected_bullion_issue_version=issue["version"]),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_POOL_INSUFFICIENT)


def test_vault_capacity_exact_fifty_tonnes_accepted(api):
    """PRD §3.2: "Vaults impose a daily receiving cap: the sum of
    `quantity_tonnes` over lots delivered at the same vault on the same UTC date
    — per the logical clock — plus the arriving lot's tonnage must not exceed 50
    tonnes, and a receipt that would break the cap is rejected with
    `ERR_VAULT_CAPACITY_EXCEEDED` (422)."

    Design: Difficulty/boundary_precision_check/vault_capacity_exact_fifty_tonnes_accepted
    """
    set_clock(api, "2026-09-10T00:00:00Z", {"COPPER": 800000})
    create_denomination(api)
    lot1 = create_metal_lot(api, quantity_tonnes=30, vault="WEST_POINT",
                            locked_unit_price_cents_per_tonne=800000,
                            planned_delivery_date="2026-09-10")
    lot2 = create_metal_lot(api, quantity_tonnes=20, vault="WEST_POINT",
                            locked_unit_price_cents_per_tonne=800000,
                            planned_delivery_date="2026-09-10")
    lot3 = create_metal_lot(api, quantity_tonnes=1, vault="WEST_POINT",
                            locked_unit_price_cents_per_tonne=800000,
                            planned_delivery_date="2026-09-10")

    lot1 = receive_metal_lot(api, lot1["id"])
    assert lot1["status"] == "DELIVERED"  # 30 <= 50
    # 30 + 20 == 50 == the daily cap exactly — accepted.
    lot2 = receive_metal_lot(api, lot2["id"])
    assert lot2["status"] == "DELIVERED"

    # 50 + 1 > 50 — the arriving tonne breaks the cap.
    resp = api.receive_metal_lot(lot3["id"], PROCUREMENT)
    validate_error(resp, ApiErrorId.ERR_VAULT_CAPACITY_EXCEEDED)
