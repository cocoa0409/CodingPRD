"""Merchant boarding, attrition, reactivation, reassignment, chargebacks (PRD 3.3)."""
from flask import Blueprint

from apierrors import fail
from auth import authorize, scope_list_filter, scope_owned
from calc import (
    apply_hold_cascade,
    bonus_clawback_cents,
    clawed_back_bonus_cents,
    recompute_statement,
    residual_hold,
    system_adjustment,
    upsert_statement,
)
from envelope import apply_filters, list_response, object_response
from serial import chargeback as ser_chargeback
from serial import merchant as ser_merchant
from shapes import (
    as_date,
    as_enum,
    as_id,
    as_int,
    as_month_string,
    as_str,
    body,
    check_month,
    present,
)
from store import db, month_of_date, new_id, ordered, parse_date, stamp_new, touch

bp = Blueprint("merchants", __name__)

LIABILITIES = ("ISO_ABSORBED", "AGENT_CHARGED")


def _lookup(merchant_id):
    row = db.merchants.get(merchant_id)
    if row is None:
        fail("ERR_MERCHANT_NOT_FOUND", "no merchant with id %s" % merchant_id)
    return row


@bp.route("/merchants", methods=["POST"])
def board_merchant():
    authorize("IsoAdmin")
    payload = body()
    # band 4
    owning_agent_id = as_id(payload, "owning_agent_id")
    processor_program_id = as_id(payload, "processor_program_id")
    mid = as_str(payload, "mid", min_len=4, max_len=32)
    monthly_minimum_cents = as_int(payload, "monthly_minimum_cents", minimum=0)
    per_transaction_fee_cents = as_int(payload, "per_transaction_fee_cents", minimum=0)
    equipment_lease_monthly_cents = as_int(
        payload, "equipment_lease_monthly_cents", minimum=0)
    boarded_on = as_date(payload, "boarded_on")
    upfront_bonus_cents = as_int(
        payload, "upfront_bonus_cents", required=False, minimum=0, default=0)
    # band 7 -- in the order the fields are declared for the endpoint
    agent = db.agents.get(owning_agent_id)
    if agent is None:
        fail("ERR_REFERENCED_AGENT_NOT_FOUND", "no agent with id %s" % owning_agent_id)
    if processor_program_id not in db.programs:
        fail("ERR_REFERENCED_PROGRAM_NOT_FOUND",
             "no processor program with id %s" % processor_program_id)
    # band 9
    if agent["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "a merchant may only be boarded under an ACTIVE agent")
    # band 12
    for row in db.merchants.values():
        if row["mid"] == mid:
            fail("ERR_DUPLICATE_MID", "mid %s is already in use" % mid)
    row = {
        "id": new_id(),
        "owning_agent_id": owning_agent_id,
        "processor_program_id": processor_program_id,
        "mid": mid,
        "monthly_minimum_cents": monthly_minimum_cents,
        "per_transaction_fee_cents": per_transaction_fee_cents,
        "equipment_lease_monthly_cents": equipment_lease_monthly_cents,
        "boarded_on": boarded_on,
        "upfront_bonus_cents": upfront_bonus_cents,
        "status": "PENDING",
        "attrition_date": None,
        "reactivation_date": None,
    }
    stamp_new(row)
    db.merchants[row["id"]] = row
    return object_response(ser_merchant(row), 201)


@bp.route("/merchants", methods=["GET"])
def list_merchants():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    scope_list_filter("owning_agent_id")
    rows = apply_filters(
        list(db.merchants.values()),
        [("owning_agent_id", "owning_agent_id"),
         ("processor_program_id", "processor_program_id"),
         ("status", "status")])
    return list_response(ordered(rows), ser_merchant)


@bp.route("/merchants/<merchant_id>", methods=["GET"])
def get_merchant(merchant_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController", "Agent")
    row = _lookup(merchant_id)
    scope_owned(row["owning_agent_id"])
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>", methods=["PATCH"])
def patch_merchant(merchant_id):
    authorize("IsoAdmin")
    payload = body()
    monthly_minimum_cents = as_int(
        payload, "monthly_minimum_cents", required=False, minimum=0)
    per_transaction_fee_cents = as_int(
        payload, "per_transaction_fee_cents", required=False, minimum=0)
    equipment_lease_monthly_cents = as_int(
        payload, "equipment_lease_monthly_cents", required=False, minimum=0)
    row = _lookup(merchant_id)
    if present(payload, "monthly_minimum_cents"):
        row["monthly_minimum_cents"] = monthly_minimum_cents
    if present(payload, "per_transaction_fee_cents"):
        row["per_transaction_fee_cents"] = per_transaction_fee_cents
    if present(payload, "equipment_lease_monthly_cents"):
        row["equipment_lease_monthly_cents"] = equipment_lease_monthly_cents
    touch(row)
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>/activate", methods=["POST"])
def activate_merchant(merchant_id):
    authorize("IsoAdmin")
    row = _lookup(merchant_id)
    # band 9 -- the addressed merchant first, then its owning agent
    if row["status"] != "PENDING":
        fail("ERR_MERCHANT_STATE_INVALID", "activation is only available from PENDING")
    agent = db.agents.get(row["owning_agent_id"])
    if agent is None or agent["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "the owning agent is no longer ACTIVE")
    row["status"] = "ACTIVE"
    touch(row)
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>/attrite", methods=["POST"])
def attrite_merchant(merchant_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    attrition_date = as_date(payload, "attrition_date")
    # band 6
    row = _lookup(merchant_id)
    # band 9
    if row["status"] != "ACTIVE":
        fail("ERR_MERCHANT_STATE_INVALID", "attrition is only available from ACTIVE")
    # band 11
    parsed = parse_date(attrition_date)
    if parsed < parse_date(row["boarded_on"]) or parsed > db.today():
        fail("ERR_MERCHANT_DATE_OUT_OF_RANGE",
             "attrition_date must fall between boarded_on and the current logical date")
    clawback = bonus_clawback_cents(row, parsed)
    row["status"] = "ATTRITED"
    row["attrition_date"] = attrition_date
    row["reactivation_date"] = None
    touched = set()
    if clawback > 0:
        statement, created = upsert_statement(
            row["owning_agent_id"], month_of_date(parsed))
        system_adjustment(statement, "BONUS_CLAWBACK", -clawback, row["id"])
        recompute_statement(statement)
        if not created:
            touch(statement)
        touched.add(statement["id"])
    if residual_hold(row["owning_agent_id"]):
        apply_hold_cascade(row["owning_agent_id"], touched)
    touch(row)
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>/reactivate", methods=["POST"])
def reactivate_merchant(merchant_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    reactivation_date = as_date(payload, "reactivation_date")
    # band 6
    row = _lookup(merchant_id)
    # band 9 -- the addressed merchant first, then its owning agent
    if row["status"] != "ATTRITED":
        fail("ERR_MERCHANT_STATE_INVALID", "reactivation is only available from ATTRITED")
    agent = db.agents.get(row["owning_agent_id"])
    if agent is None or agent["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "the owning agent is no longer ACTIVE")
    # band 11
    parsed = parse_date(reactivation_date)
    attrition = parse_date(row.get("attrition_date") or "")
    if (attrition is not None and parsed < attrition) or parsed > db.today():
        fail("ERR_MERCHANT_DATE_OUT_OF_RANGE",
             "reactivation_date must fall between attrition_date and the current logical date")
    clawed_back = clawed_back_bonus_cents(merchant_id)
    if clawed_back > 0:
        statement, created = upsert_statement(
            row["owning_agent_id"], month_of_date(parsed))
        system_adjustment(statement, "CLAWBACK_REVERSAL", clawed_back, row["id"])
        recompute_statement(statement)
        if not created:
            touch(statement)
    row["status"] = "ACTIVE"
    row["reactivation_date"] = reactivation_date
    row["attrition_date"] = None
    touch(row)
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>/reassign-agent", methods=["POST"])
def reassign_merchant(merchant_id):
    authorize("IsoAdmin")
    payload = body()
    # band 4
    new_agent_id = as_id(payload, "new_agent_id")
    expected_merchant_version = as_int(payload, "expected_merchant_version")
    # band 6
    row = _lookup(merchant_id)
    # band 7
    agent = db.agents.get(new_agent_id)
    if agent is None:
        fail("ERR_REFERENCED_AGENT_NOT_FOUND", "no agent with id %s" % new_agent_id)
    # band 8
    if expected_merchant_version != row["version"]:
        fail("ERR_STALE_MERCHANT_VERSION",
             "expected_merchant_version %d does not match the merchant's current version %d"
             % (expected_merchant_version, row["version"]))
    # band 9
    if agent["status"] != "ACTIVE":
        fail("ERR_AGENT_STATE_INVALID", "the destination agent must be ACTIVE")
    if row["status"] == "ATTRITED":
        fail("ERR_MERCHANT_STATE_INVALID", "an ATTRITED merchant may not be reassigned")
    row["owning_agent_id"] = new_agent_id
    touch(row)
    return object_response(ser_merchant(row))


@bp.route("/merchants/<merchant_id>/chargebacks", methods=["POST"])
def book_chargeback(merchant_id):
    authorize("IsoAdmin", "ResidualAnalyst")
    payload = body()
    # band 4
    amount_cents = as_int(payload, "amount_cents", minimum=0)
    occurred_on = as_date(payload, "occurred_on")
    period_month = as_month_string(payload, "period_month")
    liability = as_enum(payload, "liability", LIABILITIES)
    if amount_cents <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be strictly greater than zero")
    # band 5
    check_month(period_month, "period_month")
    # band 6
    _lookup(merchant_id)
    row = {
        "id": new_id(),
        "merchant_id": merchant_id,
        "amount_cents": amount_cents,
        "occurred_on": occurred_on,
        "period_month": period_month,
        "liability": liability,
        "created_at": db.now_iso(),
        "_seq": db.seq(),
    }
    db.chargebacks[row["id"]] = row
    return object_response(ser_chargeback(row), 201)


@bp.route("/chargeback-events", methods=["GET"])
def list_chargebacks():
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    rows = apply_filters(
        list(db.chargebacks.values()),
        [("merchant_id", "merchant_id"), ("period_month", "period_month"),
         ("liability", "liability")])
    return list_response(ordered(rows), ser_chargeback)


@bp.route("/chargeback-events/<chargeback_id>", methods=["GET"])
def get_chargeback(chargeback_id):
    authorize("IsoAdmin", "ResidualAnalyst", "ResidualController")
    row = db.chargebacks.get(chargeback_id)
    if row is None:
        fail("ERR_CHARGEBACK_NOT_FOUND", "no chargeback event with id %s" % chargeback_id)
    return object_response(ser_chargeback(row))
