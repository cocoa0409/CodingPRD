from flask import Blueprint, request

import auth
import store
from domain import (
    ser_order, recompute_member_matrix, recompute_household,
    release_posture_if_no_active_orders,
)
from envelope import success
from errors import err
from helpers import (
    new_row, touch, require_field, optional_field, require_date, optional_date,
    require_bool, date_to_str, d_from_str,
)
from store import clock_today_date
from paginate import list_response

bp = Blueprint("deployments", __name__)


def _get_member(member_id):
    m = store.T["members"].get(member_id)
    if m is None:
        raise err("ERR_NOT_FOUND", 404, "member not found")
    return m


def _get_order(order_id):
    o = store.T["deployment_orders"].get(order_id)
    if o is None:
        raise err("ERR_NOT_FOUND", 404, "deployment order not found")
    return o


def _validate_no_deployment_overlap(member_id, s, e, exclude_id=None):
    for o in store.T["deployment_orders"].values():
        if o["member_id"] != member_id or o["status"] == "CANCELLED":
            continue
        if exclude_id and o["id"] == exclude_id:
            continue
        o_s = d_from_str(o["start_date"])
        o_e = d_from_str(o["end_date"]) if o["end_date"] else None
        # Inclusive intervals: overlap iff s1 <= e2 and s2 <= e1 (None end = inf)
        left = (e is None) or (s <= e if e is not None else True)
        cond1 = (o_e is None) or (s <= o_e)
        cond2 = (e is None) or (o_s <= e)
        if cond1 and cond2:
            raise err("ERR_DEPLOYMENT_OVERLAP", 409, "deployment interval overlap")


def _activate_order(order):
    """Activate a REGISTERED order and run the posture cascade."""
    member = store.T["members"][order["member_id"]]
    order["status"] = "ACTIVE"
    touch(order)
    if member["status"] == "ACTIVE" and member["deployment_posture"] == "NONE":
        member["deployment_posture"] = "DEPLOYED"
        recompute_member_matrix(member)
        touch(member)
        if member["household_id"]:
            recompute_household(store.T["households"][member["household_id"]])


def auto_activate_due_orders():
    """Auto-activate REGISTERED orders whose start_date <= clock date."""
    today = clock_today_date()
    for o in store.T["deployment_orders"].values():
        if o["status"] != "REGISTERED":
            continue
        if d_from_str(o["start_date"]) <= today:
            _activate_order(o)


@bp.post("/membership/members/<member_id>/deployment-orders")
def create_order(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    m = _get_member(member_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")
    orders_number = require_field(body, "orders_number")
    theater = require_field(body, "theater")
    start = require_date(body, "start_date")
    end = optional_date(body, "end_date")
    scra = require_bool(body, "scra_eligible")
    expected = require_field(body, "expected_member_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", 400, "invalid expected_member_version")

    # Priority 7: duplicate orders_number
    for o in store.T["deployment_orders"].values():
        if o["orders_number"] == orders_number:
            raise err("ERR_DUPLICATE_ORDER", 409, "duplicate orders_number")

    # Priority 10: end >= start, interval overlap
    if end is not None and end < start:
        raise err("ERR_DEPLOYMENT_OVERLAP", 409, "end_date before start_date")
    _validate_no_deployment_overlap(member_id, start, end)

    # Priority 19: OCC
    if expected != m["version"]:
        raise err("ERR_STALE_VERSION", 412, "stale member version")

    row = new_row()
    row.update({
        "member_id": member_id,
        "orders_number": orders_number,
        "theater": theater,
        "start_date": date_to_str(start),
        "end_date": date_to_str(end) if end else None,
        "scra_eligible": scra,
        "status": "REGISTERED",
    })
    store.insert_row("deployment_orders", row)
    touch(m)  # member version +1 on order registration

    # auto-activation when start_date <= clock date
    if start <= clock_today_date():
        _activate_order(row)

    return success(201, ser_order(row), "object")


@bp.get("/membership/members/<member_id>/deployment-orders")
def list_member_orders(member_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    auth.enforce_ownership(c, member_id)
    _get_member(member_id)
    rows = [o for o in store.T["deployment_orders"].values() if o["member_id"] == member_id]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_order(r) for r in rows], success)


@bp.route("/membership/deployment-orders/<order_id>", methods=["PATCH"])
def patch_order(order_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    o = _get_order(order_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", 400, "malformed body")

    if o["status"] not in ("REGISTERED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", 409, "order not adjustable")

    end = d_from_str(o["end_date"]) if o["end_date"] else None
    theater = o["theater"]
    if "end_date" in body:
        if body["end_date"] is None:
            end = None
        else:
            from helpers import _iso_to_date, _MONTH_RE
            v = body["end_date"]
            if not isinstance(v, str) or not _MONTH_RE.match(v):
                raise err("ERR_INVALID_REQUEST", 400, "invalid end_date")
            end = _iso_to_date(v)
    if "theater" in body:
        v = body["theater"]
        if not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", 400, "invalid theater")
        theater = v

    start = d_from_str(o["start_date"])
    if end is not None and end < start:
        raise err("ERR_DEPLOYMENT_OVERLAP", 409, "end_date before start_date")
    _validate_no_deployment_overlap(o["member_id"], start, end, exclude_id=o["id"])

    o["end_date"] = date_to_str(end) if end else None
    o["theater"] = theater
    touch(o)
    return success(200, ser_order(o), "object")


@bp.get("/membership/deployment-orders")
def list_orders():
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer", "PlatformAdmin"])
    rows = list(store.T["deployment_orders"].values())
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if member_id:
        rows = [o for o in rows if o["member_id"] == member_id]
    if status:
        rows = [o for o in rows if o["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response([ser_order(r) for r in rows], success)


@bp.get("/membership/deployment-orders/<order_id>")
def get_order(order_id):
    c = auth.ctx()
    auth.require_roles(c, ["Member", "VerificationOfficer", "PlatformAdmin"])
    o = _get_order(order_id)
    if c["role"] == "Member" and c["uid"] != o["member_id"]:
        raise err("ERR_FORBIDDEN_ROLE", 403, "ownership mismatch")
    return success(200, ser_order(o), "object")


@bp.post("/membership/deployment-orders/<order_id>/complete")
def complete_order(order_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    o = _get_order(order_id)
    request.get_json(silent=True)

    if o["status"] not in ("REGISTERED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", 409, "order not completable")

    # Priority 26/27: end_date set, then <= clock date.
    # Priority table orders NOT_ENDED (26) before END_DATE_REQUIRED (27); PRD §2.7
    # confirms "ERR_DEPLOYMENT_NOT_ENDED, then ERR_DEPLOYMENT_END_DATE_REQUIRED".
    if o["end_date"] is not None and d_from_str(o["end_date"]) > clock_today_date():
        raise err("ERR_DEPLOYMENT_NOT_ENDED", 422, "deployment end date in the future")
    if o["end_date"] is None:
        raise err("ERR_DEPLOYMENT_END_DATE_REQUIRED", 422, "end date required")

    o["status"] = "COMPLETED"
    touch(o)
    release_posture_if_no_active_orders(o["member_id"])
    return success(200, ser_order(o), "object")


@bp.post("/membership/deployment-orders/<order_id>/cancel")
def cancel_order(order_id):
    c = auth.ctx()
    auth.require_roles(c, ["VerificationOfficer"])
    o = _get_order(order_id)
    request.get_json(silent=True)

    if o["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", 409, "only REGISTERED orders can be cancelled")

    o["status"] = "CANCELLED"
    touch(o)
    return success(200, ser_order(o), "object")
