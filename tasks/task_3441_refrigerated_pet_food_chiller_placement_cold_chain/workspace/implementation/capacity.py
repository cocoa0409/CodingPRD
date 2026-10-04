"""CapacityProject: propose, approve (segregation of duties + sequence pin),
commission (strict approval order). PRD 3.3, ledger per 2.12."""
from flask import Blueprint

from envelope import ok
from errors import ApiError
from serializers import ser_project
from state import DB, base_entity, touch
from validate import auth, body, fields, require_role

bp = Blueprint("capacity", __name__)


def _get_project(pid):
    p = DB["projects"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CapacityProject %s not found" % pid)
    return p


@bp.post("/cold-chain/capacity-projects")
def create_project():
    uid, role = auth()
    v = fields(body(), [
        ("name", "str", True, {}),
        ("capacity_delta_units", "int", True, {"gt0": True}),
    ])
    require_role(role, ["ProductionPlanner"])
    p = base_entity()
    p.update({
        "name": v["name"],
        "capacity_delta_units": v["capacity_delta_units"],
        "status": "PROPOSED",
        "sequence_no": None,
        "created_by_user_id": uid,
    })
    DB["projects"][p["id"]] = p
    return ok(ser_project(p), "object", 201)


@bp.post("/cold-chain/capacity-projects/<pid>/approve")
def approve_project(pid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["PlatformAdmin"])
    p = _get_project(pid)
    # segregation of duties (tier 2) evaluated before the state gate (tier 4)
    if uid == p["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "Approver must differ from the project creator")
    if p["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a PROPOSED project can be approved")
    seqs = [q["sequence_no"] for q in DB["projects"].values()
            if q["sequence_no"] is not None]
    p["sequence_no"] = (max(seqs) + 1) if seqs else 1
    p["status"] = "APPROVED"
    touch(p)
    return ok(ser_project(p), "object", 200)


@bp.post("/cold-chain/capacity-projects/<pid>/commission")
def commission_project(pid):
    uid, role = auth()
    fields(body(), [])
    require_role(role, ["PlatformAdmin"])
    p = _get_project(pid)
    if p["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an APPROVED project can be commissioned")
    for q in DB["projects"].values():
        if (q["id"] != p["id"] and q["status"] == "APPROVED"
                and q["sequence_no"] is not None
                and q["sequence_no"] < p["sequence_no"]):
            raise ApiError("ERR_EXPANSION_SEQUENCE_VIOLATION", 409,
                           "A lower-sequence APPROVED project must commission first")
    p["status"] = "COMMISSIONED"
    touch(p)
    return ok(ser_project(p), "object", 200)
