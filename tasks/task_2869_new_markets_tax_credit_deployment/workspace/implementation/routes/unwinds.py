"""Unwind transactions: exercise and settlement (PRD 3.9)."""
from flask import Blueprint, g

import clock
import validators as v
from db import db
from errors import fail
from middleware import ALL_ROLES, endpoint, force_bump
from services import derive

bp = Blueprint("unwinds", __name__)

OPTION_TYPES = ["PUT", "CALL"]


def load_unwind(unwind_id):
    row = db.unwinds.get(unwind_id)
    if row is None:
        fail("ERR_UNWIND_NOT_FOUND")
    return row


@bp.route("/nmtc/unwind-transactions/<unwind_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_unwind(unwind_id):
    return load_unwind(unwind_id)


@bp.route("/nmtc/unwind-transactions/<unwind_id>/exercise", methods=["POST"])
@endpoint(["TaxCreditInvestor", "QALICBSponsor"], mutating=True)
def exercise_option(unwind_id):
    data = v.body()
    option_type = v.req_enum(data, "option_type", OPTION_TYPES)
    unwind = load_unwind(unwind_id)
    qei = db.qeis[unwind["qei_id"]]

    if option_type == "PUT":
        if g.role != "TaxCreditInvestor" or g.user_id != unwind["put_holder_user_id"]:
            fail("ERR_NOT_RESOURCE_OWNER")
    else:
        if g.role != "QALICBSponsor" or g.user_id != unwind["call_holder_user_id"]:
            fail("ERR_NOT_RESOURCE_OWNER")

    if unwind["status"] != "OPTION_WINDOW_OPEN":
        fail("ERR_INVALID_STATE_TRANSITION")
    if qei["compliance_status"] != "COMPLIANT":
        fail("ERR_INVALID_STATE_TRANSITION")
    now = clock.now()
    if not (unwind["option_window_open_at"] <= now < unwind["option_window_close_at"]):
        fail("ERR_OPTION_WINDOW_CLOSED")

    unwind["exercised_option_type"] = option_type
    unwind["exercised_at"] = now
    if option_type == "PUT":
        unwind["status"] = "PUT_EXERCISED"
        unwind["settlement_amount_cents"] = unwind["put_price_cents"]
    else:
        unwind["status"] = "CALL_EXERCISED"
        unwind["settlement_amount_cents"] = unwind["call_price_cents"]
        qei["accrued_unpaid_fee_cents"] = 0
        force_bump(qei)
    force_bump(unwind)
    return unwind


@bp.route("/nmtc/unwind-transactions/<unwind_id>/settlement", methods=["POST"])
@endpoint(["CDESponsor"], mutating=True)
def settle_unwind(unwind_id):
    data = v.body()
    settlement_reference = v.req_str(data, "settlement_reference", 1, 128)
    unwind = load_unwind(unwind_id)
    qei = db.qeis[unwind["qei_id"]]
    award = derive.award_of_qei(qei)
    if g.user_id != award["cde_id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    if unwind["status"] not in ("PUT_EXERCISED", "CALL_EXERCISED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    now = clock.now()
    unwind["status"] = "SETTLED"
    unwind["settlement_reference"] = settlement_reference
    unwind["settled_at"] = now
    force_bump(unwind)

    qei["deployment_status"] = "UNWOUND"
    qei["compliance_status"] = "RELEASED"
    force_bump(qei)

    for qlici in derive.qlicis_of_qei(qei["id"]):
        if qlici["status"] == "REPAID":
            continue
        qlici["status"] = "REPAID"
        qlici["outstanding_principal_cents"] = 0
        qlici["total_repaid_cents"] = qlici["principal_cents"]
        force_bump(qlici)

    fund = db.funds[qei["investment_fund_id"]]
    fund_qeis = [q for q in derive.qeis_of_fund(fund["id"])
                 if q["deployment_status"] != "VOIDED"]
    if fund["status"] == "QEI_MADE" and all(
            q["deployment_status"] == "UNWOUND" for q in fund_qeis):
        fund["status"] = "WOUND_UP"
        fund["leverage_loan_outstanding_cents"] = 0
        fund["capital_available_cents"] = 0
        force_bump(fund)

    award_qeis = [q for q in derive.qeis_of_award(award["id"])
                  if q["deployment_status"] != "VOIDED"]
    if award["lifecycle_status"] == "ACTIVE" and all(
            q["deployment_status"] == "UNWOUND" for q in award_qeis):
        award["lifecycle_status"] = "COMPLIANCE_PERIOD_CLOSED"
        force_bump(award)
        for cba in derive.cbas_of_award(award["id"]):
            if cba["status"] in ("ACTIVE", "CURE_REQUIRED"):
                cba["status"] = "CLOSED"
                force_bump(cba)
    return unwind
