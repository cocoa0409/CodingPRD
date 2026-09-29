"""Exchange requests and confirmations: budgets, charges, holds and settlements."""

from datetime import timedelta

from flask import Blueprint

import calc
import shapes
from authz import authenticate, require_acting_identity, require_owner
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, listing, one, read
from services import deposits as deposit_service
from services import ledger
from services import requests as request_service
from store import (db, parse_date, parse_instant, serialize, touch,
                   CONFIRMATION_STATUSES, FUNDING_MODES, REQUEST_STATUSES,
                   REINSTATEMENT_WINDOW_DAYS, REQUEST_WINDOW_MAX_SPAN_DAYS, UNIT_SIZES)

bp = Blueprint("exchange", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]
AFFILIATED = ("ACTIVE", "PROBATION")


def _available(deposit):
    return deposit["deposit_status"] == "BANKED" and deposit["rental_status"] == "NOT_LISTED"


@bp.route("/exchange-requests", methods=["POST"])
def create_exchange_request():
    caller = authenticate(["Member"])
    payload = shapes.body()
    member_id = shapes.take_id(payload, "member_id")
    requested_resort_id = shapes.take_id(payload, "requested_resort_id")
    requested_unit_size = shapes.take_enum(payload, "requested_unit_size", UNIT_SIZES)
    window_start_date = shapes.take_date(payload, "window_start_date")
    window_end_date = shapes.take_date(payload, "window_end_date")
    deposit_id = shapes.take_id(payload, "deposit_id", required=False)
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    resort = shapes.find_resort(requested_resort_id)
    funding = shapes.find_deposit(deposit_id) if deposit_id else None
    require_owner(caller, member["id"])
    if funding is not None:
        require_owner(caller, funding["member_id"])
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    if funding is not None and not _available(funding):
        raise ApiError("ERR_DEPOSIT_NOT_AVAILABLE")
    if resort["affiliation_status"] not in AFFILIATED:
        raise ApiError("ERR_RESORT_NOT_AFFILIATED")
    if funding is not None and parse_instant(funding["expires_at"]) <= db.now():
        raise ApiError("ERR_DEPOSIT_EXPIRED")
    start_day = parse_date(window_start_date)
    end_day = parse_date(window_end_date)
    if end_day < start_day or (end_day - start_day).days > REQUEST_WINDOW_MAX_SPAN_DAYS:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    band = deposit_service.band_for_date(resort["id"], window_start_date)
    if band is None:
        raise ApiError("ERR_NO_SEASON_BAND_FOR_DATE")
    tier = db.membership_tiers[member["tier_id"]]
    if member["active_request_count"] >= tier["max_active_requests"]:
        raise ApiError("ERR_ACTIVE_REQUEST_LIMIT")
    funding_mode = "DEPOSIT_FIRST" if funding is not None else "REQUEST_FIRST"
    required_power_estimate = calc.trading_power(
        requested_unit_size, band["band_code"], resort["demand_index"],
        resort["quality_rating"], (start_day - db.today()).days)
    budget = 0
    if funding is not None:
        budget = calc.power_budget(funding["awarded_power"],
                                  tier["deposit_first_bonus_pct"], funding_mode)
    charge = calc.exchange_charge(required_power_estimate, budget,
                                 tier["base_exchange_fee_cents"],
                                 tier["priority_surcharge_cents"], funding_mode)
    quoted = charge["quoted_charge_cents"]
    if member["wallet_credit_cents"] < quoted:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT")
    row = db.new_row({
        "member_id": member["id"],
        "requested_resort_id": resort["id"],
        "requested_unit_size": requested_unit_size,
        "window_start_date": window_start_date,
        "window_end_date": window_end_date,
        "deposit_id": funding["id"] if funding is not None else None,
        "funding_mode": funding_mode,
        "required_power_estimate": required_power_estimate,
        "power_budget": budget,
        "quoted_charge_cents": quoted,
        "charge_refunded_cents": 0,
        "priority_score": 0,
        "decline_count": 0,
        "status": "SUBMITTED",
        "matched_deposit_id": None,
        "matched_hold_expires_at": None,
        "waitlisted_at": None,
    })
    db.exchange_requests[row["id"]] = row
    ledger.move_cash(member, "EXCHANGE_CHARGE", "EXCHANGE_REQUEST", row["id"],
                     "Exchange charge quoted at request creation.", -quoted)
    request_service.sync_active_count(member)
    return object_response(serialize(row), 201)


@bp.route("/exchange-requests/<request_id>", methods=["GET"])
def get_exchange_request(request_id):
    read(ALL_ROLES)
    return one(shapes.find_request(request_id))


@bp.route("/exchange-requests", methods=["GET"])
def list_exchange_requests():
    return listing(ALL_ROLES, db.exchange_requests, [
        ("member_id", "member_id", FK, shapes.find_member),
        ("requested_resort_id", "requested_resort_id", FK, shapes.find_resort),
        ("deposit_id", "deposit_id", FK, shapes.find_deposit),
        ("matched_deposit_id", "matched_deposit_id", FK, shapes.find_deposit),
        ("status", "status", ENUM, REQUEST_STATUSES),
        ("funding_mode", "funding_mode", ENUM, FUNDING_MODES),
    ])


@bp.route("/exchange-requests/<request_id>/funding", methods=["POST"])
def attach_funding(request_id):
    caller = authenticate(["Member"])
    payload = shapes.body()
    deposit_id = shapes.take_id(payload, "deposit_id")
    require_acting_identity(caller)
    exchange_request = shapes.find_request(request_id)
    funding = shapes.find_deposit(deposit_id)
    require_owner(caller, exchange_request["member_id"])
    require_owner(caller, funding["member_id"])
    if exchange_request["status"] not in ("SUBMITTED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member = db.members[exchange_request["member_id"]]
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    if not _available(funding):
        raise ApiError("ERR_DEPOSIT_NOT_AVAILABLE")
    tier = db.membership_tiers[member["tier_id"]]
    exchange_request["deposit_id"] = funding["id"]
    exchange_request["power_budget"] = calc.power_budget(
        funding["awarded_power"], tier["deposit_first_bonus_pct"],
        exchange_request["funding_mode"])
    touch(exchange_request)
    return one(exchange_request)


@bp.route("/exchange-requests/<request_id>/decline", methods=["POST"])
def decline_match(request_id):
    caller = authenticate(["Member"])
    shapes.body()
    require_acting_identity(caller)
    exchange_request = shapes.find_request(request_id)
    require_owner(caller, exchange_request["member_id"])
    if exchange_request["status"] != "MATCHED" or not exchange_request["matched_deposit_id"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    request_service.release_hold(exchange_request)
    exchange_request["status"] = "WAITLISTED"
    exchange_request["decline_count"] = exchange_request["decline_count"] + 1
    exchange_request["waitlisted_at"] = db.now_iso()
    touch(exchange_request)
    request_service.sync_active_count(db.members[exchange_request["member_id"]])
    return one(exchange_request)


@bp.route("/exchange-requests/<request_id>/cancellation", methods=["POST"])
def cancel_exchange_request(request_id):
    caller = authenticate(["Member"])
    shapes.body()
    require_acting_identity(caller)
    exchange_request = shapes.find_request(request_id)
    require_owner(caller, exchange_request["member_id"])
    if exchange_request["status"] not in ("SUBMITTED", "WAITLISTED", "MATCHED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member = db.members[exchange_request["member_id"]]
    request_service.release_hold(exchange_request)
    exchange_request["status"] = "CANCELLED"
    touch(exchange_request)
    request_service.refund_charge(exchange_request, member)
    request_service.sync_active_count(member)
    return one(exchange_request)


# ---------------------------------------------------------------------------
# confirmations
# ---------------------------------------------------------------------------
@bp.route("/confirmations", methods=["POST"])
def create_confirmation():
    caller = authenticate(["Member"])
    payload = shapes.body()
    exchange_request_id = shapes.take_id(payload, "exchange_request_id")
    require_acting_identity(caller)
    exchange_request = shapes.find_request(exchange_request_id)
    require_owner(caller, exchange_request["member_id"])
    if exchange_request["status"] != "MATCHED" or not exchange_request["matched_deposit_id"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    hold = parse_instant(exchange_request["matched_hold_expires_at"])
    if hold is None or hold <= db.now():
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member = db.members[exchange_request["member_id"]]
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    deposit = db.deposits[exchange_request["matched_deposit_id"]]
    settlement = deposit["settlement_power"]
    if member["trading_power_balance"] < settlement:
        raise ApiError("ERR_INSUFFICIENT_TRADING_POWER")
    row = db.new_row({
        "exchange_request_id": exchange_request["id"],
        "awarded_deposit_id": deposit["id"],
        "awarded_check_in_date": deposit["check_in_date"],
        "power_debited": settlement,
        "status": "CONFIRMED",
        "cancelled_at": None,
        "cancellation_fee_cents": 0,
        "restoration_variant": None,
        "restored_power": 0,
        "reinstatement_fee_cents": 0,
        "reinstated_from_confirmation_id": None,
    })
    db.confirmations[row["id"]] = row
    exchange_request["status"] = "CONFIRMED"
    touch(exchange_request)
    deposit["deposit_status"] = "USED"
    touch(deposit)
    ledger.post(member, "EXCHANGE_DEBIT", "CONFIRMATION", row["id"],
                "Trading power debited for the confirmed exchange.",
                power_delta=-settlement)
    _settlement_adjustment(deposit)
    request_service.sync_active_count(member)
    return object_response(serialize(row), 201)


def _settlement_adjustment(deposit):
    """The once-only reconciliation of settlement_power against awarded_power."""
    delta = deposit["settlement_power"] - deposit["awarded_power"]
    if delta == 0:
        return None
    owner = db.members[deposit["member_id"]]
    if delta < 0:
        applied = -min(-delta, owner["trading_power_balance"])
    else:
        applied = delta
    return ledger.post(owner, "SETTLEMENT_ADJUSTMENT", "DEPOSIT", deposit["id"],
                       "Reconciliation of the at-settlement valuation against the "
                       "at-deposit valuation.", power_delta=applied)


@bp.route("/confirmations/<confirmation_id>", methods=["GET"])
def get_confirmation(confirmation_id):
    read(ALL_ROLES)
    return one(shapes.find_confirmation(confirmation_id))


@bp.route("/confirmations", methods=["GET"])
def list_confirmations():
    return listing(ALL_ROLES, db.confirmations, [
        ("exchange_request_id", "exchange_request_id", FK, shapes.find_request),
        ("awarded_deposit_id", "awarded_deposit_id", FK, shapes.find_deposit),
        ("reinstated_from_confirmation_id", "reinstated_from_confirmation_id", FK,
         shapes.find_confirmation),
        ("status", "status", ENUM, CONFIRMATION_STATUSES),
    ])


@bp.route("/confirmations/<confirmation_id>/cancellation", methods=["POST"])
def cancel_confirmation(confirmation_id):
    caller = authenticate(["Member", "NetworkOperator"])
    shapes.body()
    require_acting_identity(caller)
    confirmation = shapes.find_confirmation(confirmation_id)
    exchange_request = db.exchange_requests[confirmation["exchange_request_id"]]
    require_owner(caller, exchange_request["member_id"])
    if confirmation["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member = db.members[exchange_request["member_id"]]
    tier = db.membership_tiers[member["tier_id"]]
    deposit = db.deposits[confirmation["awarded_deposit_id"]]
    days_out = (parse_date(confirmation["awarded_check_in_date"]) - db.today()).days
    settlement = calc.cancellation_settlement(days_out, confirmation["power_debited"],
                                             deposit["awarded_power"],
                                             tier["cancellation_fee_cents"])
    if member["wallet_credit_cents"] < settlement["cancellation_fee_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT")
    confirmation["status"] = "CANCELLED"
    confirmation["cancelled_at"] = db.now_iso()
    confirmation["restoration_variant"] = settlement["restoration_variant"]
    confirmation["restored_power"] = settlement["restored_power"]
    confirmation["cancellation_fee_cents"] = settlement["cancellation_fee_cents"]
    touch(confirmation)
    deposit["deposit_status"] = "BANKED"
    touch(deposit)
    ledger.credit_power(member, "EXCHANGE_RESTORATION", "CONFIRMATION", confirmation["id"],
                        "Trading power restored by the cancelled exchange.",
                        settlement["restored_power"])
    ledger.move_cash(member, "CANCELLATION_FEE", "CONFIRMATION", confirmation["id"],
                     "Cancellation fee levied on the cancelled exchange.",
                     -settlement["cancellation_fee_cents"])
    if settlement["restoration_variant"] == "PRORATED_RESTORE":
        owner = db.members[deposit["member_id"]]
        haircut = settlement["haircut_power"]
        deposit["restoration_haircut_power"] = deposit["restoration_haircut_power"] + haircut
        deposit_service.sync_remaining(deposit)
        ledger.debit_power_clamped(
            owner, "RESTORATION_HAIRCUT", "DEPOSIT", deposit["id"],
            "Prorated restoration haircut taken from the depositing owner.", haircut)
        resort = db.resorts[deposit["resort_id"]]
        deposit_service.list_on_getaway(deposit, resort, owner, db.now(), None)
    return one(confirmation)


@bp.route("/confirmations/<confirmation_id>/reinstatement", methods=["POST"])
def reinstate_confirmation(confirmation_id):
    caller = authenticate(["Member"])
    shapes.body()
    require_acting_identity(caller)
    confirmation = shapes.find_confirmation(confirmation_id)
    exchange_request = db.exchange_requests[confirmation["exchange_request_id"]]
    require_owner(caller, exchange_request["member_id"])
    if confirmation["status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    member = db.members[exchange_request["member_id"]]
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    deposit = db.deposits[confirmation["awarded_deposit_id"]]
    if not _available(deposit):
        raise ApiError("ERR_DEPOSIT_NOT_AVAILABLE")
    deadline = parse_instant(confirmation["cancelled_at"]) + timedelta(
        days=REINSTATEMENT_WINDOW_DAYS)
    if db.now() > deadline:
        raise ApiError("ERR_REINSTATEMENT_WINDOW_CLOSED")
    tier = db.membership_tiers[member["tier_id"]]
    fee = tier["reinstatement_fee_cents"]
    if member["wallet_credit_cents"] < fee:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT")
    settlement = deposit["settlement_power"]
    if member["trading_power_balance"] < settlement:
        raise ApiError("ERR_INSUFFICIENT_TRADING_POWER")
    successor = db.new_row({
        "exchange_request_id": exchange_request["id"],
        "awarded_deposit_id": deposit["id"],
        "awarded_check_in_date": deposit["check_in_date"],
        "power_debited": settlement,
        "status": "CONFIRMED",
        "cancelled_at": None,
        "cancellation_fee_cents": 0,
        "restoration_variant": None,
        "restored_power": 0,
        "reinstatement_fee_cents": fee,
        "reinstated_from_confirmation_id": confirmation["id"],
    })
    db.confirmations[successor["id"]] = successor
    confirmation["status"] = "REINSTATED"
    touch(confirmation)
    deposit["deposit_status"] = "USED"
    touch(deposit)
    ledger.move_cash(member, "REINSTATEMENT_FEE", "CONFIRMATION", successor["id"],
                     "Reinstatement fee levied on the successor confirmation.", -fee)
    ledger.post(member, "EXCHANGE_DEBIT", "CONFIRMATION", successor["id"],
                "Trading power re-debited for the reinstated exchange.",
                power_delta=-settlement)
    return object_response(serialize(successor), 201)
