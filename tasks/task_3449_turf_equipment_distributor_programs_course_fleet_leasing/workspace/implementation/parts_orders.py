"""Parts ordering: DRAFT pipeline, off-season incentive, commitment ledger."""
from flask import Blueprint

import calculations as calc
import helpers
from helpers import as_enum, as_int, as_str, auth, body, fail, ok, req, require_role, identity_entity
import storage
from storage import STORES, new_record, public, sort_created, touch

bp = Blueprint("parts_orders", __name__)

ORDER_TYPES = ("STOCK", "CUSTOMER")
READ_ROLES = ("CorporateAdmin", "DistributorManager")

# transition -> allowed actor role (endpoint roles are CorporateAdmin +
# DistributorManager; the machine assigns a single actor per transition).
_TRANSITIONS = {
    ("DRAFT", "SUBMITTED"): "DistributorManager",
    ("SUBMITTED", "ALLOCATED"): "CorporateAdmin",
    ("ALLOCATED", "SHIPPED"): "CorporateAdmin",
    ("SHIPPED", "RECEIVED"): "DistributorManager",
    ("DRAFT", "CANCELLED"): "DistributorManager",
    ("SUBMITTED", "CANCELLED"): "DistributorManager",
    ("ALLOCATED", "CANCELLED"): "CorporateAdmin",
}


def _parse_lines(raw_lines):
    """Structural shape: array of {part_id, qty}. Emptiness and qty>=1 are the
    named shape errors; part references resolve left-to-right (404)."""
    lines = helpers.as_array(raw_lines, "lines")
    if len(lines) == 0:
        fail("ERR_EMPTY_ORDER", "parts order must contain at least one line")
    parsed = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "lines[%d] must be an object" % i)
        part_id = as_str(req(line, "part_id"), "lines[%d].part_id" % i)
        qty = as_int(req(line, "qty"), "lines[%d].qty" % i)
        helpers.get_or_404("parts", part_id, "part")
        if qty < 1:
            fail("ERR_ZERO_QUANTITY_LINE", "lines[%d].qty must be >= 1" % i)
        parsed.append({"part_id": part_id, "qty": qty})
    return parsed


def _recheck_lines(lines):
    """Line rules re-checked at submit (PRD 3.3)."""
    if len(lines) == 0:
        fail("ERR_EMPTY_ORDER", "parts order must contain at least one line")
    for line in lines:
        if line["qty"] < 1:
            fail("ERR_ZERO_QUANTITY_LINE", "order line qty must be >= 1")


@bp.post("/parts-orders")
def create_order():
    role, uid = auth()
    require_role(role, ("DistributorManager",))
    d = identity_entity(role, uid)
    b = body()
    order_type = as_enum(req(b, "order_type"), "order_type", ORDER_TYPES)
    lines = _parse_lines(req(b, "lines"))
    if d["status"] == "TERMINATED":
        fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "terminated distributor is read-only")
    subtotal = calc.order_subtotal(lines)
    ordered_units = sum(l["qty"] for l in lines)
    rec = new_record("orders", {
        "distributor_id": uid,
        "order_type": order_type,
        "lines": lines,
        "off_season_applied": False,
        "discount_tier_pct": 0.0,
        "subtotal_cents": subtotal,
        "discount_cents": 0,
        "total_cents": subtotal,
        "ordered_units": ordered_units,
        "received_units": 0,
        "status": "DRAFT",
        "_received_lines": {},
    })
    return ok(public(rec), 201)


@bp.get("/parts-orders/<oid>")
def get_order(oid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    o = helpers.get_or_404("orders", oid, "parts order")
    return ok(public(o))


@bp.get("/parts-orders")
def list_orders():
    role, uid = auth()
    require_role(role, READ_ROLES)
    recs = helpers.apply_filters(sort_created(STORES["orders"].values()),
                                 {"distributor_id": "distributor_id", "status": "status"})
    return helpers.paginate(recs)


@bp.post("/parts-orders/<oid>/transition")
def transition_order(oid):
    role, uid = auth()
    require_role(role, READ_ROLES)
    if role == "DistributorManager":
        identity_entity(role, uid)
    o = helpers.get_or_404("orders", oid, "parts order")
    if role == "DistributorManager" and o["distributor_id"] != uid:
        fail("ERR_FORBIDDEN_OWNERSHIP", "parts order belongs to another distributor")
    b = body()
    to = as_str(req(b, "to"), "to")
    if to == "RECEIVED":
        received_lines = helpers.as_array(req(b, "received_lines"), "received_lines")
    else:
        received_lines = None
    key = (o["status"], to)
    if key not in _TRANSITIONS:
        fail("ERR_INVALID_STATE", "parts order cannot move from " + o["status"] + " to " + str(to))
    if role != _TRANSITIONS[key]:
        fail("ERR_UNAUTHORIZED", "role " + role + " may not drive parts order to " + to)

    d = STORES["distributors"][o["distributor_id"]]

    if to == "SUBMITTED":
        _recheck_lines(o["lines"])
        for line in o["lines"]:
            part = STORES["parts"][line["part_id"]]
            if part["support_status"] not in ("ACTIVE", "LAST_BUY"):
                fail("ERR_PART_DISCONTINUED", "part " + line["part_id"] + " is not orderable")
        if d["status"] != "ACTIVE":
            fail("ERR_DISTRIBUTOR_NOT_ACTIVE", "distributor standing is not ACTIVE")
        if d["channel"] != "EQUIPMENT":
            fail("ERR_WRONG_CHANNEL", "parts orders require the EQUIPMENT channel")
        incentive = calc.offseason_incentive(o["order_type"], o["subtotal_cents"], o["lines"])
        o["off_season_applied"] = incentive["off_season_applied"]
        o["discount_tier_pct"] = incentive["discount_tier_pct"]
        o["discount_cents"] = incentive["discount_cents"]
        o["total_cents"] = o["subtotal_cents"] - o["discount_cents"]
        d["committed_parts_cents"] += o["total_cents"]

    elif to == "RECEIVED":
        ordered_by_part = {}
        for line in o["lines"]:
            ordered_by_part[line["part_id"]] = ordered_by_part.get(line["part_id"], 0) + line["qty"]
        received = {}
        for i, line in enumerate(received_lines):
            if not isinstance(line, dict):
                fail("ERR_INVALID_REQUEST", "received_lines[%d] must be an object" % i)
            part_id = as_str(req(line, "part_id"), "received_lines[%d].part_id" % i)
            qty = as_int(req(line, "qty"), "received_lines[%d].qty" % i)
            if part_id not in ordered_by_part:
                fail("ERR_INVALID_REQUEST", "received_lines names a part not on the order")
            if part_id in received:
                fail("ERR_INVALID_REQUEST", "received_lines names part " + part_id + " twice")
            if qty < 0 or qty > ordered_by_part[part_id]:
                fail("ERR_INVALID_REQUEST", "received qty must be between 0 and the ordered qty")
            received[part_id] = qty
        o["_received_lines"] = received
        o["received_units"] = sum(received.values())
        d["committed_parts_cents"] -= o["total_cents"]

    elif to == "CANCELLED" and o["status"] in ("SUBMITTED", "ALLOCATED"):
        # Compensation: commitment released; the discount is voided with the order.
        d["committed_parts_cents"] -= o["total_cents"]

    o["status"] = to
    touch(o)
    return ok(public(o))
