"""Composite setup helpers.

The harness restarts the server before every test, so each test builds its own
world through the public API. These helpers encapsulate the recurring
multi-step preambles — category/supplier creation, full tender award chains,
Finds buys carried to ON_SALE, register shifts on a set clock — so tests can
focus on assertions.

Every step uses ``get_success_data`` so a setup failure surfaces as a clear
"Setup failed" error rather than a confusing assertion failure. Entity-backed
roles are always built with the real entity id of the entity they own.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    CATEGORY_MANAGER_HEADERS,
    CUSTOMER_SERVICE_HEADERS,
    OPERATIONS_ADMIN_HEADERS,
    PROCUREMENT_LEAD_HEADERS,
    QA_LEAD_HEADERS,
    make_cashier_headers,
    make_store_manager_headers,
    make_supplier_rep_headers,
)


def _ok(response, step: str):
    """Unwrap a setup call, failing loudly with the step name on any error."""
    if response.status_code >= 400:
        raise AssertionError(f"Setup failed at {step}: {response.status_code} {response.text}")
    return get_success_data(response)


# ── Basic resources ──────────────────────────────────────────────────────


def create_category(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return _ok(api.create_category(factories.category_payload(**overrides), CATEGORY_MANAGER_HEADERS), "create_category")


def create_supplier(api: ApiClient, name: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    return _ok(api.create_supplier(factories.supplier_payload(name=name, **overrides), PROCUREMENT_LEAD_HEADERS), "create_supplier")


def create_product(api: ApiClient, category_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(api.create_product(factories.product_payload(category_id, **overrides), CATEGORY_MANAGER_HEADERS), "create_product")


def create_store(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return _ok(api.create_store(factories.store_payload(**overrides), OPERATIONS_ADMIN_HEADERS), "create_store")


def create_employee(api: ApiClient, store: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.create_employee(store["id"], factories.employee_payload(**overrides), make_store_manager_headers(store["id"])),
        "create_employee",
    )


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    return _ok(api.set_clock({"to_iso8601": to_iso8601}, OPERATIONS_ADMIN_HEADERS), "set_clock")


# ── Tender lifecycle ─────────────────────────────────────────────────────


def create_open_tender(api: ApiClient, product_id: str, bid_ceiling_cents: int = 1000) -> Dict[str, Any]:
    """Create a tender and open it for bids."""
    tender = _ok(
        api.create_tender(factories.tender_payload(product_id, bid_ceiling_cents), PROCUREMENT_LEAD_HEADERS),
        "create_tender",
    )
    _ok(api.open_tender(tender["id"], PROCUREMENT_LEAD_HEADERS), "open_tender")
    return tender


def submit_bid(api: ApiClient, tender_id: str, supplier: Dict[str, Any], unit_cost_cents: int) -> Dict[str, Any]:
    """A supplier representative bids as their own supplier."""
    return _ok(
        api.create_bid(
            tender_id,
            factories.bid_payload(supplier["id"], unit_cost_cents),
            make_supplier_rep_headers(supplier["id"]),
        ),
        "create_bid",
    )


def score_bid_panel(api: ApiClient, bid: Dict[str, Any], score: int, sample_code: Optional[str] = None) -> Dict[str, Any]:
    """Schedule a blind panel for a bid and record its score."""
    panel = _ok(
        api.create_panel(bid["id"], factories.panel_payload(sample_code), QA_LEAD_HEADERS),
        "create_panel",
    )
    _ok(api.score_panel(panel["id"], factories.panel_score_payload(score), QA_LEAD_HEADERS), "score_panel")
    return panel


def tender_in_evaluating(
    api: ApiClient,
    product_id: str,
    bid_ceiling_cents: int = 1000,
    bids: Optional[List[Tuple[Dict[str, Any], int, int]]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build a CLOSED->EVALUATING tender.

    ``bids`` is a list of ``(supplier, unit_cost_cents, panel_score)`` triples.
    Returns (tender, bids, panels) after evaluation.
    """
    if bids is None:
        bids = []
    tender = create_open_tender(api, product_id, bid_ceiling_cents)
    created_bids: List[Dict[str, Any]] = []
    panels: List[Dict[str, Any]] = []
    for supplier, cost, panel_score in bids:
        bid = submit_bid(api, tender["id"], supplier, cost)
        created_bids.append(bid)
        panels.append(score_bid_panel(api, bid, panel_score))
    _ok(api.close_tender(tender["id"], PROCUREMENT_LEAD_HEADERS), "close_tender")
    _ok(api.evaluate_tender(tender["id"], PROCUREMENT_LEAD_HEADERS), "evaluate_tender")
    return tender, created_bids, panels


def award_tender(api: ApiClient, tender_id: str, primary_bid_id: str, secondary_bid_id: str) -> Dict[str, Any]:
    return _ok(
        api.award_tender(
            tender_id,
            {"primary_bid_id": primary_bid_id, "secondary_bid_id": secondary_bid_id},
            PROCUREMENT_LEAD_HEADERS,
        ),
        "award_tender",
    )


def award_product_with_two_suppliers(
    api: ApiClient,
    category_id: str,
    product_overrides: Optional[Dict[str, Any]] = None,
    bid_ceiling_cents: int = 1000,
    primary_cost: int = 700,
    secondary_cost: int = 800,
    primary_panel_score: int = 80,
    secondary_panel_score: int = 70,
) -> Dict[str, Any]:
    """Full happy-path chain: product + tender + two bids + panels + award.

    Returns a dict with the activated product, its category, the two suppliers,
    the tender, and the two winning bids.
    """
    sup_a = create_supplier(api)
    sup_b = create_supplier(api)
    product = create_product(api, category_id, **(product_overrides or {}))
    tender, bids, _panels = tender_in_evaluating(
        api,
        product["id"],
        bid_ceiling_cents=bid_ceiling_cents,
        bids=[(sup_a, primary_cost, primary_panel_score), (sup_b, secondary_cost, secondary_panel_score)],
    )
    award_tender(api, tender["id"], bids[0]["id"], bids[1]["id"])
    activated = _ok(api.get_product(product["id"], CATEGORY_MANAGER_HEADERS), "get_product")
    return {
        "product": activated,
        "supplier_primary": sup_a,
        "supplier_secondary": sup_b,
        "tender": tender,
        "bid_primary": bids[0],
        "bid_secondary": bids[1],
    }


def active_finds_product(api: ApiClient, category: Dict[str, Any], **product_overrides: Any) -> Dict[str, Any]:
    """Create a FINDS product and activate it through a full tender award."""
    overrides: Dict[str, Any] = {"kind": "FINDS", "shelf_ready_packaging": True, "barcode_count": 3, "price_cents": 199}
    overrides.update(product_overrides)
    result = award_product_with_two_suppliers(api, category["id"], product_overrides=overrides)
    return result["product"]


# ── Finds buys ───────────────────────────────────────────────────────────


def create_finds_buy(api: ApiClient, product_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(api.create_finds_buy(factories.finds_buy_payload(product_id, **overrides), CATEGORY_MANAGER_HEADERS), "create_finds_buy")


def plan_allocations(api: ApiClient, buy: Dict[str, Any]) -> Dict[str, Any]:
    """Run the allocation waterfall against the buy's current version."""
    return _ok(
        api.plan_allocations(
            buy["id"], {"expected_finds_buy_version": buy["version"]}, CATEGORY_MANAGER_HEADERS
        ),
        "plan_allocations",
    )


def buy_allocations(api: ApiClient, buy_id: str) -> List[Dict[str, Any]]:
    data = _ok(api.list_buy_allocations(buy_id, CATEGORY_MANAGER_HEADERS), "list_buy_allocations")
    assert isinstance(data, list), "list_buy_allocations must return a data array"
    return data


def finds_buy_on_sale(
    api: ApiClient,
    product_id: str,
    total_quantity: int = 5,
    week_start_date: str = "2026-09-07",
    week_end_date: str = "2026-09-13",
) -> Dict[str, Any]:
    """Create a Finds buy, plan allocations, and activate it to ON_SALE.

    Returns a dict with the buy (refreshed) and its allocations.
    """
    buy = create_finds_buy(
        api, product_id,
        total_quantity=total_quantity,
        week_start_date=week_start_date,
        week_end_date=week_end_date,
    )
    buy = plan_allocations(api, buy)
    buy = _ok(api.activate_finds_buy(buy["id"], CATEGORY_MANAGER_HEADERS), "activate_finds_buy")
    return {"buy": buy, "allocations": buy_allocations(api, buy["id"])}


# ── Register shifts ──────────────────────────────────────────────────────


def store_with_cashier(api: ApiClient, store_overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A store plus one CASHIER employee. Returns both with ready headers."""
    store = create_store(api, **(store_overrides or {}))
    cashier = create_employee(api, store, role="CASHIER")
    return {
        "store": store,
        "cashier": cashier,
        "store_headers": make_store_manager_headers(store["id"]),
        "cashier_headers": make_cashier_headers(cashier["id"]),
    }


def open_shift(
    api: ApiClient,
    store: Dict[str, Any],
    cashier: Dict[str, Any],
    opened_at: str = "2026-09-01T08:00:00Z",
) -> Dict[str, Any]:
    """Set the logical clock and open a register shift for the cashier."""
    set_clock(api, opened_at)
    return _ok(
        api.create_register_shift(
            store["id"],
            factories.register_shift_payload(cashier["id"]),
            make_store_manager_headers(store["id"]),
        ),
        "create_register_shift",
    )


# ── Claims ───────────────────────────────────────────────────────────────


def claims_world(api: ApiClient, **store_overrides: Any) -> Dict[str, Any]:
    """Category + product (PROPOSED is fine for claims) + store."""
    category = create_category(api)
    product = create_product(api, category["id"])
    store = create_store(api, **store_overrides)
    return {"category": category, "product": product, "store": store}


def file_claim(api: ApiClient, product_id: str, store_id: str, **overrides: Any) -> Dict[str, Any]:
    return _ok(
        api.create_claim(factories.claim_payload(product_id, store_id, **overrides), CUSTOMER_SERVICE_HEADERS),
        "create_claim",
    )


def claim_under_review(api: ApiClient, product_id: str, store_id: str, **overrides: Any) -> Dict[str, Any]:
    claim = file_claim(api, product_id, store_id, **overrides)
    return _ok(api.review_claim(claim["id"], CUSTOMER_SERVICE_HEADERS), "review_claim")
