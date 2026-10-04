"""Error catalog coverage: every error that is not already driven elsewhere."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
    make_supplier_rep_headers,
)
from test_helpers.factories import bid_payload, cart_coin_event_payload, labor_window_payload


def _manager(store):
    return make_store_manager_headers(store["id"])


def test_request_without_identity_headers_is_unauthenticated(api):
    """No X-User-Role / X-User-ID at all -> 401 ERR_UNAUTHENTICATED.

    PRD §2.1: "Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting an `X-User-Role` value that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/error_unauthenticated_missing_headers
    """
    response = api.list_categories({})
    validate_error(response, "ERR_UNAUTHENTICATED", 401)


def test_bid_ceiling_exceeded_on_open_tender(api):
    """A bid at 1001 on a ceiling-1000 OPEN tender fails ERR_BID_CEILING_EXCEEDED.

    PRD §3.4: "A bid on a tender that is not `OPEN` is rejected with `ERR_TENDER_NOT_OPEN`, and an offer above the tender's `bid_ceiling_cents` is rejected with `ERR_BID_CEILING_EXCEEDED` at submission time."

    Design: Corner/errors/error_bid_ceiling_exceeded
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    response = api.create_bid(
        tender["id"], bid_payload(supplier["id"], 1001),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, "ERR_BID_CEILING_EXCEEDED", 422)


def test_labor_budget_exceeded(api):
    """Weekly spend 7200 plus a new 3600 window over a 10000 budget -> 422.

    PRD §3.8: "And the money rule runs last: the store's weekly spend — the sum of `cost_cents` over its `PLANNED` and `CONFIRMED` windows in that same ISO week — plus the new window's cost must not exceed the store's `weekly_labor_budget_cents`, or the booking is rejected with `ERR_LABOR_BUDGET_EXCEEDED`."

    Design: Corner/errors/error_labor_budget_exceeded
    """
    store = fixtures.create_store(api, weekly_labor_budget_cents=10000)
    manager = _manager(store)

    validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", role="STOCKER",
                                 starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            manager,
        ),
        201,
    )
    validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", role="STOCKER",
                                 starts_at="2026-09-08T06:00:00Z", ends_at="2026-09-08T08:00:00Z"),
            manager,
        ),
        201,
    )

    response = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z2", role="STOCKER",
                             starts_at="2026-09-09T06:00:00Z", ends_at="2026-09-09T08:00:00Z"),
        manager,
    )
    validate_error(response, "ERR_LABOR_BUDGET_EXCEEDED", 422)


def test_coin_balance_negative_rejected_atomically(api):
    """CORRAL_COLLECT of 4 against outstanding 3 fails ERR_COIN_BALANCE_NEGATIVE.

    PRD §3.6: "The balance is checked against the running prefix: any `RETURN`, `CORRAL_COLLECT`, or `AUDIT_ADJUST` that would drive it negative is rejected with `ERR_COIN_BALANCE_NEGATIVE`."

    Design: Corner/errors/error_coin_balance_negative
    """
    store = fixtures.create_store(api)
    manager = _manager(store)

    validate_success(
        api.create_cart_coin_event(store["id"], cart_coin_event_payload("INSERT", 3), manager),
        201,
    )
    response = api.create_cart_coin_event(
        store["id"], cart_coin_event_payload("CORRAL_COLLECT", 4), manager
    )
    validate_error(response, "ERR_COIN_BALANCE_NEGATIVE", 422)

    snapshot = validate_success(api.get_cart_reconciliation(store["id"], manager))
    assert snapshot["coins_outstanding"] == 3, "the rejected event must not be recorded"


def test_window_limit_exceeded_on_seventh_window(api):
    """Six non-cancelled same-week windows are fine; the seventh fails.

    PRD §3.8: "A store may hold at most 6 non-cancelled windows whose `starts_at` falls in the same ISO week, counted from Monday 00:00 UTC up to but not including the next Monday 00:00 UTC; a seventh is rejected with `ERR_WINDOW_LIMIT_EXCEEDED`."

    Design: Corner/errors/error_window_limit_exceeded
    """
    store = fixtures.create_store(api, weekly_labor_budget_cents=1000000)
    manager = _manager(store)

    bookings = [
        ("Z1", "2026-09-07T06:00:00Z", "2026-09-07T07:00:00Z", "STOCKER"),
        ("Z1", "2026-09-07T07:00:00Z", "2026-09-07T08:00:00Z", "STOCKER"),
        ("Z2", "2026-09-07T06:00:00Z", "2026-09-07T07:00:00Z", "STOCKER"),
        ("Z2", "2026-09-08T06:00:00Z", "2026-09-08T07:00:00Z", "CASHIER"),
        ("Z3", "2026-09-09T06:00:00Z", "2026-09-09T07:00:00Z", "CASHIER"),
        ("Z3", "2026-09-10T06:00:00Z", "2026-09-10T07:00:00Z", "SHIFT_LEAD"),
    ]
    for zone, start, end, role in bookings:
        validate_success(
            api.create_labor_window(
                store["id"],
                labor_window_payload(aisle_zone=zone, role=role, starts_at=start, ends_at=end),
                manager,
            ),
            201,
        )

    response = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z4", role="STOCKER",
                             starts_at="2026-09-11T06:00:00Z", ends_at="2026-09-11T07:00:00Z"),
        manager,
    )
    validate_error(response, "ERR_WINDOW_LIMIT_EXCEEDED", 409)


def test_cashier_role_required_for_register_shift(api):
    """Opening a register for a STOCKER fails ERR_CASHIER_ROLE_REQUIRED.

    PRD §3.7: "The named employee must have the role `CASHIER` — opening a register for a `STOCKER` or `SHIFT_LEAD` is rejected with `ERR_CASHIER_ROLE_REQUIRED`."

    Design: Corner/errors/error_cashier_role_required
    """
    store = fixtures.create_store(api)
    stocker = fixtures.create_employee(api, store, role="STOCKER")

    response = api.create_register_shift(
        store["id"], {"cashier_id": stocker["id"]}, _manager(store)
    )
    validate_error(response, "ERR_CASHIER_ROLE_REQUIRED", 422)


def test_sku_cap_below_current_rejected(api):
    """Lowering the cap to 1 while two products are ACTIVE fails ERR_SKU_CAP_BELOW_CURRENT.

    PRD §3.1: "Two guards apply: raising or lowering the cap can never leave the cap below the category's current `active_sku_count` — such a request is rejected with `ERR_SKU_CAP_BELOW_CURRENT` — and the cap must remain within the 1-to-5 band."

    Design: Corner/errors/error_sku_cap_below_current
    """
    category = fixtures.create_category(api, sku_cap=2)
    fixtures.award_product_with_two_suppliers(api, category["id"])
    fixtures.award_product_with_two_suppliers(api, category["id"])

    current = validate_success(api.get_category(category["id"], CATEGORY_MANAGER_HEADERS))
    assert current["active_sku_count"] == 2

    response = api.update_category(
        category["id"],
        {"sku_cap": 1, "expected_category_version": current["version"]},
        CATEGORY_MANAGER_HEADERS,
    )
    validate_error(response, "ERR_SKU_CAP_BELOW_CURRENT", 409)
