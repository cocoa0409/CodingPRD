"""Sub-allocations: deployment and principal repayment (PRD 3.5, 3.6)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db, new_id
from errors import fail
from middleware import (ALL_ROLES, by_created_desc, endpoint, filter_str,
                        force_bump)
from services import calc, derive

bp = Blueprint("qlicis", __name__)

LOAN_CLASSES = ["A", "B"]


def load_qlici(qlici_id):
    qlici = db.qlicis.get(qlici_id)
    if qlici is None:
        fail("ERR_QLICI_NOT_FOUND")
    return qlici


def _compliance_period_conflict(qei, qalicb):
    for other in db.qeis.values():
        if other["id"] == qei["id"]:
            continue
        if other["deployment_status"] == "VOIDED":
            continue
        if other["allocation_award_id"] == qei["allocation_award_id"]:
            continue
        funds_business = any(
            q["qei_id"] == other["id"] and q["qalicb_id"] == qalicb["id"]
            for q in db.qlicis.values())
        if not funds_business:
            continue
        lower = clock.plus_days(other["issued_at"], -calc.QALICB_BUFFER_DAYS)
        upper = clock.plus_days(
            other["issued_at"], calc.COMPLIANCE_PERIOD_DAYS + calc.QALICB_BUFFER_DAYS)
        if lower <= qei["issued_at"] < upper:
            return True
    return False


@bp.route("/nmtc/qlicis", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True, status=201)
def deploy_qlici():
    data = v.body()
    qei_id = v.req_str(data, "qei_id")
    qalicb_id = v.req_str(data, "qalicb_id")
    loan_class = v.req_enum(data, "loan_class", LOAN_CLASSES)
    principal_cents = v.req_int(data, "principal_cents", 100000)

    qei = db.qeis.get(qei_id)
    if qei is None:
        fail("ERR_QEI_NOT_FOUND")
    qalicb = db.qalicbs.get(qalicb_id)
    if qalicb is None:
        fail("ERR_QALICB_NOT_FOUND")

    award = derive.award_of_qei(qei)
    cde = derive.cde_of_award(award)
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if cde["certification_status"] != "CERTIFIED":
        fail("ERR_CDE_NOT_CERTIFIED")
    if award["lifecycle_status"] != "ACTIVE":
        fail("ERR_AWARD_NOT_ACTIVE")
    if award["compliance_posture"] == "FROZEN":
        fail("ERR_AWARD_POSTURE_RESTRICTED")
    if qei["deployment_status"] in ("VOIDED", "UNWOUND"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if qei["compliance_status"] == "RECAPTURED":
        fail("ERR_QEI_RECAPTURED")
    if _compliance_period_conflict(qei, qalicb):
        fail("ERR_QALICB_COMPLIANCE_PERIOD_CONFLICT")
    if qalicb["eligibility_status"] in ("PENDING", "RECERTIFICATION_DUE", "FAILED"):
        fail("ERR_QALICB_NOT_CERTIFIED")
    if qalicb["eligibility_status"] == "DISQUALIFIED":
        fail("ERR_QALICB_DISQUALIFIED")
    if any(c["status"] == "BREACHED" for c in derive.cbas_of_qalicb(qalicb["id"])):
        fail("ERR_CBA_BREACHED")
    if not any(c["allocation_award_id"] == award["id"]
               for c in derive.cbas_of_qalicb(qalicb["id"])):
        fail("ERR_CBA_MISSING")
    if clock.now() > qei["deployment_deadline_at"]:
        fail("ERR_DEPLOYMENT_WINDOW_CLOSED")
    if (cde["service_area_scope"] != "NATIONAL"
            and qalicb["state_code"] not in award["service_area_state_codes"]):
        fail("ERR_OUTSIDE_SERVICE_AREA")
    if principal_cents > qei["uninvested_cash_cents"]:
        fail("ERR_INSUFFICIENT_UNINVESTED_CASH")

    now = clock.now()
    row = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "qei_id": qei["id"],
        "qalicb_id": qalicb["id"],
        "loan_class": loan_class,
        "principal_cents": principal_cents,
        "outstanding_principal_cents": principal_cents,
        "total_repaid_cents": 0,
        "deployed_at": now,
        "status": "DEPLOYED",
        "non_qualifying_since_at": None,
        "allocated_fee_cents": 0,
        "created_by_cure": False,
        "_seq": db.next_seq(),
    }
    db.qlicis[row["id"]] = row

    remaining = qei["uninvested_cash_cents"] - principal_cents
    qei["uninvested_cash_cents"] = remaining
    if qei["deployment_status"] in ("ISSUED", "DEPLOYING"):
        qei["deployment_status"] = "DEPLOYING" if remaining > 0 else "FULLY_DEPLOYED"
    qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
    derive.return_to_compliant_if_cured(qei)
    force_bump(qei)
    force_bump(qalicb)
    force_bump(award)
    return row, 201


@bp.route("/nmtc/qlicis", methods=["GET"])
@endpoint(ALL_ROLES)
def list_qlicis():
    rows = list(db.qlicis.values())
    rows = filter_str(rows, "qei_id")
    rows = filter_str(rows, "qalicb_id")
    rows = filter_str(rows, "status")
    rows = filter_str(rows, "loan_class")
    return by_created_desc(rows)


@bp.route("/nmtc/qlicis/<qlici_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_qlici(qlici_id):
    return load_qlici(qlici_id)


@bp.route("/nmtc/qlicis/<qlici_id>/principal-repayments", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def repay_principal(qlici_id):
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents", 1)
    qlici = load_qlici(qlici_id)
    qei = db.qeis[qlici["qei_id"]]
    award = derive.award_of_qei(qei)
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if qlici["status"] not in derive.QUALIFYING_QLICI_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")
    if amount_cents > qlici["outstanding_principal_cents"]:
        fail("ERR_REPAYMENT_EXCEEDS_PRINCIPAL")

    now = clock.now()
    # Hop one: the sub-allocation.
    fully = amount_cents == qlici["outstanding_principal_cents"]
    qlici["total_repaid_cents"] = qlici["total_repaid_cents"] + amount_cents
    qlici["outstanding_principal_cents"] = (
        qlici["outstanding_principal_cents"] - amount_cents)
    if fully:
        qlici["status"] = "REPAID"
        qlici["outstanding_principal_cents"] = 0
        qlici["total_repaid_cents"] = qlici["principal_cents"]
    else:
        qlici["status"] = "PARTIALLY_REPAID"

    # Hop two: returned cash and the redeployment duty.
    qei["uninvested_cash_cents"] = qei["uninvested_cash_cents"] + amount_cents
    obligation = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "qei_id": qei["id"],
        "source_qlici_id": qlici["id"],
        "amount_cents": amount_cents,
        "reinvested_cents": 0,
        "arose_at": now,
        "reinvest_by_at": clock.plus_days(now, calc.YEAR_DAYS),
        "status": "OPEN",
        "satisfied_at": None,
        "breached_at": None,
        "_seq": db.next_seq(),
    }
    db.obligations[obligation["id"]] = obligation
    qei["deployment_status"] = "REINVESTMENT_PENDING"

    # Hop three: re-measure compliance.
    qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
    derive.mark_at_risk_if_short(qei)
    force_bump(qlici)
    force_bump(qei)
    return qlici
