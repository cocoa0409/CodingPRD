"""Properties and dwelling units (PRD 3.2)."""

from flask import Blueprint

import auth
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common

bp = Blueprint("portfolio", __name__)


@bp.post("/properties")
def register_property():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("name", "string"),
            shapes.F("total_unit_count", "integer", minimum=1),
            shapes.F("capital_reserve_cents", "integer", minimum=0),
            shapes.F("owner_contact_email", "string"),
        ]
    )
    row = {
        "name": values["name"],
        "total_unit_count": values["total_unit_count"],
        "capital_reserve_cents": values["capital_reserve_cents"],
        "owner_contact_email": values["owner_contact_email"],
        "readiness_posture": "READY",
        "open_life_threatening_count": 0,
        "overdue_life_threatening_count": 0,
        "open_severe_count": 0,
        "last_final_score": None,
        "last_sweep_closed_at": None,
        "allocated_reserve_total_cents": 0,
    }
    store.stamp_new(row)
    store.properties[row["id"]] = row
    return envelope.created(row)


@bp.get("/properties/<property_id>")
def read_property(property_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    prop = common.fetch("property", property_id)
    auth.require_owner(role, user_id, prop["id"])
    return envelope.ok(prop)


@bp.get("/properties")
def list_properties():
    auth.authenticate([auth.INSPECTOR, auth.REVIEWER, auth.APPEALS, auth.ADMIN])
    return common.listing(store.properties.values(), ["readiness_posture"])


@bp.patch("/properties/<property_id>")
def amend_property(property_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("name", "string", required=False),
            shapes.F("total_unit_count", "integer", required=False, minimum=1),
            shapes.F("capital_reserve_cents", "integer", required=False, minimum=0),
            shapes.F("owner_contact_email", "string", required=False),
        ]
    )
    prop = common.fetch("property", property_id)
    auth.require_owner(role, user_id, prop["id"])
    for name in (
        "name",
        "total_unit_count",
        "capital_reserve_cents",
        "owner_contact_email",
    ):
        if values.get(name) is not None:
            prop[name] = values[name]
    store.touch(prop, bump_version=True)
    return envelope.ok(prop)


@bp.post("/units")
def register_unit():
    auth.authenticate([auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("property_id", "string"),
            shapes.F("unit_number", "string"),
            shapes.F("bedroom_count", "integer", minimum=0, maximum=6),
            shapes.F(
                "occupancy_status",
                "enum",
                required=False,
                values=shapes.OCCUPANCY_STATUS,
            ),
            shapes.F("occupant_display_name", "string", required=False),
        ]
    )
    prop = common.body_fetch("property", values["property_id"])
    for row in store.units.values():
        if row["property_id"] == prop["id"] and row["unit_number"] == values["unit_number"]:
            raise ApiError(
                "ERR_DUPLICATE_UNIT_NUMBER",
                "Unit number %s already exists on this property." % values["unit_number"],
            )
    row = {
        "property_id": prop["id"],
        "unit_number": values["unit_number"],
        "bedroom_count": values["bedroom_count"],
        "occupancy_status": values.get("occupancy_status") or "OCCUPIED",
        "occupant_display_name": values.get("occupant_display_name"),
        "prior_deficiency_count": 0,
        "open_deficiency_count": 0,
    }
    store.stamp_new(row)
    store.units[row["id"]] = row
    return envelope.created(row)


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    unit = common.fetch("unit", unit_id)
    auth.require_owner(role, user_id, unit["property_id"])
    return envelope.ok(unit)


@bp.get("/units")
def list_units():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.units.values(),
        ["property_id", "occupancy_status"],
        role=role,
        user_id=user_id,
        property_getter=lambda r: r["property_id"],
    )


@bp.patch("/units/<unit_id>")
def amend_unit(unit_id):
    user_id, role = auth.authenticate([auth.OWNER, auth.ADMIN])
    values = shapes.validate(
        [
            shapes.F("bedroom_count", "integer", required=False, minimum=0, maximum=6),
            shapes.F(
                "occupancy_status",
                "enum",
                required=False,
                values=shapes.OCCUPANCY_STATUS,
            ),
            shapes.F("occupant_display_name", "string", required=False),
        ]
    )
    unit = common.fetch("unit", unit_id)
    auth.require_owner(role, user_id, unit["property_id"])
    for name in ("bedroom_count", "occupancy_status", "occupant_display_name"):
        if values.get(name) is not None:
            unit[name] = values[name]
    store.touch(unit, bump_version=True)
    return envelope.ok(unit)
