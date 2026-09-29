"""Client registry, suspension controls and the disposition-audit report."""

from decimal import Decimal
from flask import Blueprint

import aggregates
import calc
import constants as K
import db
import middleware as mw
import query
import refs
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("clients", __name__)


def _duplicate_client_code(code, exclude_id=None):
    for row in db.all_rows("clients"):
        if row["client_code"] == code and row["id"] != exclude_id:
            return True
    return False


@bp.post("/clients")
def create_client():
    _user_id, _role = mw.require("CenterAdmin")
    body = response.body_json()
    name = shapes.req_str(body, "name")
    client_code = shapes.req_code(body, "client_code")
    service_level = shapes.req_enum(body, "service_level", K.SERVICE_LEVELS)
    inventory_ownership = shapes.req_enum(body, "inventory_ownership", K.INVENTORY_OWNERSHIP)
    restock_grade_floor = shapes.opt_enum(body, "restock_grade_floor", K.GRADES, "B")
    refund_hold_hours = shapes.opt_int(body, "refund_hold_hours", 48, 0, 720)
    liquidation_floor_pct = shapes.opt_pct(
        body, "liquidation_floor_pct", Decimal("0.30"), Decimal("0.00"), Decimal("1.00")
    )
    fraud_tolerance_cents = shapes.opt_int(body, "fraud_tolerance_cents", 5000, 0)
    donation_allowed = shapes.opt_bool(body, "donation_allowed", False)
    destroy_requires_dual_signoff = shapes.opt_bool(
        body, "destroy_requires_dual_signoff", False
    )
    max_refund_exposure_cents = shapes.opt_int(body, "max_refund_exposure_cents", 500000, 0)
    if _duplicate_client_code(client_code):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'client_code' must be unique.")
    row = {
        "id": db.new_id(),
        "name": name,
        "client_code": client_code,
        "service_level": service_level,
        "inventory_ownership": inventory_ownership,
        "restock_grade_floor": restock_grade_floor,
        "refund_hold_hours": refund_hold_hours,
        "liquidation_floor_pct": liquidation_floor_pct,
        "fraud_tolerance_cents": fraud_tolerance_cents,
        "donation_allowed": donation_allowed,
        "destroy_requires_dual_signoff": destroy_requires_dual_signoff,
        "max_refund_exposure_cents": max_refund_exposure_cents,
        "status": "ACTIVE",
    }
    db.stamp_new(row)
    db.insert("clients", row)
    return response.created(serialize.client(row))


@bp.get("/clients/<client_id>")
def get_client(client_id):
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    client = db.get("clients", client_id)
    if client is not None:
        mw.scope(role, user_id, client["id"])
    client = services.must_client(client_id)
    return response.ok(serialize.client(client))


@bp.get("/clients")
def list_clients():
    mw.require("CenterAdmin")
    rows = db.sorted_rows(db.all_rows("clients"))
    rows = query.eq(rows, "client_code", query.arg("client_code"))
    rows = query.eq(rows, "status", query.arg("status"))
    rows = query.eq(rows, "service_level", query.arg("service_level"))
    return response.paginate(rows, serialize.client)


@bp.post("/clients/<client_id>/suspend")
def suspend_client(client_id):
    mw.require("CenterAdmin")
    body = response.body_json()
    shapes.opt_str(body, "suspension_reason")
    client = services.must_client(client_id)
    client["status"] = "SUSPENDED"
    db.touch(client)
    return response.ok(serialize.client(client))


@bp.post("/clients/<client_id>/reinstate")
def reinstate_client(client_id):
    mw.require("CenterAdmin")
    response.body_json()
    client = services.must_client(client_id)
    client["status"] = "ACTIVE"
    db.touch(client)
    return response.ok(serialize.client(client))


@bp.get("/clients/<client_id>/disposition-audit")
def disposition_audit(client_id):
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    client = db.get("clients", client_id)
    if client is not None:
        mw.scope(role, user_id, client["id"])
    client = services.must_client(client_id)

    lines = aggregates.lines_of_client(client_id)
    counts = {
        "pending_count": 0,
        "restock_count": 0,
        "refurbish_count": 0,
        "liquidate_count": 0,
        "donate_count": 0,
        "destroy_count": 0,
    }
    key_for = {
        "PENDING": "pending_count",
        "RESTOCK": "restock_count",
        "REFURBISH": "refurbish_count",
        "LIQUIDATE": "liquidate_count",
        "DONATE": "donate_count",
        "DESTROY": "destroy_count",
    }
    for line in lines:
        counts[key_for[line["disposition"]]] += 1

    totals = dict((entry_type, 0) for entry_type in K.LEDGER_ENTRY_TYPES)
    for entry in aggregates.entries_of_client(client_id):
        totals[entry["entry_type"]] += entry["amount_cents"]

    recovery_variance = 0
    for line in lines:
        if line["disposition_state"] != "DISPOSITIONED":
            continue
        order = services.executed_order_of_line(line["id"])
        if order is None:
            continue
        item = refs.item_of_return_line(line)
        if item is None:
            continue
        provisional = calc.provisional_recovery(
            item["declared_value_cents"],
            line["condition_grade"],
            line["reason_code"],
            line["quantity"],
        )
        recovery_variance += order["net_recovery_cents"] - provisional

    buckets = aggregates.unit_buckets(client_id)
    settlement = aggregates.settlement_balance(client_id)
    entry_total = sum(totals.values())
    data = {
        "pending_count": counts["pending_count"],
        "restock_count": counts["restock_count"],
        "refurbish_count": counts["refurbish_count"],
        "liquidate_count": counts["liquidate_count"],
        "donate_count": counts["donate_count"],
        "destroy_count": counts["destroy_count"],
        "recovery_credit_cents": totals["RECOVERY_CREDIT"],
        "refund_debit_cents": totals["REFUND_DEBIT"],
        "reversal_cents": totals["REVERSAL"],
        "refurb_cost_cents": totals["REFURB_COST"],
        "donation_write_off_cents": totals["DONATION_WRITE_OFF"],
        "destruction_write_off_cents": totals["DESTRUCTION_WRITE_OFF"],
        "receipt_variance_cents": totals["RECEIPT_VARIANCE"],
        "recovery_variance_cents": recovery_variance,
        "settlement_balance_cents": settlement,
        "projected_settlement_balance_cents": aggregates.projected_settlement_balance(client_id),
        "shrink_ledger_cents": aggregates.shrink_ledger(client_id),
        "units_received": buckets["units_received"],
        "units_in_process": buckets["units_in_process"],
        "units_reserved_for_disposition": buckets["units_reserved_for_disposition"],
        "units_dispositioned": buckets["units_dispositioned"],
        "unit_conservation_ok": buckets["units_received"]
        == (
            buckets["units_in_process"]
            + buckets["units_reserved_for_disposition"]
            + buckets["units_dispositioned"]
        ),
        "money_conservation_ok": settlement == entry_total,
    }
    return response.ok(data)
