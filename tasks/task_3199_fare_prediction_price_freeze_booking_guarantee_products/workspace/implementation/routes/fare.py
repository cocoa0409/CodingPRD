"""Flask blueprint for the /fare resource surface.

Route handlers stay thin: validate the request shape, resolve identifiers in
path order, delegate to a service, serialise through the envelope helper.
"""

from flask import Blueprint, g, jsonify, request

from db import DB, fmt, public, touch
from errors import ApiError, fail
from middleware import (
    actor, as_bool, as_enum, as_int, as_int_array, as_num, as_str, as_ts,
    body, owned_itinerary, pagination, page, require_role,
)
from response import ok, ok_empty, ok_list
from services import calc
from services import claims_svc, freeze_svc, itinerary_svc, money_svc
from services import protections_svc as prot
from services import routes_svc as rs

bp = Blueprint("fare", __name__)

ALL_ROLES = ("Traveler", "OpsAgent", "RiskAnalyst", "ClaimsAdjuster", "PlatformAdmin")
FARE_COLLECTIONS = {
    "routes": "routes", "itineraries": "itineraries",
    "price-observations": "price_observations", "demand-curves": "demand_curves",
    "watch-subscriptions": "watch_subscriptions", "price-freezes": "price_freezes",
    "protections": "protections", "claims": "claims", "change-events": "change_events",
    "rebooking-options": "rebooking_options", "payments": "payments",
    "hedging-positions": "hedging_positions", "risk-pools": "risk_pools",
    "destination-options": "destination_options",
}


def created(data):
    return jsonify(ok(data, DB.clock)), 201


def succeeded(data):
    return jsonify(ok(data, DB.clock)), 200


def listed(items, limit, offset, total_count=None):
    """Pagination fields ride inside `meta`; `total_count` is the full size of
    the filtered result set, not the size of the returned page (PRD §2.3)."""
    if total_count is None:
        total_count = len(items)
    return jsonify(ok_list(items, DB.clock, limit, offset, total_count)), 200


def ordered(collection, key=None, predicate=None):
    rows = [r for r in DB.all(collection) if predicate is None or predicate(r)]
    rows.sort(key=key or (lambda r: (r["created_at"], r["id"])))
    return [public(r) for r in rows]


def _created_key(row):
    return (row.get("created_at", ""), row["id"])


# ==========================================================================
# Routes
# ==========================================================================

@bp.post("/fare/routes")
def post_route():
    require_role(("PlatformAdmin",))
    return created(public(rs.register_route(body())))


@bp.get("/fare/routes")
def get_routes():
    require_role(ALL_ROLES)
    limit, offset = pagination()
    region = request.args.get("region")
    posture = request.args.get("posture")
    origin = request.args.get("origin_airport")

    def keep(row):
        if region and row["region"] != region:
            return False
        if posture and row["posture"] != posture:
            return False
        if origin and row["origin_airport"] != origin:
            return False
        return True

    items = ordered("routes", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/routes/<route_id>")
def get_route(route_id):
    require_role(ALL_ROLES)
    return succeeded(public(rs.route_or_404(route_id)))


@bp.patch("/fare/routes/<route_id>")
def patch_route(route_id):
    require_role(("PlatformAdmin",))
    route = rs.route_or_404(route_id)
    return succeeded(public(rs.patch_route(route, body())))


@bp.post("/fare/routes/<route_id>/posture-transitions")
def post_posture(route_id):
    require_role(("PlatformAdmin",))
    route = rs.route_or_404(route_id)
    return succeeded(public(rs.posture_transition(route, body())))


@bp.get("/fare/routes/<route_id>/hedging-positions")
def get_route_positions(route_id):
    require_role(("RiskAnalyst", "PlatformAdmin"))
    route = rs.route_or_404(route_id)
    items = [
        r for r in DB.all("hedging_positions") if r["route_id"] == route["id"]]
    items.sort(key=lambda r: (_created_key(r),))
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.get("/fare/routes/<route_id>/risk-pools")
def get_route_pools(route_id):
    require_role(("RiskAnalyst", "PlatformAdmin"))
    route = rs.route_or_404(route_id)
    items = [r for r in DB.all("risk_pools") if r["region"] == route["region"]]
    items.sort(key=_created_key)
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


# ==========================================================================
# Itineraries
# ==========================================================================

@bp.post("/fare/itineraries")
def post_itinerary():
    require_role(("Traveler", "OpsAgent"))
    data = body()
    if g.actor_role == "Traveler":
        traveler = as_str(data, "traveler_user_id")
        if traveler != g.actor_id:
            fail("ERR_FORBIDDEN_FOR_ACTOR",
                 "a Traveler may only create their own itinerary")
    return created(public(itinerary_svc.create_itinerary(data)))


@bp.get("/fare/itineraries")
def get_itineraries():
    require_role(ALL_ROLES)
    limit, offset = pagination()
    route_id = request.args.get("route_id")
    traveler = request.args.get("traveler_user_id")
    status = request.args.get("travel_status")

    def keep(row):
        if route_id and row["route_id"] != route_id:
            return False
        if traveler and row["traveler_user_id"] != traveler:
            return False
        if status and row["travel_status"] != status:
            return False
        return True

    items = ordered("itineraries", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/itineraries/<itinerary_id>")
def get_itinerary(itinerary_id):
    require_role(ALL_ROLES)
    itinerary = owned_itinerary(itinerary_id, role_aware=False)
    return succeeded(public(itinerary))


@bp.post("/fare/itineraries/<itinerary_id>/watch-subscription")
def post_watch(itinerary_id):
    require_role(("Traveler", "OpsAgent"))
    itinerary = itinerary_svc.itinerary_or_404(itinerary_id)
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    # The watch-subscription endpoint creates a WatchSubscription: the created
    # resource is the watch, not the parent itinerary (PRD §2.2: "operations
    # that create a resource return the created ... resource object").
    watch = itinerary_svc.arm_watch(itinerary_id, body())
    return created(public(watch))


@bp.post("/fare/itineraries/<itinerary_id>/bookings")
def post_booking(itinerary_id):
    require_role(("Traveler", "OpsAgent"))
    itinerary = itinerary_svc.itinerary_or_404(itinerary_id)
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return succeeded(public(itinerary_svc.book(itinerary_id, body())))


@bp.post("/fare/itineraries/<itinerary_id>/cancellations")
def post_itinerary_cancellation(itinerary_id):
    require_role(("Traveler", "OpsAgent"))
    itinerary = itinerary_svc.itinerary_or_404(itinerary_id)
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return succeeded(public(itinerary_svc.cancel_itinerary(itinerary_id, body())))


@bp.get("/fare/itineraries/<itinerary_id>/price-freezes")
def get_itinerary_freezes(itinerary_id):
    require_role(ALL_ROLES)
    rs.itinerary_or_404(itinerary_id)
    items = [r for r in DB.all("price_freezes") if r["itinerary_id"] == itinerary_id]
    items.sort(key=_created_key)
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.get("/fare/itineraries/<itinerary_id>/protections")
def get_itinerary_protections(itinerary_id):
    require_role(ALL_ROLES)
    rs.itinerary_or_404(itinerary_id)
    items = [r for r in DB.all("protections") if r["itinerary_id"] == itinerary_id]
    items.sort(key=_created_key)
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.get("/fare/itineraries/<itinerary_id>/destination-options")
def get_itinerary_destinations(itinerary_id):
    require_role(ALL_ROLES)
    rs.itinerary_or_404(itinerary_id)
    items = [r for r in DB.all("destination_options") if r["itinerary_id"] == itinerary_id]
    items.sort(key=_created_key)
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.post("/fare/itineraries/<itinerary_id>/price-freezes")
def post_itinerary_freeze(itinerary_id):
    require_role(("Traveler", "OpsAgent"))
    itinerary = rs.itinerary_or_404(itinerary_id)
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return created(public(freeze_svc.create_freeze(itinerary, body())))


@bp.post("/fare/itineraries/<itinerary_id>/protections")
def post_itinerary_protection(itinerary_id):
    require_role(("Traveler", "OpsAgent"))
    itinerary = rs.itinerary_or_404(itinerary_id)
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return created(public(prot.quote(body(), itinerary=itinerary)))


# ==========================================================================
# Price observations
# ==========================================================================

@bp.post("/fare/price-observations")
def post_observation():
    require_role(("OpsAgent",))
    return created(public(rs.append_observation(body())))


@bp.get("/fare/price-observations")
def get_observations():
    require_role(("OpsAgent", "RiskAnalyst", "ClaimsAdjuster", "PlatformAdmin"))
    limit, offset = pagination()
    route_id = request.args.get("route_id")
    itinerary_id = request.args.get("itinerary_id")

    def keep(row):
        if route_id and row["route_id"] != route_id:
            return False
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        return True

    items = ordered("price_observations",
                    lambda r: (r.get("_observed_seq", 0), r["id"]), keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/price-observations/<observation_id>")
def get_observation(observation_id):
    require_role(("OpsAgent", "RiskAnalyst", "ClaimsAdjuster", "PlatformAdmin"))
    row = DB.price_observations.get(observation_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no price observation %s" % observation_id)
    return succeeded(public(row))


# ==========================================================================
# Demand curves
# ==========================================================================

@bp.post("/fare/demand-curves")
def post_curve():
    require_role(("OpsAgent",))
    return created(public(rs.publish_curve(body())))


@bp.get("/fare/demand-curves")
def get_curves():
    require_role(("OpsAgent", "RiskAnalyst", "PlatformAdmin"))
    limit, offset = pagination()
    route_id = request.args.get("route_id")

    def keep(row):
        return not route_id or row["route_id"] == route_id

    items = ordered("demand_curves",
                    lambda r: (r.get("_published_seq", 0), r["id"]), keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/demand-curves/<curve_id>")
def get_curve(curve_id):
    require_role(("OpsAgent", "RiskAnalyst", "PlatformAdmin"))
    row = DB.demand_curves.get(curve_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no demand curve %s" % curve_id)
    return succeeded(public(row))


# ==========================================================================
# Watches
# ==========================================================================

@bp.get("/fare/watch-subscriptions")
def get_watches():
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    limit, offset = pagination()
    itinerary_id = request.args.get("itinerary_id")
    status = request.args.get("notification_status")

    def keep(row):
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if status and row["notification_status"] != status:
            return False
        return True

    items = ordered("watch_subscriptions", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/watch-subscriptions/<watch_id>")
def get_watch(watch_id):
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    return succeeded(public(itinerary_svc.watch_or_404(watch_id)))


@bp.post("/fare/watch-subscriptions/<watch_id>/notifications")
def post_notification(watch_id):
    require_role(("Traveler", "OpsAgent"))
    watch = itinerary_svc.watch_or_404(watch_id)
    itinerary = DB.itineraries[watch["itinerary_id"]]
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return succeeded(public(itinerary_svc.notify(watch_id, body())))


@bp.post("/fare/watch-subscriptions/<watch_id>/confirmations")
def post_confirmation(watch_id):
    require_role(("Traveler",))
    watch = itinerary_svc.watch_or_404(watch_id)
    itinerary = DB.itineraries[watch["itinerary_id"]]
    from middleware import require_owner
    require_owner(itinerary)
    return succeeded(public(itinerary_svc.confirm_watch(watch_id, body())))


# ==========================================================================
# Clock + sweeps
# ==========================================================================

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(("PlatformAdmin",))
    data = body()
    instant = as_ts(data, "to_iso8601")
    DB.clock.set(instant)
    # PRD §2.2: a 2xx response with no data carries an empty object.
    return succeeded({})


@bp.post("/_clock/advance")
def advance_clock():
    require_role(("PlatformAdmin",))
    data = body()
    instant = as_ts(data, "to_iso8601")
    if instant > DB.clock.now():
        DB.clock.advance(instant)
    else:
        DB.clock.set(instant)
    run_sweep()
    return succeeded({})


def run_sweep():
    freeze_svc.accrue_due()
    freeze_svc.expire_due()
    itinerary_svc.lapse_watches()
    prot.lapse_change_holds()
    money_svc.retire_aged()
    money_svc.lapse_positions()
    money_svc.unlap_positions()
    derive_sweep()


def derive_sweep():
    """Re-derive curve fields, postural aggregates and every exposure chain."""
    for itinerary in DB.all("itineraries"):
        rs.derive_itinerary(itinerary)
        itinerary["guarantee_locked"] = rs.freeze_locks(itinerary["id"])
    for product in DB.all("protections"):
        if product["quoted_status"] == "QUOTED_FROZEN":
            freeze = DB.price_freezes.get(product.get("freeze_id"))
            if freeze is not None and freeze["status"] in ("FROZEN", "CLAIM_PENDING") \
                    and itinerary_status_of(product) in ("PLANNED", "WATCHING"):
                product["quoted_status"] = "QUOTED_ACTIVE"
                product["bonus_days_total"] = 0
                prot.price_product(product, DB.itineraries[product["_itinerary_id"]],
                                   DB.routes[product["_route_id"]], freeze)
                touch(product)
        elif product["quoted_status"] == "QUOTED":
            freeze = prot.covering_freeze(product["_itinerary_id"])
            if freeze is not None:
                product["quoted_status"] = "QUOTED_FROZEN"
                prot.price_product(product, DB.itineraries[product["_itinerary_id"]],
                                   DB.routes[product["_route_id"]], freeze)
                touch(product)
    for route in DB.all("routes"):
        rs.rebalance_route(route)
    for pool in DB.all("risk_pools"):
        rs.derive_pool(pool)


def itinerary_status_of(product):
    itinerary = DB.itineraries.get(product["_itinerary_id"])
    return itinerary["travel_status"] if itinerary else "CANCELLED"


@bp.post("/fare/hedge-regression-sweeps")
def post_regression_sweep():
    require_role(("PlatformAdmin", "RiskAnalyst"))
    return succeeded(public(money_svc.regression_sweep(body())))


# ==========================================================================
# Price freezes
# ==========================================================================

@bp.post("/fare/price-freezes")
def post_freeze():
    require_role(("Traveler", "OpsAgent"))
    data = body()
    itinerary = rs.itinerary_or_404(as_str(data, "itinerary_id"))
    if g.actor_role == "Traveler":
        from middleware import require_owner
        require_owner(itinerary)
    return created(public(freeze_svc.create_freeze(itinerary, data)))


@bp.get("/fare/price-freezes")
def get_freezes():
    require_role(ALL_ROLES)
    limit, offset = pagination()
    itinerary_id = request.args.get("itinerary_id")
    route_id = request.args.get("route_id")
    status = request.args.get("status")

    def keep(row):
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if route_id and row["_route_id"] != route_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    items = ordered("price_freezes", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/price-freezes/<freeze_id>")
def get_freeze(freeze_id):
    require_role(ALL_ROLES)
    return succeeded(public(freeze_svc.freeze_or_404(freeze_id)))


@bp.post("/fare/price-freezes/<freeze_id>/activations")
def post_activation(freeze_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(freeze_svc.activate(freeze_id, body())))


@bp.post("/fare/price-freezes/<freeze_id>/expirations")
def post_expiration(freeze_id):
    require_role(("OpsAgent", "SystemOperator"))
    data = body()
    expected = None
    if data.get("expected_freeze_version") is not None:
        expected = as_int(data, "expected_freeze_version")
    return succeeded(public(freeze_svc.expire(freeze_id, data, expected)))


@bp.post("/fare/price-freezes/<freeze_id>/conversions")
def post_conversion(freeze_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(freeze_svc.convert(freeze_id, body())))


@bp.post("/fare/price-freezes/<freeze_id>/cancellations")
def post_freeze_cancellation(freeze_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(freeze_svc.cancel(freeze_id, body())))


@bp.post("/fare/price-freezes/<freeze_id>/reinstatements")
def post_reinstatement(freeze_id):
    require_role(("OpsAgent",))
    return succeeded(public(freeze_svc.reinstate(freeze_id, body())))


# ==========================================================================
# Protections
# ==========================================================================

@bp.post("/fare/protections")
def post_protection():
    require_role(("Traveler", "OpsAgent"))
    return created(public(prot.quote(body())))


@bp.get("/fare/protections")
def get_protections():
    require_role(ALL_ROLES)
    limit, offset = pagination()
    itinerary_id = request.args.get("itinerary_id")
    freeze_id = request.args.get("freeze_id")
    product_type = request.args.get("product_type")
    lifecycle = request.args.get("lifecycle_status")

    def keep(row):
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if freeze_id and row.get("freeze_id") != freeze_id:
            return False
        if product_type and row["product_type"] != product_type:
            return False
        if lifecycle and row["lifecycle_status"] != lifecycle:
            return False
        return True

    items = ordered("protections", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/protections/<protection_id>")
def get_protection(protection_id):
    require_role(ALL_ROLES)
    return succeeded(public(prot.protection_or_404(protection_id)))


@bp.post("/fare/protections/<protection_id>/quotes")
def post_quote(protection_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(prot.requote(protection_id, body())))


@bp.post("/fare/protections/<protection_id>/activations")
def post_protection_activation(protection_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(prot.activate(protection_id, body())))


@bp.post("/fare/protections/<protection_id>/cancellations")
def post_protected_cancellation(protection_id):
    require_role(("Traveler",))
    product = prot.protection_or_404(protection_id)
    itinerary = DB.itineraries[product["_itinerary_id"]]
    from middleware import require_owner
    require_owner(itinerary)
    return succeeded(public(prot.protected_cancel(protection_id, body())))


@bp.post("/fare/protections/<protection_id>/reinstatements")
def post_protection_reinstatement(protection_id):
    require_role(("OpsAgent",))
    return succeeded(public(prot.reinstate(protection_id, body())))


@bp.post("/fare/protections/<protection_id>/change-events")
def post_change_event(protection_id):
    require_role(("Traveler", "OpsAgent"))
    return created(public(prot.file_change_event(protection_id, body())))


@bp.post("/fare/protections/<protection_id>/terminations")
def post_termination(protection_id):
    require_role(("OpsAgent",))
    return succeeded(public(prot.terminate(protection_id, body())))


# ==========================================================================
# Claims
# ==========================================================================

@bp.post("/fare/claims")
def post_claim():
    require_role(("Traveler",))
    data = body()
    freeze = freeze_svc.freeze_or_404(as_str(data, "freeze_id"))
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    from middleware import require_owner
    require_owner(itinerary)
    return created(public(claims_svc.file_claim(freeze["id"], data)))


@bp.post("/fare/price-freezes/<freeze_id>/claims")
def post_freeze_claim(freeze_id):
    require_role(("Traveler",))
    freeze = freeze_svc.freeze_or_404(freeze_id)
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    from middleware import require_owner
    require_owner(itinerary)
    return created(public(claims_svc.file_claim(freeze_id, body())))


@bp.get("/fare/claims")
def get_claims():
    require_role(("Traveler", "ClaimsAdjuster", "RiskAnalyst", "PlatformAdmin"))
    limit, offset = pagination()
    freeze_id = request.args.get("freeze_id")
    itinerary_id = request.args.get("itinerary_id")
    status = request.args.get("claim_status")
    approver = request.args.get("approver_user_id")

    def keep(row):
        if freeze_id and row["freeze_id"] != freeze_id:
            return False
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if status and row["claim_status"] != status:
            return False
        if approver and row.get("approver_user_id") != approver:
            return False
        return True

    items = ordered("claims", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/claims/<claim_id>")
def get_claim(claim_id):
    require_role(("Traveler", "ClaimsAdjuster", "RiskAnalyst", "PlatformAdmin"))
    return succeeded(public(claims_svc.claim_or_404(claim_id)))


@bp.post("/fare/claims/<claim_id>/reviews")
def post_review(claim_id):
    require_role(("ClaimsAdjuster",))
    return succeeded(public(claims_svc.review(claim_id, body())))


@bp.post("/fare/claims/<claim_id>/approvals")
def post_approval(claim_id):
    require_role(("ClaimsAdjuster",))
    return succeeded(public(claims_svc.approve(claim_id, body())))


@bp.post("/fare/claims/<claim_id>/rejections")
def post_rejection(claim_id):
    require_role(("ClaimsAdjuster",))
    return succeeded(public(claims_svc.reject(claim_id, body())))


@bp.post("/fare/claims/<claim_id>/withdrawals")
def post_withdrawal(claim_id):
    require_role(("Traveler",))
    return succeeded(public(claims_svc.withdraw(claim_id, body())))


@bp.post("/fare/claims/<claim_id>/reconsiderations")
def post_reconsideration(claim_id):
    require_role(("ClaimsAdjuster",))
    return succeeded(public(claims_svc.reconsider(claim_id, body())))


@bp.post("/fare/claims/<claim_id>/settlements")
def post_settlement(claim_id):
    # The segregation audit outranks the role-entitlement gate (PRD §2.5: an
    # approval, review or settlement attempted by the claim's own filer or by the
    # adjuster who approved it fails with ERR_SOD_VIOLATION before anything else).
    # Entitlement is therefore checked inside the service, where the acting
    # identity can be compared against the claim's recorded filer and approver.
    actor()
    return succeeded(public(claims_svc.settle(claim_id, body())))


# ==========================================================================
# Change events and rebooking options
# ==========================================================================

@bp.post("/fare/change-events")
def post_change_event_body():
    require_role(("Traveler", "OpsAgent"))
    data = body()
    return created(public(prot.file_change_event(as_str(data, "protection_id"), data)))


@bp.get("/fare/change-events")
def get_change_events():
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    limit, offset = pagination()
    protection_id = request.args.get("protection_id")
    itinerary_id = request.args.get("itinerary_id")
    status = request.args.get("status")

    def keep(row):
        if protection_id and row["protection_id"] != protection_id:
            return False
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    items = ordered("change_events", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/change-events/<change_event_id>")
def get_change_event(change_event_id):
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    return succeeded(public(prot.change_event_or_404(change_event_id)))


@bp.post("/fare/change-events/<change_event_id>/selections")
def post_selection(change_event_id):
    require_role(("Traveler",))
    return succeeded(public(prot.select_option(change_event_id, body())))


@bp.post("/fare/change-events/<change_event_id>/settlements")
def post_change_settlement(change_event_id):
    require_role(("Traveler",))
    event = prot.change_event_or_404(change_event_id)
    itinerary = DB.itineraries[event["_itinerary_id"]]
    from middleware import require_owner
    require_owner(itinerary)
    return succeeded(public(prot.settle_change(change_event_id, body())))


@bp.post("/fare/change-events/<change_event_id>/cancellations")
def post_change_cancellation(change_event_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(prot.cancel_change_event(change_event_id, body())))


@bp.get("/fare/change-events/<change_event_id>/rebooking-options")
def get_event_options(change_event_id):
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    prot.change_event_or_404(change_event_id)
    items = [r for r in DB.all("rebooking_options")
             if r["change_event_id"] == change_event_id]
    items.sort(key=lambda r: (r["sequence_index"], r["id"]))
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.post("/fare/rebooking-options")
def post_option():
    require_role(("Traveler", "OpsAgent"))
    return created(public(prot.create_rebooking_option(body())))


@bp.get("/fare/rebooking-options")
def get_options():
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    limit, offset = pagination()
    change_event_id = request.args.get("change_event_id")
    status = request.args.get("status")

    def keep(row):
        if change_event_id and row["change_event_id"] != change_event_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    items = ordered("rebooking_options", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/rebooking-options/<option_id>")
def get_option(option_id):
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    row = DB.rebooking_options.get(option_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no rebooking option %s" % option_id)
    return succeeded(public(row))


@bp.post("/fare/rebooking-options/<option_id>/acceptances")
def post_acceptance(option_id):
    require_role(("Traveler",))
    return succeeded(public(prot.accept_option(option_id, body())))


@bp.post("/fare/rebooking-options/<option_id>/hold-reversions")
def post_hold_reversion(option_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(prot.revert_option(option_id, body())))


# ==========================================================================
# Destination options
# ==========================================================================

@bp.post("/fare/destination-options")
def post_destination_option():
    require_role(("Traveler", "OpsAgent"))
    return created(public(prot.create_destination_option(body())))


@bp.get("/fare/destination-options")
def get_destination_options():
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    limit, offset = pagination()
    itinerary_id = request.args.get("itinerary_id")
    direction = request.args.get("direction")

    def keep(row):
        if itinerary_id and row["itinerary_id"] != itinerary_id:
            return False
        if direction and row["direction"] != direction:
            return False
        return True

    items = ordered("destination_options", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/destination-options/<destination_option_id>")
def get_destination_option(destination_option_id):
    require_role(("Traveler", "OpsAgent", "ClaimsAdjuster", "PlatformAdmin"))
    return succeeded(public(prot.destination_option_or_404(destination_option_id)))


@bp.post("/fare/destination-options/<destination_option_id>/selections")
def post_destination_selection(destination_option_id):
    require_role(("Traveler",))
    return succeeded(public(prot.bind_destination_option(destination_option_id, body())))


@bp.post("/fare/destination-options/<destination_option_id>/releases")
def post_destination_release(destination_option_id):
    require_role(("Traveler", "OpsAgent"))
    return succeeded(public(prot.release_destination_option(destination_option_id, body())))


# ==========================================================================
# Payments
# ==========================================================================

@bp.post("/fare/payments")
def post_payment():
    require_role(("OpsAgent",))
    return created(public(money_svc.record_payment(body())))


@bp.get("/fare/payments")
def get_payments():
    require_role(ALL_ROLES)
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in
               ("itinerary_id", "freeze_id", "protection_id", "claim_id", "status")}

    def keep(row):
        for key, value in filters.items():
            if value and row.get(key) != value:
                return False
        return True

    items = ordered("payments", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/payments/<payment_id>")
def get_payment(payment_id):
    require_role(ALL_ROLES)
    return succeeded(public(money_svc.payment_or_404(payment_id)))


@bp.get("/fare/price-freezes/<freeze_id>/payments")
def get_freeze_payments(freeze_id):
    require_role(ALL_ROLES)
    freeze_svc.freeze_or_404(freeze_id)
    items = [r for r in DB.all("payments") if r["freeze_id"] == freeze_id]
    items.sort(key=_created_key)
    total = len(items)
    return listed([public(r) for r in items], 100, 0, total)


@bp.post("/fare/payments/<payment_id>/captures")
def post_capture(payment_id):
    require_role(("OpsAgent",))
    return succeeded(public(money_svc.capture(payment_id, body())))


@bp.post("/fare/payments/<payment_id>/refunds")
def post_refund(payment_id):
    require_role(("OpsAgent", "ClaimsAdjuster"))
    return succeeded(public(money_svc.refund(payment_id, body())))


# ==========================================================================
# Hedging positions and pools
# ==========================================================================

@bp.post("/fare/hedging-positions")
def post_position():
    require_role(("RiskAnalyst",))
    return created(public(money_svc.open_position(body())))


@bp.get("/fare/hedging-positions")
def get_positions():
    require_role(("RiskAnalyst", "PlatformAdmin"))
    limit, offset = pagination()
    route_id = request.args.get("route_id")
    pool_id = request.args.get("pool_id")
    status = request.args.get("status")

    def keep(row):
        if route_id and row["route_id"] != route_id:
            return False
        if pool_id and row.get("pool_id") != pool_id:
            return False
        if status and row["status"] != status:
            return False
        return True

    items = ordered("hedging_positions", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/hedging-positions/<position_id>")
def get_position(position_id):
    require_role(("RiskAnalyst", "PlatformAdmin"))
    return succeeded(public(money_svc.position_or_404(position_id)))


@bp.post("/fare/hedging-positions/<position_id>/marks")
def post_mark(position_id):
    require_role(("RiskAnalyst",))
    return succeeded(public(money_svc.mark_position(position_id, body())))


@bp.post("/fare/hedging-positions/<position_id>/settlements")
def post_position_settlement(position_id):
    require_role(("RiskAnalyst",))
    return succeeded(public(money_svc.settle_position(position_id, body())))


@bp.post("/fare/risk-pools")
def post_pool():
    require_role(("RiskAnalyst",))
    return created(public(money_svc.open_pool(body())))


@bp.get("/fare/risk-pools")
def get_pools():
    require_role(("RiskAnalyst", "PlatformAdmin"))
    limit, offset = pagination()
    region = request.args.get("region")
    status = request.args.get("status")

    def keep(row):
        if region and row["region"] != region:
            return False
        if status and row["status"] != status:
            return False
        return True

    items = ordered("risk_pools", _created_key, keep)
    total = len(items)
    return listed(items[offset:offset + limit], limit, offset, total)


@bp.get("/fare/risk-pools/<pool_id>")
def get_pool(pool_id):
    require_role(("RiskAnalyst", "PlatformAdmin"))
    return succeeded(public(money_svc.pool_or_404(pool_id)))