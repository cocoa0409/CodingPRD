"""Houses and their nested families: certifications (plus record-result),
flock planning, and the per-house depopulation-order / capital-project lists
(PRD §3.1, §3.2)."""

from datetime import timedelta

from flask import Blueprint, request

from auth import authenticate, require_role
from calc import CERT_VALIDITY_DAYS, OCCUPANCY_DAYS
from db import STORE, set_dt, stamp_new, touch
from errors import (
    ApiError,
    ERR_GROWER_REQUIRED,
    ERR_HOUSE_OCCUPANCY_CONFLICT,
    ERR_INVALID_STATE,
    ERR_PROGRAM_HOUSING_MISMATCH,
)
from helpers import get_certification, get_house, list_response
from serialize import (
    serialize_capital_project,
    serialize_certification,
    serialize_depop_order,
    serialize_flock,
    serialize_house,
)
from util import CERT_PROGRAMS, CERT_RESULTS, OWNERSHIPS, PROGRAMS, success_object
from validate import apply_values, get_body, validate_payload

bp = Blueprint("houses", __name__)


@bp.route("/api/houses/<hid>", methods=["GET"])
def read_house(hid):
    authenticate()
    return success_object(serialize_house(get_house(hid)))


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------
@bp.route("/api/houses/<hid>/certifications", methods=["POST"])
def create_certification(hid):
    _uid, role = authenticate()
    require_role(role, {"QualityAuditor"})
    house = get_house(hid)
    values, raws = validate_payload(
        get_body(),
        {
            "program": {"kind": "enum", "required": True, "enum": CERT_PROGRAMS},
            "auditor_name": {"kind": "string", "required": True},
            "scheduled_date": {"kind": "datetime", "required": True},
        },
    )
    cert = {
        "house_id": house["id"],
        "program": values["program"],
        "auditor_name": values["auditor_name"],
        "status": "SCHEDULED",
        "result": None,
        "valid_from": None,
        "_dt_valid_from": None,
        "valid_until": None,
        "_dt_valid_until": None,
    }
    apply_values(cert, {"scheduled_date": values["scheduled_date"]},
                 {"scheduled_date": raws["scheduled_date"]})
    stamp_new(cert)
    STORE.certifications[cert["id"]] = cert
    return success_object(serialize_certification(cert), 201)


@bp.route("/api/houses/<hid>/certifications", methods=["GET"])
def list_certifications(hid):
    authenticate()
    house = get_house(hid)
    items = [c for c in STORE.certifications.values() if c["house_id"] == house["id"]]
    program = request.args.get("program")
    if program is not None:
        items = [c for c in items if c["program"] == program]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serialize_certification)


@bp.route("/api/certifications/<cid>/record-result", methods=["POST"])
def record_certification_result(cid):
    _uid, role = authenticate()
    require_role(role, {"QualityAuditor"})
    cert = get_certification(cid)
    values, _raws = validate_payload(
        get_body(),
        {"result": {"kind": "enum", "required": True, "enum": CERT_RESULTS}},
    )
    if cert["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "certification is not SCHEDULED"
        )
    result = values["result"]
    cert["result"] = result
    cert["status"] = result
    if result == "PASSED":
        set_dt(cert, "valid_from", STORE.clock)
        set_dt(
            cert,
            "valid_until",
            STORE.clock + timedelta(days=CERT_VALIDITY_DAYS),
        )
    touch(cert)
    return success_object(serialize_certification(cert))


# ---------------------------------------------------------------------------
# Flock planning (capacity / certification / downtime / quarantine gate
# placement, not planning — PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/api/houses/<hid>/flocks", methods=["POST"])
def create_flock(hid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    house = get_house(hid)
    body = get_body()
    values, raws = validate_payload(
        body,
        {
            "flock_code": {"kind": "string", "required": True},
            "program": {"kind": "enum", "required": True, "enum": PROGRAMS},
            "ownership": {"kind": "enum", "required": True, "enum": OWNERSHIPS},
            "placement_date": {"kind": "datetime", "required": True},
            "placed_hen_count": {"kind": "int", "required": True, "gt": 0},
            "grower_name": {"kind": "string"},
        },
    )
    if values["ownership"] == "CONTRACT" and not values.get("grower_name"):
        raise ApiError(
            ERR_GROWER_REQUIRED,
            400,
            "grower_name is required for CONTRACT flocks",
        )
    if values["program"] != house["housing_style"]:
        raise ApiError(
            ERR_PROGRAM_HOUSING_MISMATCH,
            422,
            "flock program must equal the house's housing_style",
        )
    # Half-open occupancy windows [placement_date, placement_date + 560 days):
    # pure adjacency is allowed, real overlap is a conflict.
    new_start = values["placement_date"]
    new_end = new_start + timedelta(days=OCCUPANCY_DAYS)
    for other in STORE.flocks.values():
        if other["house_id"] != house["id"]:
            continue
        if other["status"] not in ("PLANNED", "GROWING", "LAYING", "MOLT"):
            continue
        other_start = other["_dt_placement_date"]
        other_end = other_start + timedelta(days=OCCUPANCY_DAYS)
        if new_start < other_end and other_start < new_end:
            raise ApiError(
                ERR_HOUSE_OCCUPANCY_CONFLICT,
                409,
                "flock occupancy window overlaps another flock of this house",
            )
    flock = {
        "house_id": house["id"],
        "flock_code": values["flock_code"],
        "program": values["program"],
        "ownership": values["ownership"],
        "grower_name": values.get("grower_name"),
        "placed_hen_count": values["placed_hen_count"],
        "current_hen_count": 0,
        "age_weeks": 0,
        "molt_count": 0,
        "molt_start_age_weeks": None,
        "status": "PLANNED",
    }
    apply_values(flock, {"placement_date": values["placement_date"]},
                 {"placement_date": raws["placement_date"]})
    stamp_new(flock)
    STORE.flocks[flock["id"]] = flock
    return success_object(serialize_flock(flock), 201)


@bp.route("/api/houses/<hid>/flocks", methods=["GET"])
def list_flocks(hid):
    authenticate()
    house = get_house(hid)
    items = [f for f in STORE.flocks.values() if f["house_id"] == house["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    program = request.args.get("program")
    if program is not None:
        items = [f for f in items if f["program"] == program]
    return list_response(items, serialize_flock)


# ---------------------------------------------------------------------------
# Per-house listings of cross-referencing families
# ---------------------------------------------------------------------------
@bp.route("/api/houses/<hid>/depopulation-orders", methods=["GET"])
def list_house_depop_orders(hid):
    authenticate()
    house = get_house(hid)
    items = [
        o for o in STORE.depopulation_orders.values() if o["house_id"] == house["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, serialize_depop_order)


@bp.route("/api/houses/<hid>/capital-projects", methods=["GET"])
def list_house_capital_projects(hid):
    authenticate()
    house = get_house(hid)
    items = [
        p for p in STORE.capital_projects.values() if p["house_id"] == house["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items, serialize_capital_project)
