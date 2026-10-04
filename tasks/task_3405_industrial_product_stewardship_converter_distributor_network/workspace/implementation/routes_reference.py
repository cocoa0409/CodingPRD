"""Reference data: jurisdictions and the substance registry (PRD §3.1).
PlatformAdmin writes; all nine roles read by id."""

from flask import Blueprint

import auth
import envelope
import serialization as ser
import store
import validation
from errors import invalid_request, not_found

bp = Blueprint("reference", __name__)

RESTRICTION_CLASSES = {"STANDARD", "REPORTABLE", "RESTRICTED", "PROHIBITED"}


@bp.post("/stewardship/jurisdictions")
def create_jurisdiction():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["PlatformAdmin"])
    payload = validation.get_payload()
    code = validation.req_str(payload, "code")
    name = validation.req_str(payload, "name")
    declaration = validation.req_int(payload, "declaration_threshold_ppm")
    full = validation.req_int(payload, "full_disclosure_threshold_ppm")
    sla = validation.opt_int(payload, "review_sla_days", 30)
    if not full > declaration:
        raise invalid_request(
            "full_disclosure_threshold_ppm must be strictly greater than "
            "declaration_threshold_ppm")
    for existing in store.STORE["jurisdictions"].values():
        if existing["code"] == code:
            raise invalid_request("code must be unique across Jurisdiction")
    row = store.stamp_new({
        "code": code,
        "name": name,
        "declaration_threshold_ppm": declaration,
        "full_disclosure_threshold_ppm": full,
        "review_sla_days": sla,
    })
    store.STORE["jurisdictions"][row["id"]] = row
    return envelope.success_object(ser.jurisdiction(row), 201)


@bp.get("/stewardship/jurisdictions/<jid>")
def get_jurisdiction(jid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["jurisdictions"].get(jid)
    if row is None:
        raise not_found("Jurisdiction not found")
    return envelope.success_object(ser.jurisdiction(row), 200)


@bp.post("/stewardship/substances")
def create_substance():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["PlatformAdmin"])
    payload = validation.get_payload()
    cas_number = validation.req_str(payload, "cas_number")
    name = validation.req_str(payload, "name")
    restriction_class = validation.req_enum(
        payload, "restriction_class", RESTRICTION_CLASSES)
    for existing in store.STORE["substances"].values():
        if existing["cas_number"] == cas_number:
            raise invalid_request("cas_number must be unique across Substance")
    row = store.stamp_new({
        "cas_number": cas_number,
        "name": name,
        "restriction_class": restriction_class,
    })
    store.STORE["substances"][row["id"]] = row
    return envelope.success_object(ser.substance(row), 201)


@bp.get("/stewardship/substances/<sid>")
def get_substance(sid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    row = store.STORE["substances"].get(sid)
    if row is None:
        raise not_found("Substance not found")
    return envelope.success_object(ser.substance(row), 200)
