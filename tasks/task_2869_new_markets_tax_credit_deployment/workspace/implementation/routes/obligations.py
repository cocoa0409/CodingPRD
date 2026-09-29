"""Reinvestment obligations: reading and redeployment (PRD 3.6)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db
from errors import fail
from middleware import ALL_ROLES, by_field_asc, endpoint, filter_str, force_bump
from services import derive

bp = Blueprint("obligations", __name__)


def load_obligation(obligation_id):
    row = db.obligations.get(obligation_id)
    if row is None:
        fail("ERR_REINVESTMENT_OBLIGATION_NOT_FOUND")
    return row


@bp.route("/nmtc/reinvestment-obligations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_obligations():
    rows = list(db.obligations.values())
    rows = filter_str(rows, "qei_id")
    rows = filter_str(rows, "source_qlici_id")
    rows = filter_str(rows, "status")
    return by_field_asc(rows, "arose_at")


@bp.route("/nmtc/reinvestment-obligations/<obligation_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_obligation(obligation_id):
    return load_obligation(obligation_id)


@bp.route("/nmtc/reinvestment-obligations/<obligation_id>/reinvestments",
          methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def reinvest(obligation_id):
    data = v.body()
    target_qlici_id = v.req_str(data, "target_qlici_id")
    amount_cents = v.req_int(data, "amount_cents", 1)

    obligation = load_obligation(obligation_id)
    target = db.qlicis.get(target_qlici_id)
    if target is None:
        fail("ERR_QLICI_NOT_FOUND")

    qei = db.qeis[obligation["qei_id"]]
    award = derive.award_of_qei(qei)
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if obligation["status"] != "OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if target["qei_id"] != obligation["qei_id"]:
        fail("ERR_INVALID_STATE_TRANSITION")
    if target["status"] not in derive.QUALIFYING_QLICI_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")
    if qei["compliance_status"] == "RECAPTURED":
        fail("ERR_QEI_RECAPTURED")
    if clock.now() > obligation["reinvest_by_at"]:
        fail("ERR_REINVESTMENT_DEADLINE_PASSED")
    if amount_cents > qei["uninvested_cash_cents"]:
        fail("ERR_INSUFFICIENT_UNINVESTED_CASH")
    if obligation["reinvested_cents"] + amount_cents > obligation["amount_cents"]:
        fail("ERR_REINVESTMENT_EXCEEDS_OBLIGATION")

    now = clock.now()
    obligation["reinvested_cents"] = obligation["reinvested_cents"] + amount_cents
    if obligation["reinvested_cents"] == obligation["amount_cents"]:
        obligation["status"] = "SATISFIED"
        obligation["satisfied_at"] = now

    target["principal_cents"] = target["principal_cents"] + amount_cents
    target["outstanding_principal_cents"] = (
        target["outstanding_principal_cents"] + amount_cents)
    remaining = qei["uninvested_cash_cents"] - amount_cents
    qei["uninvested_cash_cents"] = remaining

    still_open = any(o["qei_id"] == qei["id"] and o["status"] == "OPEN"
                     for o in db.obligations.values())
    if not still_open and qei["deployment_status"] == "REINVESTMENT_PENDING":
        qei["deployment_status"] = "DEPLOYING" if remaining > 0 else "FULLY_DEPLOYED"

    qei["substantially_all_pct_direct"] = derive.pct_direct(qei)
    derive.return_to_compliant_if_cured(qei)
    force_bump(obligation)
    force_bump(target)
    force_bump(qei)
    force_bump(award)
    return obligation
