"""Audio asset and audio license endpoints."""
from __future__ import annotations

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import err_invalid_input, err_invalid_state
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      parse_date, require_enum, require_fields, require_str,
                      stamp_new, touch)

bp = Blueprint("audio", __name__)

ASSET_KINDS = {"COMMENTARY_LINE", "MUSIC_TRACK", "STADIUM_SOUND"}
USAGE_SCOPES = {"MENU_ONLY", "IN_GAME", "BROADCAST_SIM", "ALL"}
RO = ("RightsOfficer",)


@bp.post("/licensing/audio-assets")
def create_asset():
    require_roles(*RO)
    body = body_json()
    require_fields(body, ["asset_kind", "asset_title", "rights_holder"])
    kind = require_enum(body, "asset_kind", ASSET_KINDS)
    title = require_str(body, "asset_title")
    holder = require_str(body, "rights_holder")
    rec = {
        "asset_kind": kind,
        "asset_title": title,
        "rights_holder": holder,
        "asset_status": "CLEARED",
    }
    stamp_new(rec)
    db.audio_assets[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/audio-assets/<asset_id>")
def get_asset(asset_id):
    require_roles("LicensingAdmin", "RightsOfficer", "LiveOpsManager")
    a = H.get_asset(asset_id)
    return ok_obj(H.serialize(a))


@bp.post("/licensing/audio-assets/<asset_id>/retire")
def retire_asset(asset_id):
    require_roles(*RO)
    a = H.get_asset(asset_id)
    if a["asset_status"] != "BLOCKED":
        raise err_invalid_state("Asset must be BLOCKED to retire")
    a["asset_status"] = "RETIRED"
    touch(a)
    return ok_obj(H.serialize(a))


@bp.get("/licensing/audio-assets/<asset_id>/licenses")
def list_asset_licenses(asset_id):
    require_roles("LicensingAdmin", "RightsOfficer")
    a = H.get_asset(asset_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.licenses_of_asset(a["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/licensing/audio-licenses")
def create_license():
    require_roles(*RO)
    body = body_json()
    require_fields(body, ["asset_id", "term_start_on", "term_end_on",
                          "usage_scope", "region_scope"])
    asset = H.get_asset(body["asset_id"])
    ts = parse_date(body["term_start_on"], "term_start_on")
    te = parse_date(body["term_end_on"], "term_end_on")
    scope = require_enum(body, "usage_scope", USAGE_SCOPES)
    region = require_str(body, "region_scope")
    if te < ts:
        raise err_invalid_input("term_end_on must be >= term_start_on")
    rec = {
        "asset_id": asset["id"],
        "term_start_on": body["term_start_on"],
        "term_end_on": body["term_end_on"],
        "usage_scope": scope,
        "region_scope": region,
        "license_status": "ACTIVE",
        "_term_start": ts,
        "_term_end": te,
    }
    stamp_new(rec)
    db.audio_licenses[rec["id"]] = rec
    # un-block the asset when the new license covers it
    if asset["asset_status"] == "BLOCKED":
        asset["asset_status"] = "CLEARED"
        touch(asset)
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/audio-licenses/<license_id>")
def get_license(license_id):
    require_roles("LicensingAdmin", "RightsOfficer")
    lic = H.get_audio_license(license_id)
    return ok_obj(H.serialize(lic))


@bp.post("/licensing/audio-licenses/<license_id>/terminate")
def terminate_license(license_id):
    require_roles(*RO)
    lic = H.get_audio_license(license_id)
    if lic["license_status"] != "ACTIVE":
        raise err_invalid_state("License must be ACTIVE to terminate")
    lic["license_status"] = "TERMINATED"
    touch(lic)
    S.maybe_block_asset(lic["asset_id"])
    return ok_obj(H.serialize(lic))
