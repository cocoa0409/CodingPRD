"""Maintenance turnarounds and failover coordination (PRD 3.7)."""
from decimal import Decimal

from flask import Blueprint

from helpers import (authenticate, require_role, forbidden, json_body, respond,
                     v_str, v_dt, v_enum, v_int, as_int, by_created, paginate)
from store import (db, base_entity, pub, touch, parse_dt, clock_now, ApiError)
from domain import start_turnaround_effects

bp = Blueprint("turnarounds", __name__)


def _check_window(ws, we):
    """Window end must exceed start; duration in [24h, 720h]."""
    if we <= ws:
        raise ApiError("ERR_WINDOW_DURATION_INVALID", 422,
                       "window_end must be after window_start")
    delta = we - ws
    micros = (delta.days * 86400 + delta.seconds) * 10**6 + delta.microseconds
    hours = Decimal(micros) / Decimal(3600 * 10**6)
    if hours < 24 or hours > 720:
        raise ApiError("ERR_WINDOW_DURATION_INVALID", 422,
                       "Window duration must be within [24h, 720h]")


def _get_turnaround_or_404(tid):
    t = db["turnarounds"].get(tid)
    if t is None:
        raise ApiError("ERR_TURNAROUND_NOT_FOUND", 404, "Turnaround not found")
    return t


def _contract_of(t):
    plant = db["plants"].get(t["plant_id"])
    if plant is None:
        return None
    return db["contracts"].get(plant["contract_id"])


@bp.route("/gas-supply/onsite-plants/<plantId>/turnarounds", methods=["POST"])
def create_turnaround(plantId):
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    plant = db["plants"].get(plantId)
    if plant is None:
        raise ApiError("ERR_PLANT_NOT_FOUND", 404, "OnsitePlant not found")
    body = json_body()
    # Tier 4: plant must be OPERATING
    if plant["status"] != "OPERATING":
        raise ApiError("ERR_PLANT_NOT_OPERATING", 409,
                       "Turnarounds can only be proposed on an OPERATING plant")
    # Tier 6: window duration
    ws = parse_dt(body.get("window_start"))
    we = parse_dt(body.get("window_end"))
    if ws is not None and we is not None:
        _check_window(ws, we)
    # Tier 9 structural
    ws_raw = v_dt(body, "window_start")
    we_raw = v_dt(body, "window_end")
    scope = v_str(body, "scope")
    ent = base_entity()
    ent.update({
        "plant_id": plantId,
        "window_start": ws_raw,
        "window_end": we_raw,
        "scope": scope,
        "proposal_round": 1,
        "status": "PROPOSED",
        "_ws": parse_dt(ws_raw),
        "_we": parse_dt(we_raw),
    })
    db["turnarounds"][ent["id"]] = ent
    return respond(pub(ent), "object", 201)


@bp.route("/gas-supply/onsite-plants/<plantId>/turnarounds", methods=["GET"])
def list_turnarounds(plantId):
    authenticate()
    if plantId not in db["plants"]:
        raise ApiError("ERR_PLANT_NOT_FOUND", 404, "OnsitePlant not found")
    items = by_created([t for t in db["turnarounds"].values()
                        if t["plant_id"] == plantId])
    page, meta = paginate(items)
    return respond([pub(t) for t in page], "array", 200, meta)


@bp.route("/gas-supply/turnarounds/<turnaroundId>/respond", methods=["POST"])
def respond_turnaround(turnaroundId):
    uid, role = authenticate()
    require_role(role, {"CustomerOps"})
    t = _get_turnaround_or_404(turnaroundId)
    # CustomerOps ownership: caller must be the customer owning the contract
    contract = _contract_of(t)
    owner = contract["customer_id"] if contract is not None else None
    if uid != owner:
        forbidden("CustomerOps caller does not own this turnaround")
    body = json_body()
    # Tier 4 OCC guard
    expected = as_int(body.get("expected_turnaround_version"))
    if expected is not None and expected != t["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_turnaround_version does not match the "
                       "turnaround version")
    # Tier 4 from-state
    if t["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a PROPOSED turnaround can be answered")
    # Tier 6: counter window duration (missing counter windows included)
    decision_raw = body.get("decision")
    cs = ce = None
    if decision_raw == "COUNTER":
        cs = parse_dt(body.get("counter_window_start"))
        ce = parse_dt(body.get("counter_window_end"))
        if cs is None or ce is None:
            raise ApiError("ERR_WINDOW_DURATION_INVALID", 422,
                           "COUNTER requires counter_window_start and "
                           "counter_window_end")
        _check_window(cs, ce)
    # Tier 9 structural
    decision = v_enum(body, "decision", ("AGREE", "COUNTER"))
    v_int(body, "expected_turnaround_version")
    if decision == "AGREE":
        t["status"] = "AGREED"
    else:
        t["window_start"] = body["counter_window_start"]
        t["window_end"] = body["counter_window_end"]
        t["_ws"] = cs
        t["_we"] = ce
        t["proposal_round"] += 1
    touch(t)
    return respond(pub(t))


@bp.route("/gas-supply/turnarounds/<turnaroundId>/schedule", methods=["POST"])
def schedule_turnaround(turnaroundId):
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    t = _get_turnaround_or_404(turnaroundId)
    # Tier 4: from-state, then contract-active
    if t["status"] != "AGREED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only an AGREED turnaround can be scheduled")
    contract = _contract_of(t)
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409,
                       "Scheduling requires an ACTIVE contract")
    # Tier 6: half-open overlap with other SCHEDULED/IN_PROGRESS turnarounds
    for o in db["turnarounds"].values():
        if (o["id"] != t["id"] and o["plant_id"] == t["plant_id"]
                and o["status"] in ("SCHEDULED", "IN_PROGRESS")
                and o["_ws"] < t["_we"] and t["_ws"] < o["_we"]):
            raise ApiError("ERR_TURNAROUND_OVERLAP", 409,
                           "Window overlaps an existing turnaround on this "
                           "plant")
    # Tier 6: closed-interval blackout conflict
    customer = db["customers"].get(contract["customer_id"])
    if customer is not None:
        for bs, be in customer["_blackouts"]:
            if t["_ws"] <= be and t["_we"] > bs:
                raise ApiError("ERR_TURNAROUND_IN_BLACKOUT", 422,
                               "Window shares an instant with a customer "
                               "blackout window")
    t["status"] = "SCHEDULED"
    touch(t)
    return respond(pub(t))


@bp.route("/gas-supply/turnarounds/<turnaroundId>/start", methods=["POST"])
def start_turnaround(turnaroundId):
    _uid, role = authenticate()
    require_role(role, {"PlantOperator"})
    t = _get_turnaround_or_404(turnaroundId)
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Only a SCHEDULED turnaround can be started")
    if clock_now() < t["_ws"]:
        raise ApiError("ERR_TURNAROUND_NOT_DUE", 422,
                       "The logical clock has not reached window_start")
    t["status"] = "IN_PROGRESS"
    touch(t)
    start_turnaround_effects(t)
    return respond(pub(t))
