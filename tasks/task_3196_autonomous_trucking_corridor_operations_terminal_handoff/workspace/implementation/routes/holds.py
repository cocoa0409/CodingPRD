"""Multi-day holds and coverage dates — PRD §3.10, endpoints 124-129.

The hold is a half-open interval [hold_start_epoch_day, hold_end_epoch_day).
The `coverage_date` is system-filled from the chain's start date and the local
consecutive-run count; `sequence_in_chain` is the one-based position the hold
occupies inside its chain in `created_at` order.
"""

from datetime import timedelta

import db
import core
import services
from core import ApiError, now_iso, parse_iso, to_iso
from response import ok, page_of
from http_util import pagination, must_get, body, coerce_int, arg
from routes._common import route
from models import create

HOLD_TYPES = ("WINDOW_BLOCK", "MAINTENANCE", "REGULATORY_INSPECTION")


def register(app):

    @route(app, "/api/multi-day-holds", ["POST"], ["BookingClerk"])
    def create_hold():
        raw = body()
        allowed = {"hold_start_epoch_day", "hold_end_epoch_day", "single_day_hold",
                   "hold_type", "coverage_date"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in ("hold_start_epoch_day", "hold_end_epoch_day", "single_day_hold",
                    "hold_type"):
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        if raw["hold_type"] not in HOLD_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown hold_type.")
        start = coerce_int(raw["hold_start_epoch_day"])
        end = coerce_int(raw["hold_end_epoch_day"])
        single_day = bool(raw["single_day_hold"])
        coverage = raw.get("coverage_date")
        blank_coverage = coverage is None or str(coverage).strip() == ""

        # Priority 24 — a chain day requested without a coverage date, where the
        # request does not carry every day of the chain.
        if blank_coverage and (end - start) > 1:
            raise ApiError("ERR_COVERAGE_DATE_REQUIRED",
                           "A chain day without a coverage date must be booked day by day.")
        # Priority 25 — a multi-day request against a single_day_hold row.
        if single_day and (end - start) > 1:
            raise ApiError("ERR_MULTI_DAY_NOT_ALLOWED",
                           "A single-day hold must be booked one day at a time.")
        # Priority 26 — the window must run forward.
        if not end > start:
            raise ApiError("ERR_HOLD_WINDOW_INVERTED",
                           "hold_end_epoch_day must be strictly after hold_start_epoch_day.")

        sequence = _next_sequence(raw["hold_type"])
        if blank_coverage:
            coverage_iso = _derived_coverage(start, sequence)
        else:
            coverage_iso = to_iso(parse_iso(str(coverage)))
            if coverage_iso is None:
                raise ApiError("ERR_INVALID_REQUEST",
                               "coverage_date must be an ISO 8601 UTC datetime.")

        row = create("MultiDayHold", {
            "coverage_date": coverage_iso,
            "hold_start_epoch_day": start,
            "hold_end_epoch_day": end,
            "single_day_hold": single_day,
            "hold_type": raw["hold_type"],
        })
        row["hold_status"] = "REQUESTED"
        row["sequence_in_chain"] = sequence
        return ok(row, 201)

    @route(app, "/api/multi-day-holds", ["GET"], ["Any"])
    def list_holds():
        limit, offset = pagination()
        rows = db.all_rows("multi_day_holds")
        seq = arg("sequence_in_chain")
        if seq is not None:
            rows = [h for h in rows if str(h.get("sequence_in_chain")) == str(seq)]
        status = arg("hold_status")
        if status:
            rows = [h for h in rows if h.get("hold_status") == status]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/multi-day-holds/<rid>", ["GET"], ["Any"])
    def get_hold(rid):
        return ok(must_get("MultiDayHold", rid))

    @route(app, "/api/multi-day-holds/bulk-insert", ["POST"], ["BookingClerk"])
    def bulk_insert():
        raw = body()
        for key in raw:
            if key != "hold_ids":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        hold_ids = raw.get("hold_ids")
        if not isinstance(hold_ids, list) or not hold_ids:
            raise ApiError("ERR_INVALID_REQUEST", "hold_ids must be a non-empty array.")
        rows = []
        for hid in hold_ids:
            row = db.get("multi_day_holds", hid)
            if row is None:
                raise ApiError("ERR_REFERENCE_NOT_FOUND")
            rows.append(row)
        for row in rows:
            if row.get("hold_status") == "REQUESTED":
                services.mark(row, "hold_status", "INSERTED")
                services.flush(row)
        _renumber_rows(rows)
        return page_of(rows, max(len(rows), 1), 0)

    @route(app, "/api/multi-day-holds/<rid>/remove", ["POST"], ["BookingClerk"])
    def remove_hold(rid):
        row = must_get("MultiDayHold", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if row.get("hold_status") in ("REMOVED", "DECLINED"):
            raise ApiError("ERR_INVALID_STATE", "The hold is already terminal.")
        services.mark(row, "hold_status", "REMOVED")
        services.flush(row)
        _renumber(row.get("hold_type"))
        _carry_coverage_forward(row)
        return ok(row)

    @route(app, "/api/multi-day-holds/<rid>/decline", ["POST"], ["BookingClerk"])
    def decline_hold(rid):
        row = must_get("MultiDayHold", rid)
        raw = body()
        for key in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' is not declared for this endpoint." % key)
        if row.get("hold_status") in ("REMOVED", "DECLINED"):
            raise ApiError("ERR_INVALID_STATE", "The hold is already terminal.")
        services.mark(row, "hold_status", "DECLINED")
        services.flush(row)
        return ok(row)


def _chain_rows(hold_type):
    """The holds sharing one chain, in created_at order."""
    return db.sort_created(db.by("multi_day_holds", "hold_type", hold_type))


def _next_sequence(hold_type):
    return len(_chain_rows(hold_type)) + 1


def _renumber(hold_type):
    """§3.10: sequence_in_chain recomputes across the whole chain."""
    for index, row in enumerate(_chain_rows(hold_type), start=1):
        services.mark(row, "sequence_in_chain", index)
        services.flush(row)


def _renumber_rows(rows):
    types = {r.get("hold_type") for r in rows}
    for hold_type in types:
        _renumber(hold_type)


def _derived_coverage(hold_start_epoch_day, sequence):
    """The coverage date fills from the chain's start date and the local
    consecutive-run count."""
    epoch_start = core.active_epoch_start()
    base = parse_iso(epoch_start) if epoch_start else core.now()
    chain_start = base + timedelta(days=int(hold_start_epoch_day))
    return core.midnight_iso(to_iso(chain_start + timedelta(days=sequence - 1)))


def _carry_coverage_forward(removed):
    """§3.10: removing a hold carries the coverage_date forward to the next chain
    day."""
    position = int(removed.get("sequence_in_chain") or 0)
    for row in _chain_rows(removed.get("hold_type")):
        if int(row.get("sequence_in_chain") or 0) <= position:
            continue
        current = parse_iso(row.get("coverage_date"))
        if current is None:
            continue
        services.mark(row, "coverage_date", to_iso(current - timedelta(days=1)))
        services.flush(row)