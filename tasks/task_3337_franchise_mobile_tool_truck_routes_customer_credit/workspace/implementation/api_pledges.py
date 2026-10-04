"""Share pledges against draft replenishment orders."""

from flask import Blueprint

import auth
import envelope
import lookup
import store
from errors import fail

bp = Blueprint("pledges", __name__, url_prefix="/retail")

PLEDGE_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
                "RouteSalesRep")
PLEDGE_ACTIONS = ("BIND", "RELEASE")


def parse_pledged_lines(raw_lines):
    if not isinstance(raw_lines, list) or not raw_lines:
        fail("ERR_INVALID_REQUEST", "pledged_lines must be a non-empty array.")
    lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each pledged line must be an object.")
        product_id = entry.get("product_id")
        if not isinstance(product_id, str) or not product_id:
            fail("ERR_INVALID_REQUEST", "pledged_lines[].product_id is required.")
        qty = entry.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            fail("ERR_INVALID_REQUEST", "pledged_lines[].qty must be a non-negative integer.")
        lookup.product(product_id)
        lines.append({"product_id": product_id, "qty": qty})
    return lines


@bp.post("/product-orders/<order_id>/pledges")
def create_pledge(order_id):
    user_id, role = auth.require("FranchiseOwner", "RouteSalesRep")
    order = lookup.product_order(order_id)
    auth.ensure_owned(user_id, role, auth.product_order_owner_id(order))
    payload = envelope.body()
    credit_account_id = envelope.as_str(payload, "credit_account_id")
    expected = envelope.as_int(payload, "expected_product_order_version")
    if expected != order.get("version"):
        fail("ERR_STALE_VERSION")
    if order.get("product_order_status") != "DRAFT":
        fail("ERR_PRODUCT_ORDER_NOT_DRAFT")
    account = lookup.account(credit_account_id)
    lines = parse_pledged_lines(payload.get("pledged_lines"))

    ordered_qty = {}
    for line in order.get("ordered_lines", []):
        ordered_qty[line["product_id"]] = line.get("ordered_qty", 0)
    pledged_qty = {}
    for existing in store.pledges.values():
        if existing.get("product_order_id") != order["id"]:
            continue
        if existing.get("pledge_status") == "RELEASED":
            continue
        for share in existing.get("pledged_lines", []):
            pledged_qty[share["product_id"]] = pledged_qty.get(share["product_id"], 0) + share["qty"]
    for share in lines:
        pledged_qty[share["product_id"]] = pledged_qty.get(share["product_id"], 0) + share["qty"]
    for product_id, total in pledged_qty.items():
        if total > ordered_qty.get(product_id, 0):
            fail("ERR_PLEDGE_OVERSUBSCRIBED")

    index = len([p for p in store.pledges.values() if p.get("product_order_id") == order["id"]])
    pledge = store.create(
        store.pledges,
        product_order_id=order["id"],
        route_id=order.get("route_id"),
        credit_account_id=account["id"],
        pledged_lines=lines,
        pledge_status="HELD",
        line_index=index,
        sustained_amount_cents=0,
    )
    store.stamp(order)
    return envelope.ok(pledge, 201)


@bp.get("/pledges")
def list_pledges():
    auth.require(*PLEDGE_ROLES)
    rows = envelope.filter_query(store.ordered(store.pledges), {
        "product_order_id": "product_order_id",
        "credit_account_id": "credit_account_id",
        "pledge_status": "pledge_status",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/credit-accounts/<account_id>/pledges")
def list_account_pledges(account_id):
    auth.require(*PLEDGE_ROLES)
    account = lookup.account(account_id)
    rows = [p for p in store.ordered(store.pledges)
            if p.get("credit_account_id") == account["id"]]
    rows = envelope.filter_query(rows, {"pledge_status": "pledge_status"})
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.post("/pledges/<pledge_id>/status")
def advance_pledge(pledge_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    pledge = lookup.pledge(pledge_id)
    auth.ensure_owned(user_id, role, auth.pledge_owner_id(pledge))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", PLEDGE_ACTIONS)
    if pledge.get("pledge_status") != "HELD":
        fail("ERR_INVALID_STATE")
    store.set_field(pledge, "pledge_status", "BOUND" if action == "BIND" else "RELEASED")
    store.stamp(pledge)
    return envelope.ok(pledge)
