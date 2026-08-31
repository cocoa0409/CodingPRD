"""Return authorizations: restocking fees, loyalty rebates and the inspection fork."""
from flask import Blueprint

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError
from routes.registry import fk

bp = Blueprint("returns", __name__)

RETURN_REASONS = {"WRONG_PART", "UNUSED_SURPLUS", "DEFECTIVE", "CORE_RETURN"}
RETURN_STATUSES = {"REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "CREDITED", "SCRAPPED"}
DISPOSITIONS = {"RESTOCK", "SCRAP"}


@bp.post("/aftermarket/return-authorizations")
def create_return():
    user_id, role = auth.require("DealerUser")
    data = auth.body()

    line = fk(data, "work_order_part_line_id", domain.get_part_line)
    if line is not None:
        wo = store.work_orders.get(line["work_order_id"])
        auth.dealer_scope(role, user_id, wo["dealer_id"] if wo else None)

    line_id = auth.req_id(data, "work_order_part_line_id")
    if line is None:
        line = domain.get_part_line(line_id)
        wo = store.work_orders.get(line["work_order_id"])
        auth.dealer_scope(role, user_id, wo["dealer_id"] if wo else None)
    else:
        wo = store.work_orders.get(line["work_order_id"])

    qty_returned = auth.req_int(data, "qty_returned", minimum=1)
    return_reason = auth.req_enum(data, "return_reason", RETURN_REASONS)

    if line["line_status"] != "CONSUMED":
        raise ApiError("ERR_LINE_STATE_INVALID")

    part = store.parts.get(line["part_id"])

    delta = store.now() - line["consumed_at"]
    age_days = int(delta.total_seconds() // 86400)
    if age_days > calc.RETURN_WINDOW_DAYS:
        raise ApiError("ERR_RETURN_WINDOW_EXPIRED")

    already = sum(r["qty_returned"] for r in store.return_authorizations.values()
                  if r["work_order_part_line_id"] == line["id"] and r["status"] != "REJECTED")
    if already + qty_returned > line["qty_consumed"]:
        raise ApiError("ERR_RETURN_QTY_EXCEEDS_CONSUMED")

    figures = calc.return_credit(
        charged_amount_cents=line["charged_amount_cents"],
        qty_returned=qty_returned,
        qty_consumed=line["qty_consumed"],
        age_days=age_days,
        return_reason=return_reason,
        lifecycle_state=part["lifecycle_state"] if part else "ACTIVE",
    )

    rec = store.new_record("ReturnAuthorization", {
        "work_order_part_line_id": line["id"],
        "part_id": line["part_id"],
        "dealer_id": wo["dealer_id"] if wo else None,
        "qty_returned": qty_returned,
        "return_reason": return_reason,
        "age_days": age_days,
        "credit_posted_cents": 0,
        "disposition": None,
        "status": "REQUESTED",
        "rejection_reason": None,
    })
    rec.update(figures)
    store.return_authorizations[rec["id"]] = rec
    return envelope.created(serializers.return_authorization(rec))


@bp.get("/aftermarket/return-authorizations/<return_id>")
def read_return(return_id):
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    return envelope.ok(serializers.return_authorization(domain.get_return(return_id)))


@bp.get("/aftermarket/return-authorizations")
def list_returns():
    auth.require("DealerUser", "AftermarketPlanner", "InventoryController", "PlatformAdmin")
    limit, offset = auth.pagination()
    part_id = auth.query_str("part_id")
    dealer_id = auth.query_str("dealer_id")
    line_id = auth.query_str("work_order_part_line_id")
    status = auth.query_enum("status", RETURN_STATUSES)

    rows = list(store.return_authorizations.values())
    if part_id is not None:
        rows = [r for r in rows if r["part_id"] == part_id]
    if dealer_id is not None:
        rows = [r for r in rows if r["dealer_id"] == dealer_id]
    if line_id is not None:
        rows = [r for r in rows if r["work_order_part_line_id"] == line_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.return_authorization(r) for r in page],
                            limit, offset, total)


@bp.post("/aftermarket/return-authorizations/<return_id>/approve")
def approve_return(return_id):
    auth.require("AftermarketPlanner")
    rma = domain.get_return(return_id)
    if rma["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_STATE_INVALID")
    rma["status"] = "APPROVED"
    store.touch(rma)
    return envelope.ok(serializers.return_authorization(rma))


@bp.post("/aftermarket/return-authorizations/<return_id>/reject")
def reject_return(return_id):
    auth.require("AftermarketPlanner")
    rma = domain.get_return(return_id)
    data = auth.body()
    rejection_reason = auth.opt_str(data, "rejection_reason")
    if rma["status"] != "REQUESTED":
        raise ApiError("ERR_RETURN_STATE_INVALID")
    rma["status"] = "REJECTED"
    rma["rejection_reason"] = rejection_reason
    store.touch(rma)
    return envelope.ok(serializers.return_authorization(rma))


@bp.post("/aftermarket/return-authorizations/<return_id>/receive")
def receive_return(return_id):
    auth.require("AftermarketPlanner")
    rma = domain.get_return(return_id)
    if rma["status"] != "APPROVED":
        raise ApiError("ERR_RETURN_STATE_INVALID")

    rma["status"] = "RECEIVED"
    store.touch(rma)

    part = store.parts.get(rma["part_id"])
    if part is not None:
        part["quarantine_units"] += rma["qty_returned"]
        domain.append_ledger(part, "RETURN_RECEIPT", rma["qty_returned"],
                             "RETURN_AUTHORIZATION", rma["id"])
        store.touch(part)

    return envelope.ok(serializers.return_authorization(rma))


@bp.post("/aftermarket/return-authorizations/<return_id>/inspect")
def inspect_return(return_id):
    auth.require("AftermarketPlanner")
    rma = domain.get_return(return_id)
    data = auth.body()
    disposition = auth.req_enum(data, "disposition", DISPOSITIONS)

    if rma["status"] != "RECEIVED":
        raise ApiError("ERR_RETURN_STATE_INVALID")

    part = store.parts.get(rma["part_id"])
    if disposition == "RESTOCK" and part is not None and part["lifecycle_state"] == "OBSOLETE":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    dealer = store.dealers.get(rma["dealer_id"])
    rma["disposition"] = disposition

    if disposition == "RESTOCK":
        rma["status"] = "CREDITED"
        if part is not None:
            part["quarantine_units"] -= rma["qty_returned"]
            part["on_hand_units"] += rma["qty_returned"]
        rma["credit_posted_cents"] = rma["final_credit_cents"]
        if dealer is not None:
            domain.credit_dealer(dealer, rma["final_credit_cents"],
                                 rma["restocking_fee_cents"], rma["loyalty_rebate_cents"])
    else:
        rma["status"] = "SCRAPPED"
        if part is not None:
            part["quarantine_units"] -= rma["qty_returned"]
            domain.append_ledger(part, "SCRAP", -rma["qty_returned"],
                                 "RETURN_AUTHORIZATION", rma["id"])
        if rma["return_reason"] == "DEFECTIVE":
            rma["credit_posted_cents"] = rma["final_credit_cents"]
            if dealer is not None:
                domain.credit_dealer(dealer, rma["final_credit_cents"],
                                     rma["restocking_fee_cents"], rma["loyalty_rebate_cents"])

    store.touch(rma)
    if part is not None:
        store.touch(part)

    return envelope.ok(serializers.return_authorization(rma))
