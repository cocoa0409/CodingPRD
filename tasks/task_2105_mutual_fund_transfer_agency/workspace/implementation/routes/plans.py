"""Systematic plans (PRD 3.8)."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import dates
import db
import response
import serializers
import validation
from constants import (ACCOUNT_PARTICIPATING, PLAN_FREQUENCIES, PLAN_STATUSES, PLAN_TYPES,
                       PURCHASE_SIDE_PLAN_TYPES)
from errors import ApiError, invalid
from middleware import ALL_ROLES, ROLE_HOLDER, ROLE_TAO, authenticate
from money import q3
from routes import helpers
from services import capture as capture_service, positions as positions_service

bp = Blueprint("plans", __name__)

TRADE_TYPE_FOR_PLAN = {
    "SYSTEMATIC_INVESTMENT": "PURCHASE",
    "SYSTEMATIC_WITHDRAWAL": "REDEMPTION",
    "SYSTEMATIC_EXCHANGE": "EXCHANGE",
}


@bp.route("/systematic-plans", methods=["POST"])
def create_plan():
    caller = authenticate((ROLE_TAO, ROLE_HOLDER))
    body = validation.body()
    account_id = validation.get_id(body, "account_id", required=True)
    plan_type = validation.get_enum(body, "plan_type", PLAN_TYPES, required=True)
    source_class_id = validation.get_id(body, "source_share_class_id", required=True)
    amount = validation.get_decimal(body, "amount", 2, required=True, positive=True)
    frequency = validation.get_enum(body, "frequency", PLAN_FREQUENCIES, required=True)
    next_run_date = validation.get_date(body, "next_run_date", required=True)
    target_class_id = validation.get_id(body, "target_share_class_id")
    expected_version = validation.get_int(body, "expected_account_version", required=True)

    if plan_type == "SYSTEMATIC_EXCHANGE":
        if target_class_id is None:
            raise invalid("Field 'target_share_class_id' is required for a systematic exchange.")
    elif target_class_id is not None:
        raise invalid("Field 'target_share_class_id' is only valid for a systematic exchange.")

    account = helpers.get_account(account_id)
    source_class = helpers.get_share_class(source_class_id)
    target_class = helpers.get_share_class(target_class_id) if target_class_id else None

    helpers.require_ownership(caller, account["id"])

    if expected_version != account["version"]:
        raise ApiError("ERR_STALE_ACCOUNT_VERSION",
                       "The supplied expected_account_version is stale.")

    if account["status"] not in ACCOUNT_PARTICIPATING:
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "The account must be ACTIVE or RESTRICTED to carry a plan.")

    if target_class is not None and target_class["id"] == source_class["id"]:
        raise ApiError("ERR_EXCHANGE_TARGET_INVALID",
                       "A systematic exchange target must differ from the source class.")

    for existing in db.store.plans.values():
        if (existing["account_id"] == account["id"]
                and existing["plan_type"] == plan_type
                and existing["source_share_class_id"] == source_class["id"]
                and existing["status"] == "ACTIVE"):
            existing["status"] = "TERMINATED"
            db.touch(existing)

    plan = db.create(db.store.plans, {
        "account_id": account["id"],
        "source_share_class_id": source_class["id"],
        "target_share_class_id": target_class["id"] if target_class else None,
        "plan_type": plan_type,
        "amount": amount,
        "frequency": frequency,
        "next_run_date": dates.fmt_date(next_run_date),
        "status": "ACTIVE",
        "executed_count": 0,
        "last_run_date": None,
        "suspension_reason": None,
    })
    db.touch(account)
    return response.created(serializers.plan(plan))


@bp.route("/systematic-plans/<plan_id>", methods=["GET"])
def read_plan(plan_id):
    authenticate(ALL_ROLES)
    plan = helpers.get_plan(plan_id)
    return response.ok(serializers.plan(plan))


@bp.route("/systematic-plans", methods=["GET"])
def list_plans():
    authenticate(ALL_ROLES)
    limit, offset = validation.pagination()
    records = db.values(db.store.plans)
    records = helpers.filter_equals(records, "account_id", request.args.get("account_id"))
    records = helpers.filter_equals(records, "source_share_class_id",
                                    request.args.get("source_share_class_id"))
    records = helpers.filter_equals(records, "target_share_class_id",
                                    request.args.get("target_share_class_id"))
    records = helpers.filter_equals(records, "status",
                                    validation.query_enum("status", PLAN_STATUSES))
    records = helpers.filter_equals(records, "plan_type",
                                    validation.query_enum("plan_type", PLAN_TYPES))
    items, total = helpers.page(records, limit, offset)
    return response.listing([serializers.plan(r) for r in items], total, limit, offset)


@bp.route("/systematic-plans/<plan_id>", methods=["PATCH"])
def update_plan(plan_id):
    caller = authenticate((ROLE_TAO, ROLE_HOLDER))
    body = validation.body()
    new_status = validation.get_enum(body, "status", PLAN_STATUSES)
    amount = validation.get_decimal(body, "amount", 2, positive=True)

    plan = helpers.get_plan(plan_id)
    helpers.require_ownership(caller, plan["account_id"])
    account = db.store.accounts.get(plan["account_id"])

    if new_status is not None:
        current = plan["status"]
        if new_status == "SUSPENDED":
            if current != "ACTIVE":
                raise ApiError("ERR_INVALID_PLAN_STATE", "Only an ACTIVE plan may be suspended.")
            plan["status"] = "SUSPENDED"
            plan["suspension_reason"] = "OPERATOR_REQUEST"
        elif new_status == "ACTIVE":
            if current != "SUSPENDED":
                raise ApiError("ERR_INVALID_PLAN_STATE", "Only a SUSPENDED plan may be resumed.")
            if account is None or account["status"] != "ACTIVE":
                raise ApiError("ERR_INVALID_PLAN_STATE",
                               "The owning account must be ACTIVE to resume the plan.")
            plan["status"] = "ACTIVE"
            plan["suspension_reason"] = None
        elif new_status == "TERMINATED":
            if current not in ("ACTIVE", "SUSPENDED"):
                raise ApiError("ERR_INVALID_PLAN_STATE",
                               "Only an ACTIVE or SUSPENDED plan may be terminated.")
            plan["status"] = "TERMINATED"

    if amount is not None:
        plan["amount"] = amount

    db.touch(plan)
    return response.ok(serializers.plan(plan))


def _advance(next_run_date, frequency):
    months = 1 if frequency == "MONTHLY" else 3
    return dates.add_months(next_run_date, months)


@bp.route("/systematic-plans/<plan_id>/execute", methods=["POST"])
def execute_plan(plan_id):
    caller = authenticate((ROLE_TAO,))
    plan = helpers.get_plan(plan_id)
    account = helpers.get_account(plan["account_id"])

    if account["status"] not in ACCOUNT_PARTICIPATING:
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE",
                       "The account must be ACTIVE or RESTRICTED to run a plan.")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PLAN_STATE", "Only an ACTIVE plan may be executed.")
    if account["status"] == "RESTRICTED" and plan["plan_type"] in PURCHASE_SIDE_PLAN_TYPES:
        raise ApiError("ERR_ACCOUNT_RESTRICTED",
                       "A restricted account may not run purchase-side plans.")
    if dates.fmt_date(clock.today()) < plan["next_run_date"]:
        raise ApiError("ERR_PLAN_NOT_DUE", "The plan is not yet due to run.")

    source_class = db.store.share_classes[plan["source_share_class_id"]]
    fund = db.store.funds[source_class["fund_id"]]
    trade_type = TRADE_TYPE_FOR_PLAN[plan["plan_type"]]

    gross_amount = None
    shares_requested = None

    if plan["plan_type"] == "SYSTEMATIC_INVESTMENT":
        gross_amount = plan["amount"]
    else:
        position = positions_service.find(account["id"], source_class["id"])
        if plan["plan_type"] == "SYSTEMATIC_WITHDRAWAL":
            market_value = (positions_service.market_value_amount(position)
                            if position is not None else Decimal("0.00"))
            if market_value < plan["amount"]:
                plan["status"] = "SUSPENDED"
                plan["suspension_reason"] = "INSUFFICIENT_POSITION_VALUE"
                db.touch(plan)
                return response.ok(serializers.plan(plan))
        price = positions_service.latest_price(source_class["id"])
        if price is None or price == 0:
            raise ApiError("ERR_NAV_NOT_AVAILABLE",
                           "The source class has no priced NAV to convert the plan amount.")
        shares_requested = q3(plan["amount"] / price)

    capture_service.capture(
        caller.user_id, account, source_class, fund, trade_type,
        gross_amount=gross_amount, shares_requested=shares_requested,
        as_of_date=None, dealer_reference=None,
        exchange_target_share_class_id=plan["target_share_class_id"],
        originating_plan_id=plan["id"], check_as_of=False)

    plan["executed_count"] = plan["executed_count"] + 1
    plan["last_run_date"] = dates.fmt_date(clock.today())
    plan["next_run_date"] = dates.fmt_date(
        _advance(dates.parse_date(plan["next_run_date"]), plan["frequency"]))
    db.touch(plan)
    return response.ok(serializers.plan(plan))
