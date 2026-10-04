"""Retail accounts and assortment plans."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from store import db
from helpers import (
    ApiError, body, created, find, init_common, list_ok, need, ok,
    parse_period_val, require_roles, touch, v_enum, v_int, v_str, err400,
)
from calc import variety_velocity, is_slow_mover
from serializers import account_out, plan_out

bp = Blueprint("retail", __name__)

PLAN_TARGETS = ("PROPOSED", "APPROVED", "LOCKED", "DRAFT", "CANCELLED")

_DECLARED = {
    ("DRAFT", "PROPOSED"), ("PROPOSED", "APPROVED"), ("APPROVED", "LOCKED"),
    ("PROPOSED", "DRAFT"), ("DRAFT", "CANCELLED"), ("PROPOSED", "CANCELLED"),
}


@bp.post("/retail-accounts")
@require_roles("CategoryManager")
def create_account():
    b = body()
    account = init_common({
        "name": v_str(b, "name"),
        "region": v_str(b, "region"),
        "shelf_slots_total": v_int(b, "shelf_slots_total"),
        "productivity_floor_cents": v_int(b, "productivity_floor_cents"),
    })
    db["accounts"][account["id"]] = account
    return created(account_out(account))


@bp.get("/retail-accounts/<rid>")
@require_roles("CategoryManager")
def get_account(rid):
    return ok(account_out(find("accounts", rid)))


def _validate_slots(raw):
    if raw is None:
        err400("Missing required field: slots")
    if not isinstance(raw, list):
        err400("slots must be an array")
    if len(raw) == 0:
        raise ApiError("ERR_EMPTY_SLOTS", 400, "slots must be a non-empty array")
    slots = []
    for s in raw:
        if not isinstance(s, dict):
            err400("slot entries must be objects")
        vid = s.get("variety_id")
        if not isinstance(vid, str):
            err400("slot variety_id must be a string")
        fac = s.get("facings")
        if isinstance(fac, bool) or not isinstance(fac, int) or fac < 1:
            err400("slot facings must be an integer of at least 1")
        cf = s.get("clearance_flag")
        if not isinstance(cf, bool):
            err400("slot clearance_flag must be a boolean")
        slots.append({"variety_id": vid, "facings": fac, "clearance_flag": cf})
    return slots


@bp.post("/retail-accounts/<rid>/assortment-plans")
@require_roles("CategoryManager")
def create_plan(rid):
    account = find("accounts", rid)
    b = body()
    expected = v_int(b, "expected_retail_account_version")
    period = parse_period_val(need(b, "period"))
    slots = _validate_slots(b.get("slots"))
    for s in slots:
        if s["variety_id"] not in db["varieties"]:
            raise ApiError("ERR_NOT_FOUND", 404,
                           "PodVariety not found: %s" % s["variety_id"])
    for p in db["plans"].values():
        if p["account_id"] == account["id"] and p["period"] == period \
                and p["status"] == "LOCKED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A LOCKED plan for this period can never be superseded")
    if expected != account["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_retail_account_version does not match the current version")
    for p in db["plans"].values():
        if p["account_id"] == account["id"] and p["period"] == period \
                and p["status"] == "APPROVED":
            p["status"] = "SUPERSEDED"
            touch(p)
    touch(account)
    plan = init_common({
        "account_id": account["id"],
        "period": period,
        "slots": slots,
        "productivity_cents": None,
        "status": "DRAFT",
    })
    db["plans"][plan["id"]] = plan
    return created(plan_out(plan))


@bp.get("/retail-accounts/<rid>/assortment-plans")
@require_roles("CategoryManager")
def list_plans(rid):
    account = find("accounts", rid)
    items = [p for p in db["plans"].values() if p["account_id"] == account["id"]]
    f_period = request.args.get("period")
    f_status = request.args.get("status")
    if f_period is not None:
        items = [p for p in items if p["period"] == f_period]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return list_ok(items, plan_out)


def _slot_varieties_listable(plan):
    for s in plan["slots"]:
        v = db["varieties"].get(s["variety_id"])
        if v is None or v["status"] not in ("ACTIVE", "PHASE_OUT"):
            raise ApiError("ERR_VARIETY_NOT_LISTABLE", 409,
                           "Assortment slot references a variety outside ACTIVE/PHASE_OUT")


@bp.post("/assortment-plans/<rid>/transition")
@require_roles("CategoryManager")
def transition_plan(rid):
    plan = find("plans", rid)
    b = body()
    target = v_enum(b, "target_state", PLAN_TARGETS)
    if (plan["status"], target) not in _DECLARED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No declared transition from %s to %s" % (plan["status"], target))
    account = db["accounts"][plan["account_id"]]
    if target == "PROPOSED":
        if len(plan["slots"]) == 0:
            raise ApiError("ERR_EMPTY_SLOTS", 400, "slots must be a non-empty array")
        _slot_varieties_listable(plan)
        if sum(s["facings"] for s in plan["slots"]) > account["shelf_slots_total"]:
            raise ApiError("ERR_CAPACITY_EXCEEDED", 409,
                           "Slot facings exceed the account's shelf_slots_total")
    elif target == "APPROVED":
        _slot_varieties_listable(plan)
        total = 0
        for s in plan["slots"]:
            v = db["varieties"][s["variety_id"]]
            per_slot = (Decimal(s["facings"]) * Decimal(variety_velocity(v))
                        * Decimal(v["margin_cents"]) / Decimal(90)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            total += int(per_slot)
        if total < account["productivity_floor_cents"]:
            raise ApiError("ERR_PRODUCTIVITY_FLOOR_UNMET", 422,
                           "Plan productivity is below the account floor")
        plan["productivity_cents"] = total
    elif target == "LOCKED":
        for s in plan["slots"]:
            v = db["varieties"][s["variety_id"]]
            if is_slow_mover(v) and not s["clearance_flag"]:
                raise ApiError("ERR_SLOW_MOVER_SLOT", 409,
                               "Slow-mover slots require clearance_flag")
    plan["status"] = target
    touch(plan)
    return ok(plan_out(plan))
