"""Odor complaint endpoints (PRD 3.11)."""

from flask import Blueprint

import store
from auth import roles
from derive import (defer_pre_field_events, derive_posture, derive_site_odor,
                    recompute_substantiated_30d)
from envelope import object_response
from errors import fail
from listing import emit_list
from store import iso, now_iso, public, touch
from validate import (get_body, present, qenum, qstr, resolve_fks, vdt, venum, vstr)

bp = Blueprint("odor", __name__, url_prefix="/api/v1/odor-complaints")

SEVERITIES = ("LOW", "MODERATE", "SEVERE")
COMPLAINT_STATUSES = ("RECEIVED", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED",
                      "CLOSED")
RESOLUTION_ACTIONS = ("NONE", "PUBLIC_NOTICE", "OPERATIONAL_CHANGE", "SITE_RESTRICTION")
READ_ROLES = ("PublicLiaison", "ComplianceOfficer", "FacilityOperator", "Agronomist")


def get_complaint(complaint_id):
    complaint = store.complaints.get(complaint_id)
    if complaint is None:
        fail("ERR_COMPLAINT_NOT_FOUND", "Complaint %s does not exist." % complaint_id)
    return complaint


def _site_of(complaint):
    site_id = complaint.get("site_id")
    return store.sites.get(site_id) if site_id else None


@bp.post("")
@roles("PublicLiaison", "FacilityOperator")
def create_complaint():
    body = get_body()
    fks = resolve_fks(body, ("facility_id", "site_id"))
    facility_id = body.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        fail("ERR_INVALID_REQUEST", "Field 'facility_id' is required.")
    facility = fks["facility_id"]
    site = fks.get("site_id")
    if present(body, "site_id") and not isinstance(body.get("site_id"), str):
        fail("ERR_INVALID_REQUEST", "Field 'site_id' must be a string identifier.")
    received_at = vdt(body, "received_at", required=True)
    severity = venum(body, "severity", SEVERITIES, required=True)
    description = vstr(body, "description", required=False, min_len=1, max_len=500,
                       default=None)
    contact = vstr(body, "complainant_contact", required=False, min_len=1, max_len=120,
                   default=None)

    complaint = store.new_record({
        "facility_id": facility["id"],
        "site_id": site["id"] if site is not None else None,
        "received_at": iso(received_at),
        "severity": severity,
        "description": description,
        "complainant_contact": contact,
        "status": "RECEIVED",
        "resolution_action": None,
        "investigation_note": None,
        "resolved_at": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.complaints[complaint["id"]] = complaint
    if site is not None:
        derive_site_odor(site)
        touch(site)
    return object_response(public(complaint), 201)


@bp.get("/<complaint_id>")
@roles(*READ_ROLES)
def read_complaint(complaint_id):
    return object_response(public(get_complaint(complaint_id)))


@bp.get("")
@roles(*READ_ROLES)
def list_complaints():
    facility_id = qstr("facility_id")
    site_id = qstr("site_id")
    severity = qenum("severity", SEVERITIES)
    status = qenum("status", COMPLAINT_STATUSES)
    rows = [c for c in store.complaints.values()
            if (facility_id is None or c["facility_id"] == facility_id)
            and (site_id is None or c.get("site_id") == site_id)
            and (severity is None or c["severity"] == severity)
            and (status is None or c["status"] == status)]
    return emit_list(rows, ("received_at", "created_at"))


@bp.post("/<complaint_id>/investigate")
@roles("ComplianceOfficer", "PublicLiaison")
def investigate(complaint_id):
    complaint = get_complaint(complaint_id)
    get_body()
    if complaint["status"] != "RECEIVED":
        fail("ERR_COMPLAINT_INVALID_STATE",
             "Only a RECEIVED complaint may be investigated.")
    complaint["status"] = "INVESTIGATING"
    touch(complaint)
    site = _site_of(complaint)
    if site is not None:
        derive_site_odor(site)
        touch(site)
    return object_response(public(complaint))


@bp.post("/<complaint_id>/resolve")
@roles("ComplianceOfficer")
def resolve(complaint_id):
    complaint = get_complaint(complaint_id)
    body = get_body()
    outcome = venum(body, "outcome", ("SUBSTANTIATED", "UNSUBSTANTIATED"), required=True)
    note = vstr(body, "investigation_note", required=False, min_len=1, default=None)
    resolution_action = venum(body, "resolution_action", RESOLUTION_ACTIONS,
                              required=False, default="NONE")
    if complaint["status"] != "INVESTIGATING":
        fail("ERR_COMPLAINT_INVALID_STATE",
             "Only an INVESTIGATING complaint may be resolved.")
    if outcome == "UNSUBSTANTIATED":
        resolution_action = "NONE"
    complaint["status"] = outcome
    complaint["resolution_action"] = resolution_action
    if note is not None:
        complaint["investigation_note"] = note
    complaint["resolved_at"] = now_iso()
    touch(complaint)

    site = _site_of(complaint)
    if outcome == "SUBSTANTIATED":
        if site is not None:
            derive_site_odor(site)
            touch(site)
        facility = store.facilities.get(complaint["facility_id"])
        if facility is not None:
            recompute_substantiated_30d(facility)
            derive_posture(facility)
            touch(facility)
        if (resolution_action == "SITE_RESTRICTION" and site is not None
                and site["status"] == "PERMITTED"):
            site["status"] = "RESTRICTED"
            site["restriction_reason"] = "ODOR_RISK_HIGH"
            site["updated_at"] = now_iso()
            defer_pre_field_events(site["id"], "ODOR_RISK")
    else:
        if site is not None:
            derive_site_odor(site)
            touch(site)
    return object_response(public(complaint))


@bp.post("/<complaint_id>/close")
@roles("PublicLiaison", "ComplianceOfficer")
def close_complaint(complaint_id):
    complaint = get_complaint(complaint_id)
    get_body()
    if complaint["status"] not in ("SUBSTANTIATED", "UNSUBSTANTIATED"):
        fail("ERR_COMPLAINT_INVALID_STATE",
             "Only a resolved complaint may be closed.")
    complaint["status"] = "CLOSED"
    touch(complaint)
    return object_response(public(complaint))
