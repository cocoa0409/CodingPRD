"""Community development entities (PRD 3.1)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import ALL_ROLES, by_created_desc, endpoint, filter_str, force_bump
from services import calc, derive

bp = Blueprint("cdes", __name__)

SERVICE_AREA_SCOPES = ["NATIONAL", "MULTI_STATE", "STATEWIDE", "LOCAL"]


def public_cde(row):
    return row


def load_cde(cde_id):
    cde = db.cdes.get(cde_id)
    if cde is None:
        fail("ERR_CDE_NOT_FOUND")
    return cde


@bp.route("/nmtc/cdes", methods=["POST"])
@endpoint(["CertifyingAgency"], mutating=True, status=201)
def create_cde():
    data = v.body()
    legal_name = v.req_str(data, "legal_name", 1, 120)
    certification_number = v.req_str(data, "certification_number", 1, 40)
    service_area_scope = v.req_enum(data, "service_area_scope", SERVICE_AREA_SCOPES)

    for existing in db.cdes.values():
        if existing["certification_number"] == certification_number:
            fail("ERR_DUPLICATE_CERTIFICATION_NUMBER")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "legal_name": legal_name,
        "certification_number": certification_number,
        "service_area_scope": service_area_scope,
        "certification_status": "CERTIFIED",
        "decertified_at": None,
        "decertification_reason": None,
        "award_count": 0,
        "_seq": db.next_seq(),
    }
    db.cdes[row["id"]] = row
    return row, 201


@bp.route("/nmtc/cdes", methods=["GET"])
@endpoint(ALL_ROLES)
def list_cdes():
    rows = list(db.cdes.values())
    rows = filter_str(rows, "certification_status")
    rows = filter_str(rows, "service_area_scope")
    return by_created_desc(rows)


@bp.route("/nmtc/cdes/<cde_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_cde(cde_id):
    return load_cde(cde_id)


@bp.route("/nmtc/cdes/<cde_id>/decertification", methods=["POST"])
@endpoint(["CertifyingAgency"], mutating=True)
def decertify_cde(cde_id):
    data = v.body()
    reason = v.req_str(data, "decertification_reason", 1)
    cde = load_cde(cde_id)
    if cde["certification_status"] != "CERTIFIED":
        fail("ERR_INVALID_STATE_TRANSITION")

    now = clock.now()
    cde["certification_status"] = "DECERTIFIED"
    cde["decertified_at"] = now
    cde["decertification_reason"] = reason

    for award in db.awards.values():
        if award["cde_id"] != cde["id"]:
            continue
        if award["lifecycle_status"] not in ("ANNOUNCED", "ACTIVE"):
            continue
        if award["lifecycle_status"] == "ACTIVE" and award["issued_qei_count"] == 0:
            award["lifecycle_status"] = "TERMINATED"
            award["remaining_authority_cents"] = 0
            continue
        for qei in derive.qeis_of_award(award["id"]):
            if qei["deployment_status"] in ("VOIDED", "UNWOUND"):
                continue
            if qei["compliance_status"] not in ("COMPLIANT", "AT_RISK"):
                continue
            derive.recapture(qei, "CDE_DECERTIFICATION")
    return cde
