"""Settlement domain: SettlementWindows, PaymentEntries (+ cancel,
run-settlement), ReturnRecords, and AccountValidations (PRD sections 3.5,
3.6, 3.7)."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, g, request

from auth import ROLES, require_roles
from clock import (
    CLOCK,
    banking_days_between,
    hhmm,
    parse_hhmm,
    period_of_date,
    render_date,
    render_ts,
    render_ts3,
)
from envelope import ok
from errors import fail
from originators import compute_exposures
from store import DB, add_record, touch
from validation import (
    get_body,
    list_response,
    optional_bool,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("settlement", __name__)

AUTHORIZATION_TYPES = ("WRITTEN_SIGNED", "ORAL_RECORDED", "IMPLIED", "NONE")
REASON_CODES = (
    "UNAUTHORIZED_DEBIT",
    "AUTHORIZATION_REVOKED",
    "INSUFFICIENT_FUNDS",
    "INVALID_ACCOUNT",
    "STOP_PAYMENT",
)
REASON_CLASS_BY_CODE = {
    "UNAUTHORIZED_DEBIT": "UNAUTHORIZED",
    "AUTHORIZATION_REVOKED": "UNAUTHORIZED",
    "INSUFFICIENT_FUNDS": "ADMINISTRATIVE",
    "INVALID_ACCOUNT": "ADMINISTRATIVE",
    "STOP_PAYMENT": "OTHER",
}
ACCOUNT_VALIDATION_METHODS = ("MICRO_DEPOSIT", "PRENOTE", "COMMERCIAL_SERVICE", "PRIOR_HISTORY")

# network_settlement_fee constants
FEE_NUM = 5
FEE_DEN = 10000000
MIN_FEE_CENTS = 1
SAME_DAY_SURCHARGE_CENTS = 50


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_window(w):
    # SettlementWindow is an immutable record type: no updated_at, no version.
    return {
        "id": w["id"],
        "window_code": w["window_code"],
        "cutoff_time_utc": w["cutoff_time_utc"],
        "per_entry_limit_cents": w["per_entry_limit_cents"],
        "odfi_window_cap_cents": w["odfi_window_cap_cents"],
        "created_at": render_ts3(w["created_at"]),
    }


def serialize_entry(e):
    return {
        "id": e["id"],
        "originator_id": e["originator_id"],
        "originating_participant_id": e["originating_participant_id"],
        "transaction_code_id": e["transaction_code_id"],
        "settlement_window_id": e["settlement_window_id"],
        "amount_cents": e["amount_cents"],
        "receiver_account_number_hash": e["receiver_account_number_hash"],
        "receiver_name": e["receiver_name"],
        "authorization_type": e["authorization_type"],
        "same_day": e["same_day"],
        "entry_fee_cents": e["entry_fee_cents"],
        "status": e["status"],
        "settled_at": render_ts(e["settled_at"]),
        "settled_date": render_date(e["settled_date"]),
        "created_at": render_ts3(e["created_at"]),
        "updated_at": render_ts3(e["updated_at"]),
        "version": e["version"],
    }


def serialize_return(r):
    # ReturnRecord is an immutable record type: no updated_at, no version.
    return {
        "id": r["id"],
        "payment_entry_id": r["payment_entry_id"],
        "returning_participant_id": r["returning_participant_id"],
        "reason_code": r["reason_code"],
        "reason_class": r["reason_class"],
        "returned_at": render_ts(r["returned_at"]),
        "created_at": render_ts3(r["created_at"]),
    }


def serialize_account_validation(av):
    # Status is derived against the logical clock on every read.
    status = "VALID" if CLOCK.today() <= av["validated_until"] else "EXPIRED"
    return {
        "id": av["id"],
        "originator_id": av["originator_id"],
        "account_number_hash": av["account_number_hash"],
        "method": av["method"],
        "validated_until": render_date(av["validated_until"]),
        "status": status,
        "created_at": render_ts3(av["created_at"]),
    }


# ---------------------------------------------------------------------------
# Settlement windows
# ---------------------------------------------------------------------------


@bp.post("/settlement-windows")
@require_roles("PlatformAdmin")
def create_settlement_window():
    body = get_body()
    window_code = require_str(body, "window_code")
    cutoff_time_utc = require_str(body, "cutoff_time_utc")
    if parse_hhmm(cutoff_time_utc) is None:
        fail("ERR_INVALID_REQUEST", "cutoff_time_utc must be HH:MM (24h, UTC)")
    per_entry_limit_cents = require_int(body, "per_entry_limit_cents")
    odfi_window_cap_cents = require_int(body, "odfi_window_cap_cents")
    for w in DB.settlement_windows.values():
        if w["window_code"] == window_code:
            fail("ERR_DUPLICATE_RESOURCE", "window_code already in use")
    rec = add_record(
        "settlement_windows",
        {
            "window_code": window_code,
            "cutoff_time_utc": cutoff_time_utc,
            "per_entry_limit_cents": per_entry_limit_cents,
            "odfi_window_cap_cents": odfi_window_cap_cents,
        },
        common=False,
    )
    return ok(serialize_window(rec), 201)


@bp.get("/settlement-windows")
@require_roles(*ROLES)
def list_settlement_windows():
    return list_response(DB.settlement_windows.values(), serialize_window)


def auto_assign_window_id():
    """same_day=false: rank all windows by cutoff_time_utc ASC, tie-break by
    created_at ASC, and pick the first (earliest-cutoff) window."""
    windows = list(DB.settlement_windows.values())
    if not windows:
        return None
    windows.sort(key=lambda w: (w["cutoff_time_utc"], w["created_at"], w["_seq"]))
    return windows[0]["id"]


def compute_entry_fee(amount_cents, same_day):
    """network_settlement_fee: 5 cents per $100,000 of amount per entry,
    rounded HALF_UP to a whole cent PER ENTRY before any accumulation, with a
    1-cent minimum and a 50-cent same-day surcharge."""
    raw = Decimal(amount_cents * FEE_NUM) / Decimal(FEE_DEN)
    fee = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if fee < MIN_FEE_CENTS:
        fee = MIN_FEE_CENTS
    if same_day:
        fee += SAME_DAY_SURCHARGE_CENTS
    return fee


@bp.post("/settlement-windows/<window_id>/run-settlement")
@require_roles("PlatformAdmin")
def run_settlement(window_id):
    window = DB.settlement_windows.get(window_id)
    if window is None:
        fail("ERR_NOT_FOUND", "Settlement window %s not found" % window_id)
    cutoff = parse_hhmm(window["cutoff_time_utc"])
    now = CLOCK.now()
    # The run requires the logical time at or after the window's cutoff.
    if hhmm(now) < cutoff:
        fail("ERR_WINDOW_NOT_CLOSED", "Window cutoff has not been reached")

    today = CLOCK.today()
    month = period_of_date(today)
    entries = [
        e
        for e in DB.payment_entries.values()
        if e["settlement_window_id"] == window_id and e["status"] == "ORIGINATED"
    ]
    entries.sort(key=lambda e: (e["created_at"], e["_seq"]))

    settled_entry_ids = []
    for entry in entries:
        fee = compute_entry_fee(entry["amount_cents"], entry["same_day"])
        entry["status"] = "SETTLED"
        entry["settled_at"] = now
        entry["settled_date"] = today
        entry["entry_fee_cents"] = fee
        touch(entry)

        originator = DB.originators.get(entry["originator_id"])
        if originator is not None:
            # Exposure moves committed -> contingent; version advances.
            touch(originator)

        participant = DB.participants.get(entry["originating_participant_id"])
        if participant is not None:
            # Monthly reset, then accrue the per-entry fee.
            if participant["current_period"] != month:
                participant["current_period"] = month
                participant["current_period_fees_cents"] = 0
            participant["current_period_fees_cents"] += fee
            touch(participant)

        settled_entry_ids.append(entry["id"])

    return ok(
        {"settled_count": len(settled_entry_ids), "settled_entry_ids": settled_entry_ids}
    )


# ---------------------------------------------------------------------------
# Payment entries
# ---------------------------------------------------------------------------


@bp.post("/payment-entries")
@require_roles("ParticipantOfficer")
def create_payment_entry():
    body = get_body()
    # Ownership anchor: the originator referenced in the body must belong to
    # the acting officer's participant.
    originator_id = require_str(body, "originator_id")
    originator = DB.originators.get(originator_id)
    if originator is None:
        fail("ERR_NOT_FOUND", "Originator %s not found" % originator_id)
    if originator["participant_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "Originator belongs to another participant")

    transaction_code_id = require_str(body, "transaction_code_id")
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    receiver_account_number_hash = require_str(body, "receiver_account_number_hash")
    receiver_name = require_str(body, "receiver_name")
    authorization_type = require_enum(body, "authorization_type", AUTHORIZATION_TYPES)
    same_day = optional_bool(body, "same_day", False)
    settlement_window_id = None
    if same_day:
        settlement_window_id = require_str(body, "settlement_window_id")

    code = DB.transaction_codes.get(transaction_code_id)
    if code is None:
        fail("ERR_NOT_FOUND", "Transaction code %s not found" % transaction_code_id)
    window = None
    if same_day:
        window = DB.settlement_windows.get(settlement_window_id)
        if window is None:
            fail("ERR_NOT_FOUND", "Settlement window %s not found" % settlement_window_id)

    # Entry-specific gates in the section 3.5 / 2.8 sequence.
    participant = DB.participants.get(originator["participant_id"])
    if participant is None or participant["status"] != "ACTIVE":
        fail("ERR_PARTICIPANT_NOT_ACTIVE", "Originating participant is not ACTIVE")
    if originator["status"] != "APPROVED":
        fail("ERR_ORIGINATOR_NOT_APPROVED", "Originator is not APPROVED")

    if code["account_validation_required"]:
        today = CLOCK.today()
        has_valid = any(
            av["originator_id"] == originator["id"]
            and av["account_number_hash"] == receiver_account_number_hash
            and av["validated_until"] >= today
            for av in DB.account_validations.values()
        )
        if not has_valid:
            fail(
                "ERR_ACCOUNT_VALIDATION_REQUIRED",
                "No VALID account validation for (originator, account hash)",
            )

    if (
        code["authorization_requirement"] != "NONE"
        and authorization_type != code["authorization_requirement"]
    ):
        fail(
            "ERR_AUTHORIZATION_REQUIREMENT_VIOLATION",
            "authorization_type does not match the transaction code requirement",
        )

    if same_day:
        now = CLOCK.now()
        cutoff = parse_hhmm(window["cutoff_time_utc"])
        # The requested window's cutoff must be strictly later than now.
        if hhmm(now) >= cutoff:
            fail("ERR_WINDOW_CUTOFF_PASSED", "Requested window cutoff has passed")
        if amount_cents > window["per_entry_limit_cents"]:
            fail(
                "ERR_SAME_DAY_ENTRY_LIMIT_EXCEEDED",
                "amount_cents exceeds the window per-entry limit",
            )
        today = CLOCK.today()
        used = sum(
            e["amount_cents"]
            for e in DB.payment_entries.values()
            if e["originating_participant_id"] == originator["participant_id"]
            and e["settlement_window_id"] == window["id"]
            and e["status"] in ("ORIGINATED", "SETTLED")
            and e["created_at"].date() == today
        )
        if used + amount_cents > window["odfi_window_cap_cents"]:
            fail(
                "ERR_WINDOW_CAPACITY_EXCEEDED",
                "Entry would exceed the per-ODFI window cap for today",
            )

    # Exposure admission: contingent computed BEFORE adding the candidate.
    _, contingent = compute_exposures(originator["id"])
    if contingent + amount_cents > originator["exposure_limit_cents"]:
        fail(
            "ERR_EXPOSURE_LIMIT_EXCEEDED",
            "contingent exposure plus amount exceeds exposure_limit_cents",
        )

    assigned_window_id = window["id"] if same_day else auto_assign_window_id()
    rec = add_record(
        "payment_entries",
        {
            "originator_id": originator["id"],
            "originating_participant_id": originator["participant_id"],
            "transaction_code_id": code["id"],
            "settlement_window_id": assigned_window_id,
            "amount_cents": amount_cents,
            "receiver_account_number_hash": receiver_account_number_hash,
            "receiver_name": receiver_name,
            "authorization_type": authorization_type,
            "same_day": same_day,
            "entry_fee_cents": None,
            "status": "ORIGINATED",
            "settled_at": None,
            "settled_date": None,
        },
    )
    # Origination moves exposure; the originator's version advances.
    touch(originator)
    return ok(serialize_entry(rec), 201)


@bp.get("/payment-entries/<entry_id>")
@require_roles(*ROLES)
def get_payment_entry(entry_id):
    e = DB.payment_entries.get(entry_id)
    if e is None:
        fail("ERR_NOT_FOUND", "Payment entry %s not found" % entry_id)
    return ok(serialize_entry(e))


@bp.get("/payment-entries")
@require_roles(*ROLES)
def list_payment_entries():
    filters = []
    for param in (
        "originator_id",
        "originating_participant_id",
        "transaction_code_id",
        "settlement_window_id",
        "status",
    ):
        value = request.args.get(param)
        if value is not None:
            filters.append((param, value))
    return list_response(DB.payment_entries.values(), serialize_entry, filters)


@bp.post("/payment-entries/<entry_id>/cancel")
@require_roles("ParticipantOfficer")
def cancel_payment_entry(entry_id):
    e = DB.payment_entries.get(entry_id)
    if e is None:
        fail("ERR_NOT_FOUND", "Payment entry %s not found" % entry_id)
    if e["originating_participant_id"] != g.user_id:
        fail("ERR_FORBIDDEN", "Entry belongs to another participant")
    if e["status"] != "ORIGINATED":
        fail("ERR_INVALID_STATE", "Only an ORIGINATED entry can be cancelled")
    e["status"] = "CANCELLED"
    touch(e)
    originator = DB.originators.get(e["originator_id"])
    if originator is not None:
        # Compensating invariant: committed and contingent each release the
        # amount; the originator's version advances.
        touch(originator)
    return ok(serialize_entry(e))


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------


@bp.post("/payment-entries/<entry_id>/returns")
@require_roles("ParticipantOfficer")
def create_return(entry_id):
    e = DB.payment_entries.get(entry_id)
    if e is None:
        fail("ERR_NOT_FOUND", "Payment entry %s not found" % entry_id)
    body = get_body()
    reason_code = require_enum(body, "reason_code", REASON_CODES)

    returning = DB.participants.get(g.user_id)
    if returning is None or returning["status"] != "ACTIVE":
        fail("ERR_PARTICIPANT_NOT_ACTIVE", "Returning participant is not ACTIVE")
    if e["status"] != "SETTLED":
        fail("ERR_ENTRY_NOT_SETTLED", "Entry is not in SETTLED status")
    if g.user_id == e["originating_participant_id"]:
        fail(
            "ERR_RETURN_PARTICIPANT_CONFLICT",
            "Returning participant must differ from the originating participant",
        )
    code = DB.transaction_codes.get(e["transaction_code_id"])
    if (
        banking_days_between(e["settled_date"], CLOCK.today())
        > code["return_timeframe_banking_days"]
    ):
        fail("ERR_RETURN_WINDOW_EXPIRED", "Return timeframe has expired")

    rec = add_record(
        "return_records",
        {
            "payment_entry_id": e["id"],
            "returning_participant_id": g.user_id,
            "reason_code": reason_code,
            "reason_class": REASON_CLASS_BY_CODE[reason_code],
            "returned_at": CLOCK.now(),
        },
        common=False,
    )
    e["status"] = "RETURNED"
    touch(e)
    originator = DB.originators.get(e["originator_id"])
    if originator is not None:
        # The amount leaves the returnable set; contingent exposure decreases
        # and the originator's version advances.
        touch(originator)
    return ok(serialize_return(rec), 201)


@bp.get("/payment-entries/<entry_id>/returns")
@require_roles(*ROLES)
def list_entry_returns(entry_id):
    e = DB.payment_entries.get(entry_id)
    if e is None:
        fail("ERR_NOT_FOUND", "Payment entry %s not found" % entry_id)
    records = [r for r in DB.return_records.values() if r["payment_entry_id"] == entry_id]
    return list_response(records, serialize_return)


@bp.get("/participants/<participant_id>/returns")
@require_roles(*ROLES)
def list_participant_returns(participant_id):
    if participant_id not in DB.participants:
        fail("ERR_NOT_FOUND", "Participant %s not found" % participant_id)
    records = [
        r
        for r in DB.return_records.values()
        if r["returning_participant_id"] == participant_id
    ]
    return list_response(records, serialize_return)


# ---------------------------------------------------------------------------
# Account validations
# ---------------------------------------------------------------------------


@bp.post("/account-validations")
@require_roles("ParticipantOfficer")
def create_account_validation():
    body = get_body()
    originator_id = require_str(body, "originator_id")
    account_number_hash = require_str(body, "account_number_hash")
    method = require_enum(body, "method", ACCOUNT_VALIDATION_METHODS)
    if originator_id not in DB.originators:
        fail("ERR_NOT_FOUND", "Originator %s not found" % originator_id)
    rec = add_record(
        "account_validations",
        {
            "originator_id": originator_id,
            "account_number_hash": account_number_hash,
            "method": method,
            "validated_until": CLOCK.today() + timedelta(days=365),
        },
        common=False,
    )
    return ok(serialize_account_validation(rec), 201)


@bp.get("/account-validations/<validation_id>")
@require_roles(*ROLES)
def get_account_validation(validation_id):
    av = DB.account_validations.get(validation_id)
    if av is None:
        fail("ERR_NOT_FOUND", "Account validation %s not found" % validation_id)
    return ok(serialize_account_validation(av))


@bp.get("/account-validations")
@require_roles(*ROLES)
def list_account_validations():
    filters = []
    originator_id = request.args.get("originator_id")
    if originator_id is not None:
        filters.append(("originator_id", originator_id))
    return list_response(
        DB.account_validations.values(), serialize_account_validation, filters
    )
