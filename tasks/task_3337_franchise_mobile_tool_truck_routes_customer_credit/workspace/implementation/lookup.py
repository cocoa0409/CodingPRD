"""Entity resolution with the entity-specific 404 identifiers.

Path identifiers are resolved left to right: a parent is resolved before the
child it scopes. A child that exists but belongs to a different parent is
reported exactly as a wholly absent row.
"""

import store
from errors import fail


def franchisee(fid):
    row = store.franchisees.get(fid)
    if row is None:
        fail("ERR_FRANCHISEE_NOT_FOUND")
    return row


def route(rid):
    row = store.routes.get(rid)
    if row is None:
        fail("ERR_ROUTE_NOT_FOUND")
    return row


def route_of_franchisee(fid, rid):
    """Resolve the franchisee first, then the route it owns."""
    franchisee(fid)
    row = store.routes.get(rid)
    if row is None or row.get("franchisee_id") != fid:
        fail("ERR_ROUTE_NOT_FOUND")
    return row


def shop(sid):
    row = store.shops.get(sid)
    if row is None:
        fail("ERR_SHOP_NOT_FOUND")
    return row


def technician(tid):
    row = store.technicians.get(tid)
    if row is None:
        fail("ERR_TECHNICIAN_NOT_FOUND")
    return row


def application(aid):
    row = store.applications.get(aid)
    if row is None:
        fail("ERR_APPLICATION_NOT_FOUND")
    return row


def account(aid):
    row = store.accounts.get(aid)
    if row is None:
        fail("ERR_ACCOUNT_NOT_FOUND")
    return row


def payment(account_row, payment_id):
    row = store.payments.get(payment_id)
    if row is None or row.get("account_id") != account_row["id"]:
        fail("ERR_PAYMENT_NOT_FOUND")
    return row


def sales_order(oid):
    row = store.sales_orders.get(oid)
    if row is None:
        fail("ERR_ORDER_NOT_FOUND")
    return row


def claim(order_row, claim_id):
    row = store.claims.get(claim_id)
    if row is None or row.get("order_id") != order_row["id"]:
        fail("ERR_CLAIM_NOT_FOUND")
    return row


def product(pid):
    row = store.products.get(pid)
    if row is None:
        fail("ERR_PRODUCT_NOT_FOUND")
    return row


def product_order(poid):
    row = store.product_orders.get(poid)
    if row is None:
        fail("ERR_PRODUCT_ORDER_NOT_FOUND")
    return row


def pledge(plid):
    row = store.pledges.get(plid)
    if row is None:
        fail("ERR_PRODUCT_ORDER_NOT_FOUND", "No share pledge exists for the id in the path.")
    return row


def launch_allocation(lid):
    row = store.launch_allocations.get(lid)
    if row is None:
        fail("ERR_PRODUCT_NOT_FOUND", "No launch allocation exists for the id in the path.")
    return row


def inventory_position_for(route_id, product_id):
    for row in store.positions.values():
        if row.get("route_id") == route_id and row.get("product_id") == product_id:
            return row
    return None
