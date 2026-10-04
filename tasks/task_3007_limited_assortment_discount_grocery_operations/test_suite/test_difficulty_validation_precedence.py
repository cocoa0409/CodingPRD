"""Validation precedence pairs: state beats fiscal, temporal beats structural."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import (
    PROCUREMENT_LEAD_HEADERS,
    fixtures,
    make_store_manager_headers,
    make_supplier_rep_headers,
)
from test_helpers.factories import bid_payload, labor_window_payload


def test_bid_on_draft_tender_reports_state_before_ceiling(api):
    """A bid on a DRAFT tender above the ceiling fails ERR_TENDER_NOT_OPEN, not the fiscal error.

    PRD §2.8: "5. State admissibility: the target resource is in a state that permits the operation (`ERR_INVALID_STATE`, and its state-specific counterparts such as `ERR_TENDER_NOT_OPEN` and `ERR_SHIFT_NOT_OPEN`)."
    PRD §2.8: "9. Fiscal rules, always last (`ERR_BID_CEILING_EXCEEDED`, `ERR_LABOR_BUDGET_EXCEEDED`, `ERR_COIN_BALANCE_NEGATIVE`, `ERR_ALLOCATION_EXHAUSTED`)."

    Design: Difficulty/priority_pair_validation_conflict/tender_bid_state_before_fiscal
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    # Tender left in DRAFT: never opened.
    tender = validate_success(
        api.create_tender(
            {"product_id": product["id"], "bid_ceiling_cents": 1000}, PROCUREMENT_LEAD_HEADERS
        ),
        201,
    )

    response = api.create_bid(
        tender["id"],
        bid_payload(supplier["id"], 1500),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, "ERR_TENDER_NOT_OPEN", 409)

    bids = validate_paginated(
        api.list_tender_bids(tender["id"], PROCUREMENT_LEAD_HEADERS)
    )[0]
    assert bids == [], "no bid row may be created by the rejected submission"


def test_bid_above_ceiling_on_open_tender_reports_fiscal(api):
    """When state passes, the ceiling rule surfaces ERR_BID_CEILING_EXCEEDED.

    PRD §3.4: "A bid on a tender that is not `OPEN` is rejected with `ERR_TENDER_NOT_OPEN`, and an offer above the tender's `bid_ceiling_cents` is rejected with `ERR_BID_CEILING_EXCEEDED` at submission time."

    Design: Difficulty/priority_pair_validation_conflict/tender_bid_state_before_fiscal
    """
    category = fixtures.create_category(api)
    supplier = fixtures.create_supplier(api)
    product = fixtures.create_product(api, category["id"])
    tender = fixtures.create_open_tender(api, product["id"], bid_ceiling_cents=1000)

    response = api.create_bid(
        tender["id"],
        bid_payload(supplier["id"], 1001),
        make_supplier_rep_headers(supplier["id"]),
    )
    validate_error(response, "ERR_BID_CEILING_EXCEEDED", 422)


def _book(api, store, zone, day, start, end, role="STOCKER"):
    payload = labor_window_payload(
        aisle_zone=zone, role=role,
        starts_at=f"2026-09-{day:02d}T{start}:00Z",
        ends_at=f"2026-09-{day:02d}T{end}:00Z",
    )
    return api.create_labor_window(store["id"], payload, make_store_manager_headers(store["id"]))


def test_seventh_window_overlapping_reports_temporal_before_limit(api):
    """A 7th window that also overlaps fails ERR_WINDOW_OVERLAP, not ERR_WINDOW_LIMIT_EXCEEDED.

    PRD §2.8: "7. Temporal and window rules (`ERR_WINDOW_OVERLAP`, `ERR_SALE_WINDOW_CONFLICT`, `ERR_CLEARANCE_GAP_VIOLATION`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SALE_WINDOW_INACTIVE`)."
    PRD §2.8: "8. Structural business constraints (`ERR_SKU_CAP_EXCEEDED`, `ERR_SKU_CAP_BELOW_CURRENT`, `ERR_DUPLICATE_SKU`, `ERR_BARCODE_COUNT_INVALID`, `ERR_SHELF_READY_REQUIRED`, `ERR_BID_DUPLICATE`, `ERR_DUAL_SOURCE_REQUIRED`, `ERR_SUPPLIER_SUSPENDED`, `ERR_ALLOCATION_INCOMPLETE`, `ERR_PRODUCT_NOT_ACTIVE`, `ERR_FINDS_NO_REPLENISHMENT`, `ERR_WINDOW_LIMIT_EXCEEDED`, `ERR_CASHIER_ROLE_REQUIRED`)."
    PRD §2.8: "A structural violation therefore surfaces before a budget violation on the same request, and a blind-panel violation before a window conflict."

    Design: Difficulty/priority_pair_validation_conflict/labor_window_temporal_before_constraint
    """
    store = fixtures.create_store(api, weekly_labor_budget_cents=100000)
    # Six non-overlapping windows in the ISO week of 2026-09-07 (Mon .. Sun).
    validate_success(_book(api, store, "Z1", 7, "06:00", "08:00"), 201)
    validate_success(_book(api, store, "Z1", 7, "08:00", "10:00"), 201)
    validate_success(_book(api, store, "Z2", 7, "06:00", "08:00"), 201)
    validate_success(_book(api, store, "Z2", 8, "06:00", "08:00", role="CASHIER"), 201)
    validate_success(_book(api, store, "Z3", 9, "06:00", "08:00", role="CASHIER"), 201)
    validate_success(_book(api, store, "Z3", 10, "06:00", "07:00", role="SHIFT_LEAD"), 201)

    # Seventh window, overlapping the first Z1 window: temporal fires before the limit.
    response = _book(api, store, "Z1", 7, "07:00", "09:00")
    validate_error(response, "ERR_WINDOW_OVERLAP", 409)

    windows = validate_paginated(
        api.list_labor_windows(store["id"], make_store_manager_headers(store["id"]))
    )[0]
    assert len(windows) == 6, f"the rejected seventh window must not persist, got {len(windows)}"


def test_seventh_window_non_overlapping_reports_limit(api):
    """When temporal passes, the seventh same-week window fails ERR_WINDOW_LIMIT_EXCEEDED.

    PRD §3.8: "A store may hold at most 6 non-cancelled windows whose `starts_at` falls in the same ISO week, counted from Monday 00:00 UTC up to but not including the next Monday 00:00 UTC; a seventh is rejected with `ERR_WINDOW_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/labor_window_temporal_before_constraint
    """
    store = fixtures.create_store(api, weekly_labor_budget_cents=1000000)
    validate_success(_book(api, store, "Z1", 7, "06:00", "07:00"), 201)
    validate_success(_book(api, store, "Z1", 7, "07:00", "08:00"), 201)
    validate_success(_book(api, store, "Z2", 7, "06:00", "07:00"), 201)
    validate_success(_book(api, store, "Z2", 8, "06:00", "07:00", role="CASHIER"), 201)
    validate_success(_book(api, store, "Z3", 9, "06:00", "07:00", role="CASHIER"), 201)
    validate_success(_book(api, store, "Z3", 10, "06:00", "07:00", role="SHIFT_LEAD"), 201)

    response = _book(api, store, "Z4", 11, "06:00", "07:00")
    validate_error(response, "ERR_WINDOW_LIMIT_EXCEEDED", 409)
