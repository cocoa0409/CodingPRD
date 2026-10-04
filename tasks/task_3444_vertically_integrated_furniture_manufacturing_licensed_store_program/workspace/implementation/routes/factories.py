"""Factories (PRD §3.1)."""
from flask import Blueprint

from constants import COMPONENT_LINES, FACTORY_REGIONS, FACTORY_STATES
from db import store
from errors import err
from middleware import auth, require_role
from util import (
    get_body, new_record, ok_object, req_enum, req_int, req_list, req_str,
    serialize, touch,
)

bp = Blueprint("factories", __name__)

# Valid posture edges (PRD §3.1).
_FACTORY_EDGES = {
    ("ACTIVE", "CONSTRAINED"),
    ("CONSTRAINED", "ACTIVE"),
    ("ACTIVE", "OFFLINE"),
    ("CONSTRAINED", "OFFLINE"),
    ("OFFLINE", "ACTIVE"),
}


def get_factory(fid):
    f = store.factories.get(fid)
    if f is None:
        err("ERR_FACTORY_NOT_FOUND", "unknown factory id")
    return f


@bp.route("/api/factories", methods=["POST"])
def create_factory():
    _uid, role = auth()
    data = get_body()
    code = req_str(data, "code")
    region = req_enum(data, "region", FACTORY_REGIONS)
    lines = req_list(data, "component_lines")
    if not lines or any(x not in COMPONENT_LINES for x in lines):
        err("ERR_VALIDATION", "component_lines must be a non-empty array of FOAM/FRAMES/UPHOLSTERY")
    capacity = req_int(data, "weekly_capacity_units", minimum=1)
    require_role(role, ["PlatformAdmin"])
    if any(f["code"] == code for f in store.factories.values()):
        err("ERR_VALIDATION", "factory code must be unique")
    rec = new_record()
    rec.update({
        "code": code,
        "region": region,
        "component_lines": list(lines),
        "weekly_capacity_units": capacity,
        "status": "ACTIVE",
    })
    store.factories[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/factories/<fid>", methods=["GET"])
def fetch_factory(fid):
    auth()
    return ok_object(serialize(get_factory(fid)), 200)


@bp.route("/api/factories/<fid>/transition", methods=["POST"])
def transition_factory(fid):
    _uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", FACTORY_STATES)
    require_role(role, ["ProductionPlanner"])
    f = get_factory(fid)
    if (f["status"], to_state) not in _FACTORY_EDGES:
        err("ERR_INVALID_TRANSITION", "factory cannot move %s -> %s" % (f["status"], to_state))
    bumped = set()
    f["status"] = to_state
    touch(f, bumped)
    return ok_object(serialize(f), 200)
