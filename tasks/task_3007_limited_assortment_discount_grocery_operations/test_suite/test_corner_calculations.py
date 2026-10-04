"""Calculation rules with literal expected values: labor cost, coin ledger, scan precision."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures, make_store_manager_headers
from test_helpers.factories import cart_coin_event_payload, labor_window_payload, scan_payload


def test_labor_window_cost_constants_applied(api):
    """A 2-hour STOCKER window costs 2.00 * 1800 = 3600 cents.

    PRD §3.8: "Its `cost_cents` is computed before any budget check: the duration in seconds divided by 3600 and rounded half-up to 2 decimal places gives the hours, and the hours multiplied by the role's hourly rate — 1700 cents for a `CASHIER`, 1800 cents for a `STOCKER`, 2400 cents for a `SHIFT_LEAD` — rounded half-up to whole cents gives the cost."

    Design: Corner/calculations/labor_window_cost_constants_applied
    """
    store = fixtures.create_store(api)
    window = validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(
                aisle_zone="Z1", role="STOCKER",
                starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z",
            ),
            make_store_manager_headers(store["id"]),
        ),
        201,
    )
    assert window["cost_cents"] == 3600, (
        f"2.00 hours at 1800 cents/hour = 3600, got {window['cost_cents']}"
    )


def test_labor_window_cost_varies_by_role(api):
    """The same 2-hour span costs 3400 for CASHIER and 4800 for SHIFT_LEAD.

    PRD §3.8: "Its `cost_cents` is computed before any budget check: the duration in seconds divided by 3600 and rounded half-up to 2 decimal places gives the hours, and the hours multiplied by the role's hourly rate — 1700 cents for a `CASHIER`, 1800 cents for a `STOCKER`, 2400 cents for a `SHIFT_LEAD` — rounded half-up to whole cents gives the cost."

    Design: Corner/calculations/labor_window_cost_constants_applied
    """
    store = fixtures.create_store(api)
    manager = make_store_manager_headers(store["id"])

    cashier = validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", role="CASHIER",
                                 starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            manager,
        ),
        201,
    )
    shift_lead = validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z2", role="SHIFT_LEAD",
                                 starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            manager,
        ),
        201,
    )
    assert cashier["cost_cents"] == 3400
    assert shift_lead["cost_cents"] == 4800


def test_cart_reconciliation_includes_every_event_type(api):
    """INSERT 10, RETURN 4, CORRAL_COLLECT 3, AUDIT_ADJUST -1 -> outstanding 2, liability 50.

    PRD §3.6: "The store's `coins_outstanding` — coins currently held by customers in carts — is derived by replaying the store's events in `created_at` ascending order (timestamps carry three fractional digits, and `id` is never used for ordering): an `INSERT` adds its `coin_count`, a `RETURN` and a `CORRAL_COLLECT` each subtract theirs, and an `AUDIT_ADJUST` adds its signed `coin_count`."
    PRD §3.6: "A reconciliation snapshot for a store reports `coins_inserted`, `coins_returned`, `coins_collected`, `coins_adjusted`, `coins_outstanding`, and `coin_liability_cents`, and events may be listed chronologically with an optional `event_type` filter."

    Design: Corner/calculations/cart_reconciliation_input_set_all_events
    """
    store = fixtures.create_store(api)
    manager = make_store_manager_headers(store["id"])

    validate_success(api.create_cart_coin_event(store["id"], cart_coin_event_payload("INSERT", 10), manager), 201)
    validate_success(api.create_cart_coin_event(store["id"], cart_coin_event_payload("RETURN", 4), manager), 201)
    validate_success(api.create_cart_coin_event(store["id"], cart_coin_event_payload("CORRAL_COLLECT", 3), manager), 201)
    validate_success(api.create_cart_coin_event(store["id"], cart_coin_event_payload("AUDIT_ADJUST", -1), manager), 201)

    snapshot = validate_success(api.get_cart_reconciliation(store["id"], manager))
    assert snapshot["coins_inserted"] == 10
    assert snapshot["coins_returned"] == 4
    assert snapshot["coins_collected"] == 3
    assert snapshot["coins_adjusted"] == -1
    assert snapshot["coins_outstanding"] == 2, "10 - 4 - 3 - 1 = 2"
    assert snapshot["coin_liability_cents"] == 50, "2 coins at 25 cents each"


def test_scan_rate_rounded_half_up_to_two_decimals(api):
    """500 items over 1799 seconds rounds to exactly 1000.56.

    PRD §3.7: "Closing a shift — a `StoreManager` action restricted to the manager's own store — moves it `OPEN → CLOSED`, stamps `closed_at` from the logical clock, and computes the final variant exactly once: the count of scanned items minus 2 per void, multiplied by 3600 and divided by the shift's full duration in seconds (again with a denominator of at least 1), rounded half-up to 2 decimal places, stored as `final_scan_rate`."

    Design: Corner/calculations/scan_rate_precision_two_decimals
    """
    world = fixtures.store_with_cashier(api)
    store, cashier = world["store"], world["cashier"]
    shift = fixtures.open_shift(api, store, cashier, opened_at="2026-09-01T08:00:00Z")

    validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=500), world["cashier_headers"])
    )
    fixtures.set_clock(api, "2026-09-01T08:29:59Z")

    closed = validate_success(
        api.close_shift(shift["id"], make_store_manager_headers(store["id"]))
    )
    assert closed["final_scan_rate"] == 1000.56, (
        f"500*3600/1799 rounds half-up to 1000.56, got {closed['final_scan_rate']}"
    )
    assert closed["compliance"] == "COMPLIANT"
