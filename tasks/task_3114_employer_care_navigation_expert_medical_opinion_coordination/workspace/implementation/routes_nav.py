"""Routes: navigation cases and appointments."""
from flask import Blueprint, request

from db import db, _parse_dt
from errors import fail
from common import (envelope, paginate, body, auth, require_role,
                    check_member_scope, active_consent, touch)
from helpers import new_entity, get_or_404, req_str, opt_str, req_int, req_enum
from calcs import intake_routing, PROVIDER_DAILY_CAPACITY

bp = Blueprint("nav", __name__)

NAV_DISCIPLINE_TO_ROLE = {"NURSE": "NurseNavigator", "ADVOCATE": "CareAdvocate", "PHYSICIAN": "PhysicianAdvisor"}
ESCALATE = {"ADVOCATE": "NURSE", "NURSE": "PHYSICIAN", "PHYSICIAN": "PHYSICIAN"}


def _nav_case(cid):
    return get_or_404(db.navigation_cases, cid, "navigation case")


# ---- navigation cases -------------------------------------------------------

@bp.post("/care/members/<mid>/navigation-cases")
def create_navigation_case(mid):
    user_id, role = auth()
    require_role(role, {"Member", "NurseNavigator", "CareAdvocate"})
    data = body()
    qt = req_enum(data, "question_type", {"CLINICAL", "BENEFIT", "COST"})
    acuity = data.get("acuity")
    est = data.get("estimated_cost_cents")
    if qt == "CLINICAL":
        if acuity not in ("LOW", "MEDIUM", "HIGH"):
            fail("ERR_INVALID_REQUEST", "acuity required for CLINICAL")
    elif acuity is not None and acuity not in ("LOW", "MEDIUM", "HIGH"):
        fail("ERR_INVALID_REQUEST", "invalid acuity")
    if qt == "COST":
        if est is None or isinstance(est, bool) or not isinstance(est, int):
            fail("ERR_INVALID_REQUEST", "estimated_cost_cents required for COST")
    elif est is not None and (isinstance(est, bool) or not isinstance(est, int)):
        fail("ERR_INVALID_REQUEST", "estimated_cost_cents must be an integer")
    m = get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    discipline = intake_routing(qt, acuity, est, m["relationship"])
    case = new_entity({
        "member_id": mid,
        "question_type": qt,
        "acuity": acuity if qt == "CLINICAL" else None,
        "estimated_cost_cents": est if qt == "COST" else None,
        "routed_discipline": discipline,
        "assigned_user_id": None,
        "escalation_count": 0,
        "status": "ROUTED",
    })
    db.navigation_cases[case["id"]] = case
    return envelope(case, status=201)


@bp.get("/care/navigation-cases/<cid>")
def get_navigation_case(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    case = _nav_case(cid)
    check_member_scope(case["member_id"], user_id, role)
    return envelope(case)


@bp.get("/care/members/<mid>/navigation-cases")
def list_member_navigation_cases(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [c for c in db.navigation_cases.values() if c["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: c["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/navigation-cases/<cid>/start")
def start_navigation_case(cid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    case = _nav_case(cid)
    if case["status"] not in ("ROUTED", "ESCALATED"):
        fail("ERR_INVALID_STATE", "case is not ROUTED or ESCALATED")
    if NAV_DISCIPLINE_TO_ROLE[case["routed_discipline"]] != role:
        fail("ERR_DISCIPLINE_MISMATCH", "acting role discipline does not match routed_discipline")
    case["status"] = "IN_PROGRESS"
    case["assigned_user_id"] = user_id
    touch(case)
    return envelope(case)


@bp.post("/care/navigation-cases/<cid>/escalate")
def escalate_navigation_case(cid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    case = _nav_case(cid)
    if case["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "case is not IN_PROGRESS")
    case["status"] = "ESCALATED"
    case["escalation_count"] += 1
    case["routed_discipline"] = ESCALATE[case["routed_discipline"]]
    case["assigned_user_id"] = None
    touch(case)
    return envelope(case)


@bp.post("/care/navigation-cases/<cid>/resolve")
def resolve_navigation_case(cid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    case = _nav_case(cid)
    if case["status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE", "case is not IN_PROGRESS")
    if case["assigned_user_id"] != user_id:
        fail("ERR_NOT_ASSIGNED_NAVIGATOR", "only the assigned navigator may resolve the case")
    case["status"] = "RESOLVED"
    touch(case)
    return envelope(case)


@bp.post("/care/navigation-cases/<cid>/close")
def close_navigation_case(cid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    case = _nav_case(cid)
    if case["status"] != "RESOLVED":
        fail("ERR_INVALID_STATE", "case is not RESOLVED")
    case["status"] = "CLOSED"
    touch(case)
    return envelope(case)


@bp.get("/care/navigation-cases/<cid>/appointments")
def list_case_appointments(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "CareAdvocate",
                        "PhysicianAdvisor", "EmployerAdmin"})
    case = _nav_case(cid)
    check_member_scope(case["member_id"], user_id, role)
    items = [a for a in db.appointments.values() if a.get("navigation_case_id") == cid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/navigation-cases/<cid>/expert-opinions")
def list_case_opinions(cid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "PhysicianAdvisor",
                        "RecordsSpecialist", "ExpertReviewer"})
    case = _nav_case(cid)
    check_member_scope(case["member_id"], user_id, role)
    items = [o for o in db.expert_opinions.values() if o.get("navigation_case_id") == cid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    items.sort(key=lambda o: o["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


# ---- appointments -----------------------------------------------------------

def _slot_checks(provider_id, slot_start_s, slot_end_s, exclude_id=None):
    start = _parse_dt(slot_start_s)
    end = _parse_dt(slot_end_s)
    for a in db.appointments.values():
        if a["provider_id"] != provider_id or a["status"] != "BOOKED":
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        ex_start = _parse_dt(a["slot_start"])
        ex_end = _parse_dt(a["slot_end"])
        if start < ex_end and ex_start < end:
            fail("ERR_SLOT_CONFLICT", "slot overlaps an existing BOOKED slot")
    day = start.date()
    count = 0
    for a in db.appointments.values():
        if a["provider_id"] != provider_id or a["status"] != "BOOKED":
            continue
        if exclude_id and a["id"] == exclude_id:
            continue
        if _parse_dt(a["slot_start"]).date() == day:
            count += 1
    if count >= PROVIDER_DAILY_CAPACITY:
        fail("ERR_PROVIDER_DAY_CAPACITY", "provider daily capacity reached")


@bp.post("/care/members/<mid>/appointments")
def create_appointment(mid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate"})
    data = body()
    provider_id = req_str(data, "provider_id")
    slot_start = req_str(data, "slot_start")
    slot_end = req_str(data, "slot_end")
    nav_case_id = opt_str(data, "navigation_case_id")
    redirected = data.get("redirected_from_out_of_network", False)
    if not isinstance(redirected, bool):
        fail("ERR_INVALID_REQUEST", "redirected_from_out_of_network must be a boolean")
    m = get_or_404(db.members, mid, "member")
    get_or_404(db.providers, provider_id, "provider")
    if nav_case_id is not None:
        get_or_404(db.navigation_cases, nav_case_id, "navigation case")
    if m["eligibility_status"] != "ACTIVE":
        fail("ERR_MEMBER_INELIGIBLE", "member is not ACTIVE")
    if active_consent(mid, "APPOINTMENT_BOOKING") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE APPOINTMENT_BOOKING consent")
    _slot_checks(provider_id, slot_start, slot_end)
    a = new_entity({
        "member_id": mid,
        "provider_id": provider_id,
        "navigation_case_id": nav_case_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "redirected_from_out_of_network": redirected,
        "status": "BOOKED",
        "booked_by_user_id": user_id,
        "late_cancel": False,
    })
    db.appointments[a["id"]] = a
    return envelope(a, status=201)


@bp.get("/care/appointments/<aid>")
def get_appointment(aid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "CareAdvocate", "PhysicianAdvisor"})
    a = get_or_404(db.appointments, aid, "appointment")
    check_member_scope(a["member_id"], user_id, role)
    return envelope(a)


@bp.get("/care/members/<mid>/appointments")
def list_member_appointments(mid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "Member", "NurseNavigator", "CareAdvocate"})
    get_or_404(db.members, mid, "member")
    check_member_scope(mid, user_id, role)
    items = [a for a in db.appointments.values() if a["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.get("/care/providers/<pid>/appointments")
def list_provider_appointments(pid):
    user_id, role = auth()
    require_role(role, {"PlatformAdmin", "NurseNavigator", "CareAdvocate"})
    get_or_404(db.providers, pid, "provider")
    items = [a for a in db.appointments.values() if a["provider_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda a: a["created_at"])
    page, meta = paginate(items)
    return envelope(page, "array", meta)


@bp.post("/care/appointments/<aid>/reschedule")
def reschedule_appointment(aid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate"})
    data = body()
    slot_start = req_str(data, "slot_start")
    slot_end = req_str(data, "slot_end")
    a = get_or_404(db.appointments, aid, "appointment")
    if a["status"] != "BOOKED":
        fail("ERR_INVALID_STATE", "appointment is not BOOKED")
    if active_consent(a["member_id"], "APPOINTMENT_BOOKING") is None:
        fail("ERR_CONSENT_REQUIRED", "no ACTIVE APPOINTMENT_BOOKING consent")
    _slot_checks(a["provider_id"], slot_start, slot_end, exclude_id=aid)
    a["slot_start"] = slot_start
    a["slot_end"] = slot_end
    touch(a)
    return envelope(a)


@bp.post("/care/appointments/<aid>/cancel")
def cancel_appointment(aid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate", "Member"})
    a = get_or_404(db.appointments, aid, "appointment")
    check_member_scope(a["member_id"], user_id, role)
    if a["status"] != "BOOKED":
        fail("ERR_INVALID_STATE", "appointment is not BOOKED")
    a["status"] = "CANCELLED"
    a["late_cancel"] = db.clock >= _parse_dt(a["slot_start"])
    touch(a)
    return envelope(a)


@bp.post("/care/appointments/<aid>/complete")
def complete_appointment(aid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate"})
    a = get_or_404(db.appointments, aid, "appointment")
    if a["status"] != "BOOKED":
        fail("ERR_INVALID_STATE", "appointment is not BOOKED")
    if db.clock < _parse_dt(a["slot_end"]):
        fail("ERR_APPOINTMENT_NOT_DUE", "slot has not ended")
    a["status"] = "COMPLETED"
    touch(a)
    return envelope(a)


@bp.post("/care/appointments/<aid>/mark-no-show")
def no_show_appointment(aid):
    user_id, role = auth()
    require_role(role, {"NurseNavigator", "CareAdvocate"})
    a = get_or_404(db.appointments, aid, "appointment")
    if a["status"] != "BOOKED":
        fail("ERR_INVALID_STATE", "appointment is not BOOKED")
    if db.clock <= _parse_dt(a["slot_end"]):
        fail("ERR_APPOINTMENT_NOT_DUE", "slot has not passed")
    a["status"] = "NO_SHOW"
    touch(a)
    return envelope(a)
