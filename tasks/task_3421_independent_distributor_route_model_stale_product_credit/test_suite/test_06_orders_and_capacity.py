"""Order confirmation, capacity accounting, OCC on the production day, the
close gate, and order-list pagination.

Covers PRD §3.3 (confirm/cancel capacity semantics, close gate), §2.7 (OCC on
production-day version), and §2.3 (pagination meta).
Instances:
Difficulty/boundary_precision_check/confirm_capacity_exact_fit_allowed_one_over_rejected,
Difficulty/compensating_invariant/confirm_cancel_capacity_conservation,
Corner/cross_cutting_complexity_layers/occ_confirm_stale_version_412,
Corner/state_machines/cancel_submitted_order_releases_nothing,
Corner/endpoints/close_future_production_day_rejected,
Corner/cross_cutting_complexity_layers/orders_list_pagination_filter_interaction.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    cancel_order,
    confirm_order,
    confirm_order_payload,
    create_bakery,
    create_order,
    create_production_day,
    find_production_day,
    list_orders,
    make_distributor_headers,
    order_line,
    reset_clock_to_default,
    setup_active_cash_agreement,
    submit_order,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["company_admin_headers"]
_ROUTE_OPS = TEST_USERS["route_ops_manager_headers"]


def _find_order(distributor_id: str, order_id: str) -> dict:
    matches = [o for o in list_orders(distributor_id) if o["id"] == order_id]
    assert len(matches) == 1, f"order {order_id} not found"
    return matches[0]


def test_confirm_exact_capacity_fit_allowed(api):
    """PRD §3.3: "the day must have room — the day's `allocated_units` plus the
    order's `units_total` may not exceed `capacity_units`, though landing
    exactly at capacity is allowed (`ERR_CAPACITY_EXCEEDED` otherwise)."
    PRD §3.3: "On success the order becomes `CONFIRMED`, the day's
    `allocated_units` grows by the order's `units_total`, and the day's
    `version` advances by one."

    Design: Difficulty/boundary_precision_check/confirm_capacity_exact_fit_allowed_one_over_rejected
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    order_a = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 60)])
    )
    order_b = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("BUN-12", 40)])
    )
    confirmed_a = confirm_order(order_a, day)
    assert confirmed_a["status"] == "CONFIRMED"
    day_mid = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_mid["allocated_units"] == 60
    confirmed_b = confirm_order(order_b, day_mid)
    assert confirmed_b["status"] == "CONFIRMED"
    day_end = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_end["allocated_units"] == 100, "exact fit: 60 + 40 <= 100 allowed"
    assert day_end["capacity_units"] == 100


def test_confirm_one_over_capacity_rejected(api):
    """PRD §3.3: "the day must have room — the day's `allocated_units` plus the
    order's `units_total` may not exceed `capacity_units`, though landing
    exactly at capacity is allowed (`ERR_CAPACITY_EXCEEDED` otherwise)."

    Design: Difficulty/boundary_precision_check/confirm_capacity_exact_fit_allowed_one_over_rejected
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    order_a = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 60)])
    )
    order_b = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("BUN-12", 40)])
    )
    order_c = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 1)])
    )
    confirm_order(order_a, day)
    day_v2 = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    confirm_order(order_b, day_v2)
    day_v3 = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_v3["allocated_units"] == 100

    resp = api_client.confirm_order(
        order_c["id"],
        confirm_order_payload(day_v3["version"]),
        _ROUTE_OPS,
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)
    current = _find_order(ctx["distributor"]["id"], order_c["id"])
    assert current["status"] == "SUBMITTED", "failed confirm leaves the order"
    assert find_production_day(ctx["bakery"]["id"], "2026-09-04")[
        "allocated_units"
    ] == 100, "100 + 1 > 100 rejected without moving the reservation"


def test_confirm_reserves_capacity(api):
    """PRD §3.3: "On success the order becomes `CONFIRMED`, the day's
    `allocated_units` grows by the order's `units_total`, and the day's
    `version` advances by one."

    Design: Difficulty/compensating_invariant/confirm_cancel_capacity_conservation
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day["allocated_units"] == 0
    assert day["capacity_units"] == 100
    assert day["allocated_units"] + (
        day["capacity_units"] - day["allocated_units"]
    ) == 100

    order = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 25)])
    )
    confirm_order(order, day)
    day_mid = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_mid["allocated_units"] == 25
    assert day_mid["version"] == 2
    assert day_mid["allocated_units"] + (
        day_mid["capacity_units"] - day_mid["allocated_units"]
    ) == 100, "reserved plus free capacity is conserved at capacity_units"


def test_cancel_releases_reserved_capacity(api):
    """PRD §3.3: "A distributor may cancel an order while it is `SUBMITTED` or
    `CONFIRMED`; the order lands in `CANCELLED` with `cancelled_reason`
    `DISTRIBUTOR_CANCELLED`, and cancelling a confirmed order releases its
    reservation — the production day's `allocated_units` drops by the order's
    `units_total` and the day's `version` advances by one."

    Design: Difficulty/compensating_invariant/confirm_cancel_capacity_conservation
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    order = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 25)])
    )
    confirm_order(order, day)
    day_mid = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_mid["allocated_units"] == 25
    assert day_mid["version"] == 2

    cancelled = cancel_order(order)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "DISTRIBUTOR_CANCELLED"
    day_end = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_end["allocated_units"] == 0, "compensating cancel releases 25"
    assert day_end["version"] == 3
    assert day_end["allocated_units"] + (
        day_end["capacity_units"] - day_end["allocated_units"]
    ) == 100


def test_occ_confirm_stale_version_412(api):
    """PRD §2.7: "Confirming a submitted order requires the request to carry
    `expected_production_day_version`, the client's last observed `version` of
    the relevant production day. Every successful confirmation or cancellation
    moves the day's `allocated_units` and advances its `version`, so a
    confirmation carrying a value that no longer equals the day's current
    `version` is acting on a stale capacity view and is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_confirm_stale_version_412
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    stale_version = day["version"]
    order_a = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 25)])
    )
    order_b = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("BUN-12", 10)])
    )
    confirm_order(order_a, day)
    day_now = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_now["allocated_units"] == 25
    assert day_now["version"] == 2

    resp = api_client.confirm_order(
        order_b["id"], confirm_order_payload(stale_version), _ROUTE_OPS
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    assert _find_order(ctx["distributor"]["id"], order_b["id"])["status"] == (
        "SUBMITTED"
    )
    assert find_production_day(ctx["bakery"]["id"], "2026-09-04")[
        "allocated_units"
    ] == 25


def test_cancel_submitted_order_releases_nothing(api):
    """PRD §3.3: "A distributor may cancel an order while it is `SUBMITTED` or
    `CONFIRMED`; the order lands in `CANCELLED` with `cancelled_reason`
    `DISTRIBUTOR_CANCELLED`, and cancelling a confirmed order releases its
    reservation — the production day's `allocated_units` drops by the order's
    `units_total` and the day's `version` advances by one."
    PRD §3.3: "`CANCELLED` and `RECONCILED` are the order's terminal states."

    Design: Corner/state_machines/cancel_submitted_order_releases_nothing
    """
    ctx = setup_active_cash_agreement()
    day = create_production_day(ctx["bakery"]["id"], "2026-09-04")
    order = submit_order(
        create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 5)])
    )
    cancelled = cancel_order(order)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "DISTRIBUTOR_CANCELLED"
    day_now = find_production_day(ctx["bakery"]["id"], "2026-09-04")
    assert day_now["allocated_units"] == 0, (
        "the release side effect is conditional on CONFIRMED"
    )
    assert day_now["version"] == 1

    resp = api_client.cancel_order(
        order["id"], make_distributor_headers(ctx["distributor"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_close_future_production_day_rejected(api):
    """PRD §3.3: "Once the logical date has reached the production day's
    `date`, a `CompanyAdmin` closes it (`PLANNING → CLOSED`); attempting to
    close a future production date, or to close a day that is already closed,
    is rejected with `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/endpoints/close_future_production_day_rejected
    """
    reset_clock_to_default()
    bakery = create_bakery()
    day = create_production_day(bakery["id"], "2026-09-04")
    resp = api_client.close_production_day(day["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    day_now = find_production_day(bakery["id"], "2026-09-04")
    assert day_now["status"] == "PLANNING"
    assert day_now["version"] == 1


def test_orders_list_pagination_filter_interaction(api):
    """PRD §2.3: "`limit` specifies the maximum number of items to return; it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    specifies the number of items to skip and defaults to 0."
    PRD §2.3: "List responses include the following fields in the `meta` object
    of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/cross_cutting_complexity_layers/orders_list_pagination_filter_interaction
    """
    ctx = setup_active_cash_agreement()
    dist_id = ctx["distributor"]["id"]
    headers = make_distributor_headers(dist_id)
    create_order(ctx["distributor"], "2026-09-04", [order_line("WHT-24", 1)])
    create_order(ctx["distributor"], "2026-09-05", [order_line("WHT-24", 2)])
    order3 = create_order(
        ctx["distributor"], "2026-09-08", [order_line("WHT-24", 3)]
    )
    submit_order(order3)

    rows, meta = validate_paginated(
        api_client.list_orders(dist_id, headers, params={"limit": 2, "offset": 0})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api_client.list_orders(dist_id, headers, params={"limit": 2, "offset": 2})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api_client.list_orders(dist_id, headers, params={"status": "DRAFT"})
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2, "total_count counts the filtered set"
    assert meta["has_more"] is False

    rows, meta = validate_paginated(api_client.list_orders(dist_id, headers))
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
