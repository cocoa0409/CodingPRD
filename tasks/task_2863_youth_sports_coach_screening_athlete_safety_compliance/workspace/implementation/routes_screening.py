"""Screening orders: vendor return, adjudication and void."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("screening", __name__)

ORDER_STATUSES = ("ORDERED", "RESULT_RETURNED", "ADJUDICATED", "VOIDED")
CLEARING = ("CLEAR", "NON_DISQUALIFYING_RECORD")


def _member_of(order):
    return store.MEMBERS[order["member_id"]]


@bp.get("/screening-orders")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "SafeSportOfficer")
def list_orders():
    args = request.args
    validate.query_enum(args, "status", ORDER_STATUSES)
    rows = [o for o in store.SCREENING_ORDERS.values()
            if pagelib.match(o, args, "member_id") and pagelib.match(o, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.screening_order, args)


@bp.get("/screening-orders/<screening_order_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer",
               "ScreeningVendor")
def read_order(screening_order_id):
    order = auth.screening_order(screening_order_id)
    auth.scope_member(_member_of(order))
    return envelope.ok(serialize.screening_order(order))


@bp.post("/screening-orders/<screening_order_id>/result")
@auth.endpoint("ScreeningVendor")
def post_result(screening_order_id):
    order = auth.screening_order(screening_order_id)
    data = validate.body(auth.payload(),
                         {"vendor_disposition": validate.enum(("NO_RECORD", "RECORD_FOUND"))})
    if order["status"] != "ORDERED":
        fail("ERR_SCREENING_ORDER_INVALID_STATE",
             "a vendor result is only accepted while the order is ORDERED")
    member = _member_of(order)
    order["vendor_disposition"] = data["vendor_disposition"]
    order["status"] = "RESULT_RETURNED"
    order["returned_at"] = clock.now()
    store.bump(order)
    if data["vendor_disposition"] == "RECORD_FOUND" and member["screening_status"] == "SCREENING_ORDERED":
        member["screening_status"] = "FLAGGED"
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.screening_order(order))


ADJUDICATE_SPEC = {
    "disposition": validate.enum(("CLEAR", "NON_DISQUALIFYING_RECORD", "DISQUALIFYING_RECORD")),
    "rationale": validate.string(min_len=1, max_len=4000),
}


@bp.post("/screening-orders/<screening_order_id>/adjudicate")
@auth.endpoint("SafeSportOfficer")
def adjudicate(screening_order_id):
    order = auth.screening_order(screening_order_id)
    data = validate.body(auth.payload(), ADJUDICATE_SPEC)
    member = _member_of(order)
    disposition = data["disposition"]
    if order["status"] != "RESULT_RETURNED":
        fail("ERR_SCREENING_ORDER_INVALID_STATE",
             "adjudication is only available from RESULT_RETURNED")
    if disposition == "CLEAR":
        if order["vendor_disposition"] != "NO_RECORD" or member["screening_status"] != "SCREENING_ORDERED":
            fail("ERR_SCREENING_ORDER_INVALID_STATE",
                 "CLEAR is only permitted over a NO_RECORD return")
    elif disposition == "NON_DISQUALIFYING_RECORD":
        if member["screening_status"] not in ("SCREENING_ORDERED", "FLAGGED"):
            fail("ERR_SCREENING_ORDER_INVALID_STATE",
                 "no clearing transition exists from %s" % member["screening_status"])
    else:
        if order["vendor_disposition"] != "RECORD_FOUND" or member["screening_status"] != "FLAGGED":
            fail("ERR_SCREENING_ORDER_INVALID_STATE",
                 "DISQUALIFYING_RECORD is only available over a RECORD_FOUND return")

    order["status"] = "ADJUDICATED"
    order["disposition"] = disposition
    order["adjudicated_at"] = clock.now()
    if disposition in CLEARING:
        order["expires_at"] = clock.plus_days(order["adjudicated_at"], calc.SCREENING_VALIDITY_DAYS)
    else:
        order["expires_at"] = None
    store.bump(order)

    if disposition in CLEARING:
        member["screening_status"] = "CLEARED"
        member["screening_expires_at"] = order["expires_at"]
        if disposition == "NON_DISQUALIFYING_RECORD":
            calc.apply_tier_assignment(member)
        derive.recompute_member(member)
        ops.stamp_horizons(member)
        ops.bubble_membership(member)
    else:
        member["screening_status"] = "DISQUALIFIED"
        member["screening_expires_at"] = None
        ops.revoke_member(member, "SCREENING_DISQUALIFICATION")
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.screening_order(order))


@bp.post("/screening-orders/<screening_order_id>/void")
@auth.endpoint("NgbAdmin")
def void_order(screening_order_id):
    order = auth.screening_order(screening_order_id)
    data = validate.body(auth.payload(), {"reason": validate.string(min_len=1, max_len=1000)})
    member = _member_of(order)
    if order["status"] not in ("ORDERED", "RESULT_RETURNED"):
        fail("ERR_SCREENING_ORDER_INVALID_STATE",
             "only an ORDERED or RESULT_RETURNED order may be voided")
    for other in store.orders_of(member["id"]):
        if (other["id"] != order["id"] and other["status"] == "ADJUDICATED"
                and other["disposition"] in CLEARING):
            fail("ERR_SCREENING_ORDER_INVALID_STATE",
                 "another adjudicated order already confers a clearance")
    order["status"] = "VOIDED"
    order["void_reason"] = data["reason"]
    store.bump(order)
    club = store.CLUBS[member["club_id"]]
    club["escrow_balance_cents"] += order["charged_cents"]
    store.bump(club)
    member["screening_status"] = "UNSCREENED"
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.screening_order(order))
