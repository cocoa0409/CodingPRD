"""Routes: directory-number reservations and commit."""

from flask import Blueprint, request

import clock
import errors
import lookups
import middleware
import models
import response
import storage

bp = Blueprint("reservations", __name__, url_prefix="/portability")

DEFAULT_HOLD_DAYS = 45


def _window_overlaps(pool_code, new_start, new_until):
    """Half-open interval overlap against HELD holds that began strictly earlier."""
    for existing in storage.db.all("number_reservations"):
        if existing["reservation_state"] != "HELD":
            continue
        if existing["pool_code"] != pool_code:
            continue
        start = clock.parse_instant(existing["reserved_at"])
        until = clock.parse_instant(existing["reserved_until"])
        if start is None or until is None:
            continue
        if start >= new_start:
            # A hold that begins at the same instant or later does not conflict.
            continue
        if until > new_start:
            return True
    return False


@bp.post("/number-reservations")
@middleware.require_roles("PlatformAdmin", "CustomerService")
def create_reservation(caller):
    data = middleware.body()
    account_id = middleware.required_str(data, "account_id")
    lookups.account(account_id)

    mdn = middleware.required_str(data, "mdn")
    pool_code = middleware.required_str(data, "pool_code")

    reserved_at = middleware.optional_instant(data, "reserved_at")
    if reserved_at is None:
        errors.fail("ERR_INVALID_REQUEST", "Field 'reserved_at' is required.")

    hold_days = middleware.optional_int(data, "hold_days", DEFAULT_HOLD_DAYS)
    reserved_until = middleware.optional_instant(data, "reserved_until")
    if reserved_until is None:
        reserved_until = clock.add_days(reserved_at, hold_days)

    if _window_overlaps(pool_code, reserved_at, reserved_until):
        errors.fail("ERR_RESERVATION_WINDOW_OVERLAP",
                    "The requested hold interval overlaps a HELD reservation on the pool.")

    record = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "account_id": account_id,
        "mdn": mdn,
        "pool_code": pool_code,
        "reservation_state": "HELD",
        "reserved_at": clock.fmt(reserved_at),
        "reserved_until": clock.fmt(reserved_until),
        "hold_days": hold_days,
        "committed_line_id": None,
    }
    storage.db.add("number_reservations", record)
    models.recompute_account_counters(account_id)
    return response.ok(models.reservation_out(record), 201)


@bp.get("/accounts/<account_id>/number-reservations")
@middleware.require_roles("PlatformAdmin", "CustomerService", "CreditAnalyst")
def list_account_reservations(caller, account_id):
    lookups.account(account_id)
    rows = [
        r for r in storage.db.all("number_reservations") if r["account_id"] == account_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.reservation_out(r) for r in page], limit, offset, total)


@bp.post("/number-reservations/<reservation_id>/commit")
@middleware.require_roles("PlatformAdmin")
def commit_reservation(caller, reservation_id):
    data = middleware.body()
    record = lookups.reservation(reservation_id)

    line_id = middleware.required_str(data, "subscriber_line_id")
    line = lookups.line(line_id)

    # A hold that the clock has already carried past its exclusive upper bound is
    # reported as ERR_RESERVATION_WINDOW_CLOSED (409) rather than the generic state
    # gate, so the closed window is not masked by the HELD-state check. Both the
    # HELD state and the open-window precondition are checked, in that order.
    until = clock.parse_instant(record["reserved_until"])
    if until is not None and not clock.now() < until:
        errors.fail("ERR_RESERVATION_WINDOW_CLOSED",
                    "The hold interval has closed; the reservation can no longer be committed.")

    if record["reservation_state"] != "HELD":
        errors.fail("ERR_INVALID_STATE", "Only a HELD reservation can be committed.")

    if line["number_status"] != "UNASSIGNED":
        errors.fail("ERR_INVALID_STATE",
                    "The named line's number_status is not UNASSIGNED.")

    record["committed_line_id"] = line_id
    record["reservation_state"] = "COMMITTED"
    models.touch(record)

    line["number_status"] = "ASSIGNED"
    line["mdn"] = record["mdn"]
    line["service_status"] = "ACTIVE"
    if line["line_opened_at"] is None:
        line["line_opened_at"] = clock.fmt_now()
    models.recompute_line_tenure(line)
    models.touch(line)

    models.recompute_account_counters(record["account_id"])
    models.recompute_account_counters(line["account_id"])
    return response.ok(models.reservation_out(record))