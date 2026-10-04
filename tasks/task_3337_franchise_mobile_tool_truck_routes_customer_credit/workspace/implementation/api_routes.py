"""Route lifecycle, territory development and territory resale."""

from flask import Blueprint

import auth
import calc
import clock
import envelope
import lookup
import recompute
import store
from errors import fail

bp = Blueprint("routes", __name__, url_prefix="/retail")

ROUTE_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer",
               "RouteSalesRep", "WarrantyAdmin")
LIFECYCLE_ACTIONS = ("ACTIVATE", "SUSPEND", "REINSTATE", "RETIRE")
TERRITORY_ACTIONS = ("DEVELOP", "SURRENDER")
RESALE_ACTIONS = ("FILE", "APPROVE", "DECLINE")
ROUTE_TIERS = ("A", "B", "C")
MIX_PLANS = ("DIAGNOSTIC_WEIGHTED", "TOOL_STORAGE", "POWER_TOOLS")
TERRITORY_MODELS = ("FRANCHISEE_ASSUMED", "FRANCHISOR_RECOURSE")
BUYER_TRAINING = ("NOT_ENROLLED", "ENROLLED", "CERTIFIED")


@bp.get("/routes")
def list_routes():
    auth.require(*ROUTE_ROLES)
    rows = envelope.filter_query(store.ordered(store.routes), {
        "franchisee_id": "franchisee_id",
        "route_status": "route_status",
        "territory_development_status": "territory_development_status",
        "resale_status": "resale_status",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.get("/routes/<route_id>")
def get_route(route_id):
    auth.require(*ROUTE_ROLES)
    route = lookup.route(route_id)
    recompute.recompute_route(route)
    return envelope.ok(route)


@bp.put("/routes/<route_id>")
def update_route(route_id):
    user_id, role = auth.require("FranchiseOwner")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()

    if payload.get("route_code") is not None:
        code = envelope.as_str(payload, "route_code")
        for other in store.routes.values():
            if other.get("route_code") == code and other["id"] != route["id"]:
                fail("ERR_ROUTE_CODE_DUPLICATE")
        store.set_field(route, "route_code", code)
    if payload.get("route_tier") is not None:
        store.set_field(route, "route_tier", envelope.as_enum(payload, "route_tier", ROUTE_TIERS))
    if payload.get("zip_codes") is not None:
        codes = envelope.as_list(payload, "zip_codes")
        for entry in codes:
            if not isinstance(entry, str) or not entry:
                fail("ERR_INVALID_REQUEST", "zip_codes must be an array of strings.")
        store.set_field(route, "zip_codes", list(codes))
    if payload.get("visit_weekday") is not None:
        store.set_field(route, "visit_weekday",
                        envelope.as_int(payload, "visit_weekday", minimum=1, maximum=7))
    if payload.get("truck_label") is not None:
        store.set_field(route, "truck_label", envelope.as_str(payload, "truck_label"))
    if payload.get("inventory_invested_cents") is not None:
        store.set_field(route, "inventory_invested_cents",
                        envelope.as_int(payload, "inventory_invested_cents", minimum=0))
    if payload.get("mix_plan") is not None:
        mix = envelope.as_enum(payload, "mix_plan", MIX_PLANS)
        for other in store.routes.values():
            if (other["id"] != route["id"]
                    and other.get("franchisee_id") == route.get("franchisee_id")
                    and other.get("mix_plan") == mix):
                fail("ERR_UNIQUENESS_VIOLATION",
                     "The territory-level product mix is already used by this franchisee.")
        store.set_field(route, "mix_plan", mix)
    if payload.get("territory_model") is not None:
        store.set_field(route, "territory_model",
                        envelope.as_enum(payload, "territory_model", TERRITORY_MODELS))
    if payload.get("territory_points") is not None:
        store.set_field(route, "territory_points",
                        envelope.as_int(payload, "territory_points", minimum=0))

    recompute.recompute_route(route)
    return envelope.ok(route)


@bp.post("/routes/<route_id>/status")
def advance_route(route_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", LIFECYCLE_ACTIONS)

    expected = payload.get("expected_route_version")
    if action == "RETIRE":
        if expected is None:
            fail("ERR_INVALID_REQUEST", "expected_route_version is required to retire a route.")
        if not isinstance(expected, int) or isinstance(expected, bool):
            fail("ERR_INVALID_REQUEST", "expected_route_version must be an integer.")
        if expected != route.get("version"):
            fail("ERR_STALE_VERSION")
    elif expected is not None:
        fail("ERR_INVALID_REQUEST",
             "expected_route_version is only accepted by the retire action.")

    status = route.get("route_status")
    if action == "ACTIVATE":
        if status != "DRAFT":
            fail("ERR_ROUTE_ALREADY_IN_SERVICE")
        if not route.get("zip_codes"):
            fail("ERR_INVALID_STATE", "The route's zip_codes array is empty.")
        if route.get("inventory_invested_cents", 0) < 1:
            fail("ERR_INVALID_STATE", "The route's inventory investment is below 1 cent.")
        franchisee = lookup.franchisee(route.get("franchisee_id"))
        if franchisee.get("training_status") != "CERTIFIED":
            fail("ERR_FRANCHISEE_NOT_CERTIFIED")
        store.set_field(route, "route_status", "IN_SERVICE")
        recompute.recompute_route(route)
    elif action == "SUSPEND":
        if status != "IN_SERVICE":
            fail("ERR_INVALID_STATE")
        store.set_field(route, "route_status", "SUSPENDED")
        for shop in store.shops.values():
            if shop.get("route_id") == route["id"] and shop.get("shop_status") == "ACTIVE":
                store.set_field(shop, "shop_status", "INACTIVE")
                recompute.recompute_shop(shop)
    elif action == "REINSTATE":
        if status != "SUSPENDED":
            fail("ERR_INVALID_STATE")
        store.set_field(route, "route_status", "IN_SERVICE")
    else:
        if status not in ("DRAFT", "SUSPENDED"):
            fail("ERR_INVALID_STATE")
        if route.get("resale_status") == "PENDING":
            fail("ERR_INVALID_STATE", "A route with a pending resale filing may not be retired.")
        store.set_field(route, "route_status", "RETIRED")
        if route.get("territory_development_status") == "QUALIFIED":
            store.set_field(route, "territory_development_status", "SURRENDERED")
            store.set_field(route, "in_force_to_week", clock.fmt_week(clock.current_week_start()))

    store.stamp(route)
    recompute.recompute_franchisee_of_route(route)
    return envelope.ok(route)


@bp.post("/routes/<route_id>/territory")
def advance_territory(route_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", TERRITORY_ACTIONS)
    points = envelope.as_int(payload, "territory_points", minimum=0)

    development = route.get("territory_development_status")
    if action == "DEVELOP":
        if development in ("UNASSIGNED", "QUALIFIED"):
            if not route.get("territory_model"):
                fail("ERR_INVALID_STATE", "The route has no territory_model.")
            if development == "UNASSIGNED":
                if route.get("in_force_from_week") and not route.get("in_force_to_week"):
                    fail("ERR_TERRITORY_WINDOW_CONFLICT")
                qualifies = (points >= 60
                             and route.get("route_status") == "IN_SERVICE")
                if qualifies:
                    franchisee = lookup.franchisee(route.get("franchisee_id"))
                    if franchisee.get("training_status") != "CERTIFIED":
                        fail("ERR_FRANCHISEE_NOT_CERTIFIED")
                store.set_field(route, "territory_development_status", "IN_DEVELOPMENT")
                store.set_field(route, "territory_points", points)
                store.set_field(route, "in_force_from_week",
                                clock.fmt_week(clock.current_week_start()))
                if qualifies:
                    store.set_field(route, "territory_development_status", "QUALIFIED")
            else:
                store.set_field(route, "territory_development_status", "IN_DEVELOPMENT")
                store.set_field(route, "territory_points", 0)
                store.set_field(route, "in_force_to_week", None)
        elif development == "IN_DEVELOPMENT":
            if points >= 60:
                if route.get("route_status") != "IN_SERVICE":
                    fail("ERR_ROUTE_NOT_IN_SERVICE")
                franchisee = lookup.franchisee(route.get("franchisee_id"))
                if franchisee.get("training_status") != "CERTIFIED":
                    fail("ERR_FRANCHISEE_NOT_CERTIFIED")
                store.set_field(route, "territory_points", points)
                store.set_field(route, "territory_development_status", "QUALIFIED")
            else:
                store.set_field(route, "territory_points", points)
        else:
            fail("ERR_INVALID_STATE")
    else:
        if development not in ("QUALIFIED", "IN_DEVELOPMENT"):
            fail("ERR_INVALID_STATE")
        if route.get("resale_status") != "NONE":
            fail("ERR_INVALID_STATE", "Surrender is refused while a resale filing is live.")
        store.set_field(route, "territory_development_status", "SURRENDERED")
        store.set_field(route, "in_force_to_week", clock.fmt_week(clock.current_week_start()))

    store.stamp(route)
    return envelope.ok(route)


@bp.post("/routes/<route_id>/resale")
def advance_resale(route_id):
    user_id, role = auth.require("FranchiseOwner", "FranchiseManager")
    route = lookup.route(route_id)
    auth.ensure_owned(user_id, role, route.get("franchisee_id"))
    payload = envelope.body()
    action = envelope.as_enum(payload, "action", RESALE_ACTIONS)

    resale = route.get("resale_status")
    if action == "FILE":
        if resale == "PENDING":
            fail("ERR_RESALE_ALREADY_PENDING")
        if resale not in ("NONE", "DECLINED"):
            fail("ERR_INVALID_STATE")
        if route.get("territory_development_status") != "QUALIFIED":
            fail("ERR_TERRITORY_NOT_QUALIFIED")
        franchisee = lookup.franchisee(route.get("franchisee_id"))
        if franchisee.get("training_status") != "CERTIFIED":
            fail("ERR_FRANCHISEE_NOT_CERTIFIED")
        buyer_status = envelope.as_enum(payload, "buyer_training_status", BUYER_TRAINING,
                                        required=False, default="NOT_ENROLLED")
        buyer_points = envelope.as_int(payload, "buyer_training_points", required=False,
                                       default=0, minimum=0)
        store.set_field(route, "resale_buyer_training_status", buyer_status)
        store.set_field(route, "resale_trained_points", buyer_points)
        store.set_field(route, "reopening_fee_cents",
                        calc.reopening_fee(buyer_status, buyer_points))
        store.set_field(route, "resale_status", "PENDING")
    elif action == "APPROVE":
        if resale != "PENDING":
            fail("ERR_RESALE_NOT_PENDING")
        if route.get("reopening_fee_cents", 0) > calc.FRANCHISEE_RESALE_FEE_CAP_CENTS:
            fail("ERR_INVALID_STATE", "The reopening fee exceeds the franchisee resale fee cap.")
        store.set_field(route, "resale_status", "APPROVED")
    else:
        if resale != "PENDING":
            fail("ERR_RESALE_NOT_PENDING")
        store.set_field(route, "resale_status", "DECLINED")

    store.stamp(route)
    return envelope.ok(route)
