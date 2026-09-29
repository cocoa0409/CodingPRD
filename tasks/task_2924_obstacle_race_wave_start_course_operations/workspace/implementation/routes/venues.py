"""Venue parcels (PRD 3.1): registration, listing and the ledger read."""

from flask import Blueprint

import auth
import db
import validation
from routes import common

bp = Blueprint("venues", __name__)


@bp.post("/ocr/venues")
def register_venue():
    auth.require(auth.PERMIT_OFFICER)
    payload = validation.body()
    name = validation.field_str(payload, "name", 1, 120)
    terrain_type = validation.field_enum(payload, "terrain_type", validation.TERRAIN_TYPES)
    water_access = validation.field_enum(payload, "water_access", validation.WATER_ACCESS)
    land_use_zone = validation.field_str(payload, "land_use_zone", 1, 40)
    protected = validation.field_int(payload, "protected_acreage_sqm", minimum=0)
    bond = validation.field_int(payload, "restoration_bond_cents", minimum=0)

    row = db.insert(
        "venues",
        {
            "name": name,
            "terrain_type": terrain_type,
            "water_access": water_access,
            "land_use_zone": land_use_zone,
            "protected_acreage_sqm": protected,
            "restoration_bond_cents": bond,
            "site_posture": "OPEN",
            "disturbed_area_sqm": 0,
            "bond_released_cents": 0,
            "bond_forfeited_cents": 0,
            "bond_held_cents": bond,
        },
    )
    return common.created(row)


@bp.get("/ocr/venues")
def list_venues():
    auth.require(*auth.OPERATOR_READERS)
    terrain_type = validation.query_enum("terrain_type", validation.TERRAIN_TYPES)
    site_posture = validation.query_enum("site_posture", validation.SITE_POSTURES)
    rows = db.all_rows("venues")
    if terrain_type is not None:
        rows = [r for r in rows if r["terrain_type"] == terrain_type]
    if site_posture is not None:
        rows = [r for r in rows if r["site_posture"] == site_posture]
    return common.listing(rows)


@bp.get("/ocr/venues/<venue_id>")
def read_venue(venue_id):
    auth.require(*auth.OPERATOR_READERS)
    venue = validation.path_venue(venue_id)
    return common.ok(venue)
