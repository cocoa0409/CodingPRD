"""District and district-link routes."""
from flask import Blueprint, request
from db import store, clock, fmt_iso
from errors import fail
from response import success_object, success_list, parse_pagination
from middleware import authenticate, require_role, require_parent_scope
import services as svc

bp = Blueprint("districts", __name__)

JURISDICTIONS = {"MANDATED_REPORTING", "DISCRETIONARY"}


def _get_district(district_id):
    d = store.districts.get(district_id)
    if not d:
        fail("ERR_NOT_FOUND", "District not found")
    return d


@bp.post("/api/districts")
def create_district():
    role, _uid = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = request.get_json(silent=True) or {}
    name = body.get("district_name")
    email = body.get("contact_email")
    jurisdiction = body.get("jurisdiction")
    if not isinstance(name, str) or not name:
        fail("ERR_INVALID_REQUEST", "district_name is required")
    if not isinstance(email, str) or not email:
        fail("ERR_INVALID_REQUEST", "contact_email is required")
    if jurisdiction not in JURISDICTIONS:
        fail("ERR_INVALID_REQUEST", "invalid jurisdiction")
    with store.lock:
        d = svc.new_entity()
        d.update({
            "district_name": name,
            "contact_email": email,
            "jurisdiction": jurisdiction,
            "district_status": "ACTIVE",
            "open_obligation_count": 0,
        })
        store.districts[d["id"]] = d
    return success_object(svc.ser_district(d), status=201)


@bp.get("/api/districts/<district_id>")
def get_district(district_id):
    role, uid = authenticate()
    require_role(role, {"SchoolAdmin", "PlatformAdmin"})
    d = _get_district(district_id)
    if role == "SchoolAdmin" and uid != d["id"]:
        fail("ERR_CROSS_DISTRICT_ACCESS", "SchoolAdmin may only view their own district")
    return success_object(svc.ser_district(d))


@bp.post("/api/districts/<district_id>/links")
def create_link(district_id):
    role, uid = authenticate()
    require_role(role, {"SchoolAdmin"})
    d = _get_district(district_id)
    if uid != d["id"]:
        fail("ERR_CROSS_DISTRICT_ACCESS", "SchoolAdmin may only act for their own district")
    if d["district_status"] != "ACTIVE":
        fail("ERR_DISTRICT_SUSPENDED", "District is SUSPENDED")
    body = request.get_json(silent=True) or {}
    child_id = body.get("child_profile_id")
    if not isinstance(child_id, str) or not child_id:
        fail("ERR_INVALID_REQUEST", "child_profile_id is required")
    child = store.children.get(child_id)
    if not child:
        fail("ERR_NOT_FOUND", "Child not found")
    with store.lock:
        l = svc.new_entity()
        l.update({
            "district_id": d["id"],
            "child_profile_id": child["id"],
            "link_status": "PENDING_CONSENT",
            "pending_legal_report": False,
            "consented_at": None,
        })
        store.district_links[l["id"]] = l
    return success_object(svc.ser_district_link(l), status=201)


@bp.get("/api/districts/<district_id>/links")
def list_links(district_id):
    role, uid = authenticate()
    require_role(role, {"SchoolAdmin", "PlatformAdmin"})
    d = _get_district(district_id)
    if role == "SchoolAdmin" and uid != d["id"]:
        fail("ERR_CROSS_DISTRICT_ACCESS", "SchoolAdmin may only view their own district")
    limit, offset = parse_pagination(request.args)
    items = [l for l in store.district_links.values()
             if l.get("district_id") == d["id"]]
    page, total = svc.paginate(items, limit, offset)
    return success_list([svc.ser_district_link(l) for l in page], limit, offset, total)


@bp.post("/api/district-links/<link_id>/state")
def link_state(link_id):
    role, uid = authenticate()
    require_role(role, {"Parent"})
    l = store.district_links.get(link_id)
    if not l:
        fail("ERR_NOT_FOUND", "DistrictLink not found")
    child = store.children.get(l["child_profile_id"])
    require_parent_scope(uid, child["family_account_id"] if child else None)
    body = request.get_json(silent=True) or {}
    to_status = body.get("to_status")
    if to_status not in ("ACTIVE", "WITHDRAWN"):
        fail("ERR_INVALID_REQUEST", "to_status must be ACTIVE or WITHDRAWN")
    current = l["link_status"]
    if current == "WITHDRAWN":
        fail("ERR_ALREADY_TERMINAL", "DistrictLink is WITHDRAWN")
    if (current, to_status) not in (("PENDING_CONSENT", "ACTIVE"),
                                    ("PENDING_CONSENT", "WITHDRAWN"),
                                    ("ACTIVE", "WITHDRAWN")):
        fail("ERR_INVALID_STATE",
             "Transition %s -> %s not permitted" % (current, to_status))
    district = store.districts.get(l["district_id"])
    if to_status == "ACTIVE":
        if district and district["district_status"] != "ACTIVE":
            fail("ERR_DISTRICT_SUSPENDED", "District is SUSPENDED")
        if child and child["profile_status"] != "ACTIVE":
            fail("ERR_CHILD_ARCHIVED", "Child is archived")
    elif to_status == "WITHDRAWN" and current == "ACTIVE":
        if l.get("pending_legal_report"):
            fail("ERR_LINK_WITHDRAW_BLOCKED",
                 "Withdrawal blocked while pending_legal_report is true")
    with store.lock:
        l["link_status"] = to_status
        if to_status == "ACTIVE":
            l["consented_at"] = fmt_iso(clock.now())
        svc.touch(l)
    return success_object(svc.ser_district_link(l))
