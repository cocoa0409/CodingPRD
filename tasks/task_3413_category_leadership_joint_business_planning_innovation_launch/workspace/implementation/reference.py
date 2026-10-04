"""Reference data: Retailer and Category creation (PlatformAdmin only)."""

from flask import Blueprint

import validation as V
from auth import ROLE_PLATFORM_ADMIN, authenticate, authorize
from constants import ADVISORY_SCOPES, CHANNELS, RETAILER_STATUSES
from envelope import success
from errors import err
from storage import STORE, new_id, public, stamp_new

bp = Blueprint("reference", __name__)


@bp.post("/jbp/retailers")
def create_retailer():
    _uid, role = authenticate()
    authorize(role, [ROLE_PLATFORM_ADMIN])
    data = V.body()
    V.check_undeclared(data, {"name", "country_code", "channels", "status"})
    name = V.as_str(V.require(data, "name"), "name")
    country_code = V.as_str(V.require(data, "country_code"), "country_code")
    channels = V.as_str_list(V.require(data, "channels"), "channels")
    if len(channels) == 0:
        err("ERR_VALIDATION", "channels must be a non-empty array")
    if len(set(channels)) != len(channels):
        err("ERR_VALIDATION", "channels must be duplicate-free")
    for c in channels:
        if c not in CHANNELS:
            err("ERR_VALIDATION", "channels members must be drawn from " + ", ".join(CHANNELS))
    status = V.as_enum(data.get("status", "ACTIVE"), "status", RETAILER_STATUSES)
    rec = {
        "id": new_id(),
        "name": name,
        "country_code": country_code,
        "channels": channels,
        "status": status,
    }
    stamp_new(rec)
    STORE["retailers"][rec["id"]] = rec
    return success(public(rec), 201)


@bp.post("/jbp/categories")
def create_category():
    _uid, role = authenticate()
    authorize(role, [ROLE_PLATFORM_ADMIN])
    data = V.body()
    V.check_undeclared(data, {"name", "advisory_scope"})
    name = V.as_str(V.require(data, "name"), "name")
    scope = V.as_enum(data.get("advisory_scope", "FULL_CATEGORY"), "advisory_scope", ADVISORY_SCOPES)
    rec = {"id": new_id(), "name": name, "advisory_scope": scope}
    stamp_new(rec)
    STORE["categories"][rec["id"]] = rec
    return success(public(rec), 201)
