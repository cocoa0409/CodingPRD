"""WorkPhase and DisruptionLog routes."""
from flask import Blueprint

import db
import domain
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  parse_dt, req_int, req_string, require_roles, touch)

bp = Blueprint("phases", __name__)


def _ser_phase(p):
    out = domain.ser_phase(p)
    out.pop("_window_start", None)
    out.pop("_window_end", None)
    return out


@bp.route("/performance-contracts/<contractId>/phases", methods=["POST"])
def create_phase(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    start = parse_dt(data.get("window_start"), "window_start")
    end = parse_dt(data.get("window_end"), "window_end")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400, "window_end must be after window_start")
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "phase_label": req_string(data, "phase_label"),
        "window_start": start.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "window_end": end.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "disruption_budget_hours": req_int(data, "disruption_budget_hours", min_v=1),
        "consumed_disruption_hours": 0,
        "status": "PLANNED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_window_start": start,
        "_window_end": end,
    }
    db.phases[rec["id"]] = rec
    return ok(_ser_phase(rec), code=201)


@bp.route("/performance-contracts/<contractId>/phases", methods=["GET"])
def list_phases(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [p for p in db.phases.values() if p["contract_id"] == c["id"]]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([_ser_phase(p) for p in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>", methods=["GET"])
def get_phase(contractId, phaseId):
    require_roles()
    _, p = domain.get_phase(contractId, phaseId)
    return ok(_ser_phase(p))


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/mobilize", methods=["POST"])
def mobilize_phase(contractId, phaseId):
    require_roles("ESCOEngineer")
    c, p = domain.get_phase(contractId, phaseId)
    if p["status"] != "PLANNED":
        raise ApiError("ERR_PHASE_NOT_PLANNED", 409, "phase must be in PLANNED")
    if c["status"] != "EXECUTED":
        raise ApiError("ERR_CONTRACT_NOT_EXECUTED", 409, "contract must be in EXECUTED")
    for other in db.phases.values():
        if (other["contract_id"] == c["id"] and other["id"] != p["id"]
                and other["status"] in ("MOBILIZED", "IN_PROGRESS")):
            if p["_window_start"] < other["_window_end"] and other["_window_start"] < p["_window_end"]:
                raise ApiError("ERR_PHASE_WINDOW_OVERLAP", 409,
                               "phase window overlaps an active phase window")
    p["status"] = "MOBILIZED"
    touch(p)
    return ok(_ser_phase(p))


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/start", methods=["POST"])
def start_phase(contractId, phaseId):
    require_roles("ESCOEngineer")
    _, p = domain.get_phase(contractId, phaseId)
    if p["status"] == "MOBILIZED":
        if db.logical_now() < p["_window_start"]:
            raise ApiError("ERR_PHASE_WINDOW_NOT_STARTED", 409,
                           "the phase window has not started")
    elif p["status"] == "SUSPENDED":
        if db.logical_now() >= p["_window_end"]:
            raise ApiError("ERR_PHASE_WINDOW_CLOSED", 409, "the phase window has closed")
    else:
        raise ApiError("ERR_PHASE_NOT_MOBILIZED", 409, "phase must be in MOBILIZED")
    p["status"] = "IN_PROGRESS"
    touch(p)
    return ok(_ser_phase(p))


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/complete", methods=["POST"])
def complete_phase(contractId, phaseId):
    require_roles("OwnerRep")
    c, p = domain.get_phase(contractId, phaseId)
    if p["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PHASE_NOT_IN_PROGRESS", 409, "phase must be in IN_PROGRESS")
    if db.logical_now() >= p["_window_end"]:
        contract_measures = [m for m in db.measures.values() if m["contract_id"] == c["id"]]
        unfinished = [m for m in contract_measures
                      if m["status"] not in ("INSTALLED", "VERIFIED", "EXCLUDED")]
        if unfinished:
            raise ApiError("ERR_PHASE_OVERRUN", 409,
                           "late completion requires all measures installed or verified")
    p["status"] = "COMPLETE"
    touch(p)
    return ok(_ser_phase(p))


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/suspend", methods=["POST"])
def suspend_phase(contractId, phaseId):
    require_roles("OwnerRep")
    _, p = domain.get_phase(contractId, phaseId)
    if p["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PHASE_NOT_IN_PROGRESS", 409, "phase must be in IN_PROGRESS")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok(_ser_phase(p))


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/disruptions", methods=["POST"])
def create_disruption(contractId, phaseId):
    require_roles("ESCOEngineer")
    _, p = domain.get_phase(contractId, phaseId)
    data = body()
    occurred = parse_dt(data.get("occurred_at"), "occurred_at")
    hours = req_int(data, "hours", min_v=1)
    cause = req_string(data, "cause")
    if p["status"] != "IN_PROGRESS":
        raise ApiError("ERR_PHASE_NOT_IN_PROGRESS", 409, "phase must be in IN_PROGRESS")
    if p["consumed_disruption_hours"] + hours > p["disruption_budget_hours"]:
        raise ApiError("ERR_DISRUPTION_BUDGET_EXCEEDED", 422,
                       "disruption would exceed the phase budget")
    if not (p["_window_start"] <= occurred < p["_window_end"]):
        raise ApiError("ERR_DISRUPTION_OUTSIDE_WINDOW", 422,
                       "occurred_at is outside the phase window")
    rec = {
        "id": new_id(),
        "phase_id": p["id"],
        "occurred_at": occurred.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "hours": hours,
        "cause": cause,
        "created_at": now_iso(),
    }
    db.disruptions[rec["id"]] = rec
    p["consumed_disruption_hours"] += hours
    touch(p)
    return ok(domain.ser_disruption(rec), code=201)


@bp.route("/performance-contracts/<contractId>/phases/<phaseId>/disruptions", methods=["GET"])
def list_disruptions(contractId, phaseId):
    require_roles()
    _, p = domain.get_phase(contractId, phaseId)
    limit, offset = paginate_args()
    items = [d for d in db.disruptions.values() if d["phase_id"] == p["id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_disruption(d) for d in page], response_type="array", pagination=meta)
