"""Event endpoints (PRD 3.7): creation fork, security approval, confirm, cancel."""

from flask import Blueprint

from constants import EVENT_KINDS
from helpers import (
    authn,
    base_entity,
    body,
    bump,
    err,
    get_center,
    get_event,
    opt_bool,
    opt_int,
    opt_str,
    paginate,
    req_datetime,
    req_enum,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    validation,
)
from services import active_agreement
from storage import STORE

bp = Blueprint("events", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")


@bp.route("/centers/<cid>/events", methods=["POST"])
def create_event(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    b = body()
    kind = req_enum(b, "kind", EVENT_KINDS)
    name = req_str(b, "name")
    start_at = req_datetime(b, "start_at")
    end_at = req_datetime(b, "end_at")
    if not end_at > start_at:
        validation("end_at must be later than start_at")
    unit_name = opt_str(b, "unit_name")
    min_volunteers = opt_int(b, "min_volunteers", default=2, minimum=0)
    required_security_level = opt_int(b, "required_security_level", default=1, minimum=1, maximum=5)
    talent_signed = opt_bool(b, "talent_agreement_signed", default=False)
    budget = opt_int(b, "event_budget_cents", default=0, minimum=0)
    center = get_center(cid)

    # Event calendar: half-open overlap with any non-CANCELLED event at the center.
    for ev in STORE.events.values():
        if ev["center_id"] != center["id"] or ev["status"] == "CANCELLED":
            continue
        if start_at < ev["end_at"] and ev["start_at"] < end_at:
            err("ERR_EVENT_OVERLAP", 409, "Event overlaps another event at this center")

    ev = base_entity()
    ev.update({
        "center_id": center["id"],
        "kind": kind,
        "name": name,
        "start_at": start_at,
        "end_at": end_at,
        "unit_name": unit_name,
        "min_volunteers": min_volunteers,
        "required_security_level": required_security_level,
        "talent_agreement_signed": talent_signed,
        "event_budget_cents": budget,
        "status": "SECURITY_REVIEW" if kind == "ENTERTAINMENT_TOUR" else "PLANNED",
    })
    STORE.events[ev["id"]] = ev
    return success_object(serialize(ev), status=201)


@bp.route("/centers/<cid>/events", methods=["GET"])
def list_events(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    items = [e for e in STORE.events.values() if e["center_id"] == center["id"]]
    page, meta = paginate(items)
    return success_list(page, meta)


@bp.route("/events/<eid>/approve-security", methods=["POST"])
def approve_security(eid):
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    ev = get_event(eid)
    if ev["kind"] != "ENTERTAINMENT_TOUR" or ev["status"] != "SECURITY_REVIEW":
        err("ERR_INVALID_STATE", 409, "Only an ENTERTAINMENT_TOUR in SECURITY_REVIEW can be approved")
    center = get_center(ev["center_id"])
    ag = active_agreement(center)
    if ag is None:
        err("ERR_AGREEMENT_NOT_ACTIVE", 409, "Host center has no ACTIVE site agreement")
    if ag["security_level"] < ev["required_security_level"]:
        err("ERR_SECURITY_LEVEL_INSUFFICIENT", 409, "Agreement security level is below the requirement")
    if not ev["talent_agreement_signed"]:
        err("ERR_TALENT_AGREEMENT_UNSIGNED", 409, "Talent agreement is not signed")
    ev["status"] = "SECURITY_APPROVED"
    bump(ev)
    return success_object(serialize(ev))


@bp.route("/events/<eid>/confirm", methods=["POST"])
def confirm_event(eid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    ev = get_event(eid)
    if ev["kind"] == "ENTERTAINMENT_TOUR":
        if ev["status"] != "SECURITY_APPROVED":
            err("ERR_INVALID_STATE", 409, "Tours confirm only from SECURITY_APPROVED")
    else:
        if ev["status"] != "PLANNED":
            err("ERR_INVALID_STATE", 409, "Deployment/homecoming events confirm only from PLANNED")

    # Optimistic staffing: CONFIRMED + 0.5 * ASSIGNED over overlapping shifts,
    # compared exactly: 2*confirmed + assigned >= 2*min_volunteers.
    confirmed = 0
    assigned = 0
    for s in STORE.shifts.values():
        if s["center_id"] != ev["center_id"]:
            continue
        if not (s["start_at"] < ev["end_at"] and ev["start_at"] < s["end_at"]):
            continue
        for a in STORE.assignments.values():
            if a["shift_id"] != s["id"]:
                continue
            if a["status"] == "CONFIRMED":
                confirmed += 1
            elif a["status"] == "ASSIGNED":
                assigned += 1
    if 2 * confirmed + assigned < 2 * ev["min_volunteers"]:
        err("ERR_STAFFING_SHORTFALL", 409, "Pledged staffing is below min_volunteers")

    ev["status"] = "CONFIRMED"
    bump(ev)
    return success_object(serialize(ev))


@bp.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    ev = get_event(eid)
    if ev["status"] not in ("PLANNED", "SECURITY_REVIEW", "SECURITY_APPROVED", "CONFIRMED"):
        err("ERR_INVALID_STATE", 409, "Only a non-terminal event can be cancelled")
    ev["status"] = "CANCELLED"
    bump(ev)
    return success_object(serialize(ev))
