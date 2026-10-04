"""Composite helpers for payments, warranty, replenishment and launches."""
from prd_bench_local_runner.testing import get_success_data

from . import factories as F
from .api_client import api_client
from .fixtures import (
    CREDIT_OFFICER,
    MANAGER,
    PLATFORM_ADMIN,
    WARRANTY_ADMIN,
    add_inventory,
    create_order,
    create_product,
    set_clock,
)


# --- reads ------------------------------------------------------------------
def get_account(account_id):
    return get_success_data(api_client.get_credit_account(account_id, CREDIT_OFFICER))


def get_route(route_id, headers=None):
    return get_success_data(api_client.get_route(route_id, headers or MANAGER))


def get_technician(technician_id, headers=None):
    return get_success_data(api_client.get_technician(technician_id, headers or MANAGER))


def get_franchisee(franchisee_id, headers=None):
    return get_success_data(api_client.get_franchisee(franchisee_id, headers or MANAGER))


def get_shop(shop_id, headers=None):
    return get_success_data(api_client.get_shop(shop_id, headers or MANAGER))


def get_order(order_id, headers=None):
    return get_success_data(api_client.get_sales_order(order_id, headers or MANAGER))


def get_product_order(product_order_id, headers=None):
    return get_success_data(api_client.get_product_order(product_order_id, headers or MANAGER))


def list_positions(franchisee, route_id, product_id=None):
    params = {"route_id": route_id}
    if product_id:
        params["product_id"] = product_id
    body = get_success_data(api_client.list_inventory_positions(
        franchisee["owner_headers"], params))
    return body["data"] if isinstance(body, dict) else body


def position_for(franchisee, route_id, product_id):
    rows = list_positions(franchisee, route_id, product_id)
    assert rows, f"no inventory position for product {product_id} on route {route_id}"
    return rows[0]


# --- payments ---------------------------------------------------------------
def book_payment(franchisee, account, expected_week_start, amount_cents=20_000,
                 collection_source="TRUCK_COLLECTION"):
    return get_success_data(api_client.book_payment(
        account["id"], F.payment_payload(expected_week_start, amount_cents=amount_cents,
                                         collection_source=collection_source),
        franchisee["rep_headers"]))


def collect_payment(franchisee, account, payment):
    return api_client.advance_payment(account["id"], payment["id"],
                                      {"action": "COLLECT"}, franchisee["rep_headers"])


def miss_payment(account, payment):
    return api_client.advance_payment(account["id"], payment["id"],
                                      {"action": "MISS"}, MANAGER)


def cancel_payment(account, payment):
    return api_client.advance_payment(account["id"], payment["id"],
                                      {"action": "CANCEL"}, MANAGER)


def reverse_payment(account, payment):
    return api_client.advance_payment(account["id"], payment["id"],
                                      {"action": "REVERSE"}, CREDIT_OFFICER)


def list_warranty_claims(franchisee, params=None):
    body = get_success_data(api_client.list_warranty_claims(
        franchisee["rep_headers"], params))
    return body["data"] if isinstance(body, dict) else body


def list_pledges(franchisee, params=None):
    body = get_success_data(api_client.list_pledges(franchisee["owner_headers"], params))
    return body["data"] if isinstance(body, dict) else body


def list_product_orders(franchisee, params=None):
    body = get_success_data(api_client.list_product_orders(
        franchisee["owner_headers"], params))
    return body["data"] if isinstance(body, dict) else body


def list_credit_accounts(params=None):
    body = get_success_data(api_client.list_credit_accounts(CREDIT_OFFICER, params))
    return body["data"] if isinstance(body, dict) else body


def list_charges(account_id):
    body = get_success_data(api_client.list_finance_charges(account_id, CREDIT_OFFICER))
    return body["data"] if isinstance(body, dict) else body


# --- warranty ---------------------------------------------------------------
def file_claim(franchisee, order, idempotency_key, line_index=0, claim_kind="CLAIM",
               apply_to_account_id=None):
    payload = F.warranty_claim_payload(idempotency_key, line_index=line_index,
                                       claim_kind=claim_kind)
    if apply_to_account_id:
        payload["apply_to_account_id"] = apply_to_account_id
    return api_client.file_warranty_claim(order["id"], payload, franchisee["rep_headers"])


def advance_claim(franchisee, order, claim, action, headers=None):
    if headers is None:
        headers = (WARRANTY_ADMIN if action in ("APPROVE", "REJECT", "REOPEN")
                   else franchisee["rep_headers"])
    return api_client.advance_warranty_claim(order["id"], claim["id"], {"action": action},
                                             headers)


def approve_claim(franchisee, order, claim):
    advance_claim(franchisee, order, claim, "SUBMIT")
    return get_success_data(advance_claim(franchisee, order, claim, "APPROVE"))


# --- replenishment ----------------------------------------------------------
def create_product_order(franchisee, route, requested_lines, ceiling=60_000,
                         mix_profile="DIAGNOSTIC_WEIGHTED"):
    return get_success_data(api_client.create_product_order(
        route["id"], F.product_order_payload(requested_lines, mix_profile=mix_profile,
                                             investment_ceiling_cents=ceiling),
        franchisee["owner_headers"]))


def advance_product_order(franchisee, product_order, action, expected_version=None):
    payload = {"action": action}
    if expected_version is not None:
        payload["expected_product_order_version"] = expected_version
    headers = MANAGER if action in ("SHIP", "ALLOCATE", "CANCEL") else franchisee["owner_headers"]
    return api_client.advance_product_order(product_order["id"], payload, headers)


def submit_product_order(franchisee, product_order):
    return get_success_data(advance_product_order(franchisee, product_order, "SUBMIT"))


def ship_product_order(franchisee, product_order):
    return get_success_data(advance_product_order(franchisee, product_order, "SHIP"))


def receive_product_order(franchisee, product_order, expected_version):
    return advance_product_order(franchisee, product_order, "RECEIVE", expected_version)


def file_pledge(franchisee, product_order, account, pledged_lines,
                expected_version=None):
    version = expected_version
    if version is None:
        version = get_product_order(product_order["id"], franchisee["owner_headers"])["version"]
    return api_client.file_pledge(
        product_order["id"], F.pledge_payload(account["id"], pledged_lines, version),
        franchisee["rep_headers"])


def advance_pledge(pledge, action):
    return api_client.advance_pledge(pledge["id"], {"action": action},
                                     MANAGER if action == "BIND" else MANAGER)


# --- launch allocation ------------------------------------------------------
def plan_launch(product, total_launch_qty=10, run_priority="PRIMARY"):
    return api_client.plan_launch(product["id"],
                                  {"total_launch_qty": total_launch_qty,
                                   "run_priority": run_priority}, MANAGER)


def list_allocations(params=None):
    body = get_success_data(api_client.list_launch_allocations(MANAGER, params))
    return body["data"] if isinstance(body, dict) else body


# --- composite stock helpers ------------------------------------------------
def stock_route(store, product, qty, price=None):
    """Create the product's position on the storefront route."""
    return add_inventory(store["franchisee"], store["route"], product, qty)


def setup_product_with_stock(store, sku="P1", category="POWER_TOOLS", cost=12_000,
                             retail=15_000, on_hand=10, **product_kwargs):
    product = create_product(sku=sku, category=category, unit_cost_cents=cost,
                             retail_price_cents=retail, **product_kwargs)
    add_inventory(store["franchisee"], store["route"], product, on_hand)
    return product


def draft_order(store, technician, account, lines, mix_profile="DIAGNOSTIC_WEIGHTED"):
    return create_order(store["franchisee"], store["route"], technician, account,
                        lines, mix_profile)


def edit_order(franchisee, order, lines, mix_profile=None):
    payload = {"lines": lines}
    if mix_profile:
        payload["mix_profile"] = mix_profile
    return api_client.edit_sales_order(order["id"], payload, franchisee["rep_headers"])
