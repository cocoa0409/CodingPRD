"""Settlement windows, custody accounts and the settlement cycle."""

from flask import Blueprint, request

from db import db, new_record, touch
from errors import (
    api_error,
    ERR_AFFIRMATION_DEADLINE_ORDER,
    ERR_AFFIRMATION_DEADLINE_PASSED,
    ERR_EMPTY_NET_POSITION_SET,
    ERR_INVALID_STATE,
    ERR_OBLIGATION_UNDERFUNDED,
    ERR_PARTICIPANT_NOT_ACTIVE,
    ERR_RESOURCE_NOT_FOUND,
    ERR_SECURITY_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_WINDOW_DEADLINE_REGRESSION,
    ERR_WINDOW_HAS_ACTIVE_FAILS,
)
from lookups import custody_accounts_of, net_positions_of_window, windows_of_security
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
    custody_account as serialize_account,
    window as serialize_window,
)
from services.custody import apply_on_settle
from services.deposit import apply_grace_on_close
from services.marks import recompute_marks
from services.netting import run_cycle
from services.trades import affirm
from timeutil import instant_ge, instant_lt, require_date, require_instant

bp = Blueprint("windows", __name__)

ACCOUNT_TYPES = ("SEGREGATED", "HOUSE", "PLEDGED")
WINDOW_STATUSES = ("OPEN", "NETTED", "SETTLED", "CLOSED")

WINDOW_CREATE_FIELDS = (
    "security_id",
    "settlement_date",
    "trade_entry_deadline",
    "affirmation_deadline",
)
WINDOW_MUTABLE = ("trade_entry_deadline", "affirmation_deadline")
WINDOW_IMMUTABLE = (
    "security_id",
    "settlement_date",
    "status",
    "id",
    "created_at",
    "updated_at",
    "version",
)


def require_record(table, identifier):
    record = table.get(identifier)
    if record is None:
        raise api_error(ERR_RESOURCE_NOT_FOUND)
    return record


# ---------------------------------------------------------------------------
# Custody accounts
# ---------------------------------------------------------------------------
@bp.post("/clearing/participants/<pid>/custody-accounts")
def open_custody_account_route(pid):
    principal((PLATFORM_ADMIN,))
    participant = require_record(db.participants, pid)
    data = body()
    check_unknown(data, ("account_number", "account_type"))
    account_number = require(data, "account_number", type_=str)
    account_type = require(data, "account_type", type_=str, enum=ACCOUNT_TYPES)
    record = new_record(
        participant_id=participant["id"],
        account_number=account_number,
        account_type=account_type,
        status="OPEN",
        positions=[],
    )
    db.custody_accounts[record["id"]] = record
    return ok(serialize_account(record), 201)


@bp.get("/clearing/participants/<pid>/custody-accounts")
def list_custody_accounts_route(pid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    require_record(db.participants, pid)
    rows = custody_accounts_of(pid)
    rows.sort(key=lambda r: r["created_at"])
    return ok_array([serialize_account(r) for r in rows])


# ---------------------------------------------------------------------------
# Settlement windows
# ---------------------------------------------------------------------------
@bp.post("/clearing/settlement-windows")
def create_window_route():
    principal((PLATFORM_ADMIN,))
    data = body()
    check_unknown(data, WINDOW_CREATE_FIELDS)
    security_id = require(data, "security_id", type_=str)
    settlement_date = require(data, "settlement_date", type_=str)
    trade_entry_deadline = require(data, "trade_entry_deadline", type_=str)
    affirmation_deadline = require(data, "affirmation_deadline", type_=str)

    if db.securities.get(security_id) is None:
        raise api_error(ERR_SECURITY_NOT_FOUND)
    require_date(settlement_date, "settlement_date")
    require_instant(trade_entry_deadline, "trade_entry_deadline")
    require_instant(affirmation_deadline, "affirmation_deadline")

    if not instant_lt(trade_entry_deadline, affirmation_deadline):
        raise api_error(ERR_AFFIRMATION_DEADLINE_ORDER)

    for existing in windows_of_security(security_id):
        if existing["settlement_date"] == settlement_date:
            raise api_error(
                ERR_INVALID_STATE,
                "A non-CLOSED settlement window already exists for that security and settlement date.",
            )

    record = new_record(
        security_id=security_id,
        settlement_date=settlement_date,
        trade_entry_deadline=trade_entry_deadline,
        affirmation_deadline=affirmation_deadline,
        status="OPEN",
    )
    db.settlement_windows[record["id"]] = record
    return ok(serialize_window(record), 201)


@bp.put("/clearing/settlement-windows/<wid>")
def update_window_route(wid):
    principal((PLATFORM_ADMIN,))
    window = require_record(db.settlement_windows, wid)
    if window["status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)
    data = body()
    check_unknown(data, WINDOW_MUTABLE + WINDOW_IMMUTABLE)
    reject_immutable(data, WINDOW_IMMUTABLE)

    trade_entry_deadline = optional(data, "trade_entry_deadline", type_=str)
    affirmation_deadline = optional(data, "affirmation_deadline", type_=str)
    if trade_entry_deadline is not None:
        require_instant(trade_entry_deadline, "trade_entry_deadline")
    if affirmation_deadline is not None:
        require_instant(affirmation_deadline, "affirmation_deadline")

    new_entry = trade_entry_deadline or window["trade_entry_deadline"]
    new_affirmation = affirmation_deadline or window["affirmation_deadline"]
    if not instant_lt(new_entry, new_affirmation):
        raise api_error(ERR_WINDOW_DEADLINE_REGRESSION)
    if trade_entry_deadline is not None and instant_ge(
        db.get_clock(), window["trade_entry_deadline"]
    ):
        if instant_lt(trade_entry_deadline, window["trade_entry_deadline"]):
            raise api_error(ERR_WINDOW_DEADLINE_REGRESSION)

    window["trade_entry_deadline"] = new_entry
    window["affirmation_deadline"] = new_affirmation
    touch(window)
    return ok(serialize_window(window))


@bp.get("/clearing/settlement-windows")
def list_windows_route():
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    limit, offset = pagination()
    security_id = request.args.get("security_id")
    status = request.args.get("status")
    rows = list(db.settlement_windows.values())
    if security_id is not None:
        rows = [r for r in rows if r["security_id"] == security_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset, lambda r: r["created_at"])
    return ok_list([serialize_window(r) for r in page], limit, offset, total)


@bp.get("/clearing/settlement-windows/<wid>")
def read_window_route(wid):
    principal((PLATFORM_ADMIN, RISK_OFFICER, CLEARING_MEMBER))
    window = require_record(db.settlement_windows, wid)
    return ok(serialize_window(window))


def _guard_deadline_order(window):
    if not instant_lt(window["trade_entry_deadline"], window["affirmation_deadline"]):
        raise api_error(ERR_AFFIRMATION_DEADLINE_ORDER)


@bp.post("/clearing/settlement-windows/<wid>/net")
def net_window_route(wid):
    principal((PLATFORM_ADMIN,))
    window = require_record(db.settlement_windows, wid)
    if window["status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)
    _guard_deadline_order(window)
    if not instant_lt(db.get_clock(), window["affirmation_deadline"]):
        raise api_error(ERR_AFFIRMATION_DEADLINE_PASSED)

    run_cycle(window)
    window["status"] = "NETTED"
    touch(window)
    return ok(serialize_window(window))


@bp.post("/clearing/settlement-windows/<wid>/run-cycle")
def run_cycle_route(wid):
    principal((PLATFORM_ADMIN,))
    window = require_record(db.settlement_windows, wid)
    if window["status"] != "OPEN":
        raise api_error(ERR_INVALID_STATE)
    _guard_deadline_order(window)

    data = body()
    check_unknown(data, ("expected_window_version",))
    expected = require(data, "expected_window_version", type_=int)
    if expected != window["version"]:
        raise api_error(ERR_STALE_VERSION)

    run_cycle(window)
    touch(window)
    return ok(serialize_window(window))


@bp.post("/clearing/settlement-windows/<wid>/settle")
def settle_window_route(wid):
    principal((PLATFORM_ADMIN,))
    window = require_record(db.settlement_windows, wid)
    if window["status"] != "NETTED":
        raise api_error(ERR_INVALID_STATE)

    rows = net_positions_of_window(window["id"])
    if not rows:
        raise api_error(ERR_EMPTY_NET_POSITION_SET)
    for net_position in rows:
        if net_position["funded_amount_cents"] < net_position["settlement_obligation_cents"]:
            raise api_error(ERR_OBLIGATION_UNDERFUNDED)
    for net_position in rows:
        if net_position["dvp_status"] != "FAILED":
            continue
        participant = db.participants.get(net_position["participant_id"])
        if participant is not None and participant["membership_status"] == "ACTIVE":
            raise api_error(ERR_WINDOW_HAS_ACTIVE_FAILS)

    for net_position in rows:
        if net_position["net_quantity"] > 0:
            net_position["dvp_status"] = "RECEIVED"
        elif net_position["net_quantity"] < 0:
            net_position["dvp_status"] = "DELIVERED"
        touch(net_position)

    apply_on_settle(window)
    recompute_marks(rows)

    window["status"] = "SETTLED"
    touch(window)
    return ok(serialize_window(window))


@bp.post("/clearing/settlement-windows/<wid>/close-cycle")
def close_window_route(wid):
    principal((PLATFORM_ADMIN,))
    window = require_record(db.settlement_windows, wid)
    if window["status"] not in ("NETTED", "SETTLED"):
        raise api_error(ERR_INVALID_STATE)

    for deposit in db.deposits.values():
        apply_grace_on_close(deposit["participant_id"])

    window["status"] = "CLOSED"
    touch(window)
    return ok(serialize_window(window))


@bp.post("/clearing/settlement-windows/<wid>/affirm")
def affirm_window_route(wid):
    actor = principal((CLEARING_MEMBER,))
    window = require_record(db.settlement_windows, wid)
    participant = db.participants.get(actor.user_id)
    if participant is None:
        from errors import ERR_PARTICIPANT_NOT_FOUND

        raise api_error(ERR_PARTICIPANT_NOT_FOUND)
    if participant["membership_status"] != "ACTIVE":
        raise api_error(ERR_PARTICIPANT_NOT_ACTIVE)

    affirm(participant["id"], window["security_id"], window["settlement_date"])
    touch(window)
    return ok(serialize_window(window))