"""Booth assignment and the lead-capture licences provisioned on a booth."""
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import ANY_ROLE, own_exhibitor, require_roles
from services import state
from validation import json_body, require_row

bp = Blueprint("booths", __name__)
store = db.store

BOOTH_TYPES = ("INLINE", "CORNER", "PENINSULA", "ISLAND")


@bp.post("/booths")
def create_booth():
    require_roles("ShowOperations")
    body = json_body()
    show_id = body.string("show_id")
    exhibitor_id = body.string("exhibitor_id")
    booth_number = body.string("booth_number")
    sqft = body.integer("sqft")
    booth_type = body.enum("booth_type", BOOTH_TYPES)

    require_row(store.shows, show_id, "ERR_SHOW_NOT_FOUND", "Show")
    require_row(store.exhibitors, exhibitor_id, "ERR_EXHIBITOR_NOT_FOUND", "Exhibitor")

    for existing in store.booths.values():
        if existing["show_id"] == show_id and existing["booth_number"] == booth_number:
            raise ApiError("ERR_DUPLICATE_BOOTH_NUMBER",
                           "booth_number is already taken on this show")

    booth = {
        "id": db.new_id(),
        "show_id": show_id,
        "exhibitor_id": exhibitor_id,
        "booth_number": booth_number,
        "sqft": sqft,
        "booth_type": booth_type,
        "posture": "OPEN",
        "posture_reason": None,
    }
    db.stamp_common(booth)
    store.booths[booth["id"]] = booth
    # A booth is born with its posture already computed from the §2.10 clauses.
    posture, reason = state.compute_posture(booth)
    booth["posture"] = posture
    booth["posture_reason"] = reason
    return response.created(booth)


@bp.get("/booths/<booth_id>")
def get_booth(booth_id):
    require_roles(ANY_ROLE)
    booth = store.booths.get(booth_id)
    own_exhibitor(booth["exhibitor_id"] if booth else None)
    booth = require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")
    return response.ok(booth)


@bp.get("/booths")
def list_booths():
    require_roles(ANY_ROLE)
    rows = list(store.booths.values())
    rows = response.filter_rows(rows, "show_id", "exhibitor_id", "posture")
    return response.listing(rows)


@bp.get("/booths/<booth_id>/lead-capture-licenses")
def list_booth_licenses(booth_id):
    require_roles(ANY_ROLE)
    response.pagination_params()
    booth = store.booths.get(booth_id)
    own_exhibitor(booth["exhibitor_id"] if booth else None)
    require_row(store.booths, booth_id, "ERR_BOOTH_NOT_FOUND", "Booth")
    rows = [lic for lic in store.licenses.values() if lic["booth_id"] == booth_id]
    return response.listing(rows)
