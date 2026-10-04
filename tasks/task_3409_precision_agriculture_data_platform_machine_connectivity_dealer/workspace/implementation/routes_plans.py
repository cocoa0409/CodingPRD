"""Data plans: creation, activation, suspension, resume, and the OCC-guarded
mid-cycle tier change with proration (PRD section 3.2)."""

from decimal import Decimal

from flask import Blueprint, request

from auth import (
    as_enum,
    as_int,
    as_str,
    body_json,
    caller,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from constants import TIER_PRICE_CENTS
from db import STORES, now
from domain import (
    cascade_plan_suspended,
    compute_proration,
    compute_usage_posture,
    machine_plan,
    new_record,
    recompute_posture,
    serialize,
    touch,
)
from envelope import created, ok, ok_list
from errors import (
    ERR_INVALID_REQUEST,
    ERR_ORG_SUSPENDED,
    ERR_PLAN_ALREADY_EXISTS,
    ERR_PLAN_NOT_ACTIVE,
    ERR_STALE_PLAN_VERSION,
    ERR_TIER_CHANGE_INVALID,
    ApiError,
    invalid_state,
)

bp = Blueprint("plans", __name__)

TIERS = {"BASIC", "STANDARD", "UNLIMITED"}
PRORATION_METHODS = {"CALENDAR_DAY", "THIRTY_DAY"}


def _owning_grower_gate(plan, role, uid):
    if role == "GrowerManager" and uid != plan["organization_id"]:
        raise access_denied("plan belongs to another organization")


@bp.post("/data-plans")
def create_plan():
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    b = body_json()
    organization_id = as_str(need(b, "organization_id"), "organization_id")
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    tier = as_enum(need(b, "tier"), "tier", TIERS)
    proration_method = as_enum(
        need(b, "proration_method"), "proration_method", PRORATION_METHODS
    )
    get_or_404("organizations", organization_id, "organization")
    machine = get_or_404("machines", machine_id, "machine")
    if role == "GrowerManager" and uid != organization_id:
        raise access_denied("grower may create plans only for its own organization")
    # Capacity: at most one plan per machine in PENDING, ACTIVE or SUSPENDED
    if machine_plan(machine_id) is not None:
        raise ApiError(ERR_PLAN_ALREADY_EXISTS, 409, "machine already has a plan")
    # Cross-reference agreement: the plan's organization must equal the machine's
    if machine["organization_id"] != organization_id:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "plan organization must equal the machine's organization"
        )
    rec = new_record(
        {
            "organization_id": organization_id,
            "machine_id": machine_id,
            "tier": tier,
            "proration_method": proration_method,
            "status": "PENDING",
            "monthly_price_cents": TIER_PRICE_CENTS[tier],
            "used_mb": Decimal(0),
            "usage_posture": "NORMAL",
            "cycle_anchor_day": None,
            "cycle_start_date": None,
            "last_proration_charge_cents": None,
        }
    )
    STORES["data_plans"][rec["id"]] = rec
    recompute_posture(machine)
    return created(serialize(rec))


@bp.get("/data-plans/<pid>")
def get_plan(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    p = get_or_404("data_plans", pid, "data plan")
    _owning_grower_gate(p, role, uid)
    return ok(serialize(p))


@bp.get("/data-plans")
def list_plans():
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    org_filter = request.args.get("organization_id")
    filters = []
    for f in ("organization_id", "machine_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    else:
        if org_filter is not None and org_filter != uid:
            raise access_denied("grower may list only its own organization")
        visible = lambda r: r["organization_id"] == uid
    page, total, limit, offset = list_resources("data_plans", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/data-plans/<pid>/activate")
def activate_plan(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    p = get_or_404("data_plans", pid, "data plan")
    _owning_grower_gate(p, role, uid)
    if p["status"] != "PENDING":
        raise invalid_state("plan is not PENDING")
    org = STORES["organizations"].get(p["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    p["status"] = "ACTIVE"
    p["cycle_anchor_day"] = now().day
    p["cycle_start_date"] = now().date()
    touch(p)
    machine = STORES["machines"].get(p["machine_id"])
    if machine is not None:
        recompute_posture(machine)
    return ok(serialize(p))


@bp.post("/data-plans/<pid>/suspend")
def suspend_plan(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    p = get_or_404("data_plans", pid, "data plan")
    _owning_grower_gate(p, role, uid)
    if p["status"] != "ACTIVE":
        raise invalid_state("plan is not ACTIVE")
    p["status"] = "SUSPENDED"
    touch(p)
    cascade_plan_suspended(p)
    return ok(serialize(p))


@bp.post("/data-plans/<pid>/resume")
def resume_plan(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    p = get_or_404("data_plans", pid, "data plan")
    _owning_grower_gate(p, role, uid)
    if p["status"] != "SUSPENDED":
        raise invalid_state("plan is not SUSPENDED")
    org = STORES["organizations"].get(p["organization_id"])
    if org is None or org["status"] != "ACTIVE":
        raise ApiError(ERR_ORG_SUSPENDED, 409, "owning organization is SUSPENDED")
    p["status"] = "ACTIVE"
    touch(p)
    machine = STORES["machines"].get(p["machine_id"])
    if machine is not None:
        recompute_posture(machine)
    return ok(serialize(p))


@bp.post("/data-plans/<pid>/change-tier")
def change_tier(pid):
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    b = body_json()
    new_tier = as_enum(need(b, "new_tier"), "new_tier", TIERS)
    expected_plan_version = as_int(need(b, "expected_plan_version"), "expected_plan_version")
    p = get_or_404("data_plans", pid, "data plan")
    _owning_grower_gate(p, role, uid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409, "plan is not ACTIVE")
    if new_tier == p["tier"]:
        raise ApiError(ERR_TIER_CHANGE_INVALID, 409, "new_tier equals the current tier")
    # Optimistic concurrency is evaluated last, after every domain rule
    if expected_plan_version != p["version"]:
        raise ApiError(ERR_STALE_PLAN_VERSION, 412, "plan version is stale")
    # The proration charge is computed before the new tier is stored
    charge = compute_proration(p, new_tier)
    p["last_proration_charge_cents"] = charge
    p["tier"] = new_tier
    p["monthly_price_cents"] = TIER_PRICE_CENTS[new_tier]
    p["usage_posture"] = compute_usage_posture(p)
    touch(p)
    machine = STORES["machines"].get(p["machine_id"])
    if machine is not None:
        recompute_posture(machine)
    return ok(serialize(p))
