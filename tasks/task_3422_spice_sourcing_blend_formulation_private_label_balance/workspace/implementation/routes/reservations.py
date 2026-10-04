"""CapacityReservation routes (PRD 3.8): a reservation consumes
reserved_kg_per_week from EVERY ISO week its half-open window intersects,
all-or-nothing (ERR_RESERVATION_OVER_COMMIT)."""
from decimal import Decimal

from flask import Blueprint, request

from errors import ApiError
from helpers import (F, new_entity, not_found, paged, pub, require_roles,
                     respond, validate_body, validation_error)
from services.capacity import free_kg, weeks_intersecting
from state import DB

bp = Blueprint("reservations", __name__)


@bp.post("/spice/reservations")
@require_roles("ProductionScheduler")
def create_reservation():
    data = validate_body({
        "line_id": F("str", required=True),
        "agreement_id": F("str", nullable=True, default=None),
        "window_start": F("dt", required=True),
        "window_end": F("dt", required=True),
        "reserved_kg_per_week": F("int", required=True),
    })
    if not data["window_end"] > data["window_start"]:
        validation_error("window_end must be strictly after window_start")
    if data["reserved_kg_per_week"] <= 0:
        validation_error("reserved_kg_per_week must be > 0")
    line = DB.production_lines.get(data["line_id"])
    if line is None:
        not_found("production line not found")
    if data["agreement_id"] is not None and data["agreement_id"] not in DB.agreements:
        not_found("agreement not found")
    for monday in weeks_intersecting(data["window_start"], data["window_end"]):
        if free_kg(line, monday) - Decimal(data["reserved_kg_per_week"]) < 0:
            raise ApiError("ERR_RESERVATION_OVER_COMMIT", 409,
                           "Reservation would drive an intersected week's pool negative")
    reservation = new_entity(data)
    DB.reservations[reservation["id"]] = reservation
    return respond(pub(reservation), 201)


@bp.get("/spice/reservations/<reservation_id>")
@require_roles("ProductionScheduler", "SupplyPlanner")
def get_reservation(reservation_id):
    reservation = DB.reservations.get(reservation_id)
    if reservation is None:
        not_found("reservation not found")
    return respond(pub(reservation))


@bp.get("/spice/reservations")
@require_roles("ProductionScheduler", "SupplyPlanner")
def list_reservations():
    line_id = request.args.get("line_id")
    agreement_id = request.args.get("agreement_id")
    items = []
    for r in DB.reservations.values():
        if line_id is not None and r["line_id"] != line_id:
            continue
        if agreement_id is not None and r["agreement_id"] != agreement_id:
            continue
        items.append(r)
    data, meta = paged(items)
    return respond(data, page=meta)
