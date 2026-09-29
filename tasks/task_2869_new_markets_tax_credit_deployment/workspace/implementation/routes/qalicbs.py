"""Project companies and the six-prong eligibility test (PRD 3.3)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import (ALL_ROLES, by_created_desc, by_field_asc, endpoint,
                        filter_str, force_bump)
from services import calc, derive

bp = Blueprint("qalicbs", __name__)

TESTABLE_STATUSES = ("PENDING", "CERTIFIED", "RECERTIFICATION_DUE", "FAILED")


def load_qalicb(qalicb_id):
    qalicb = db.qalicbs.get(qalicb_id)
    if qalicb is None:
        fail("ERR_QALICB_NOT_FOUND")
    return qalicb


@bp.route("/nmtc/qalicbs", methods=["POST"])
@endpoint(["QALICBSponsor"], mutating=True, status=201)
def create_qalicb():
    data = v.body()
    census_tract_id = v.req_str(data, "census_tract_id")
    legal_name = v.req_str(data, "legal_name", 1, 120)
    state_code = v.req_str(data, "state_code", 2, 2, v.TWO_UPPER)
    naics_code = v.req_str(data, "naics_code", 6, 6, v.SIX_DIGITS)

    tract = db.tracts.get(census_tract_id)
    if tract is None:
        fail("ERR_CENSUS_TRACT_NOT_FOUND")
    if not tract["eligible_for_qlici"]:
        fail("ERR_TRACT_NOT_LIC_ELIGIBLE")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "census_tract_id": census_tract_id,
        "legal_name": legal_name,
        "state_code": state_code,
        "naics_code": naics_code,
        "sponsor_user_id": g.user_id,
        "eligibility_status": "PENDING",
        "last_certified_at": None,
        "latest_test_result": None,
        "consecutive_failed_test_count": 0,
        "funding_qlici_count": 0,
        "_seq": db.next_seq(),
    }
    db.qalicbs[row["id"]] = row
    return row, 201


@bp.route("/nmtc/qalicbs", methods=["GET"])
@endpoint(ALL_ROLES)
def list_qalicbs():
    rows = list(db.qalicbs.values())
    rows = filter_str(rows, "census_tract_id")
    rows = filter_str(rows, "eligibility_status")
    rows = filter_str(rows, "state_code")
    return by_created_desc(rows)


@bp.route("/nmtc/qalicbs/<qalicb_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_qalicb(qalicb_id):
    return load_qalicb(qalicb_id)


@bp.route("/nmtc/qalicbs/<qalicb_id>/eligibility-tests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_eligibility_tests(qalicb_id):
    load_qalicb(qalicb_id)
    rows = [t for t in db.eligibility_tests.values() if t["qalicb_id"] == qalicb_id]
    rows = filter_str(rows, "result")
    return by_field_asc(rows, "performed_at")


@bp.route("/nmtc/qalicbs/<qalicb_id>/eligibility-tests", methods=["POST"])
@endpoint(["ComplianceReviewer"], mutating=True, status=201)
def run_eligibility_test(qalicb_id):
    data = v.body()
    gross_income = v.req_pct(data, "gross_income_lic_pct")
    services = v.req_pct(data, "services_lic_pct")
    tangible = v.req_pct(data, "tangible_property_lic_pct")
    collectibles = v.req_pct(data, "collectibles_pct")
    nqfp = v.req_pct(data, "nonqualified_financial_property_pct")
    location_passed = v.req_bool(data, "location_prong_passed")

    qalicb = load_qalicb(qalicb_id)
    if qalicb["eligibility_status"] not in TESTABLE_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")

    result, failed_prongs = calc.eligibility_result(
        location_passed, gross_income, services, tangible, collectibles, nqfp)

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "qalicb_id": qalicb["id"],
        "performed_by_user_id": g.user_id,
        "performed_at": now,
        "gross_income_lic_pct": gross_income,
        "services_lic_pct": services,
        "tangible_property_lic_pct": tangible,
        "collectibles_pct": collectibles,
        "nonqualified_financial_property_pct": nqfp,
        "location_prong_passed": location_passed,
        "result": result,
        "failed_prongs": failed_prongs,
        "_seq": db.next_seq(),
    }
    db.eligibility_tests[row["id"]] = row

    previous_status = qalicb["eligibility_status"]
    force_bump(qalicb)
    if result == "PASS":
        qalicb["eligibility_status"] = "CERTIFIED"
        qalicb["last_certified_at"] = now
        qalicb["latest_test_result"] = "PASS"
        qalicb["consecutive_failed_test_count"] = 0
        if previous_status == "FAILED":
            requalification_cascade(qalicb)
    else:
        qalicb["latest_test_result"] = "FAIL"
        raised = qalicb["consecutive_failed_test_count"] + 1
        qalicb["consecutive_failed_test_count"] = raised
        qalicb["eligibility_status"] = "DISQUALIFIED" if raised >= 2 else "FAILED"
        disqualification_cascade(qalicb, breach_agreements=(raised >= 2))
    return row, 201


def disqualification_cascade(qalicb, breach_agreements):
    """PRD 3.3: three hops, plus agreement breaches on permanent disqualification."""
    now = clock.now()
    touched_qeis = []
    for qlici in db.qlicis.values():
        if qlici["qalicb_id"] != qalicb["id"]:
            continue
        if qlici["status"] not in derive.QUALIFYING_QLICI_STATUSES:
            continue
        qlici["status"] = "NON_QUALIFYING"
        qlici["non_qualifying_since_at"] = now
        if qlici["qei_id"] not in touched_qeis:
            touched_qeis.append(qlici["qei_id"])

    for qei_id in touched_qeis:
        qei = db.qeis.get(qei_id)
        if qei is None:
            continue
        qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
        derive.mark_at_risk_if_short(qei)

    if breach_agreements:
        for cba in derive.cbas_of_qalicb(qalicb["id"]):
            if cba["status"] in ("ACTIVE", "CURE_REQUIRED"):
                cba["status"] = "BREACHED"
                cba["breached_at"] = now


def requalification_cascade(qalicb):
    """PRD 3.3: NON_QUALIFYING rows return to the state their repayment history implies."""
    touched_qeis = []
    for qlici in db.qlicis.values():
        if qlici["qalicb_id"] != qalicb["id"]:
            continue
        if qlici["status"] != "NON_QUALIFYING":
            continue
        if qlici["outstanding_principal_cents"] == 0:
            qlici["status"] = "REPAID"
        elif qlici["total_repaid_cents"] > 0:
            qlici["status"] = "PARTIALLY_REPAID"
        else:
            qlici["status"] = "DEPLOYED"
        qlici["non_qualifying_since_at"] = None
        if qlici["qei_id"] not in touched_qeis:
            touched_qeis.append(qlici["qei_id"])

    for qei_id in touched_qeis:
        qei = db.qeis.get(qei_id)
        if qei is None:
            continue
        qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
        derive.return_to_compliant_if_cured(qei)
