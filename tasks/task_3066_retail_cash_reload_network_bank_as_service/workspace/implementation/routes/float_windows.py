"""Float window endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core

bp = Blueprint("float_windows", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
    "RetailerClerk",
)
LIST_ROLES = ("PlatformAdmin", "ProgramManager", "SettlementOperator", "RetailerClerk")


@bp.post("/v1/float-windows")
def create_float_window():
    user_id, role = middleware.authenticate(("SettlementOperator", "ProgramManager"))
    data = rh.body()
    location_id = rh.require_str(data, "reload_location_id")
    start = rh.require_datetime(data, "window_start_at")
    end = rh.require_datetime(data, "window_end_at")
    carrier = rh.require_str(data, "armored_carrier")
    amount = rh.require_int(data, "float_amount_cents")
    buffer_minutes = rh.optional_int(data, "buffer_minutes", 120)

    location = core.ref_location(location_id)
    agreement = core.agreement_of_location(location)
    program = core.get_program(agreement["program_id"])

    if role == "ProgramManager" and agreement["program_id"] != user_id:
        raise errors.unauthorized("The acting program manager does not own this location.")
    core.guard_not_frozen(program)
    if location["location_status"] != "OPEN":
        raise errors.location_not_open(
            "The reload location is %s, not OPEN." % location["location_status"]
        )
    if amount < 1:
        raise errors.invalid_request("float_amount_cents must be at least 1.")
    if end < start:
        raise errors.invalid_request("window_start_at must not be after window_end_at.")

    buffer = timedelta(minutes=buffer_minutes)
    buffered_start = start - buffer
    buffered_end = end + buffer
    for window in db.float_windows.values():
        if window["reload_location_id"] != location["id"]:
            continue
        if window["window_status"] == "CANCELLED":
            continue
        # PRD 3.8: the candidate's interval is extended by its buffer on both
        # sides and compared against the stored window as given; the stored
        # window is not inflated by its own buffer.
        if _intervals_overlap(
            buffered_start, buffered_end, window["window_start_at"], window["window_end_at"]
        ):
            raise errors.float_window_overlap(
                "The window, including its buffer, overlaps another window of this location."
            )

    if int(agreement["float_position_cents"]) + amount > calc.FLOAT_CAP_CENTS:
        raise errors.float_cap_exceeded(
            "The float position would exceed the float cap."
        )

    row = core.common_fields()
    row.update(
        {
            "reload_location_id": location["id"],
            "window_start_at": start,
            "window_end_at": end,
            "armored_carrier": carrier,
            "float_amount_cents": amount,
            "buffer_minutes": buffer_minutes,
            "window_status": "REQUESTED",
        }
    )
    db.register(db.float_windows, row)
    return response.ok(core.public(core.FLOAT_WINDOW, row), 201)


def _intervals_overlap(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


@bp.get("/v1/float-windows/<window_id>")
def get_float_window(window_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.FLOAT_WINDOW, core.get_float_window(window_id)))


@bp.get("/v1/float-windows")
def list_float_windows():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.float_windows,
        reload_location_id=request.args.get("reload_location_id"),
        window_status=request.args.get("window_status"),
    )
    total = len(rows)
    return response.array(
        core.public_list(core.FLOAT_WINDOW, rows[offset : offset + limit]), limit, offset, total
    )


@bp.post("/v1/float-windows/<window_id>/confirm")
def confirm_float_window(window_id):
    middleware.authenticate(("SettlementOperator",))
    window = core.get_float_window(window_id)
    rh.body()
    if window["window_status"] != "REQUESTED":
        raise errors.invalid_state(
            "A window in status %s cannot be confirmed." % window["window_status"]
        )
    window["window_status"] = "CONFIRMED"
    core.touch(window)
    return response.ok(core.public(core.FLOAT_WINDOW, window))


@bp.post("/v1/float-windows/<window_id>/cancel")
def cancel_float_window(window_id):
    middleware.authenticate(("SettlementOperator",))
    window = core.get_float_window(window_id)
    rh.body()
    if window["window_status"] not in ("REQUESTED", "CONFIRMED"):
        raise errors.invalid_state(
            "A window in status %s cannot be cancelled." % window["window_status"]
        )
    window["window_status"] = "CANCELLED"
    core.touch(window)
    return response.ok(core.public(core.FLOAT_WINDOW, window))


@bp.post("/v1/float-windows/<window_id>/complete")
def complete_float_window(window_id):
    middleware.authenticate(("SettlementOperator",))
    window = core.get_float_window(window_id)
    rh.body()
    if window["window_status"] != "CONFIRMED":
        raise errors.invalid_state(
            "A window in status %s cannot be completed." % window["window_status"]
        )
    location = core.get_location(window["reload_location_id"])
    agreement = core.agreement_of_location(location)
    if (
        int(agreement["float_position_cents"]) + int(window["float_amount_cents"])
        > calc.FLOAT_CAP_CENTS
    ):
        raise errors.float_cap_exceeded("The float position would exceed the float cap.")
    window["window_status"] = "COMPLETED"
    core.touch(window)
    agreement["float_position_cents"] = int(agreement["float_position_cents"]) + int(
        window["float_amount_cents"]
    )
    core.touch(agreement)
    return response.ok(core.public(core.FLOAT_WINDOW, window))