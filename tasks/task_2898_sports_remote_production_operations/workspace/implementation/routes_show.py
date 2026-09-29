"""Show executions: the two independent state dimensions, and the incident log."""

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
    require_roles,
    respond_object,
    whole_minutes,
)

bp = Blueprint("show", __name__, url_prefix="/broadcast-ops")


def show_state_invalid():
    return ApiError(
        "ERR_SHOW_STATE_INVALID",
        "The show execution's air dimension does not permit this operation.",
        409,
    )


def drive_off_air(show):
    off_air = now_utc()
    store.set_fields(
        show,
        air_status="OFF_AIR",
        off_air_at_utc=off_air,
        air_minutes_total=(
            whole_minutes(show["on_air_at_utc"], off_air)
            if show["on_air_at_utc"] is not None
            else 0
        ),
    )


@bp.post("/show-executions")
@require_roles(ROLE_PRODUCTION_MANAGER)
def create_show():
    body = Payload()
    production_id = body.string("production_id")
    production = store.find_production(production_id)
    if production["status"] not in ("PROVISIONED", "REHEARSED"):
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "A show record may only be opened for a PROVISIONED or REHEARSED production.",
            409,
        )
    show = store.new_row(
        production_id=production["id"],
        air_status="PRE_SHOW",
        signal_status="NOMINAL",
        readiness_hold=False,
        weather_hold_minutes=0,
        extended_play_minutes=0,
        technical_downtime_minutes=0,
        on_air_at_utc=None,
        off_air_at_utc=None,
        air_minutes_total=0,
    )
    store.SHOWS[show["id"]] = show
    return respond_object(domain.show_json(show), 201)


@bp.get("/show-executions/<show_id>")
@require_roles(*OPERATOR_ROLES)
def read_show(show_id):
    return respond_object(domain.show_json(store.find_show(show_id)))


@bp.get("/productions/<production_id>/show-executions")
@require_roles(*OPERATOR_ROLES)
def list_production_shows(production_id):
    production = store.find_production(production_id)
    air_status = query_enum("air_status", domain.AIR_STATUSES)
    rows = domain.production_shows(production)
    if air_status is not None:
        rows = [r for r in rows if r["air_status"] == air_status]
    return page_result(rows, domain.show_json)


@bp.post("/show-executions/<show_id>/air-status")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def drive_air_status(show_id):
    body = Payload()
    target = body.enum("target_air_status", domain.AIR_STATUSES)

    show = store.find_show(show_id)
    production = store.PRODUCTIONS.get(show["production_id"])
    current = show["air_status"]
    launching = target == "ON_AIR" and current == "PRE_SHOW"

    # Rung 19 applies to the launch only; a resume out of IN_EXTENDED_PLAY happens while the
    # production already stands at ON_AIR and is guarded by the show's own dimension alone.
    if launching and (production is None or production["status"] not in ("PROVISIONED", "REHEARSED")):
        raise ApiError(
            "ERR_PRODUCTION_STATE_INVALID",
            "Going on air requires a PROVISIONED or REHEARSED production.",
            409,
        )

    # Rung 27: the show's own air dimension.
    if target == "ON_AIR":
        if current not in ("PRE_SHOW", "IN_EXTENDED_PLAY"):
            raise show_state_invalid()
    elif target == "IN_EXTENDED_PLAY":
        if current != "ON_AIR" or show["extended_play_minutes"] < 1:
            raise show_state_invalid()
    elif target == "OFF_AIR":
        if current not in ("ON_AIR", "IN_EXTENDED_PLAY"):
            raise show_state_invalid()
    else:
        raise show_state_invalid()

    if launching:
        # Rung 39, then rung 45.
        if (
            show["readiness_hold"]
            or production["status"] != "REHEARSED"
            or production["readiness_score_certified"] != 100
        ):
            raise ApiError(
                "ERR_READINESS_NOT_CERTIFIED",
                "The show is not certified for air.",
                422,
            )
        if now_utc() >= production["venue_curfew_utc"]:
            raise ApiError(
                "ERR_VENUE_CURFEW_EXCEEDED",
                "The venue curfew has already been reached.",
                422,
            )

    if target == "ON_AIR":
        if launching:
            store.set_fields(show, air_status="ON_AIR", on_air_at_utc=now_utc())
            store.set_fields(production, status="ON_AIR")
        else:
            store.set_fields(show, air_status="ON_AIR")
    elif target == "IN_EXTENDED_PLAY":
        store.set_fields(show, air_status="IN_EXTENDED_PLAY")
    else:
        drive_off_air(show)
    return respond_object(domain.show_json(show))


@bp.post("/show-executions/<show_id>/incidents")
@require_roles(ROLE_TECHNICAL_DIRECTOR)
def create_incident(show_id):
    body = Payload()
    kind = body.enum("kind", domain.INCIDENT_KINDS)
    started_at = body.instant("started_at_utc")
    duration = body.integer("duration_minutes", minimum=1)
    severity = body.enum("severity", domain.SEVERITIES)
    note = body.string("note", required=False, allow_blank=True)

    show = store.find_show(show_id)
    production = store.PRODUCTIONS.get(show["production_id"])

    if kind == "WEATHER_HOLD":
        allowed = ("PRE_SHOW", "ON_AIR", "IN_EXTENDED_PLAY")
    else:
        allowed = ("ON_AIR", "IN_EXTENDED_PLAY")
    if show["air_status"] not in allowed:
        raise show_state_invalid()

    if kind == "EXTENDED_PLAY" and production is not None:
        projected = production["scheduled_end_utc"] + timedelta(
            minutes=show["extended_play_minutes"] + duration
        )
        if projected > production["venue_curfew_utc"]:
            raise ApiError(
                "ERR_VENUE_CURFEW_EXCEEDED",
                "Extending play by that long would run past the venue curfew.",
                422,
            )

    incident = store.new_row(
        versioned=False,
        show_execution_id=show["id"],
        kind=kind,
        started_at_utc=started_at,
        duration_minutes=duration,
        severity=severity,
        note=note,
    )
    store.INCIDENTS[incident["id"]] = incident

    if kind == "WEATHER_HOLD":
        store.set_fields(
            show, weather_hold_minutes=show["weather_hold_minutes"] + duration
        )
    elif kind == "EXTENDED_PLAY":
        store.set_fields(
            show, extended_play_minutes=show["extended_play_minutes"] + duration
        )
    else:
        store.set_fields(
            show, technical_downtime_minutes=show["technical_downtime_minutes"] + duration
        )
        if (
            show["technical_downtime_minutes"] >= domain.MAX_TECHNICAL_DOWNTIME_MINUTES
            and show["air_status"] in ("ON_AIR", "IN_EXTENDED_PLAY")
        ):
            drive_off_air(show)

    if kind == "PATH_LOSS" and production is not None:
        apply_path_loss(show, production)

    return respond_object(domain.incident_json(incident), 201)


def apply_path_loss(show, production):
    """Fail the transport of record over, then either promote a standby or lose the signal."""
    bookings = domain.production_bookings(production)

    failed_over = None
    for booking in bookings:
        if booking["booking_role"] == "PRIMARY" and booking["status"] == "CONFIRMED":
            failed_over = booking
            break
    if failed_over is None:
        for booking in bookings:
            if booking["status"] == "PROMOTED":
                failed_over = booking
                break
    if failed_over is not None:
        store.set_fields(failed_over, status="FAILED_OVER")
        path = store.PATHS.get(failed_over["path_id"])
        if path is not None:
            domain.recompute_path_aggregates(path)

    standby = None
    for booking in bookings:
        if booking["booking_role"] == "BACKUP" and booking["status"] == "CONFIRMED":
            standby = booking
            break

    if standby is not None:
        store.set_fields(standby, status="PROMOTED")
        standby_path = store.PATHS.get(standby["path_id"])
        if standby_path is not None:
            domain.recompute_path_aggregates(standby_path)
        store.set_fields(show, signal_status="ON_BACKUP")
    else:
        store.set_fields(show, signal_status="LOST")
        if show["air_status"] != "OFF_AIR":
            drive_off_air(show)


@bp.get("/show-executions/<show_id>/incidents")
@require_roles(*OPERATOR_ROLES)
def list_incidents(show_id):
    show = store.find_show(show_id)
    kind = query_enum("kind", domain.INCIDENT_KINDS)
    rows = [r for r in store.ordered(store.INCIDENTS) if r["show_execution_id"] == show["id"]]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return page_result(rows, domain.incident_json)
