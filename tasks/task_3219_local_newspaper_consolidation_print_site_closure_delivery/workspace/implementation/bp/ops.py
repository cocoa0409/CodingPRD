"""Operational clock and print-volume feed."""
from flask import Blueprint, request

from core import DB, fail
from helpers import ok_object, create
from guards import body, identity, query_pagination, path_one, require_row

bp = Blueprint("ops", __name__)

ALL_ROLES = ["PrintOperationsDirector", "NewsroomOperationsManager",
             "DeliveryNetworkManager", "CustomerService", "Auditor", "PlatformAdmin"]


@bp.post("/_clock/set_current_utc")
def set_clock():
    data = body()
    identity(["PlatformAdmin"])
    if "current_utc" not in data or data["current_utc"] is None:
        fail("ERR_INVALID_REQUEST", "current_utc is required.")
    for key in data:
        if key != "current_utc":
            fail("ERR_INVALID_REQUEST", "Unknown field %s." % key)
    DB.clock.set(data["current_utc"])
    return ok_object({})


@bp.post("/regional-news-ops/_print-volume/records")
def record_volume():
    data = body()
    identity(["PrintOperationsDirector"])
    for key in data:
        if key not in ("print_site_id", "day", "charge_cents"):
            fail("ERR_INVALID_REQUEST", "Unknown field %s." % key)
    for key in ("print_site_id", "day", "charge_cents"):
        if key not in data or data[key] is None:
            fail("ERR_INVALID_REQUEST", "Field %s is required." % key)
    site = require_row("print_sites", data["print_site_id"])
    try:
        charge = int(data["charge_cents"])
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "charge_cents must be an integer.")
    DB.volume[(site["id"], str(data["day"]))] = charge
    from calcs import site_savings
    site_savings(site)
    from models import touch
    touch(site)
    return ok_object({}, 201)