"""Transmission path bookings: window geometry, proving tests and release."""

from datetime import timedelta

from flask import Blueprint

import domain
import store
from core import (
    ApiError,
    OPERATOR_ROLES,
    Payload,
    ROLE_PRODUCTION_MANAGER,
    ROLE_TECHNICAL_DIRECTOR,
    now_utc,
    page_result,
    query_enum,
    query_string,
    require_roles,
    respond_object,
)
from routes_production import check_occ, require_open_production

bp = Blueprint("transport", __name__, url_prefix="/broadcast-ops")


def _active_on_path(path, exclude_id=None):
    rows = []
    for booking in store.ordered(store.BOOKINGS):
        if booking["path_id"] != path["id"]:
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        if booking["status"] in domain.ACTIVE_BOOKING_STATUSES:
            rows.append(booking)
    return rows


@bp.post("/path-bookings")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_booking():
    body = Payload()
    production_id = body.string("production_id")
    path_id = body.string("path_id")
    booking_role = body.enum("booking_role", domain.BOOKING_ROLES)
    window_start = body.instant("window_start_utc")
    window_end = body.instant("window_end_utc")
    requested_mbps = body.integer("requested_mbps", minimum=1)
    expected = body.integer("expected_production_version")

    production = store.find_production(production_id)
    path = store.find_path(path_id)
    check_occ(production, expected)
    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "window_end_utc must be strictly later than window_start_utc.",
            422,
        )
    require_open_production(production)

    if booking_role == "PRIMARY" and path["redundancy_class"] != "PRIMARY_ELIGIBLE":
        raise ApiError(
            "ERR_PATH_REDUNDANCY_INVALID",
            "A BACKUP_ONLY path may only carry BACKUP bookings.",
            422,
        )

    if path["path_type"] == "SATELLITE":
        guard = timedelta(minutes=path["guard_band_minutes"])
        for other in _active_on_path(path):
            if window_start < other["window_end_utc"] + guard and (
                other["window_start_utc"] - guard < window_end
            ):
                raise ApiError(
                    "ERR_PATH_WINDOW_CONFLICT",
                    "The transponder is already occupied within its guard band.",
                    409,
                )
    elif path["path_type"] == "FIBER":
        concurrent = 0
        for other in _active_on_path(path):
            if other["window_start_utc"] < window_end and window_start < other["window_end_utc"]:
                concurrent += other["requested_mbps"]
        if concurrent + requested_mbps > path["capacity_mbps"]:
            raise ApiError(
                "ERR_PATH_CAPACITY_EXCEEDED",
                "The circuit does not have enough aggregate capacity for this window.",
                409,
            )

    booking = store.new_row(
        production_id=production["id"],
        path_id=path["id"],
        booking_role=booking_role,
        window_start_utc=window_start,
        window_end_utc=window_end,
        requested_mbps=requested_mbps,
        test_window_start_utc=None,
        test_window_end_utc=None,
        test_attempt_count=0,
        status="RESERVED",
    )
    store.BOOKINGS[booking["id"]] = booking

    if booking_role == "PRIMARY":
        for other in domain.production_bookings(production):
            if other["id"] == booking["id"] or other["booking_role"] != "PRIMARY":
                continue
            if other["status"] in domain.ACTIVE_BOOKING_STATUSES:
                store.set_fields(other, status="RELEASED")
                other_path = store.PATHS.get(other["path_id"])
                if other_path is not None:
                    domain.recompute_path_aggregates(other_path)

    domain.recompute_path_aggregates(path)
    domain.recompute_production_stage(production)
    return respond_object(domain.booking_json(booking), 201)


@bp.get("/path-bookings/<booking_id>")
@require_roles(*OPERATOR_ROLES)
def read_booking(booking_id):
    return respond_object(domain.booking_json(store.find_booking(booking_id)))


@bp.get("/path-bookings")
@require_roles(*OPERATOR_ROLES)
def list_bookings():
    production_id = query_string("production_id")
    path_id = query_string("path_id")
    status = query_enum("status", domain.BOOKING_STATUSES)
    booking_role = query_enum("booking_role", domain.BOOKING_ROLES)
    rows = store.ordered(store.BOOKINGS)
    if production_id is not None:
        rows = [r for r in rows if r["production_id"] == production_id]
    if path_id is not None:
        rows = [r for r in rows if r["path_id"] == path_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if booking_role is not None:
        rows = [r for r in rows if r["booking_role"] == booking_role]
    return page_result(rows, domain.booking_json)


@bp.post("/path-bookings/<booking_id>/schedule-test")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def schedule_test(booking_id):
    body = Payload()
    test_start = body.instant("test_window_start_utc")
    test_end = body.instant("test_window_end_utc")

    booking = store.find_booking(booking_id)
    if test_end <= test_start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "test_window_end_utc must be strictly later than test_window_start_utc.",
            422,
        )
    if booking["status"] not in ("RESERVED", "TEST_FAILED"):
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "Only a RESERVED or TEST_FAILED booking may schedule a transmission test.",
            409,
        )
    if test_start < booking["window_start_utc"] or test_end > booking["window_end_utc"]:
        raise ApiError(
            "ERR_TEST_WINDOW_INVALID",
            "The test window must lie fully inside the booking's occupation window.",
            422,
        )
    if booking["test_attempt_count"] >= domain.MAX_TEST_ATTEMPTS:
        raise ApiError(
            "ERR_TEST_ATTEMPT_LIMIT",
            "The booking has exhausted its transmission-test attempts.",
            409,
        )

    store.set_fields(
        booking,
        test_window_start_utc=test_start,
        test_window_end_utc=test_end,
        status="TEST_SCHEDULED",
    )
    return respond_object(domain.booking_json(booking))


@bp.post("/path-bookings/<booking_id>/test-result")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def record_test_result(booking_id):
    body = Payload()
    outcome = body.enum("outcome", ("PASS", "FAIL"))
    body.string("notes", required=False, allow_blank=True)

    booking = store.find_booking(booking_id)
    if booking["status"] != "TEST_SCHEDULED":
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "Only a TEST_SCHEDULED booking may record a transmission-test result.",
            409,
        )
    now = now_utc()
    start = booking["test_window_start_utc"]
    end = booking["test_window_end_utc"]
    if start is None or end is None or now < start or now >= end:
        raise ApiError(
            "ERR_TEST_WINDOW_INVALID",
            "The result must be recorded while the clock lies inside the booked test window.",
            422,
        )

    store.set_fields(
        booking,
        test_attempt_count=booking["test_attempt_count"] + 1,
        status="CONFIRMED" if outcome == "PASS" else "TEST_FAILED",
    )
    path = store.PATHS.get(booking["path_id"])
    if path is not None:
        domain.recompute_path_aggregates(path)
    production = store.PRODUCTIONS.get(booking["production_id"])
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.booking_json(booking))


@bp.post("/path-bookings/<booking_id>/release")
@require_roles(ROLE_PRODUCTION_MANAGER)
def release_booking(booking_id):
    booking = store.find_booking(booking_id)
    if booking["status"] not in ("RESERVED", "TEST_SCHEDULED", "TEST_FAILED", "CONFIRMED"):
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "The booking is not in a status that can be handed back to the carrier.",
            409,
        )
    store.set_fields(booking, status="RELEASED")
    path = store.PATHS.get(booking["path_id"])
    if path is not None:
        domain.recompute_path_aggregates(path)
    production = store.PRODUCTIONS.get(booking["production_id"])
    if production is not None:
        domain.recompute_production_stage(production)
    return respond_object(domain.booking_json(booking))
