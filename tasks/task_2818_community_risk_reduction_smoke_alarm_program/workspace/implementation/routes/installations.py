"""Alarm installations: reservation, verification and voiding (PRD 3.6)."""

from flask import Blueprint, g

import db
import domain
import response
import util
import validation
from db import store, touch
from errors import ApiError
from middleware import endpoint
from services import installations as installation_service
from services import visits as visit_service

bp = Blueprint("installations", __name__)

READ_ROLES = ("ProgramAdmin", "GrantOfficer", "CrrTechnician")


def load_installation(installation_id):
    installation = store.installations.get(installation_id)
    if installation is None:
        raise ApiError("ERR_INSTALLATION_NOT_FOUND")
    return installation


@bp.post("/crr/installations")
@endpoint("CrrTechnician")
def create_installation():
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    visit_id = validation.req_str(body, "visit_id")
    device_type = validation.req_enum(body, "device_type", domain.DEVICE_TYPES)
    placement_location = validation.req_enum(
        body, "placement_location", domain.PLACEMENT_LOCATIONS
    )
    storey = validation.req_int(body, "storey", minimum=1)
    device_lot_id = validation.opt_str(body, "device_lot_id", non_empty=True)
    serial_number = validation.opt_str(body, "serial_number")

    visit = store.visits.get(visit_id)
    if visit is None:
        raise ApiError("ERR_VISIT_NOT_FOUND")
    named_lot = None
    if device_lot_id is not None:
        named_lot = store.device_lots.get(device_lot_id)
        if named_lot is None:
            raise ApiError("ERR_LOT_NOT_FOUND")

    household = store.households.get(visit["household_id"])
    if household is not None and storey > household["storeys"]:
        validation.bad("Field storey must not exceed the household's storeys.")

    route = visit_service.route_of(visit)
    if route is None or route["crew_id"] != g.user_id:
        raise ApiError("ERR_CREW_NOT_ASSIGNED")
    crew = store.crews.get(g.user_id)

    # Ladder step 9 - the visit must be surveyed and physically visitable.
    if (
        visit["cancelled_at"] is not None
        or visit["install_status"] != "SURVEYED"
        or visit["appointment_option"] == "VIRTUAL_ASSESSMENT"
    ):
        raise ApiError("ERR_INVALID_VISIT_STATE")

    # Ladder step 10 - the funding grant of an explicitly named lot must be ACTIVE.
    named_grant = None
    if named_lot is not None:
        named_grant = installation_service.grant_of_lot(named_lot)
        if named_grant is None or named_grant["status"] != "ACTIVE":
            raise ApiError("ERR_GRANT_NOT_ACTIVE")

    # Ladder steps 11 to 13 - the life-safety allow-table, in order.
    if placement_location in domain.FORBIDDEN_LOCATIONS:
        raise ApiError("ERR_PLACEMENT_LOCATION_FORBIDDEN")
    if placement_location not in domain.PLACEMENT_ALLOW_TABLE[device_type]:
        raise ApiError("ERR_PLACEMENT_TYPE_LOCATION_MISMATCH")
    if device_type == "STROBE_HOH":
        if crew is None or crew["certification_level"] != "ADVANCED":
            raise ApiError("ERR_CREW_NOT_CERTIFIED")

    # Ladder step 19 - the clock's date must lie inside the grant's period.
    today = util.clock.today()
    if named_grant is not None:
        if (
            today < named_grant["period_start_date"]
            or today > named_grant["period_end_date"]
        ):
            raise ApiError("ERR_OUTSIDE_GRANT_PERIOD")

    # Ladder step 22 - at most one non-voided placement per combination.
    for existing in installation_service.installations_of_visit(visit_id):
        if existing["status"] == "VOIDED":
            continue
        if (
            existing["device_type"] == device_type
            and existing["placement_location"] == placement_location
            and existing["storey"] == storey
        ):
            raise ApiError("ERR_DUPLICATE_PLACEMENT")

    # Ladder step 29 - the resolved lot's family must equal the requested one.
    if named_lot is not None and named_lot["device_type"] != device_type:
        raise ApiError("ERR_LOT_TYPE_MISMATCH")

    lot = named_lot
    if lot is not None:
        # Ladder steps 32 and 33 - stock, then funds.
        if lot["on_hand_qty"] - lot["reserved_qty"] < 1:
            raise ApiError("ERR_INSUFFICIENT_DEVICE_STOCK")
        if named_grant["available_cents"] < lot["unit_cost_cents"]:
            raise ApiError("ERR_GRANT_FUNDS_EXHAUSTED")
    else:
        # Ladder step 35 - the waterfall needs a non-empty candidate set.
        lot = installation_service.select_lot(device_type)
        if lot is None:
            raise ApiError("ERR_NO_ELIGIBLE_DEVICE_LOT")

    installation = installation_service.reserve(
        visit, lot, device_type, placement_location, storey, serial_number, g.user_id
    )
    return response.ok_row(installation, 201)


@bp.get("/crr/installations")
@endpoint(*READ_ROLES)
def list_installations():
    limit, offset = validation.pagination()
    rows = db.by_created_at(list(store.installations.values()))
    for name in (
        "visit_id",
        "device_lot_id",
        "installed_by_crew_id",
        "verified_by_crew_id",
        "device_type",
        "status",
    ):
        wanted = validation.filter_value(name)
        if wanted is not None:
            rows = [r for r in rows if r[name] == wanted]
    page, total = validation.paginate(rows, limit, offset)
    return response.ok_list(page, limit, offset, total)


@bp.get("/crr/installations/<installation_id>")
@endpoint(*READ_ROLES)
def get_installation(installation_id):
    return response.ok_row(load_installation(installation_id))


@bp.post("/crr/installations/<installation_id>/verify")
@endpoint("CrrTechnician")
def verify_installation(installation_id):
    installation = load_installation(installation_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)

    # Ladder step 7 - a crew may not verify its own work (PRD 2.1).
    crew = store.crews.get(g.user_id)
    if g.user_id == installation["installed_by_crew_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if crew is None or crew["status"] != "ACTIVE":
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if installation["status"] != "INSTALLED":
        raise ApiError("ERR_INSTALLATION_NOT_VOIDABLE")

    installation["status"] = "VERIFIED"
    installation["verified_by_crew_id"] = g.user_id
    installation["verified_at"] = util.clock.now()
    touch(installation)
    # PRD 3.6: no unit and no money move on verification.
    return response.ok_row(installation)


@bp.post("/crr/installations/<installation_id>/void")
@endpoint("CrrTechnician", "GrantOfficer")
def void_installation(installation_id):
    installation = load_installation(installation_id)
    body = validation.json_body()
    validation.reject_unexpected_version(body)
    voided_reason = validation.req_enum(body, "voided_reason", domain.VOID_REASONS)

    if installation["status"] not in ("RESERVED", "INSTALLED"):
        raise ApiError("ERR_INSTALLATION_NOT_VOIDABLE")

    # Ladder step 35 - an accepted report freezes the reimbursable amount.
    if installation["status"] == "INSTALLED" and installation["installed_at"] is not None:
        lot = store.device_lots.get(installation["device_lot_id"])
        grant_id = lot["funding_grant_id"] if lot is not None else None
        installed_date = installation["installed_at"].date()
        for report in store.grant_reports.values():
            if report["grant_id"] != grant_id or report["status"] != "ACCEPTED":
                continue
            if (
                report["period_start_date"] <= installed_date
                and installed_date <= report["period_end_date"]
            ):
                raise ApiError("ERR_INSTALLATION_ALREADY_REPORTED")

    installation_service.void(installation, voided_reason)
    return response.ok_row(installation)
