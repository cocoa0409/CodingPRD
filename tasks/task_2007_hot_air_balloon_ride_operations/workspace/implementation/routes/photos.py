"""PhotoPackageRecord read endpoint (PRD 3.8): cascade-created at booking,
delivered at reservation COMPLETE."""
from flask import Blueprint

from db import db
from middleware import authorized, ALL_READ_ROLES
from response import success_list
from services.core import public_photo, sort_created
from validate import require_path_resource, get_pagination

bp = Blueprint("photos", __name__, url_prefix="/v1")


@bp.get("/reservations/<reservation_id>/photo-packages")
def list_photo_packages(reservation_id):
    authorized(ALL_READ_ROLES)
    require_path_resource("reservations", reservation_id, "reservation")
    items = [p for p in db["photo_packages"].values()
             if p["reservation_id"] == reservation_id]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_photo(p) for p in page], total, limit, offset)
