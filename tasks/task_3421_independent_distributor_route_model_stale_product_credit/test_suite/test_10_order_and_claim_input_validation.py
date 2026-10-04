"""Order and stale-claim input validation: 400 shape errors and the 422
referential/temporal rules, including their pipeline ordering.

Covers PRD §2.8 (pipeline order: referential ninth, temporal tenth), §3.3
(order sku check), and §3.6 (claim eligibility and timing windows).
Instances:
Difficulty/priority_pair_validation_conflict/claim_submit_sku_referential_beats_window_temporal,
Corner/entities/order_create_unknown_sku_returns_sku_unknown,
Corner/entities/claim_create_missing_items_returns_invalid_request,
Corner/validations/claim_qty_over_delivered_returns_qty_exceeded,
Corner/validations/claim_pulled_before_shelf_end_returns_not_stale_yet.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    claim_item,
    create_claim_payload,
    create_order_payload,
    list_orders,
    list_stale_claims,
    make_distributor_headers,
    order_line,
    set_clock,
    setup_active_cash_agreement,
    setup_delivered_order,
    validate_error,
    validate_success,
)


def test_claim_unknown_sku_beats_expired_window(api):
    """PRD §2.8: "Ninth, line- and item-level referential integrity
    (`ERR_SKU_UNKNOWN`, `ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE`). Tenth, temporal
    windows (`ERR_ORDER_LEAD_TIME`, `ERR_CLAIM_NOT_STALE_YET`,
    `ERR_CLAIM_WINDOW_EXPIRED`)."
    PRD §3.6: "The sku must exist in the agreement bakery's catalog and have
    been delivered to this distributor (`ERR_SKU_UNKNOWN`)."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_sku_referential_beats_window_temporal
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(ctx, "2026-09-04", [order_line("WHT-24", 10)])
    set_clock("2026-09-17T09:00:00Z")
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("XXX-99", "2026-09-04", 1, "2026-09-17")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    error = validate_error(resp, ApiErrorId.ERR_SKU_UNKNOWN)
    assert error["error_id"] != "ERR_CLAIM_WINDOW_EXPIRED", (
        "the pull date 2026-09-17 is past the 2026-09-16 window for a real "
        "sku, but the referential check (ninth) is ordered first"
    )
    assert list_stale_claims(ctx["distributor"]["id"]) == []


def test_claim_expired_window_rejected_for_known_sku(api):
    """PRD §3.6: "And the timing windows must hold: the `pull_date` must fall
    on or after the delivery date plus the sku's `shelf_life_days` — an earlier
    pull is not yet stale (`ERR_CLAIM_NOT_STALE_YET`) — while a `pull_date`
    later than the delivery date plus the shelf life plus seven days, or a
    claim submitted more than two days after the pull, is too late
    (`ERR_CLAIM_WINDOW_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/claim_submit_sku_referential_beats_window_temporal
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(ctx, "2026-09-04", [order_line("WHT-24", 10)])
    set_clock("2026-09-17T09:00:00Z")
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("WHT-24", "2026-09-04", 1, "2026-09-17")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_WINDOW_EXPIRED)
    assert list_stale_claims(ctx["distributor"]["id"]) == []


def test_order_create_unknown_sku_returns_sku_unknown(api):
    """PRD §3.3: "Every `sku` must exist in the catalog of the agreement's
    bakery, or creation fails with `ERR_SKU_UNKNOWN`."

    Design: Corner/entities/order_create_unknown_sku_returns_sku_unknown
    """
    ctx = setup_active_cash_agreement()
    resp = api_client.create_order(
        ctx["distributor"]["id"],
        create_order_payload("2026-09-04", [order_line("XXX-99", 1)]),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SKU_UNKNOWN)
    assert list_orders(ctx["distributor"]["id"]) == []


def test_claim_create_missing_items_returns_invalid_request(api):
    """PRD §3.6: "A distributor files a stale claim under its own id — recorded
    as the claim's `distributor_id` — as a non-empty `items` array, each item
    naming a `sku`, the `delivery_date` it arrived on, the `pulled_qty` removed
    from the shelf (at least 1), and the `pull_date` it was removed."
    PRD §2.8: "Sixth, request shape: required fields, enum membership, and
    ranges (`ERR_INVALID_REQUEST`, and `ERR_AUDIT_SCORE_RANGE` for audit scores
    outside the inclusive 0 to 100 range)."

    Design: Corner/entities/claim_create_missing_items_returns_invalid_request
    """
    ctx = setup_active_cash_agreement()
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        {},
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert list_stale_claims(ctx["distributor"]["id"]) == []


def test_claim_qty_over_delivered_returns_qty_exceeded(api):
    """PRD §3.6: "The claimed quantity may not exceed what was delivered to
    this distributor for that sku on that date — summed over the distributor's
    `DELIVERED` and `RECONCILED` orders — minus what has already been credited
    for the same sku and date on claims that are `APPROVED` or `CREDIT_ISSUED`
    (`ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE`)."

    Design: Corner/validations/claim_qty_over_delivered_returns_qty_exceeded
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(ctx, "2026-09-04", [order_line("WHT-24", 5)])
    set_clock("2026-09-10T09:00:00Z")
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("WHT-24", "2026-09-04", 6, "2026-09-10")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_QTY_EXCEEDS_ELIGIBLE)
    assert list_stale_claims(ctx["distributor"]["id"]) == []


def test_claim_pulled_before_shelf_end_returns_not_stale_yet(api):
    """PRD §3.6: "the `pull_date` must fall on or after the delivery date plus
    the sku's `shelf_life_days` — an earlier pull is not yet stale
    (`ERR_CLAIM_NOT_STALE_YET`)..."
    PRD §3.6: "For each item, the unit charge is the catalog `list_price_cents`
    multiplied by one minus the agreement's `discount_pct`, rounded half-up to
    whole cents; the eligible quantity is the lesser of the pulled quantity and
    the not-yet-credited delivered quantity for that sku and date; each item's
    base is the eligible quantity multiplied by the unit charge and by three
    quarters — a stale credit rate of 0.75 — rounded half-up to whole cents;
    and the provisional credit is the sum of the item bases."

    Design: Corner/validations/claim_pulled_before_shelf_end_returns_not_stale_yet
    """
    ctx = setup_active_cash_agreement()
    setup_delivered_order(ctx, "2026-09-04", [order_line("WHT-24", 5)])
    set_clock("2026-09-06T09:00:00Z")
    resp = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("WHT-24", "2026-09-04", 1, "2026-09-06")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_STALE_YET)

    set_clock("2026-09-09T09:00:00Z")
    resp_ok = api_client.create_stale_claim(
        ctx["distributor"]["id"],
        create_claim_payload(
            [claim_item("WHT-24", "2026-09-04", 1, "2026-09-09")]
        ),
        make_distributor_headers(ctx["distributor"]["id"]),
    )
    claim = validate_success(resp_ok, 201)
    assert claim["provisional_credit_cents"] == 192, (
        "boundary pull_date == delivery + shelf_life accepted; "
        "round_half_up(1 * 256 * 0.75)"
    )
