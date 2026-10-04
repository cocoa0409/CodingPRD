"""Disease events and depopulation orders (PRD §3.3): report, confirm (the
three-link cascade), dismiss, issue and complete depopulation orders."""

from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, require_role
from calc import depop_downtime_days, recompute_hen_inventory, recompute_postures
from db import STORE, set_dt, stamp_new, touch
from errors import (
    ApiError,
    ERR_DEPOPULATION_ORDER_EXISTS,
    ERR_HOUSE_NOT_FOUND,
    ERR_HOUSE_NOT_IN_SCOPE,
    ERR_INVALID_STATE,
    ERR_NO_ACTIVE_FLOCK_IN_HOUSE,
    ERR_SCOPE_HOUSE_NOT_IN_COMPLEX,
)
from helpers import (
    get_complex,
    get_depop_order,
    get_disease_event,
    get_house,
    list_response,
)
from serialize import serialize_depop_order, serialize_disease_event
from util import DISPOSAL_METHODS, PATHOGENS, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("disease", __name__)


@bp.route("/api/complexes/<cid>/disease-events", methods=["POST"])
def create_disease_event(cid):
    _uid, role = authenticate()
    require_role(role, {"HealthOfficial"})
    cx = get_complex(cid)
    body = get_body()
    # Priority 5 (body-reference existence) precedes priority 6 (shape):
    # every scope member must resolve before the payload shape is judged.
    raw_scope = body.get("scope_house_ids") if isinstance(body, dict) else None
    if isinstance(raw_scope, list):
        for hid in raw_scope:
            if isinstance(hid, str) and hid not in STORE.houses:
                raise ApiError(ERR_HOUSE_NOT_FOUND, 404, "house not found: %s" % hid)
    values, raws = validate_payload(
        body,
        {
            "pathogen": {"kind": "enum", "required": True, "enum": PATHOGENS},
            "detection_date": {"kind": "datetime", "required": True},
            "scope_house_ids": {
                "kind": "str_list", "required": True, "non_empty": True,
            },
        },
    )
    for hid in values["scope_house_ids"]:
        house = STORE.houses.get(hid)
        if house is None:
            raise ApiError(ERR_HOUSE_NOT_FOUND, 404, "house not found: %s" % hid)
        if house["complex_id"] != cx["id"]:
            raise ApiError(
                ERR_SCOPE_HOUSE_NOT_IN_COMPLEX,
                422,
                "scope house %s does not belong to this complex" % hid,
            )
    event = {
        "complex_id": cx["id"],
        "pathogen": values["pathogen"],
        "scope_house_ids": list(values["scope_house_ids"]),
        "status": "SUSPECTED",
        "confirmed_at": None,
        "_dt_confirmed_at": None,
        "cleared_at": None,
        "_dt_cleared_at": None,
    }
    apply_values(event, {"detection_date": values["detection_date"]},
                 {"detection_date": raws["detection_date"]})
    stamp_new(event)
    STORE.disease_events[event["id"]] = event
    # The mere report recomputes posture region-wide (own complex -> ELEVATED).
    recompute_postures()
    return success_object(serialize_disease_event(event), 201)


@bp.route("/api/complexes/<cid>/disease-events", methods=["GET"])
def list_disease_events(cid):
    authenticate()
    cx = get_complex(cid)
    items = [
        e for e in STORE.disease_events.values() if e["complex_id"] == cx["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return list_response(items, serialize_disease_event)


@bp.route("/api/disease-events/<eid>", methods=["GET"])
def read_disease_event(eid):
    authenticate()
    return success_object(serialize_disease_event(get_disease_event(eid)))


@bp.route("/api/disease-events/<eid>/confirm", methods=["POST"])
def confirm_disease_event(eid):
    _uid, role = authenticate()
    require_role(role, {"HealthOfficial"})
    event = get_disease_event(eid)
    validate_payload(get_body(), {})
    if event["status"] != "SUSPECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "event is not SUSPECTED")
    clock = STORE.clock
    event["status"] = "CONFIRMED"
    set_dt(event, "confirmed_at", clock)
    touch(event)
    # LINK 1 — posture recomputed region-wide; the own complex -> QUARANTINE.
    recompute_postures()
    complex_id = event["complex_id"]
    # LINK 2a — every PLANNED flock of the complex is cancelled.
    for flock in STORE.flocks.values():
        house = STORE.houses.get(flock["house_id"])
        if (
            house is not None
            and house["complex_id"] == complex_id
            and flock["status"] == "PLANNED"
        ):
            flock["status"] = "CANCELLED"
            touch(flock)
    # LINK 2b — ALLOCATED orders sourced from this complex whose ship week has
    # not yet closed are forced back to BLOCKED with allocation cleared.
    for order in STORE.orders.values():
        if (
            order.get("allocated_complex_id") == complex_id
            and order["status"] == "ALLOCATED"
            and order["_dt_ship_week_start"] + timedelta(days=7) > clock
        ):
            order["status"] = "BLOCKED"
            order["allocated_complex_id"] = None
            order["allocated_dozen"] = None
            touch(order)
            # LINK 3 — each blocked order increments its commitment's counter.
            commitment = STORE.commitments.get(order["commitment_id"])
            if commitment is not None:
                commitment["blocked_order_count"] += 1
                touch(commitment)
    return success_object(serialize_disease_event(event))


@bp.route("/api/disease-events/<eid>/dismiss", methods=["POST"])
def dismiss_disease_event(eid):
    _uid, role = authenticate()
    require_role(role, {"HealthOfficial"})
    event = get_disease_event(eid)
    validate_payload(get_body(), {})
    if event["status"] != "SUSPECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "event is not SUSPECTED")
    event["status"] = "DISMISSED"
    touch(event)
    # Lighter branch: posture recompute only, no flock/order/commitment effects.
    recompute_postures()
    return success_object(serialize_disease_event(event))


# ---------------------------------------------------------------------------
# Depopulation orders
# ---------------------------------------------------------------------------
@bp.route("/api/disease-events/<eid>/depopulation-orders", methods=["POST"])
def create_depop_order(eid):
    _uid, role = authenticate()
    require_role(role, {"HealthOfficial"})
    event = get_disease_event(eid)
    body = get_body()
    # Priority 5: the body house_id resolves before payload shape is judged.
    raw_house = body.get("house_id") if isinstance(body, dict) else None
    if isinstance(raw_house, str) and raw_house not in STORE.houses:
        raise ApiError(ERR_HOUSE_NOT_FOUND, 404, "house not found: %s" % raw_house)
    values, _raws = validate_payload(
        body,
        {
            "house_id": {"kind": "string", "required": True},
            "disposal_method": {
                "kind": "enum", "required": True, "enum": DISPOSAL_METHODS,
            },
        },
    )
    house = get_house(values["house_id"])
    if house["id"] not in event["scope_house_ids"]:
        raise ApiError(
            ERR_HOUSE_NOT_IN_SCOPE,
            422,
            "house is not in the event's scope_house_ids",
        )
    has_active_flock = any(
        f["house_id"] == house["id"]
        and f["status"] in ("GROWING", "LAYING", "MOLT")
        for f in STORE.flocks.values()
    )
    if not has_active_flock:
        raise ApiError(
            ERR_NO_ACTIVE_FLOCK_IN_HOUSE,
            422,
            "house holds no flock in GROWING, LAYING or MOLT",
        )
    duplicate = any(
        o["disease_event_id"] == event["id"]
        and o["house_id"] == house["id"]
        and o["status"] == "ISSUED"
        for o in STORE.depopulation_orders.values()
    )
    if duplicate:
        raise ApiError(
            ERR_DEPOPULATION_ORDER_EXISTS,
            409,
            "an ISSUED depopulation order already exists for this event and house",
        )
    order = {
        "disease_event_id": event["id"],
        "house_id": house["id"],
        "disposal_method": values["disposal_method"],
        "downtime_days": depop_downtime_days(
            event, values["disposal_method"], STORE.clock
        ),
        "status": "ISSUED",
        "completed_at": None,
        "_dt_completed_at": None,
    }
    stamp_new(order)
    STORE.depopulation_orders[order["id"]] = order
    return success_object(serialize_depop_order(order), 201)


@bp.route("/api/disease-events/<eid>/depopulation-orders", methods=["GET"])
def list_event_depop_orders(eid):
    authenticate()
    event = get_disease_event(eid)
    items = [
        o
        for o in STORE.depopulation_orders.values()
        if o["disease_event_id"] == event["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, serialize_depop_order)


@bp.route("/api/depopulation-orders/<oid>/complete", methods=["POST"])
def complete_depop_order(oid):
    _uid, role = authenticate()
    require_role(role, {"HealthOfficial"})
    order = get_depop_order(oid)
    validate_payload(get_body(), {})
    if order["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not ISSUED")
    clock = STORE.clock
    order["status"] = "COMPLETED"
    set_dt(order, "completed_at", clock)
    touch(order)
    house = get_house(order["house_id"])
    for flock in STORE.flocks.values():
        if flock["house_id"] == house["id"] and flock["status"] in (
            "GROWING",
            "LAYING",
            "MOLT",
        ):
            flock["status"] = "DEPOPULATED"
            flock["current_hen_count"] = 0
            touch(flock)
    # Recompute hen inventory and start downtime; the house is bumped once.
    house["hen_inventory"] = sum(
        f["current_hen_count"]
        for f in STORE.flocks.values()
        if f["house_id"] == house["id"]
        and f["status"] in ("GROWING", "LAYING", "MOLT")
    )
    set_dt(house, "downtime_until", clock + timedelta(days=order["downtime_days"]))
    touch(house)
    return success_object(serialize_depop_order(order))
