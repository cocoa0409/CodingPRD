"""Family cost participation: the sliding scale and the family ledger."""
from flask import Blueprint, g, request

import domain as D
from auth import STAFF_READ, endpoint
from envelope import paginate, single
from errors import fail
from helpers import get_cost_share, get_referral, not_future, ser_cost_share
from services import compute, money
from store import db, flush, new_row, ordered, set_field, set_fields
from validate import (Field, parse_body, v_bool, v_date, v_enum, v_id, v_int,
                      v_month, v_str)

bp = Blueprint("cost_shares", __name__)


@bp.route("/ei/cost-shares", methods=["POST"])
@endpoint(["FiscalOfficer"])
def create_cost_share():
    payload = parse_body([
        Field("referral_id", v_id()),
        Field("effective_month", v_month()),
        Field("household_size", v_int(1, 12)),
        Field("declared_annual_gross_income_cents", v_int(0)),
        Field("insurance_use_consent", v_bool()),
        Field("insurance_policy_id", v_str(), required=False),
    ])
    referral = get_referral(payload["referral_id"])
    if referral["status"] in D.REFERRAL_TERMINAL:
        fail("ERR_REFERRAL_STATE_INVALID",
             "A terminal case accepts no cost-share determination.")
    for existing in compute.referral_cost_shares(referral["id"]):
        if (existing["status"] in D.COST_SHARE_LIVE
                and existing["effective_month"] == payload["effective_month"]):
            fail("ERR_COST_SHARE_DUPLICATE",
                 "The case already holds a live determination for %s."
                 % payload["effective_month"])
    cost_share = new_row({
        "referral_id": referral["id"],
        "effective_month": payload["effective_month"],
        "household_size": payload["household_size"],
        "declared_annual_gross_income_cents":
            payload["declared_annual_gross_income_cents"],
        "verified_annual_gross_income_cents": None,
        "insurance_use_consent": payload["insurance_use_consent"],
        "insurance_policy_id": payload["insurance_policy_id"],
        "determined_by_user_id": g.user_id,
        "verification_date": None,
        "status": "PROVISIONAL",
        "waiver_reason_code": None,
        "fpl_threshold_cents": 0,
        "fpl_percent": 0.0,
        "tier_code": "TIER_0",
        "coinsurance_rate": 0.0,
        "monthly_cap_cents": 0,
        "assessed_monthly_fee_cents": 0,
        "insurance_offset_cents": 0,
        "final_monthly_fee_cents": None,
        "effective_coinsurance_rate": 0.0,
        "total_assessed_cents": 0,
        "family_balance_cents": 0,
        "family_waived_cents": 0,
        "month_accrued_cents": 0,
    })
    db.cost_shares[cost_share["id"]] = cost_share
    for existing in compute.referral_cost_shares(referral["id"]):
        if existing["id"] == cost_share["id"]:
            continue
        if (existing["status"] in D.COST_SHARE_LIVE
                and existing["effective_month"] < cost_share["effective_month"]):
            set_field(existing, "status", "SUPERSEDED")
    money.recompute_cost_share(cost_share, final=False)
    flush()
    return single(ser_cost_share(cost_share), 201)


@bp.route("/ei/cost-shares/<cost_share_id>", methods=["GET"])
@endpoint(STAFF_READ)
def read_cost_share(cost_share_id):
    return single(ser_cost_share(get_cost_share(cost_share_id)))


@bp.route("/ei/cost-shares", methods=["GET"])
@endpoint(STAFF_READ)
def list_cost_shares():
    rows = ordered(db.cost_shares)
    referral_id = request.args.get("referral_id")
    status = request.args.get("status")
    if referral_id is not None:
        rows = [r for r in rows if r["referral_id"] == referral_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser_cost_share)


@bp.route("/ei/cost-shares/<cost_share_id>/finalize", methods=["POST"])
@endpoint(["FiscalOfficer"])
def finalize_cost_share(cost_share_id):
    payload = parse_body([
        Field("verified_annual_gross_income_cents", v_int(0)),
        Field("verification_date", v_date()),
    ])
    cost_share = get_cost_share(cost_share_id)
    if cost_share["status"] != "PROVISIONAL":
        fail("ERR_COST_SHARE_NOT_PROVISIONAL",
             "Only a PROVISIONAL determination may be finalized.")
    if cost_share["insurance_use_consent"] and not cost_share["insurance_policy_id"]:
        fail("ERR_INSURANCE_POLICY_REQUIRED",
             "A determination consenting to insurance billing needs a policy "
             "identifier.")
    not_future(payload["verification_date"], "verification_date")
    set_fields(cost_share, {
        "status": "VERIFIED",
        "verified_annual_gross_income_cents":
            payload["verified_annual_gross_income_cents"],
        "verification_date": payload["verification_date"],
    })
    money.recompute_cost_share(cost_share, final=True)
    money.assert_ledger(cost_share)
    flush()
    return single(ser_cost_share(cost_share))


@bp.route("/ei/cost-shares/<cost_share_id>/waive", methods=["POST"])
@endpoint(["FiscalOfficer"])
def waive_cost_share(cost_share_id):
    payload = parse_body([
        Field("waive_amount_cents", v_int()),
        Field("waiver_reason_code", v_enum(D.WAIVER_REASONS)),
    ])
    cost_share = get_cost_share(cost_share_id)
    if cost_share["determined_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The officer who determined this cost share may not waive it.")
    if cost_share["status"] not in D.COST_SHARE_LIVE:
        fail("ERR_COST_SHARE_NOT_PROVISIONAL",
             "A determination in status '%s' may not be "
             "waived." % cost_share["status"])
    amount = payload["waive_amount_cents"]
    if amount < 1 or amount > (cost_share["family_balance_cents"] or 0):
        fail("ERR_WAIVE_EXCEEDS_BALANCE",
             "The waived amount must be between 1 cent and the outstanding "
             "family balance.")
    set_fields(cost_share, {
        "family_waived_cents": (cost_share["family_waived_cents"] or 0) + amount,
        "family_balance_cents": (cost_share["family_balance_cents"] or 0) - amount,
        "waiver_reason_code": payload["waiver_reason_code"],
    })
    money.assert_ledger(cost_share)
    flush()
    return single(ser_cost_share(cost_share))


@bp.route("/ei/cost-shares/<cost_share_id>/insurance-consent", methods=["POST"])
@endpoint(["FiscalOfficer"])
def insurance_consent(cost_share_id):
    payload = parse_body([
        Field("insurance_use_consent", v_bool()),
        Field("insurance_policy_id", v_str(), required=False),
    ])
    cost_share = get_cost_share(cost_share_id)
    if cost_share["status"] != "PROVISIONAL":
        fail("ERR_COST_SHARE_NOT_PROVISIONAL",
             "Consent may only be recorded on a PROVISIONAL determination.")
    if payload["insurance_use_consent"] and not payload["insurance_policy_id"]:
        fail("ERR_INSURANCE_POLICY_REQUIRED",
             "Consenting to insurance billing requires a policy identifier.")
    set_fields(cost_share, {
        "insurance_use_consent": payload["insurance_use_consent"],
        "insurance_policy_id": payload["insurance_policy_id"],
    })
    flush()
    return single(ser_cost_share(cost_share))
