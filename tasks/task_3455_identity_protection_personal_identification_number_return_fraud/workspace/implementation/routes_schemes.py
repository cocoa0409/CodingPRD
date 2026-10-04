"""Preparer registry and FraudSchemeAlert routes, including the confirm
cascade (preparer suspension + re-hold of their passed returns)."""
from flask import Blueprint, request

from auth import require_roles
from domain import (create_hold, get_alert, get_preparer, hold_for_return,
                    new_record, pub, touch)
from envelope import created, list_response, ok
from errors import err
from store import DB
from validate import body, invalid, page, pagination, req_str

bp = Blueprint("schemes", __name__)


def _own_preparer_path(uid, role, preparer_id):
    if role == "TaxPreparer" and uid != preparer_id:
        err("ERR_UNAUTHORIZED")


@bp.post("/identity-protection/preparers")
def create_preparer():
    require_roles(["SystemAdmin"])
    b = body()
    # Priority 8: ptin uniqueness (ERR_INVALID_REQUEST per catalog).
    ptin = b.get("ptin")
    if isinstance(ptin, str):
        for p in DB.preparers.values():
            if p["ptin"] == ptin:
                invalid("ptin must be unique")
    # Priority 14: payload shape.
    ptin = req_str(b, "ptin")
    firm_name = req_str(b, "firm_name")
    rec = new_record(DB.preparers, {
        "ptin": ptin,
        "firm_name": firm_name,
        "status": "ACTIVE",
        "filed_return_count": 0,
    })
    return created(pub(rec))


@bp.get("/identity-protection/preparers/<string:preparer_id>")
def read_preparer(preparer_id):
    uid, role = require_roles(["SystemAdmin", "FraudAnalyst", "TaxPreparer"])
    _own_preparer_path(uid, role, preparer_id)
    return ok(pub(get_preparer(preparer_id)))


@bp.get("/identity-protection/preparers/<string:preparer_id>/fraud-scheme-alerts")
def list_preparer_alerts(preparer_id):
    uid, role = require_roles(["FraudAnalyst", "TaxPreparer", "SystemAdmin"])
    _own_preparer_path(uid, role, preparer_id)
    preparer = get_preparer(preparer_id)
    limit, offset = pagination()
    rows = [a for a in DB.alerts.values() if a["preparer_id"] == preparer["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    items, total = page(rows, limit, offset)
    return list_response([pub(a) for a in items], total, limit, offset)


@bp.get("/identity-protection/fraud-scheme-alerts")
def list_alerts():
    require_roles(["FraudAnalyst", "SystemAdmin"])
    limit, offset = pagination()
    rows = list(DB.alerts.values())
    for param in ("pattern_type", "status"):
        v = request.args.get(param)
        if v is not None:
            rows = [a for a in rows if a.get(param) == v]
    items, total = page(rows, limit, offset)
    return list_response([pub(a) for a in items], total, limit, offset)


@bp.get("/identity-protection/fraud-scheme-alerts/<string:alert_id>")
def read_alert(alert_id):
    require_roles(["FraudAnalyst", "SystemAdmin"])
    return ok(pub(get_alert(alert_id)))


@bp.post("/identity-protection/fraud-scheme-alerts/<string:alert_id>/confirm")
def confirm_alert(alert_id):
    uid, role = require_roles(["FraudAnalyst"])
    alert = get_alert(alert_id)
    # CONFIRMED_SCHEME / CLEARED are non-terminal (PRD §2.10) -> INVALID_STATE.
    if alert["status"] != "FLAGGED":
        err("ERR_INVALID_STATE", "Only a FLAGGED alert can be confirmed.")
    alert["status"] = "CONFIRMED_SCHEME"
    alert["confirmed_by_user_id"] = uid
    touch(alert)
    if alert["preparer_id"] is not None:
        preparer = DB.preparers.get(alert["preparer_id"])
        if preparer is not None and preparer["status"] == "ACTIVE":
            preparer["status"] = "SUSPENDED"
            touch(preparer)
            # Re-hold cascade: every FILTER_PASSED return of this preparer is
            # pulled back to FILTER_HELD; a hold is created for each that has
            # none (zone FULL, reason_codes exactly [SCHEME_CONFIRMED]).
            for r in list(DB.returns.values()):
                if r["preparer_id"] == preparer["id"] and r["status"] == "FILTER_PASSED":
                    r["status"] = "FILTER_HELD"
                    touch(r)
                    if hold_for_return(r["id"]) is None:
                        create_hold(r, "FULL", ["SCHEME_CONFIRMED"])
    return ok(pub(alert))


@bp.post("/identity-protection/fraud-scheme-alerts/<string:alert_id>/clear")
def clear_alert(alert_id):
    uid, role = require_roles(["FraudAnalyst"])
    alert = get_alert(alert_id)
    if alert["status"] != "FLAGGED":
        err("ERR_INVALID_STATE", "Only a FLAGGED alert can be cleared.")
    alert["status"] = "CLEARED"
    touch(alert)
    return ok(pub(alert))
