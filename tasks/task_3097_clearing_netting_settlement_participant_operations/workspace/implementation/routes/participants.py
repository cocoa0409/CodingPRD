"""Participants, collateral deposits and securities."""

from flask import Blueprint, request

from db import db, new_ledger_row, new_record, touch
from errors import (
    api_error,
    ERR_DEPOSIT_RELEASE_INVALID,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
)
from lookups import (
    deposits_of_participant,
    postings_of_deposit,
    postings_of_participant,
)
from middleware import CLEARING_MEMBER, PLATFORM_ADMIN, RISK_OFFICER, principal
from request import (
    body,
    check_unknown,
    optional,
    pagination,
    reject_immutable,
    require,
)
from routes.common import ok, ok_array, ok_list, paginate
from serializers import (
    deposit as serialize_deposit,
    deposit_transaction,
    participant as serialize_participant,
    security as serialize_security,
)
from services.deposit import deposit_of_participant, derive_coverage
from services.participants import (
    activate,
    create_participant,
    financial_review,
    reinstate,
    suspend,
    update_terms,
)

bp = Blueprint("participants", __name__)

PARTICIPANT_CLASSES = ("BANK", "BROKER_DEALER", "CUSTODIAN_BANK", "INSURANCE_CARRIER")
MEMBERSHIP_STATUSES = ("PENDING", "ACTIVE", "SUSPENDED", "DEFAULTED", "EXPELLED")

CREATE_FIELDS = (
    "legal_name",
    "lei",
    "participant_class",
    "net_capital_cents",
    "requires_segregated_custody",
)
UPDATE_MUTABLE = ("legal_name", "requires_segregated_custody")
UPDATE_IMMUTABLE = (
    "lei",
    "participant_class",
    "membership_status",
    "net_capital_cents",
    "required_min_net_capital_cents",
    "financial_standard_status",
    "is_defaulted",
    "last_financial_review_at",
    "id",
    "created_at",
    "updated_at",
    "version",
)

SECURITY_CREATE_FIELDS = (
    "ticker",
    "cusip",
    "currency",
    "prev_settlement_price_cents",
    "current_volatility_bps",
)
SECURITY_MUTABLE = ("prev_settlement_price_cents", "current_volatility_bps")
SECURITY_IMMUTABLE = (
    "ticker",
    "cusip",
    "currency",
    "id",
    "created_at",
    "updated_at",
    "version",
)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------
@bp.post("/clearing/participants")
def create_participant_route():
    principal((PLATFORM_ADMIN,))
    data = body()
    check_unknown(data, CREATE_FIELDS)
    legal_name = require(data, "legal_name", type_=str)
    lei = require(data, "lei", type_=str)
    participant_class = require(data, "participant_class", type_=str, enum=PARTICIPANT_CLASSES)
    net_capital_cents = require(data, "net_capital_cents", type_=int)
    segregated = optional(data, "requires_segregated_custody", type_=bool, default=False)

    for existing in db.participants.values():
        if existing["lei"] == lei:
            raise api_error(ERR_INVALID_REQUEST, "The lei is unique across participants.")

    record = create_participant(
        legal_name, lei, participant_class, net_capital_cents, segregated
    )
    return ok(serialize_participant(record), 201)


@bp.get("/clearing/participants")
def list_participants_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    membership_status = request.args.get("membership_status")
    participant_class = request.args.get("participant_class")
    rows = list(db.participants.values())
    if membership_status is not None:
        rows = [r for r in rows if r["membership_status"] == membership_status]
    if participant_class is not None:
        rows = [r for r in rows if r["participant_class"] == participant_class]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_participant(r) for r in page], limit, offset, total)


@bp.get("/clearing/participants/<pid>")
def read_participant_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return ok(serialize_participant(record))


@bp.post("/clearing/participants/<pid>/financial-review")
def financial_review_route(pid):
    principal((RISK_OFFICER,))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    data = body()
    check_unknown(data, ("net_capital_cents",))
    net_capital_cents = require(data, "net_capital_cents", type_=int)
    financial_review(record, net_capital_cents)
    return ok(serialize_participant(record))


@bp.put("/clearing/participants/<pid>")
def update_participant_route(pid):
    principal((PLATFORM_ADMIN,))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    data = body()
    check_unknown(data, UPDATE_MUTABLE + UPDATE_IMMUTABLE)
    reject_immutable(data, UPDATE_IMMUTABLE)
    legal_name = optional(data, "legal_name", type_=str)
    segregated = optional(data, "requires_segregated_custody", type_=bool)
    update_terms(record, legal_name=legal_name, requires_segregated_custody=segregated)
    return ok(serialize_participant(record))


@bp.post("/clearing/participants/<pid>/activate")
def activate_route(pid):
    principal((PLATFORM_ADMIN,))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    activate(record)
    return ok(serialize_participant(record))


@bp.post("/clearing/participants/<pid>/suspend")
def suspend_route(pid):
    principal((PLATFORM_ADMIN,))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    suspend(record)
    return ok(serialize_participant(record))


@bp.post("/clearing/participants/<pid>/reinstate")
def reinstate_route(pid):
    principal((PLATFORM_ADMIN,))
    record = db.participants.get(pid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    reinstate(record)
    return ok(serialize_participant(record))


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------
@bp.get("/clearing/participants/<pid>/deposits")
def list_participant_deposits_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    if db.participants.get(pid) is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    rows = deposits_of_participant(pid)
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_deposit(r) for r in rows])


@bp.get("/clearing/deposits")
def list_deposits_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    participant_id = request.args.get("participant_id")
    rows = list(db.deposits.values())
    if participant_id is not None:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_deposit(r) for r in page], limit, offset, total)


@bp.get("/clearing/deposits/<did>")
def read_deposit_route(did):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = db.deposits.get(did)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    derive_coverage(record)
    return ok(serialize_deposit(record))


@bp.post("/clearing/deposits/<did>/postings")
def post_deposit_route(did):
    actor = principal((CLEARING_MEMBER,))
    record = db.deposits.get(did)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    if not actor.owns_participant(record["participant_id"]):
        from errors import ERR_UNAUTHORIZED

        raise api_error(ERR_UNAUTHORIZED)
    data = body()
    check_unknown(data, ("amount_cents", "reason_code"))
    amount_cents = require(data, "amount_cents", type_=int)
    reason_code = optional(data, "reason_code", type_=str)

    if amount_cents == 0:
        raise api_error(ERR_INVALID_AMOUNT)
    if amount_cents < 0:
        if not reason_code:
            raise api_error(ERR_DEPOSIT_RELEASE_INVALID)
        current = sum(
            txn["amount_cents"] for txn in postings_of_deposit(record["id"])
        )
        if current + amount_cents < 0:
            raise api_error(ERR_DEPOSIT_RELEASE_INVALID)

    txn = new_ledger_row(
        deposit_id=record["id"],
        participant_id=record["participant_id"],
        amount_cents=amount_cents,
        txn_type="POST" if amount_cents > 0 else "RELEASE",
        reason_code=reason_code,
    )
    db.deposit_transactions[txn["id"]] = txn
    derive_coverage(record)
    touch(record)

    proceeding = _open_proceeding_for(record["participant_id"])
    if proceeding is not None:
        from services.defaults import defaulter_resources

        proceeding["defaulter_resources_cents"] = defaulter_resources(record["participant_id"])
        touch(proceeding)
    return ok(deposit_transaction(txn), 201)


def _open_proceeding_for(participant_id):
    for proceeding in db.default_proceedings.values():
        if proceeding["participant_id"] == participant_id:
            return proceeding
    return None


@bp.get("/clearing/participants/<pid>/deposit-postings")
def participant_postings_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    if db.participants.get(pid) is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    limit, offset = pagination()
    rows = postings_of_participant(pid)
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([deposit_transaction(r) for r in page], limit, offset, total)


@bp.get("/clearing/deposits/<did>/postings")
def deposit_postings_route(did):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = db.deposits.get(did)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    limit, offset = pagination()
    rows = postings_of_deposit(did)
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([deposit_transaction(r) for r in page], limit, offset, total)


@bp.post("/clearing/securities/<sid>/allocate-fund-cost")
def allocate_fund_cost_route(sid):
    principal((PLATFORM_ADMIN,))
    if db.securities.get(sid) is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    data = body()
    check_unknown(data, ("participant_id", "amount_cents", "reason_code"))
    participant_id = require(data, "participant_id", type_=str)
    amount_cents = require(data, "amount_cents", type_=int)
    reason_code = require(data, "reason_code", type_=str)
    participant = db.participants.get(participant_id)
    if participant is None:
        from errors import ERR_PARTICIPANT_NOT_FOUND

        raise api_error(ERR_PARTICIPANT_NOT_FOUND)

    if amount_cents == 0:
        raise api_error(ERR_INVALID_AMOUNT)
    deposit = deposit_of_participant(participant_id)
    if deposit is None:
        from errors import ERR_INVALID_STATE

        raise api_error(ERR_INVALID_STATE)
    if amount_cents < 0:
        current = sum(txn["amount_cents"] for txn in postings_of_deposit(deposit["id"]))
        if current + amount_cents < 0:
            raise api_error(ERR_DEPOSIT_RELEASE_INVALID)

    txn = new_ledger_row(
        deposit_id=deposit["id"],
        participant_id=participant_id,
        amount_cents=amount_cents,
        txn_type="POST" if amount_cents > 0 else "RELEASE",
        reason_code=reason_code,
    )
    db.deposit_transactions[txn["id"]] = txn
    derive_coverage(deposit)
    touch(deposit)
    touch(participant)

    proceeding = _open_proceeding_for(participant_id)
    if proceeding is not None:
        from services.defaults import defaulter_resources

        proceeding["defaulter_resources_cents"] = defaulter_resources(participant_id)
        touch(proceeding)
    return ok(deposit_transaction(txn))


# ---------------------------------------------------------------------------
# Securities
# ---------------------------------------------------------------------------
@bp.post("/clearing/securities")
def create_security_route():
    principal((PLATFORM_ADMIN,))
    data = body()
    check_unknown(data, SECURITY_CREATE_FIELDS)
    ticker = require(data, "ticker", type_=str)
    cusip = require(data, "cusip", type_=str)
    currency = optional(data, "currency", type_=str, default="USD")
    prev_price = require(data, "prev_settlement_price_cents", type_=int)
    volatility = optional(data, "current_volatility_bps", type_=int, default=0)

    for existing in db.securities.values():
        if existing["ticker"] == ticker:
            raise api_error(ERR_INVALID_REQUEST, "The ticker is unique across securities.")
        if existing["cusip"] == cusip:
            raise api_error(ERR_INVALID_REQUEST, "The cusip is unique across securities.")

    record = new_record(
        ticker=ticker,
        cusip=cusip,
        currency=currency,
        prev_settlement_price_cents=prev_price,
        current_volatility_bps=volatility,
    )
    db.securities[record["id"]] = record
    return ok(serialize_security(record), 201)


@bp.get("/clearing/securities")
def list_securities_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    page, total = paginate(
        db.securities.values(), limit, offset, lambda r: r["created_at"]
    )
    return ok_list([serialize_security(r) for r in page], limit, offset, total)


@bp.get("/clearing/securities/<sid>")
def read_security_route(sid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    record = db.securities.get(sid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return ok(serialize_security(record))


@bp.put("/clearing/securities/<sid>")
def update_security_route(sid):
    principal((PLATFORM_ADMIN,))
    record = db.securities.get(sid)
    if record is None:
        from errors import ERR_RESOURCE_NOT_FOUND

        raise api_error(ERR_RESOURCE_NOT_FOUND)
    data = body()
    check_unknown(data, SECURITY_MUTABLE + SECURITY_IMMUTABLE)
    reject_immutable(data, SECURITY_IMMUTABLE)
    prev_price = optional(data, "prev_settlement_price_cents", type_=int)
    volatility = optional(data, "current_volatility_bps", type_=int)
    if prev_price is not None:
        record["prev_settlement_price_cents"] = prev_price
    if volatility is not None:
        record["current_volatility_bps"] = volatility
    touch(record)
    return ok(serialize_security(record))