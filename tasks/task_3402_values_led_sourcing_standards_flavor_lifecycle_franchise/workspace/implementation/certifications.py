"""Supplier certifications: register, list, verify, revoke (PRD 3.1).

Creation window rules run in this order: first half-open window overlap
against PENDING/VERIFIED certificates of the same (supplier, scheme, scope)
— pure adjacency is allowed because the window end is exclusive — then
window validity (valid_until strictly later than issued_at).
"""
from flask import Blueprint, request

import cascades
from auth import authenticate, authorize
from db import STORE, new_resource, public, sorted_items, touch
from envelope import ok, ok_list, pagination_args
from errors import fail
from suppliers import get_supplier
from timeutil import fmt_dt, parse_iso
from validate import (CERT_SCHEMES, CERT_SCOPES, get_body, req_dt, req_enum,
                      req_num, req_str)

bp = Blueprint("certifications", __name__)


def get_certification(cid):
    c = STORE["certifications"].get(cid)
    if c is None:
        fail("ERR_CERTIFICATION_NOT_FOUND", "Certification id does not exist")
    return c


@bp.post("/suppliers/<sid>/certifications")
def create_certification(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager",))
    get_supplier(sid)
    body = get_body()
    scheme = req_enum(body, "scheme", CERT_SCHEMES)
    number = req_str(body, "certificate_number")
    scope = req_enum(body, "ingredient_scope", CERT_SCOPES)
    issued = req_dt(body, "issued_at")
    valid_until = req_dt(body, "valid_until")
    declared = req_num(body, "declared_coverage_pct", 0, 100)
    # Rule 1 (priority 11): half-open overlap, adjacency allowed.
    for c in STORE["certifications"].values():
        if (c["supplier_id"] == sid and c["scheme"] == scheme
                and c["ingredient_scope"] == scope
                and c["status"] in ("PENDING", "VERIFIED")):
            o_issued = parse_iso(c["issued_at"])
            o_until = parse_iso(c["valid_until"])
            if issued < o_until and o_issued < valid_until:
                fail("ERR_CERT_WINDOW_OVERLAP",
                     "Certification window overlaps an existing "
                     "PENDING/VERIFIED certificate for the same scheme "
                     "and scope")
    # Rule 2 (priority 12): non-degenerate window.
    if not valid_until > issued:
        fail("ERR_CERT_WINDOW_INVALID",
             "valid_until must be strictly later than issued_at")
    r = new_resource()
    r.update({
        "supplier_id": sid,
        "scheme": scheme,
        "certificate_number": number,
        "ingredient_scope": scope,
        "issued_at": fmt_dt(issued),
        "valid_until": fmt_dt(valid_until),
        "declared_coverage_pct": declared,
        "verified_coverage_pct": None,
        "status": "PENDING",
    })
    STORE["certifications"][r["id"]] = r
    return ok(public(r), 201)


@bp.get("/suppliers/<sid>/certifications")
def list_certifications(sid):
    _, role = authenticate()
    authorize(role, ("SourcingManager", "AuditVerifier", "FlavorManager"))
    get_supplier(sid)
    status = request.args.get("status")
    items = [c for c in STORE["certifications"].values()
             if c["supplier_id"] == sid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = [public(c) for c in sorted_items(items)]
    limit, offset = pagination_args()
    return ok_list(items, limit, offset)


@bp.post("/certifications/<cid>/verify")
def verify_certification(cid):
    _, role = authenticate()
    authorize(role, ("AuditVerifier",))
    c = get_certification(cid)
    body = get_body()
    verified = req_num(body, "verified_coverage_pct", 0, 100)
    supplier = STORE["suppliers"].get(c["supplier_id"])
    if supplier is not None and supplier["status"] == "TERMINATED":
        fail("ERR_INVALID_STATE",
             "A terminated supplier's certifications cannot be verified")
    if c["status"] != "PENDING":
        fail("ERR_INVALID_STATE",
             "Only a PENDING certification can be verified")
    c["verified_coverage_pct"] = verified
    c["status"] = "VERIFIED"
    touch(c)
    return ok(public(c))


@bp.post("/certifications/<cid>/revoke")
def revoke_certification(cid):
    _, role = authenticate()
    authorize(role, ("AuditVerifier",))
    c = get_certification(cid)
    if c["status"] not in ("PENDING", "VERIFIED"):
        fail("ERR_INVALID_STATE",
             "Only a PENDING or VERIFIED certification can be revoked")
    c["status"] = "REVOKED"
    touch(c)
    cascades.challenge_claims_citing([c["id"]])
    return ok(public(c))
