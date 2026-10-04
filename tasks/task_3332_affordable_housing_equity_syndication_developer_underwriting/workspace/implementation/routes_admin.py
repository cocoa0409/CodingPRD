"""Developers, investors and the logical clock."""

from flask import Blueprint, request

import clock
import response
import state
import store
import validate

bp = Blueprint("admin", __name__)

DEVELOPER_TYPES = ("NONPROFIT", "FOR_PROFIT", "JOINT_VENTURE")
INVESTOR_TYPES = ("BANK", "INSURANCE", "CORPORATE", "FOUNDATION", "PENSION")
RISK_TIERS = ("TIER_1", "TIER_2", "TIER_3")

READ_DEVELOPER = ("Developer", "Underwriter", "AssetManager", "ComplianceOfficer", "PlatformAdmin")
READ_INVESTOR = ("Investor", "Underwriter", "AssetManager", "PlatformAdmin")


@bp.post("/developers")
def create_developer():
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("PlatformAdmin",))
    payload = validate.body(request)
    name = validate.as_string(payload, "name")
    developer_type = validate.in_enum(validate.as_string(payload, "developer_type"),
                                      DEVELOPER_TYPES, "developer_type")
    months = validate.non_negative(validate.as_int(payload, "sponsor_experience_months"),
                                   "sponsor_experience_months")
    completed = validate.non_negative(validate.as_int(payload, "projects_completed"),
                                      "projects_completed")
    net_worth = validate.non_negative(validate.as_int(payload, "net_worth_cents"), "net_worth_cents")
    liquid = validate.non_negative(validate.as_int(payload, "liquid_assets_cents"), "liquid_assets_cents")

    developer = store.create(store.developers, {
        "name": name,
        "developer_type": developer_type,
        "sponsor_experience_months": months,
        "projects_completed": completed,
        "net_worth_cents": net_worth,
        "liquid_assets_cents": liquid,
        "guarantee_exposure_cents": 0,
        "active_project_count": 0,
        "status": "ELIGIBLE",
    })
    state.recompute_developer(developer["id"])
    return response.ok(store.public(developer), 201)


@bp.get("/developers/<developer_id>")
def read_developer(developer_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_DEVELOPER)
    developer = validate.get_developer(developer_id)
    validate.scope_developer(role, user_id, developer_id)
    state.recompute_developer(developer_id)
    return response.ok(store.public(developer), 200)


@bp.post("/investors")
def create_investor():
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("PlatformAdmin",))
    payload = validate.body(request)
    name = validate.as_string(payload, "name")
    investor_type = validate.in_enum(validate.as_string(payload, "investor_type"),
                                     INVESTOR_TYPES, "investor_type")
    capacity = validate.non_negative(validate.as_int(payload, "committed_capacity_cents"),
                                     "committed_capacity_cents")
    risk_tier = validate.in_enum(validate.as_string(payload, "risk_tier"), RISK_TIERS, "risk_tier")

    investor = store.create(store.investors, {
        "name": name,
        "investor_type": investor_type,
        "committed_capacity_cents": capacity,
        "risk_tier": risk_tier,
        "outstanding_commitment_cents": 0,
        "funded_cents": 0,
        "status": "ACTIVE",
    })
    state.recompute_investor(investor["id"])
    return response.ok(store.public(investor), 201)


@bp.get("/investors/<investor_id>")
def read_investor(investor_id):
    role, user_id = validate.authenticate(request)
    validate.require_role(role, READ_INVESTOR)
    investor = validate.get_investor(investor_id)
    if role == "Investor" and user_id != investor_id:
        from errors import ERR_FORBIDDEN_SCOPE, fail
        fail(ERR_FORBIDDEN_SCOPE, "An Investor may read only its own record.")
    state.recompute_investor(investor_id)
    return response.ok(store.public(investor), 200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _ = validate.authenticate(request)
    validate.require_role(role, ("PlatformAdmin",))
    payload = validate.body(request)
    validate.required(payload, ["current_utc"])
    supplied = payload["current_utc"]
    try:
        instant = clock._parse(supplied)
    except Exception:
        from errors import ERR_INVALID_REQUEST, fail
        fail(ERR_INVALID_REQUEST, "current_utc must be an ISO 8601 instant.")
    clock.set_now(instant)
    state.on_clock_advanced()
    return response.ok({"current_utc": supplied}, 200)
