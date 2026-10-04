"""Composite setup helpers.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before each test, so state never carries
over). Setup calls use get_success_data so failures surface as clear setup
errors rather than assertion failures.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_INITIAL
from .factories import (
    create_container_payload,
    create_coupon_payload,
    create_customer_payload,
    create_item_payload,
    create_membership_payload,
    create_purchase_order_payload,
    create_recall_payload,
    create_sale_line_payload,
    create_sale_payload,
    create_store_payload,
    create_warranty_claim_payload,
    create_warranty_line_payload,
)
from .test_users import TEST_USERS, make_customer_headers

OPS = TEST_USERS["ops_admin_headers"]
PM = TEST_USERS["purchasing_manager_headers"]
LC = TEST_USERS["logistics_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]
IP = TEST_USERS["inventory_planner_headers"]
MM = TEST_USERS["marketing_manager_headers"]
SC = TEST_USERS["store_clerk_headers"]
WA = TEST_USERS["warranty_adjuster_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity state progression
# ---------------------------------------------------------------------------

def create_active_item(**overrides) -> dict:
    """Create an item and activate it. Returns the item."""
    item = get_success_data(api_client.create_item(create_item_payload(**overrides), PM))
    item = get_success_data(api_client.activate_item(item["id"], PM))
    return item


def make_store(assortment_item_ids: Optional[List[str]] = None, **overrides) -> dict:
    store = get_success_data(api_client.create_store(
        create_store_payload(assortment_item_ids, **overrides), OPS))
    return store


def make_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SC))


def enroll_member(customer_id: str, tier: str = "CLUB") -> dict:
    return get_success_data(api_client.create_membership(
        customer_id, create_membership_payload(tier), SC))


def make_coupon(active: bool = True, **overrides) -> dict:
    coupon = get_success_data(api_client.create_coupon(create_coupon_payload(**overrides), MM))
    if active:
        coupon = get_success_data(api_client.activate_coupon(coupon["id"], MM))
    return coupon


def set_clock(to_iso8601: str):
    get_success_data(api_client.set_clock(to_iso8601, OPS))


# ---------------------------------------------------------------------------
# Tier 2: import-pipeline hierarchy (item -> PO -> container)
# ---------------------------------------------------------------------------

def make_issued_po(item_id: str, quantity: int = 10, unit_cost_cents: int = 500,
                   estimated_duty_cents: int = 0, estimated_freight_cents: int = 0,
                   lines: Optional[List[dict]] = None) -> dict:
    """Create a PO and issue it. Returns the issued PO."""
    payload = create_purchase_order_payload(
        item_id, quantity, unit_cost_cents,
        estimated_duty_cents=estimated_duty_cents,
        estimated_freight_cents=estimated_freight_cents,
    )
    if lines is not None:
        payload["lines"] = lines
    po = get_success_data(api_client.create_purchase_order(payload, PM))
    return get_success_data(api_client.issue_purchase_order(po["id"], PM))


def make_container(po_id: str, item_id: str, quantity: int = 10,
                   lines: Optional[List[dict]] = None) -> dict:
    payload = create_container_payload(po_id, item_id, quantity)
    if lines is not None:
        payload["lines"] = lines
    return get_success_data(api_client.create_container(payload, LC))


def advance_container_to_at_port(container_id: str) -> dict:
    """BOOKED -> DEPARTED -> AT_PORT."""
    get_success_data(api_client.depart_container(container_id, LC))
    return get_success_data(api_client.arrive_port_container(container_id, LC))


def advance_container_to_cleared(container_id: str) -> dict:
    """BOOKED -> DEPARTED -> AT_PORT -> CLEARED."""
    advance_container_to_at_port(container_id)
    return get_success_data(api_client.clear_customs_container(container_id, CO))


def receive_container(container_id: str, payload: Optional[Dict] = None) -> dict:
    return get_success_data(api_client.receive_container(container_id, payload, LC))


# ---------------------------------------------------------------------------
# Tier 3: allocations
# ---------------------------------------------------------------------------

def make_planned_allocation(store_id: str, container_id: str, item_id: str,
                            quantity: int) -> dict:
    return get_success_data(api_client.create_store_allocation(
        store_id, {"container_id": container_id, "item_id": item_id,
                   "quantity": quantity}, IP))


def commit_allocation(allocation_id: str, expected_container_version: int) -> dict:
    return get_success_data(api_client.commit_allocation(
        allocation_id, expected_container_version, IP))


# ---------------------------------------------------------------------------
# Tier 4: point-of-sale flows
# ---------------------------------------------------------------------------

def make_open_sale(store_id: str, customer_id: str) -> dict:
    return get_success_data(api_client.create_sale(
        create_sale_payload(store_id, customer_id), SC))


def add_line(sale_id: str, item_id: str, quantity: int = 1, **overrides) -> dict:
    return get_success_data(api_client.add_sale_line(
        sale_id, create_sale_line_payload(item_id, quantity, **overrides), SC))


def add_warranty_line(sale_id: str, item_id: str, covered_item_id: str,
                      warranty_price_cents: int = 500, quantity: int = 1) -> dict:
    return get_success_data(api_client.add_sale_line(
        sale_id,
        create_warranty_line_payload(item_id, covered_item_id,
                                     warranty_price_cents, quantity),
        SC))


def make_completed_sale(store_id: str, customer_id: str, item_id: str,
                        quantity: int = 1, coupon_code: Optional[str] = None,
                        complete_payload: Optional[Dict] = None) -> dict:
    """Open a sale, add one merchandise line, optionally apply a coupon, complete."""
    sale = make_open_sale(store_id, customer_id)
    add_line(sale["id"], item_id, quantity)
    if coupon_code:
        get_success_data(api_client.apply_coupon(sale["id"], coupon_code, SC))
    return get_success_data(api_client.complete_sale(sale["id"], complete_payload, SC))


def make_completed_warranty_sale(store_id: str, customer_id: str, item_id: str,
                                 warranty_price_cents: int = 500,
                                 merchandise_qty: int = 1,
                                 warranty_qty: int = 1):
    """Completed sale with a merchandise line and a warranty line covering it.
    Returns (sale, merchandise_line, warranty_line)."""
    sale = make_open_sale(store_id, customer_id)
    merch = add_line(sale["id"], item_id, merchandise_qty)
    wline = add_warranty_line(sale["id"], item_id, item_id,
                              warranty_price_cents, warranty_qty)
    sale = get_success_data(api_client.complete_sale(sale["id"], {}, SC))
    return sale, merch, wline


def make_claim(warranty_line_id: str, claim_amount_cents: int = 500,
               reason: str = "defect") -> dict:
    return get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(warranty_line_id, claim_amount_cents,
                                      reason=reason), SC))


def make_denied_claim(warranty_line_id: str, claim_amount_cents: int = 500) -> dict:
    """File a claim and drive it to DENIED."""
    claim = make_claim(warranty_line_id, claim_amount_cents)
    get_success_data(api_client.start_review_claim(claim["id"], WA))
    return get_success_data(api_client.deny_claim(claim["id"], WA))


# ---------------------------------------------------------------------------
# Tier 5: recalls
# ---------------------------------------------------------------------------

def make_active_recall(item_id: str, severity: str = "NOTICE") -> dict:
    recall = get_success_data(api_client.create_recall(
        create_recall_payload(item_id, severity), CO))
    return get_success_data(api_client.activate_recall(recall["id"], CO))
