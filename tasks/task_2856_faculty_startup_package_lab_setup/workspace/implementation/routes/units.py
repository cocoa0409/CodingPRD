"""Funding unit endpoints (PRD 3.1)."""

from flask import Blueprint

import authz
import envelope
import lookups
import serialize
import store
import validate
from errors import fail

bp = Blueprint("units", __name__)

UNIT_TYPES = ("COLLEGE", "DEPARTMENT", "DEAN_OFFICE")
APPOINTMENT_STATUSES = (
    "CANDIDATE",
    "ACTIVE",
    "DEPARTURE_NOTICE",
    "DEPARTED",
    "TRANSFERRED_INTERNAL",
)

READ_ROLES = (authz.ROLE_DEAN_OFFICE, authz.ROLE_DEAN, authz.ROLE_DEPARTMENT_CHAIR)


@bp.post("/funding-units")
def create_funding_unit():
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    name = validate.string(payload, "name")
    unit_type = validate.enum(payload, "unit_type", UNIT_TYPES)
    pool = validate.cents(payload, "cost_share_pool_cents")
    parent_id = validate.identifier(payload, "parent_unit_id", required=False)
    if unit_type in ("DEPARTMENT", "DEAN_OFFICE") and parent_id is None:
        fail("ERR_VALIDATION", "parent_unit_id is required for a %s unit" % unit_type)
    if unit_type == "COLLEGE":
        if parent_id is not None:
            # A COLLEGE unit must leave parent_unit_id null (PRD 2.8 / 2.13 p5).
            fail("ERR_RESOURCE_NOT_FOUND", "a COLLEGE unit must not name a parent unit")
    else:
        lookups.get_unit_typed(parent_id, "COLLEGE", "parent_unit_id")
    record = {
        "id": store.new_id(),
        "name": name,
        "unit_type": unit_type,
        "parent_unit_id": parent_id if unit_type != "COLLEGE" else None,
        "cost_share_pool_cents": pool,
    }
    store.stamp_new(record)
    store.db.funding_units[record["id"]] = record
    return envelope.created(serialize.funding_unit(record))


@bp.get("/funding-units")
def list_funding_units():
    authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    parent_filter = validate.filter_value("parent_unit_id")
    type_filter = validate.filter_value("unit_type", UNIT_TYPES)
    units = store.by_created(list(store.db.funding_units.values()))
    if parent_filter is not None:
        units = [u for u in units if u["parent_unit_id"] == parent_filter]
    if type_filter is not None:
        units = [u for u in units if u["unit_type"] == type_filter]
    page, total = validate.paginate(units, limit, offset)
    return envelope.array_response(
        [serialize.funding_unit(u) for u in page], limit, offset, total
    )


@bp.get("/funding-units/<unit_id>")
def read_funding_unit(unit_id):
    act = authz.actor(READ_ROLES)
    unit = lookups.get_unit(unit_id)
    authz.unit_scope_on_unit(act, unit_id)
    return envelope.object_response(serialize.funding_unit(unit))


@bp.get("/funding-units/<unit_id>/faculty")
def list_unit_faculty(unit_id):
    act = authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    status_filter = validate.filter_value("appointment_status", APPOINTMENT_STATUSES)
    lookups.get_unit(unit_id)
    authz.unit_scope_on_unit(act, unit_id)
    records = [
        f for f in store.db.faculty.values() if f["funding_unit_id"] == unit_id
    ]
    if status_filter is not None:
        records = [f for f in records if f["appointment_status"] == status_filter]
    records = store.by_created(records)
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.faculty(f) for f in page], limit, offset, total
    )
