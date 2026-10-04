"""Degree reporting, sealing, and revocation (PRD §3.6)."""
from flask import Blueprint, request

import calc
import cascade
import db
from auth import (
    ROLE_CERTIFIER,
    ROLE_CLEARINGHOUSE_OPS,
    ROLE_SUBMITTER,
    REGISTRAR_ROLES,
    authenticate,
    require_role,
)
from core import (
    ERR_AGREEMENT_LAPSED,
    ERR_CROSS_INSTITUTION_ACCESS,
    ERR_DEGREE_NOT_FOUND,
    ERR_INSTITUTION_NON_COMPLIANT,
    ERR_INSTITUTION_NOT_FOUND,
    ERR_INSTITUTION_SUSPENDED,
    ERR_INVALID_STATE,
    ERR_STUDENT_NOT_FOUND,
    ERR_UNAUTHORIZED,
    get_body,
    list_response,
    ok_object,
    raise_err,
    req_date,
    req_enum,
    req_str,
)

bp = Blueprint("degrees", __name__)

READ_ROLES = (ROLE_CLEARINGHOUSE_OPS, ROLE_SUBMITTER, ROLE_CERTIFIER)
LEVELS = ("CERTIFICATE", "ASSOCIATE", "BACHELOR", "MASTER", "DOCTORATE")


@bp.route("/degree-records", methods=["POST"])
def create_degree():
    caller = authenticate()
    require_role(caller, ROLE_SUBMITTER)
    data = get_body()
    # Tenancy (priority 4) precedes well-formedness (priority 7).
    raw_inst = data.get("institution_id")
    if isinstance(raw_inst, str) and raw_inst != caller.institution_id:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "submitter's institution does not match the degree's")
    institution_id = req_str(data, "institution_id")
    student_id = req_str(data, "student_id")
    degree_level = req_enum(data, "degree_level", LEVELS)
    degree_title = req_str(data, "degree_title")
    conferred_on = req_date(data, "conferred_on")
    if db.store.institutions.get(institution_id) is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    if db.store.students.get(student_id) is None:
        raise_err(ERR_STUDENT_NOT_FOUND, "student not found")
    degree = db.new_entity(
        {
            "institution_id": institution_id,
            "student_id": student_id,
            "degree_level": degree_level,
            "degree_title": degree_title,
            "conferred_on": conferred_on,
            "status": "REPORTED",
            "sealed_at": None,
            "created_by_user_id": caller.user_id,
        }
    )
    db.store.degrees[degree["id"]] = degree
    return ok_object(db.serialize(degree), 201)


@bp.route("/degree-records/<did>", methods=["GET"])
def get_degree(did):
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    degree = db.store.degrees.get(did)
    if degree is None:
        raise_err(ERR_DEGREE_NOT_FOUND, "degree record not found")
    if caller.role in REGISTRAR_ROLES and caller.institution_id != degree["institution_id"]:
        raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
    return ok_object(db.serialize(degree))


@bp.route("/degree-records", methods=["GET"])
def list_degrees():
    caller = authenticate()
    require_role(caller, *READ_ROLES)
    q = request.args
    institution_id = q.get("institution_id")
    if caller.role in REGISTRAR_ROLES:
        if institution_id is not None and institution_id != caller.institution_id:
            raise_err(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
        institution_id = caller.institution_id
    items = list(db.store.degrees.values())
    if q.get("student_id") is not None:
        items = [d for d in items if d["student_id"] == q["student_id"]]
    if institution_id is not None:
        items = [d for d in items if d["institution_id"] == institution_id]
    if q.get("status") is not None:
        items = [d for d in items if d["status"] == q["status"]]
    # conferred_on ASC, then created_at ASC (PRD §3.6)
    items.sort(key=lambda d: d["_seq"])
    items.sort(key=lambda d: d["conferred_on"])  # stable
    return list_response(items, db.serialize)


@bp.route("/degree-records/<did>/seal", methods=["POST"])
def seal_degree(did):
    caller = authenticate()
    require_role(caller, ROLE_CERTIFIER)
    degree = db.store.degrees.get(did)
    if degree is None:
        raise_err(ERR_DEGREE_NOT_FOUND, "degree record not found")
    if caller.institution_id != degree["institution_id"]:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "certifier's institution does not match the degree's")
    if degree["status"] != "REPORTED":
        raise_err(ERR_INVALID_STATE, "only a REPORTED degree can be sealed")
    inst = db.store.institutions.get(degree["institution_id"])
    if inst is None:
        raise_err(ERR_INSTITUTION_NOT_FOUND, "institution not found")
    if inst["status"] != "ACTIVE":
        raise_err(ERR_INSTITUTION_SUSPENDED, "institution is suspended")
    if not cascade.active_agreement_covers(degree["institution_id"]):
        raise_err(ERR_AGREEMENT_LAPSED, "no ACTIVE agreement covers now")
    if inst["compliance_standing"] == "NON_COMPLIANT":
        raise_err(ERR_INSTITUTION_NON_COMPLIANT, "institution is NON_COMPLIANT")
    degree["sealed_at"] = db.now()
    degree["status"] = "SEALED"
    db.touch(degree)
    return ok_object(db.serialize(degree))


@bp.route("/degree-records/<did>/revoke", methods=["POST"])
def revoke_degree(did):
    caller = authenticate()
    require_role(caller, ROLE_CERTIFIER)
    degree = db.store.degrees.get(did)
    if degree is None:
        raise_err(ERR_DEGREE_NOT_FOUND, "degree record not found")
    if caller.institution_id != degree["institution_id"]:
        raise_err(ERR_CROSS_INSTITUTION_ACCESS, "certifier's institution does not match the degree's")
    if degree["status"] != "SEALED":
        raise_err(ERR_INVALID_STATE, "only a SEALED degree can be revoked")
    degree["status"] = "REVOKED"
    db.touch(degree)
    return ok_object(db.serialize(degree))
