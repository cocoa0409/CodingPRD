"""Talkgroup architecture and availability."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import AGENCY_RADIO_MANAGER

bp = Blueprint("talkgroups", __name__, url_prefix=common.PREFIX)


@bp.post("/talkgroups")
def create_talkgroup():
    actor = validate.authenticate([AGENCY_RADIO_MANAGER])
    body = validate.get_body()
    agency = validate.req_fk(body, "owner_agency_id", "agencies")
    site = validate.req_fk(body, "home_site_id", "sites")
    alias = validate.req_str(body, "alias", 1, 16)
    decimal_id = validate.req_int(body, "tg_decimal_id", 1, 65535)
    kind = validate.req_enum(body, "kind", enums.TALKGROUP_KINDS)
    mode = validate.req_enum(body, "encryption_mode", enums.ENCRYPTION_MODES)
    priority = validate.opt_int(body, "priority_level", 1, 10, 5)
    common.require_scope(actor, agency["id"])
    for existing in db.store.talkgroups.values():
        if existing["tg_decimal_id"] == decimal_id:
            raise ApiError("ERR_DUPLICATE_TALKGROUP_ID", "tg_decimal_id is already in use.")
    row = db.base_row({
        "owner_agency_id": agency["id"],
        "home_site_id": site["id"],
        "alias": alias,
        "tg_decimal_id": decimal_id,
        "kind": kind,
        "encryption_mode": mode,
        "priority_level": priority,
        "status": "ACTIVE",
        "lock_reason": "NONE",
        "active_patch_count": 0,
    })
    db.store.talkgroups[row["id"]] = row
    return response.ok(serialize.talkgroup(row), 201)


@bp.get("/talkgroups")
def list_talkgroups():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("owner_agency_id", validate.filter_str("owner_agency_id")),
        ("home_site_id", validate.filter_str("home_site_id")),
        ("status", validate.filter_enum("status", enums.TALKGROUP_STATUSES)),
        ("kind", validate.filter_enum("kind", enums.TALKGROUP_KINDS)),
    )
    return common.list_endpoint("talkgroups", serialize.talkgroup, filters)


@bp.get("/talkgroups/<talkgroup_id>")
def read_talkgroup(talkgroup_id):
    validate.authenticate(common.ANY_ROLE)
    talkgroup = validate.lookup("talkgroups", talkgroup_id)
    return response.ok(serialize.talkgroup(talkgroup))


@bp.post("/talkgroups/<talkgroup_id>/status")
def talkgroup_status(talkgroup_id):
    actor = validate.authenticate([AGENCY_RADIO_MANAGER])
    talkgroup = validate.lookup("talkgroups", talkgroup_id)
    body = validate.get_body()
    action = validate.req_enum(body, "action", enums.TALKGROUP_ACTIONS)
    common.require_scope(actor, talkgroup["owner_agency_id"])
    if talkgroup["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if action == "LOCK":
        if talkgroup["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        talkgroup["status"] = "LOCKED"
        talkgroup["lock_reason"] = "MANUAL"
        db.touch(talkgroup)
        _release_for(talkgroup)
    elif action == "UNLOCK":
        if talkgroup["status"] != "LOCKED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if talkgroup["lock_reason"] == "KEY_COMPROMISE" and \
                not compute.agency_has_keyed_unit(talkgroup["owner_agency_id"]):
            raise ApiError(
                "ERR_KEYSET_NOT_ACTIVE",
                "The owning agency holds no keyed subscriber unit.",
            )
        talkgroup["status"] = "ACTIVE"
        talkgroup["lock_reason"] = "NONE"
        db.touch(talkgroup)
    else:
        if talkgroup["status"] not in ("ACTIVE", "LOCKED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        talkgroup["status"] = "DECOMMISSIONED"
        db.touch(talkgroup)
        _release_for(talkgroup)
    return response.ok(serialize.talkgroup(talkgroup))


def _release_for(talkgroup):
    doomed = compute.open_patches_naming([talkgroup["id"]])
    if doomed:
        compute.release_patches(doomed, "OPERATOR")
    else:
        compute.recompute_talkgroup_patch_count(talkgroup)
