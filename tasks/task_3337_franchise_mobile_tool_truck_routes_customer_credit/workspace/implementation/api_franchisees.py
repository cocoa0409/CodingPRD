"""Franchisee endpoints: standing, training, draft summary and route creation."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("franchisees", __name__, url_prefix="/retail")

TRAINING_ACTIONS = ("ENROLL", "CERTIFY", "RECERTIFY")
ROUTE_TIERS = ("A", "B", "C")
MIX_PLANS = ("DIAGNOSTIC_WEIGHTED", "TOOL_STORAGE", "POWER_TOOLS")
TERRITORY_MODELS = ("FRANCHISEE_ASSUMED", "FRANCHISOR_RECOURSE")


@bp.post("/franchisees")
def create_franchisee():
    auth.require("PlatformAdmin")
    payload = envelope.body()
    legal_name = envelope.as_str(payload, "legal_name")
    franchisee = store.create(
        store.franchisees,
        legal_name=legal_name,
        training_status="NOT_ENROLLED",
        training_points=0,
        certified_on=None,
        total_route_count=0,
        active_route_count=0,
        credit_ceiling_cents=0,
        outstanding_credit_cents=0,
        recourse_exposure_cents=0,
        franchisee_capital_at_risk_cents=0,
        fallback_shop_location_id=None,
        can_resell_territory=False,
    )
    return envelope.ok(franchisee, 201)


@bp.get("/franchisees")
def list_franchisees():
    auth.require("PlatformAdmin", "FranchiseManager", "CreditOfficer")
    rows = envelope.filter_query(store.ordered(store.franchisees),
                                 {"training_status": "training_status"})
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/franchisees/<franchisee_id>/draft-summary")
def draft_summary(franchisee_id):
    auth.require("PlatformAdmin", "FranchiseManager", "CreditOfficer")
    franchisee = lookup.franchisee(franchisee_id)
    recompute.recompute_franchisee(franchisee)
    if not franchisee.get("fallback_shop_location_id"):
        fail("ERR_FALLBACK_LOCATION_MISSING")
    active_accounts = [a for a in store.accounts.values()
                       if a.get("account_status") == "ACTIVE"
                       and _owned_by(a, franchisee["id"])]
    return envelope.ok({
        "franchisee_id": franchisee["id"],
        "fallback_shop_location_id": franchisee["fallback_shop_location_id"],
        "active_account_count": len(active_accounts),
        "recourse_exposure_cents": franchisee.get("recourse_exposure_cents", 0),
    })


def _owned_by(account, franchisee_id):
    route = store.routes.get(account.get("territory_id"))
    return bool(route) and route.get("franchisee_id") == franchisee_id


@bp.get("/franchisees/<franchisee_id>")
def get_franchisee(franchisee_id):
    user_id, role = auth.require("PlatformAdmin", "FranchiseOwner", "FranchiseManager",
                                 "CreditOfficer")
    franchisee = lookup.franchisee(franchisee_id)
    auth.ensure_owned(user_id, role, franchisee["id"])
    recompute.recompute_franchisee(franchisee)
    return envelope.ok(franchisee)


@bp.post("/franchisees/<franchisee_id>/training")
def advance_training(franchisee_id):
    user_id, role = auth.require("FranchiseOwner")
    franchisee = lookup.franchisee(franchisee_id)
    auth.ensure_owned(user_id, role, franchisee["id"])
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", TRAINING_ACTIONS)
    points = envelope.as_int(payload, "training_points", minimum=0)

    status = franchisee.get("training_status")
    if action == "ENROLL":
        if status != "NOT_ENROLLED":
            fail("ERR_INVALID_STATE")
        franchisee["training_points"] = points
        new_status = calc.franchisee_training_progress(points)
    elif action == "CERTIFY":
        if status != "ENROLLED":
            fail("ERR_INVALID_STATE")
        if points < calc.CERTIFICATION_THRESHOLD:
            fail("ERR_CERTIFICATION_POINTS_SHORT")
        franchisee["training_points"] = points
        new_status = "CERTIFIED"
    else:
        if status != "CERTIFIED":
            fail("ERR_INVALID_STATE")
        franchisee["training_points"] = points
        new_status = "ENROLLED"

    store.set_field(franchisee, "training_status", new_status)
    store.set_field(franchisee, "certified_on",
                    clock.fmt_week(clock.now()) if new_status == "CERTIFIED" else None)
    store.set_field(franchisee, "can_resell_territory", new_status == "CERTIFIED")
    store.stamp(franchisee)
    return envelope.ok(franchisee)


@bp.post("/franchisees/<franchisee_id>/routes")
def create_route(franchisee_id):
    user_id, role = auth.require("FranchiseOwner")
    franchisee = lookup.franchisee(franchisee_id)
    auth.ensure_owned(user_id, role, franchisee["id"])
    payload = envelope.body()

    route_code = envelope.as_str(payload, "route_code")
    route_tier = envelope.as_enum(payload, "route_tier", ROUTE_TIERS)
    zip_codes = envelope.as_list(payload, "zip_codes")
    for entry in zip_codes:
        if not isinstance(entry, str) or not entry:
            fail("ERR_INVALID_REQUEST", "zip_codes must be an array of strings.")
    visit_weekday = envelope.as_int(payload, "visit_weekday", minimum=1, maximum=7)
    truck_label = envelope.as_str(payload, "truck_label")
    inventory_invested_cents = envelope.as_int(payload, "inventory_invested_cents", minimum=0)
    mix_plan = envelope.as_enum(payload, "mix_plan", MIX_PLANS)
    territory_model = envelope.as_enum(payload, "territory_model", TERRITORY_MODELS)
    territory_points = envelope.as_int(payload, "territory_points", required=False, default=0,
                                       minimum=0)

    for route in store.routes.values():
        if route.get("route_code") == route_code:
            fail("ERR_ROUTE_CODE_DUPLICATE")
    for route in store.routes.values():
        if route.get("franchisee_id") == franchisee["id"] and route.get("mix_plan") == mix_plan:
            fail("ERR_UNIQUENESS_VIOLATION",
                 "The territory-level product mix is already used by this franchisee.")

    route = store.create(
        store.routes,
        franchisee_id=franchisee["id"],
        route_code=route_code,
        route_tier=route_tier,
        zip_codes=list(zip_codes),
        visit_weekday=visit_weekday,
        truck_label=truck_label,
        inventory_invested_cents=inventory_invested_cents,
        mix_plan=mix_plan,
        territory_model=territory_model,
        territory_points=territory_points,
        inventory_at_risk_cents=0,
        over_pledge_cents=0,
        schedule_anchor_utc=clock.fmt_week(clock.route_anchor(visit_weekday)),
        route_status="DRAFT",
        territory_development_status="UNASSIGNED",
        in_force_from_week=None,
        in_force_to_week=None,
        resale_status="NONE",
        resale_buyer_training_status="NOT_ENROLLED",
        resale_trained_points=0,
        reopening_fee_cents=0,
        launch_risk_band="HIGH",
    )
    recompute.recompute_franchisee(franchisee)
    return envelope.ok(route, 201)
