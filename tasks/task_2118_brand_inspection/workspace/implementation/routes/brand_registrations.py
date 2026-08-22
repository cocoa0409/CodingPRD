"""Recorded brands (reads only; records are minted by the recording route)."""

from flask import Blueprint, request

from db import by_created_at, db
from middleware import endpoint
from response import object_response, paginate
from routes import lookup

bp = Blueprint("brand_registrations", __name__)

READ_ROLES = ("BoardAdmin", "BrandRecorder", "LivestockOwner", "FieldInspector", "TheftInvestigator")


@bp.get("/brand-registrations/<registration_id>")
@endpoint(*READ_ROLES)
def read_registration(registration_id):
    return object_response(lookup.registration(registration_id))


@bp.get("/brand-registrations")
@endpoint(*READ_ROLES)
def list_registrations():
    rows = lookup.filtered(
        db.registrations,
        {
            "owner_id": request.args.get("owner_id"),
            "source_application_id": request.args.get("source_application_id"),
            "superseded_by_registration_id": request.args.get("superseded_by_registration_id"),
            "state_code": request.args.get("state_code"),
            "brand_symbol": request.args.get("brand_symbol"),
            "position_code": request.args.get("position_code"),
            "species_class": request.args.get("species_class"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))
