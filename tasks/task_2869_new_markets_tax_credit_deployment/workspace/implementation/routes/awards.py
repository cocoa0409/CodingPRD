"""Allocation awards (PRD 3.1)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import (ALL_ROLES, by_created_desc, endpoint, filter_int,
                        filter_str, force_bump)
from services import calc, derive

bp = Blueprint("awards", __name__)

SUBSTANTIALLY_ALL_METHODS = ["DIRECT_TRACING", "AGGREGATE_BALANCE"]


def load_award(award_id):
    award = db.awards.get(award_id)
    if award is None:
        fail("ERR_ALLOCATION_AWARD_NOT_FOUND")
    return award


def require_award_owner(award):
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")


@bp.route("/nmtc/allocation-awards", methods=["POST"])
@endpoint(["CertifyingAgency"], mutating=True, status=201)
def create_award():
    data = v.body()
    cde_id = v.req_str(data, "cde_id")
    award_year = v.req_int(data, "award_year", 2020, 2035)
    allocation_amount_cents = v.req_int(data, "allocation_amount_cents", 100000000)
    state_codes = v.req_state_codes(data, "service_area_state_codes")
    min_severe = v.req_pct(data, "min_severe_distress_share_pct")
    method = v.req_enum(data, "substantially_all_method", SUBSTANTIALLY_ALL_METHODS)

    cde = db.cdes.get(cde_id)
    if cde is None:
        fail("ERR_CDE_NOT_FOUND")
    if cde["certification_status"] != "CERTIFIED":
        fail("ERR_CDE_NOT_CERTIFIED")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "cde_id": cde_id,
        "award_year": award_year,
        "allocation_amount_cents": allocation_amount_cents,
        "remaining_authority_cents": allocation_amount_cents,
        "service_area_state_codes": state_codes,
        "min_severe_distress_share_pct": min_severe,
        "substantially_all_method": method,
        "lifecycle_status": "ANNOUNCED",
        "compliance_posture": "UNRESTRICTED",
        "allocation_agreement_signed_at": None,
        "signatory_name": None,
        "issued_qei_count": 0,
        "at_risk_qei_count": 0,
        "recaptured_qei_count": 0,
        "severe_distress_share_pct": calc.ZERO,
        "cba_breach_count": 0,
        "last_agency_report_year": None,
        "_seq": db.next_seq(),
    }
    db.awards[row["id"]] = row
    cde["award_count"] = cde["award_count"] + 1
    return row, 201


@bp.route("/nmtc/allocation-awards", methods=["GET"])
@endpoint(ALL_ROLES)
def list_awards():
    rows = list(db.awards.values())
    rows = filter_str(rows, "cde_id")
    rows = filter_str(rows, "lifecycle_status")
    rows = filter_str(rows, "compliance_posture")
    rows = filter_int(rows, "award_year")
    return by_created_desc(rows)


@bp.route("/nmtc/allocation-awards/<award_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_award(award_id):
    return load_award(award_id)


@bp.route("/nmtc/allocation-awards/<award_id>/allocation-agreement", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def sign_agreement(award_id):
    data = v.body()
    signatory_name = v.req_str(data, "signatory_name", 1, 120)
    award = load_award(award_id)
    require_award_owner(award)
    cde = derive.cde_of_award(award)
    if cde["certification_status"] != "CERTIFIED":
        fail("ERR_CDE_NOT_CERTIFIED")
    if award["lifecycle_status"] != "ANNOUNCED":
        fail("ERR_INVALID_STATE_TRANSITION")
    award["lifecycle_status"] = "ACTIVE"
    award["allocation_agreement_signed_at"] = clock.now()
    award["signatory_name"] = signatory_name
    return award


@bp.route("/nmtc/allocation-awards/<award_id>/agency-reports", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True, status=201)
def file_agency_report(award_id):
    data = v.body()
    report_year = v.req_int(data, "report_year")
    award = load_award(award_id)
    require_award_owner(award)
    if award["lifecycle_status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE")

    derive.recompute_award(award)

    deployed_principal = 0
    qualifying_ids = []
    for qei in derive.qeis_of_award(award["id"]):
        if qei["deployment_status"] == "VOIDED":
            continue
        for qlici in derive.qlicis_of_qei(qei["id"]):
            if qlici["status"] not in derive.QUALIFYING_QLICI_STATUSES:
                continue
            deployed_principal += qlici["outstanding_principal_cents"]
            if qlici["qalicb_id"] not in qualifying_ids:
                qualifying_ids.append(qlici["qalicb_id"])

    share = award["severe_distress_share_pct"]
    award["last_agency_report_year"] = report_year
    force_bump(award)

    return {
        "allocation_award_id": award["id"],
        "report_year": report_year,
        "issued_qei_count": award["issued_qei_count"],
        "deployed_principal_cents": deployed_principal,
        "qualifying_qalicb_count": len(qualifying_ids),
        "severe_distress_share_pct": share,
        "severe_distress_shortfall": bool(share < award["min_severe_distress_share_pct"]),
        "at_risk_qei_count": award["at_risk_qei_count"],
        "recaptured_qei_count": award["recaptured_qei_count"],
        "cba_breach_count": award["cba_breach_count"],
    }, 201
