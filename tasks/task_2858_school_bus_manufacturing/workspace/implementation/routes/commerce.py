"""Solicitations, bids, revision rounds, awards and contract orders (PRD 3.3-3.5)."""

from flask import Blueprint

import shapes
from db import (by_creation, db, get_or_404, make_record, now_iso, public,
                touch, values)
from errors import ApiError
from middleware import CONTRACTS_ADMIN, SALES_ENGINEER, actor
from response import (created, list_response, object_response, q_bool, q_enum,
                      q_str)
from services import calc, domain

bp = Blueprint("commerce", __name__)

SOLICITATION_STATUSES = ("OPEN", "CLOSED", "AWARDED")
BID_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "AWARDED", "REJECTED")
ORDER_STATUSES = ("ACTIVE", "FULFILLED")
POSTURES = ("ON_TRACK", "AT_RISK", "BREACHED")


def read_offered_config(data):
    """The seven offered_* configuration inputs of a bid or revision."""
    return {
        "seat_capacity": shapes.get_int(data, "offered_seat_capacity", minimum=1),
        "emergency_exit_count": shapes.get_int(data, "offered_emergency_exit_count", minimum=1),
        "mirror_config": shapes.get_enum(data, "offered_mirror_config", calc.MIRROR_CONFIGS),
        "lap_shoulder_belts": shapes.get_bool(data, "offered_lap_shoulder_belts"),
        "eight_lamp_system": shapes.get_bool(data, "offered_eight_lamp_system"),
        "crossing_arm": shapes.get_bool(data, "offered_crossing_arm"),
        "rollover_reinforcement": shapes.get_bool(data, "offered_rollover_reinforcement"),
    }


def evaluate(model, package, profile, cfg):
    """Joint strength, both range figures, provisional price and the verdict."""
    joint = calc.joint_strength_kn(model, cfg["rollover_reinforcement"])
    nominal, derated = calc.range_validation(package, profile)
    price = calc.unit_price_cents(model, package, cfg)
    status, exceptions, unmet = calc.spec_compliance(cfg, joint, derated, profile)
    return {
        "offered_joint_strength_kn": joint,
        "nominal_range_mi": nominal,
        "derated_route_range_mi": derated,
        "provisional_unit_price_cents": price,
        "spec_compliance_status": status,
        "exception_count": exceptions,
        "unmet_mandatory_items": unmet,
    }


# ------------------------------------------------------------ solicitations

@bp.post("/solicitations")
def create_solicitation():
    actor(SALES_ENGINEER)
    data = shapes.body()
    code = shapes.get_str(data, "solicitation_code")
    buyer_type = shapes.get_enum(data, "buyer_type", calc.BUYER_TYPES)
    buyer_name = shapes.get_str(data, "buyer_name")
    profile_id = shapes.get_str(data, "spec_profile_id")
    unit_count = shapes.get_int(data, "unit_count", minimum=1)
    required_raw, _required_date = shapes.get_date(data, "required_delivery_date")
    price_cap = shapes.get_int(data, "price_cap_cents_per_unit", minimum=1)

    profile = get_or_404(db.profiles, profile_id, "ERR_SPEC_PROFILE_NOT_FOUND")
    if profile["status"] != "PUBLISHED":
        raise ApiError("ERR_SPEC_PROFILE_NOT_PUBLISHED")

    solicitation = make_record({
        "solicitation_code": code,
        "buyer_type": buyer_type,
        "buyer_name": buyer_name,
        "spec_profile_id": profile["id"],
        "state_code": profile["state_code"],
        "school_year": profile["school_year"],
        "unit_count": unit_count,
        "required_delivery_date": required_raw,
        "price_cap_cents_per_unit": price_cap,
        "status": "OPEN",
    })
    db.solicitations[solicitation["id"]] = solicitation
    return created(public(solicitation))


@bp.get("/solicitations")
def list_solicitations():
    actor()
    profile_id = q_str("spec_profile_id")
    status = q_enum("status", SOLICITATION_STATUSES)
    buyer_type = q_enum("buyer_type", calc.BUYER_TYPES)
    rows = []
    for row in values(db.solicitations):
        if profile_id is not None and row["spec_profile_id"] != profile_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if buyer_type is not None and row["buyer_type"] != buyer_type:
            continue
        rows.append(row)
    return list_response(by_creation(rows))


@bp.get("/solicitations/<sid>")
def read_solicitation(sid):
    actor()
    row = get_or_404(db.solicitations, sid, "ERR_SOLICITATION_NOT_FOUND")
    return object_response(public(row))


@bp.post("/solicitations/<sid>/close")
def close_solicitation(sid):
    actor(CONTRACTS_ADMIN)
    row = get_or_404(db.solicitations, sid, "ERR_SOLICITATION_NOT_FOUND")
    if row["status"] != "OPEN":
        raise ApiError("ERR_SOLICITATION_NOT_OPEN")
    row["status"] = "CLOSED"
    touch(row)
    return object_response(public(row))


# --------------------------------------------------------------------- bids

@bp.post("/bids")
def create_bid():
    actor(SALES_ENGINEER)
    data = shapes.body()
    solicitation_id = shapes.get_str(data, "solicitation_id")
    model_id = shapes.get_str(data, "bus_model_id")
    package_id = shapes.get_str(data, "propulsion_package_id")
    unit_count = shapes.get_int(data, "unit_count", minimum=1)
    cfg = read_offered_config(data)

    model = get_or_404(db.models, model_id, "ERR_BUS_MODEL_NOT_FOUND")
    package = get_or_404(db.packages, package_id, "ERR_PROPULSION_PACKAGE_NOT_FOUND")
    solicitation = get_or_404(db.solicitations, solicitation_id, "ERR_SOLICITATION_NOT_FOUND")
    if solicitation["status"] != "OPEN":
        raise ApiError("ERR_SOLICITATION_NOT_OPEN")
    if package["compatible_bus_model_id"] != model["id"]:
        raise ApiError("ERR_PROPULSION_MODEL_INCOMPATIBLE")
    if (package["propulsion_type"] == "ELECTRIC"
            and int(package["battery_pack_count"]) > int(model["max_battery_bays"])):
        raise ApiError("ERR_BATTERY_BAY_CAPACITY_EXCEEDED")

    profile = get_or_404(db.profiles, solicitation["spec_profile_id"],
                         "ERR_SPEC_PROFILE_NOT_FOUND")
    computed = evaluate(model, package, profile, cfg)

    bid = make_record({
        "solicitation_id": solicitation["id"],
        "bus_model_id": model["id"],
        "propulsion_package_id": package["id"],
        "evaluated_spec_profile_id": profile["id"],
        "unit_count": unit_count,
        "offered_seat_capacity": cfg["seat_capacity"],
        "offered_emergency_exit_count": cfg["emergency_exit_count"],
        "offered_mirror_config": cfg["mirror_config"],
        "offered_lap_shoulder_belts": cfg["lap_shoulder_belts"],
        "offered_eight_lamp_system": cfg["eight_lamp_system"],
        "offered_crossing_arm": cfg["crossing_arm"],
        "offered_rollover_reinforcement": cfg["rollover_reinforcement"],
        "offered_joint_strength_kn": computed["offered_joint_strength_kn"],
        "nominal_range_mi": computed["nominal_range_mi"],
        "derated_route_range_mi": computed["derated_route_range_mi"],
        "provisional_unit_price_cents": computed["provisional_unit_price_cents"],
        "spec_compliance_status": computed["spec_compliance_status"],
        "exception_count": computed["exception_count"],
        "unmet_mandatory_items": computed["unmet_mandatory_items"],
        "revision_round": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "submitted_by_user_id": None,
    })
    db.bids[bid["id"]] = bid
    domain.new_revision(bid, cfg, None, 0, computed["provisional_unit_price_cents"])
    return created(public(bid))


@bp.get("/bids")
def list_bids():
    actor()
    solicitation_id = q_str("solicitation_id")
    model_id = q_str("bus_model_id")
    package_id = q_str("propulsion_package_id")
    profile_id = q_str("evaluated_spec_profile_id")
    status = q_enum("status", BID_STATUSES)
    rows = []
    for bid in values(db.bids):
        if solicitation_id is not None and bid["solicitation_id"] != solicitation_id:
            continue
        if model_id is not None and bid["bus_model_id"] != model_id:
            continue
        if package_id is not None and bid["propulsion_package_id"] != package_id:
            continue
        if profile_id is not None and bid["evaluated_spec_profile_id"] != profile_id:
            continue
        if status is not None and bid["status"] != status:
            continue
        rows.append(bid)
    return list_response(by_creation(rows))


@bp.get("/bids/<bid_id>")
def read_bid(bid_id):
    actor()
    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    return object_response(public(bid))


@bp.post("/bids/<bid_id>/revisions")
def append_revision(bid_id):
    actor(SALES_ENGINEER)
    data = shapes.body()
    expected_version = shapes.get_int(data, "expected_bid_version", minimum=0)
    cfg = read_offered_config(data)
    note = shapes.get_str(data, "note", required=False, default=None, allow_empty=True)

    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    if int(expected_version) != int(bid["version"]):
        raise ApiError("ERR_STALE_BID_VERSION")
    solicitation = db.solicitations.get(bid["solicitation_id"])
    if solicitation is None or solicitation["status"] != "OPEN":
        raise ApiError("ERR_SOLICITATION_NOT_OPEN")
    if bid["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_BID_STATE_INVALID")
    round_index = int(bid["revision_round"]) + 1
    if round_index > calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_ROUND_LIMIT")

    model = db.models[bid["bus_model_id"]]
    package = db.packages[bid["propulsion_package_id"]]
    profile = db.profiles[solicitation["spec_profile_id"]]
    computed = evaluate(model, package, profile, cfg)

    for previous in domain.revisions_of_bid(bid["id"]):
        if not previous["is_superseded"]:
            previous["is_superseded"] = True
    revision = domain.new_revision(bid, cfg, note, round_index,
                                   computed["provisional_unit_price_cents"])

    domain.apply_offered_config(bid, cfg)
    bid["evaluated_spec_profile_id"] = profile["id"]
    bid["offered_joint_strength_kn"] = computed["offered_joint_strength_kn"]
    bid["nominal_range_mi"] = computed["nominal_range_mi"]
    bid["derated_route_range_mi"] = computed["derated_route_range_mi"]
    bid["provisional_unit_price_cents"] = computed["provisional_unit_price_cents"]
    bid["spec_compliance_status"] = computed["spec_compliance_status"]
    bid["exception_count"] = computed["exception_count"]
    bid["unmet_mandatory_items"] = computed["unmet_mandatory_items"]
    bid["revision_round"] = round_index
    if bid["status"] == "REVISION_REQUESTED":
        bid["status"] = "DRAFT"
    touch(bid)
    return created(public(revision))


@bp.get("/bids/<bid_id>/revisions")
def list_revisions(bid_id):
    actor()
    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    superseded = q_bool("is_superseded")
    rows = [r for r in domain.revisions_of_bid(bid["id"])
            if superseded is None or bool(r["is_superseded"]) == superseded]
    rows.sort(key=lambda r: (int(r["round_index"]), r["_seq"]))
    return list_response(rows)


@bp.post("/bids/<bid_id>/submit")
def submit_bid(bid_id):
    user_id, _role = actor(SALES_ENGINEER)
    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    solicitation = db.solicitations.get(bid["solicitation_id"])
    if solicitation is None or solicitation["status"] != "OPEN":
        raise ApiError("ERR_SOLICITATION_NOT_OPEN")
    if bid["status"] != "DRAFT":
        raise ApiError("ERR_BID_STATE_INVALID")

    profile = domain.published_profile(solicitation["state_code"], solicitation["school_year"])
    if profile is None:
        profile = db.profiles[bid["evaluated_spec_profile_id"]]
    model = db.models[bid["bus_model_id"]]
    package = db.packages[bid["propulsion_package_id"]]
    cfg = domain.bid_offered_config(bid)
    computed = evaluate(model, package, profile, cfg)

    if computed["spec_compliance_status"] == "NONCONFORMING":
        raise ApiError("ERR_SPEC_NONCONFORMING")
    if int(bid["provisional_unit_price_cents"]) > int(solicitation["price_cap_cents_per_unit"]):
        raise ApiError("ERR_PRICE_CAP_EXCEEDED")

    bid["evaluated_spec_profile_id"] = profile["id"]
    bid["offered_joint_strength_kn"] = computed["offered_joint_strength_kn"]
    bid["nominal_range_mi"] = computed["nominal_range_mi"]
    bid["derated_route_range_mi"] = computed["derated_route_range_mi"]
    bid["spec_compliance_status"] = computed["spec_compliance_status"]
    bid["exception_count"] = computed["exception_count"]
    bid["unmet_mandatory_items"] = computed["unmet_mandatory_items"]
    bid["status"] = "SUBMITTED"
    bid["submitted_at"] = now_iso()
    bid["submitted_by_user_id"] = user_id
    touch(bid)
    return object_response(public(bid))


@bp.post("/bids/<bid_id>/request-revision")
def request_revision(bid_id):
    actor(CONTRACTS_ADMIN)
    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    solicitation = db.solicitations.get(bid["solicitation_id"])
    if solicitation is None or solicitation["status"] != "OPEN":
        raise ApiError("ERR_SOLICITATION_NOT_OPEN")
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_STATE_INVALID")
    if int(bid["revision_round"]) >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_ROUND_LIMIT")
    bid["status"] = "REVISION_REQUESTED"
    touch(bid)
    return object_response(public(bid))


@bp.post("/bids/<bid_id>/award")
def award_bid(bid_id):
    user_id, _role = actor(CONTRACTS_ADMIN)
    data = shapes.body()
    promised_raw, promised_date = shapes.get_date(data, "promised_delivery_date")

    bid = get_or_404(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    solicitation = db.solicitations.get(bid["solicitation_id"])
    if solicitation is None or solicitation["status"] != "CLOSED":
        raise ApiError("ERR_SOLICITATION_NOT_CLOSED")
    if bid["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_STATE_INVALID")
    if bid["submitted_by_user_id"] is not None and user_id == bid["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if promised_date > domain.to_date(solicitation["required_delivery_date"]):
        raise ApiError("ERR_PROMISE_EXCEEDS_REQUIRED_DATE")

    profile = domain.published_profile(solicitation["state_code"], solicitation["school_year"])
    if profile is None:
        profile = db.profiles[bid["evaluated_spec_profile_id"]]
    model = db.models[bid["bus_model_id"]]
    package = db.packages[bid["propulsion_package_id"]]

    upgraded = calc.upgrade_config(domain.bid_offered_config(bid), profile)
    joint = calc.joint_strength_kn(model, upgraded["rollover_reinforcement"])
    upgraded_price = calc.unit_price_cents(model, package, upgraded)
    months = 0
    if bid["submitted_at"]:
        elapsed_days = (domain.to_date(now_iso()) - domain.to_date(bid["submitted_at"])).days
        if elapsed_days > 0:
            months = elapsed_days // 30
    awarded_price = calc.escalated_price(upgraded_price, months)
    total = calc.contract_total_cents(awarded_price, bid["unit_count"])

    order = make_record({
        "bid_id": bid["id"],
        "spec_profile_id": profile["id"],
        "unit_count": int(bid["unit_count"]),
        "promised_delivery_date": promised_raw,
        "awarded_unit_price_cents": awarded_price,
        "total_contract_cents": total,
        "awarded_seat_capacity": upgraded["seat_capacity"],
        "awarded_emergency_exit_count": upgraded["emergency_exit_count"],
        "awarded_mirror_config": upgraded["mirror_config"],
        "awarded_lap_shoulder_belts": upgraded["lap_shoulder_belts"],
        "awarded_eight_lamp_system": upgraded["eight_lamp_system"],
        "awarded_crossing_arm": upgraded["crossing_arm"],
        "awarded_rollover_reinforcement": upgraded["rollover_reinforcement"],
        "awarded_joint_strength_kn": joint,
        "created_unit_count": 0,
        "delivered_unit_count": 0,
        "at_risk_unit_count": 0,
        "delivery_posture": "ON_TRACK",
        "liquidated_damages_cents": 0,
        "status": "ACTIVE",
    })
    db.orders[order["id"]] = order

    bid["status"] = "AWARDED"
    touch(bid)
    solicitation["status"] = "AWARDED"
    touch(solicitation)
    siblings = [b for b in values(db.bids)
                if b["solicitation_id"] == solicitation["id"] and b["id"] != bid["id"]]
    for other in by_creation(siblings):
        if other["status"] in ("SUBMITTED", "REVISION_REQUESTED"):
            other["status"] = "REJECTED"
            touch(other)
    return created(public(order))


# ----------------------------------------------------------- contract orders

@bp.get("/contract-orders")
def list_orders():
    actor()
    bid_id = q_str("bid_id")
    profile_id = q_str("spec_profile_id")
    status = q_enum("status", ORDER_STATUSES)
    posture = q_enum("delivery_posture", POSTURES)
    rows = []
    for order in values(db.orders):
        if bid_id is not None and order["bid_id"] != bid_id:
            continue
        if profile_id is not None and order["spec_profile_id"] != profile_id:
            continue
        if status is not None and order["status"] != status:
            continue
        if posture is not None and order["delivery_posture"] != posture:
            continue
        rows.append(order)
    return list_response(by_creation(rows))


@bp.get("/contract-orders/<order_id>")
def read_order(order_id):
    actor()
    order = get_or_404(db.orders, order_id, "ERR_CONTRACT_ORDER_NOT_FOUND")
    return object_response(public(order))
