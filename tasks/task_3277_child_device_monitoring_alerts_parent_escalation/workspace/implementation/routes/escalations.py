"""Escalation case routes: get, list, state transitions."""
from flask import Blueprint, request
from db import store, clock, fmt_iso
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import (authenticate, require_role, require_parent_scope,
                        require_school_scope_child)
import services as svc

bp = Blueprint("escalations", __name__)

CASE_STATUSES = {"OPEN", "GUIDANCE_ISSUED", "RESOURCE_REFERRED",
                 "CRISIS_ESCALATED", "LEGAL_REPORTED", "CLOSED"}

# (from, to) -> allowed roles
EDGES = {
    ("GUIDANCE_ISSUED", "RESOURCE_REFERRED"): {"Parent"},
    ("GUIDANCE_ISSUED", "CRISIS_ESCALATED"): {"Parent"},
    ("RESOURCE_REFERRED", "CLOSED"): {"Parent"},
    ("CRISIS_ESCALATED", "LEGAL_REPORTED"): {"SchoolAdmin", "PlatformAdmin"},
    ("CRISIS_ESCALATED", "CLOSED"): {"Parent"},
    ("LEGAL_REPORTED", "CLOSED"): {"SchoolAdmin", "PlatformAdmin"},
}


def _get_case(case_id):
    c = store.escalation_cases.get(case_id)
    if not c:
        fail("ERR_NOT_FOUND", "EscalationCase not found")
    return c


def _scope_check(role, uid, case):
    if role == "Parent":
        child = store.children.get(case["child_profile_id"])
        require_parent_scope(uid, child["family_account_id"] if child else None)
    elif role == "SchoolAdmin":
        require_school_scope_child(uid, case["child_profile_id"])


@bp.get("/api/escalation-cases/<case_id>")
def get_case(case_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    c = _get_case(case_id)
    _scope_check(role, uid, c)
    return success_object(svc.ser_case(c))


@bp.get("/api/escalation-cases")
def list_cases():
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    f_alert = request.args.get("alert_id")
    f_child = request.args.get("child_profile_id")
    f_status = request.args.get("case_status")
    if f_status is not None and f_status not in CASE_STATUSES:
        fail("ERR_INVALID_REQUEST", "invalid case_status")

    fam_id = None
    if role == "Parent":
        from middleware import parent_family_id
        fam_id = parent_family_id(uid)
        if fam_id is None:
            fail("ERR_FORBIDDEN_ROLE", "Parent identity not recognized")
        if f_child:
            child = store.children.get(f_child)
            if child and child.get("family_account_id") != fam_id:
                fail("ERR_CROSS_FAMILY_ACCESS", "Child belongs to a different family")
    if role == "SchoolAdmin" and f_child:
        require_school_scope_child(uid, f_child)

    limit, offset = parse_pagination(request.args)
    items = []
    for c in store.escalation_cases.values():
        if f_alert and c.get("alert_id") != f_alert:
            continue
        if f_child and c.get("child_profile_id") != f_child:
            continue
        if f_status and c.get("case_status") != f_status:
            continue
        if role == "Parent":
            child = store.children.get(c.get("child_profile_id"))
            if not child or child.get("family_account_id") != fam_id:
                continue
        elif role == "SchoolAdmin":
            from middleware import school_admin_child_ids
            if c.get("child_profile_id") not in school_admin_child_ids(uid):
                continue
        items.append(c)
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_case(c) for c in page], limit, offset, total)


@bp.post("/api/escalation-cases/<case_id>/state")
def case_state(case_id):
    role, uid = authenticate()
    require_role(role, {"Parent", "SchoolAdmin", "PlatformAdmin"})
    c = _get_case(case_id)
    _scope_check(role, uid, c)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in CASE_STATUSES:
        fail("ERR_INVALID_REQUEST", "invalid to_status")
    current = c["case_status"]
    if current == "CLOSED":
        fail("ERR_ALREADY_TERMINAL", "EscalationCase is CLOSED")
    edge = (current, to_status)
    if edge not in EDGES:
        fail("ERR_INVALID_ESCALATION_STEP",
             "Transition %s -> %s not permitted" % (current, to_status))
    if role not in EDGES[edge]:
        fail("ERR_INVALID_ESCALATION_STEP",
             "Role %s not permitted for this escalation step" % role)

    child = store.children.get(c["child_profile_id"])
    family = svc.family_of_child(c["child_profile_id"])

    if edge == ("CRISIS_ESCALATED", "LEGAL_REPORTED"):
        # Requires an ACTIVE MANDATED_REPORTING link with pending_legal_report
        target = None
        if c.get("district_link_id"):
            link = store.district_links.get(c["district_link_id"])
            if (link and link.get("link_status") == "ACTIVE"
                    and link.get("pending_legal_report")):
                district = store.districts.get(link.get("district_id"))
                if district and district.get("jurisdiction") == "MANDATED_REPORTING":
                    target = link
        if target is None:
            for link in store.district_links.values():
                if (link.get("child_profile_id") == c["child_profile_id"]
                        and link.get("link_status") == "ACTIVE"
                        and link.get("pending_legal_report")):
                    district = store.districts.get(link.get("district_id"))
                    if district and district.get("jurisdiction") == "MANDATED_REPORTING":
                        target = link
                        break
        if target is None:
            fail("ERR_LEGAL_REPORT_NOT_REQUIRED",
                 "No ACTIVE mandated-reporting link with pending_legal_report")
        with store.lock:
            c["case_status"] = "LEGAL_REPORTED"
            c["legal_report_filed_at"] = fmt_iso(clock.now())
            svc.touch(c)
            target["pending_legal_report"] = False
            svc.bump(target)
            district = store.districts.get(target["district_id"])
            if district:
                svc.recompute_district_obligations(district)
        return success_object(svc.ser_case(c))

    if edge == ("CRISIS_ESCALATED", "CLOSED"):
        for link in store.district_links.values():
            if (link.get("child_profile_id") == c["child_profile_id"]
                    and link.get("link_status") == "ACTIVE"
                    and link.get("pending_legal_report")):
                fail("ERR_INVALID_ESCALATION_STEP",
                     "Mandated legal report must be filed before closing")

    with store.lock:
        c["case_status"] = to_status
        svc.touch(c)
        if to_status == "CLOSED" and family:
            svc.recompute_open_escalation_count(family)
    return success_object(svc.ser_case(c))
