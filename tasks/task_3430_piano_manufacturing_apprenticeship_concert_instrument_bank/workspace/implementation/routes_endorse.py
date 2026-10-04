"""Skill endorsement track endpoints (PRD 3.3)."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import (
    fail_scaled_hours,
    maybe_promote_endorsement,
    recompute_endorsement_hours,
    top_supervisor_id,
)
from db import STORE, clock_now, new_entity, touch
from envelope import ok, paged
from errors import raise_err
from serialize import endorsement as ser_track
from validate import get_body, opt_fk, req_enum, req_number

bp = Blueprint("endorsements", __name__, url_prefix="/piano-works")

TRAINABLE_OPS = ("RIM_BENDING", "SEASONING_CHECK")
LIVE_STATUSES = ("IN_TRAINING", "PENDING_ASSESSMENT", "ENDORSED")
WM = ("WorkshopManager",)


def _get_track(tid):
    t = STORE["endorsements"].get(tid)
    if t is None:
        raise_err("ERR_NOT_FOUND", "skill endorsement %s not found" % tid)
    return t


@bp.post("/skill-endorsements")
def create_track():
    authenticate(WM)
    body = get_body()
    app_id = opt_fk(body, "apprentice_id")
    if app_id is None:
        raise_err("ERR_VALIDATION", "apprentice_id is required")
    if app_id not in STORE["apprentices"]:
        raise_err("ERR_NOT_FOUND", "apprentice %s not found" % app_id)
    # Only RIM_BENDING / SEASONING_CHECK are apprentice-trainable.
    op = req_enum(body, "operation_type", TRAINABLE_OPS)
    for t in STORE["endorsements"].values():
        if t["apprentice_id"] == app_id and t["operation_type"] == op and t["status"] in LIVE_STATUSES:
            raise_err("ERR_DUPLICATE_ENDORSEMENT", "a live track already exists for this pair")
    t = new_entity()
    t.update({
        "apprentice_id": app_id,
        "operation_type": op,
        "status": "IN_TRAINING",
        "logged_hours": 0.0,
        "effective_hours": 0.0,
        "supervision_log": [],
        "endorsed_by_craftsman_id": None,
    })
    STORE["endorsements"][t["id"]] = t
    return ok(ser_track(t), 201)


@bp.get("/skill-endorsements")
def list_tracks():
    authenticate(ALL_ROLES)
    items = list(STORE["endorsements"].values())
    for field in ("apprentice_id", "endorsed_by_craftsman_id", "operation_type", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [t for t in items if t[field] == v]
    return paged(items, ser_track)


@bp.get("/skill-endorsements/<tid>")
def get_track(tid):
    authenticate(ALL_ROLES)
    return ok(ser_track(_get_track(tid)))


@bp.post("/skill-endorsements/<tid>/log-hours")
def log_hours(tid):
    caller = authenticate(("Apprentice",))
    t = _get_track(tid)
    # Ownership (priority 2): an apprentice logs hours only on their own track.
    if t["apprentice_id"] != caller["id"]:
        raise_err("ERR_FORBIDDEN_RESOURCE", "apprentice does not own this endorsement track")
    body = get_body()
    sup_id = opt_fk(body, "supervising_craftsman_id")
    if sup_id is not None and sup_id not in STORE["craftsmen"]:
        raise_err("ERR_NOT_FOUND", "supervising_craftsman_id %s not found" % sup_id)
    hours = req_number(body, "hours")
    if not hours > 0:
        raise_err("ERR_VALIDATION", "hours must be greater than 0")
    if t["status"] == "REVOKED":
        raise_err("ERR_INVALID_STATE", "a REVOKED track accepts no hours")
    # Null supervisor is permitted only for endorsed unsupervised work.
    if sup_id is None and t["status"] != "ENDORSED":
        raise_err("ERR_VALIDATION", "supervising_craftsman_id is required before endorsement")
    match = True if sup_id is None else STORE["craftsmen"][sup_id]["specialty"] == t["operation_type"]
    t["supervision_log"].append({
        "supervising_craftsman_id": sup_id,
        "hours": hours,
        "specialty_match": match,
        "logged_at": clock_now(),
    })
    recompute_endorsement_hours(t)
    touch(t)
    if maybe_promote_endorsement(t):
        touch(t)
    return ok(ser_track(t))


@bp.post("/skill-endorsements/<tid>/assess")
def assess_track(tid):
    caller = authenticate(("MasterCraftsman",))
    t = _get_track(tid)
    body = get_body()
    outcome = req_enum(body, "outcome", ("ENDORSE", "FAIL"))
    if t["status"] != "PENDING_ASSESSMENT":
        raise_err("ERR_INVALID_STATE", "only a PENDING_ASSESSMENT track can be assessed")
    # Segregation of duties: assessor must not be the top supervisor.
    top = top_supervisor_id(t)
    if top is not None and top == caller["id"]:
        raise_err("ERR_SOD_ASSESSOR_IS_SUPERVISOR", "assessor is the track's top supervisor")
    if outcome == "ENDORSE":
        t["status"] = "ENDORSED"
        t["endorsed_by_craftsman_id"] = caller["id"]
    else:
        t["status"] = "IN_TRAINING"
        for e in t["supervision_log"]:
            e["hours"] = fail_scaled_hours(e["hours"])
        recompute_endorsement_hours(t)
    touch(t)
    return ok(ser_track(t))


@bp.post("/skill-endorsements/<tid>/review")
def review_track(tid):
    authenticate(WM)
    t = _get_track(tid)
    body = get_body()
    action = req_enum(body, "action", ("REVOKE", "REOPEN"))
    if action == "REVOKE":
        if t["status"] != "ENDORSED":
            raise_err("ERR_INVALID_STATE", "only an ENDORSED track can be revoked")
        t["status"] = "REVOKED"
    else:
        if t["status"] != "REVOKED":
            raise_err("ERR_INVALID_STATE", "only a REVOKED track can be reopened")
        t["status"] = "ENDORSED"
    touch(t)
    return ok(ser_track(t))
