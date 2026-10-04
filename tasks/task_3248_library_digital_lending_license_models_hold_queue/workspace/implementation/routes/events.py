"""Circulation event query routes (global and sub-resource)."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    get_library, get_title, get_patron, get_loan, get_license, get_hold,
    serialize_event,
)
from errors import (
    ERR_LIBRARY_NOT_FOUND, ERR_TITLE_NOT_FOUND, ERR_PATRON_NOT_FOUND,
    ERR_LOAN_NOT_FOUND, ERR_LICENSE_NOT_FOUND, ERR_HOLD_NOT_FOUND,
)

bp = Blueprint("events", __name__)

READ_ROLES = {"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"}


def _list(items):
    items.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    page, meta = paginate([serialize_event(e) for e in items], request.args)
    return success(page, 200, meta)


def _filter_type(items):
    et = request.args.get("event_type")
    if et is not None:
        items = [e for e in items if e["event_type"] == et]
    return items


@bp.get("/lending/circulation-events")
def list_events():
    require_roles(READ_ROLES)
    items = list(stores["events"].values())
    for key in ("library_id", "title_id", "patron_id", "loan_id", "hold_id",
                "license_id", "event_type"):
        v = request.args.get(key)
        if v is not None:
            items = [e for e in items if str(e.get(key)) == v]
    return _list(items)


@bp.get("/lending/libraries/<rid>/circulation-events")
def library_events(rid):
    require_roles(READ_ROLES)
    get_library(rid, ERR_LIBRARY_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["library_id"] == rid]))


@bp.get("/lending/titles/<rid>/circulation-events")
def title_events(rid):
    require_roles(READ_ROLES)
    get_title(rid, ERR_TITLE_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["title_id"] == rid]))


@bp.get("/lending/patrons/<rid>/circulation-events")
def patron_events(rid):
    require_roles(READ_ROLES)
    get_patron(rid, ERR_PATRON_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["patron_id"] == rid]))


@bp.get("/lending/loans/<rid>/circulation-events")
def loan_events(rid):
    require_roles(READ_ROLES)
    get_loan(rid, ERR_LOAN_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["loan_id"] == rid]))


@bp.get("/lending/licenses/<rid>/circulation-events")
def license_events(rid):
    require_roles(READ_ROLES)
    get_license(rid, ERR_LICENSE_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["license_id"] == rid]))


@bp.get("/lending/holds/<rid>/circulation-events")
def hold_events(rid):
    require_roles(READ_ROLES)
    get_hold(rid, ERR_HOLD_NOT_FOUND)
    return _list(_filter_type([e for e in stores["events"].values() if e["hold_id"] == rid]))
