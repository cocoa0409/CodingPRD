"""The hauling fleet (PRD 3.8, first paragraph)."""

from decimal import Decimal

from flask import Blueprint

import constants as K
import validators as v
from auth import authorize, scope_hatchery
from envelope import created, enum_filter, ok, pagination, paginate, str_filter
from serialize import dump
from store import base_record, fmt_instant, get_or_404, insert, sort_key, values

bp = Blueprint("transport", __name__)

READ_ROLES = (K.PROGRAM_ADMIN, K.HATCHERY_MANAGER, K.REGIONAL_BIOLOGIST)


@bp.post("/transport-units")
def create_transport_unit():
    user_id, role = authorize(K.PROGRAM_ADMIN, K.HATCHERY_MANAGER)
    body = v.body()
    hatchery = get_or_404("hatcheries", v.req_id(body, "hatchery_id"))
    scope_hatchery(role, user_id, hatchery["id"])

    unit_code = v.req_str(body, "unit_code")
    tank_gallons = v.req_num(body, "tank_gallons", minimum=Decimal(0), exclusive_min=True)
    max_load_lbs = v.req_num(body, "max_load_lbs", minimum=Decimal(0), exclusive_min=True)
    oxygen_lpm = v.req_num(body, "oxygen_lpm", minimum=Decimal(0), exclusive_min=True)
    certification_expires_at = v.req_instant(body, "certification_expires_at")

    record = base_record()
    record.update({
        "hatchery_id": hatchery["id"],
        "unit_code": unit_code,
        "certification_expires_at": fmt_instant(certification_expires_at),
        "current_event_id": None,
        "tank_gallons": tank_gallons,
        "max_load_lbs": max_load_lbs,
        "oxygen_lpm": oxygen_lpm,
        "status": "AVAILABLE",
    })
    insert("transport_units", record)
    return created(dump(record))


@bp.get("/transport-units/<identifier>")
def get_transport_unit(identifier):
    user_id, role = authorize(*READ_ROLES)
    unit = get_or_404("transport_units", identifier)
    scope_hatchery(role, user_id, unit["hatchery_id"])
    return ok(dump(unit))


@bp.get("/transport-units")
def list_transport_units():
    authorize(*READ_ROLES)
    hatchery_id = str_filter("hatchery_id")
    status = enum_filter("status", K.UNIT_STATUSES)
    current_event_id = str_filter("current_event_id")
    limit, offset = pagination()

    records = values("transport_units")
    if hatchery_id is not None:
        records = [r for r in records if r["hatchery_id"] == hatchery_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if current_event_id is not None:
        records = [r for r in records if r["current_event_id"] == current_event_id]
    records.sort(key=sort_key)
    return paginate(records, limit, offset, dump)
