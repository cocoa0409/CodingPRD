"""Live season endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import err_invalid_input, err_invalid_state, err_reference_state, err_temporal
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      parse_date, require_fields, require_str, stamp_new, touch)

bp = Blueprint("seasons", __name__)

LOM = ("LiveOpsManager",)


@bp.post("/licensing/seasons")
def create_season():
    require_roles(*LOM)
    body = body_json()
    require_fields(body, ["title_code", "sport_category", "season_label",
                          "agreement_id", "season_opens_on", "season_closes_on"])
    title = require_str(body, "title_code")
    sport = require_str(body, "sport_category")
    label = require_str(body, "season_label")
    agreement = H.get_agreement(body["agreement_id"])
    opens = parse_date(body["season_opens_on"], "season_opens_on")
    closes = parse_date(body["season_closes_on"], "season_closes_on")
    rec = {
        "title_code": title,
        "sport_category": sport,
        "season_label": label,
        "agreement_id": agreement["id"],
        "season_status": "PRELAUNCH",
        "season_opens_on": body["season_opens_on"],
        "season_closes_on": body["season_closes_on"],
        "roster_epoch": 0,
        "_opens": opens,
        "_closes": closes,
    }
    stamp_new(rec)
    db.seasons[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/seasons/<season_id>")
def get_season(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "RosterOperator",
                  "RosterReviewer", "FinanceController", "ComplianceReviewer")
    s = H.get_season(season_id)
    return ok_obj(H.serialize(s))


@bp.post("/licensing/seasons/<season_id>/launch")
def launch_season(season_id):
    require_roles(*LOM)
    s = H.get_season(season_id)
    if s["season_status"] != "PRELAUNCH":
        raise err_invalid_state("Season must be PRELAUNCH to launch")
    agreement = H.get_agreement(s["agreement_id"])
    if agreement["agreement_status"] != "ACTIVE":
        raise err_reference_state("Governing agreement is not ACTIVE")
    if db.now_date() < s["_opens"]:
        raise err_temporal("Clock date before season_opens_on")
    has_published = any(
        b["season_id"] == s["id"] and b["batch_status"] == "PUBLISHED"
        for b in db.roster_batches.values())
    if not has_published:
        raise err_invalid_state("At least one roster batch must be PUBLISHED")
    s["season_status"] = "LIVE"
    touch(s)
    return ok_obj(H.serialize(s))


@bp.post("/licensing/seasons/<season_id>/sunset")
def sunset_season(season_id):
    require_roles(*LOM)
    s = H.get_season(season_id)
    if s["season_status"] != "LIVE":
        raise err_invalid_state("Season must be LIVE to sunset")
    s["season_status"] = "SUNSET"
    touch(s)
    S.cascade_season_sunset(s)
    return ok_obj(H.serialize(s))


@bp.post("/licensing/seasons/<season_id>/archive")
def archive_season(season_id):
    require_roles(*LOM)
    s = H.get_season(season_id)
    if s["season_status"] != "SUNSET":
        raise err_invalid_state("Season must be SUNSET to archive")
    for p in S.programs_of_season(s["id"]):
        if p["program_status"] in ("REGISTRATION_OPEN", "REGISTRATION_CLOSED", "COMPLETED"):
            raise err_invalid_state(
                "Tournament programs must be PAYOUT_FINALIZED or CANCELED before archive")
    agreement = db.agreements.get(s["agreement_id"])
    if agreement is not None:
        for st in S.statements_of_agreement(agreement["id"]):
            if st["statement_status"] in ("OPEN", "PROVISIONAL", "DISPUTED"):
                raise err_invalid_state(
                    "No OPEN/PROVISIONAL/DISPUTED royalty statement may remain on the agreement")
    s["season_status"] = "ARCHIVED"
    touch(s)
    for w in S.wallets_of_season(s["id"]):
        if w["wallet_status"] == "FROZEN":
            w["wallet_status"] = "CLOSED"
            touch(w)
    return ok_obj(H.serialize(s))


# --- nested collections ----------------------------------------------------

@bp.get("/licensing/seasons/<season_id>/roster-batches")
def season_batches(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "RosterOperator", "RosterReviewer")
    s = H.get_season(season_id)
    limit, offset = pagination_params()
    status = request.args.get("batch_status")
    rows = [b for b in db.roster_batches.values() if b["season_id"] == s["id"]]
    items, total = H.list_paginated(rows, [(status, "batch_status")], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/seasons/<season_id>/content-drops")
def season_drops(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController", "ComplianceReviewer")
    s = H.get_season(season_id)
    limit, offset = pagination_params()
    status = request.args.get("drop_status")
    items, total = H.list_paginated(S.drops_of_season(s["id"]),
                                    [(status, "drop_status")], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/seasons/<season_id>/wallets")
def season_wallets(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    s = H.get_season(season_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.wallets_of_season(s["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/seasons/<season_id>/tournaments")
def season_tournaments(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    s = H.get_season(season_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.programs_of_season(s["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/seasons/<season_id>/editions")
def season_editions(season_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "ComplianceReviewer")
    s = H.get_season(season_id)
    limit, offset = pagination_params()
    status = request.args.get("edition_status")
    items, total = H.list_paginated(S.editions_of_season(s["id"]),
                                    [(status, "edition_status")], limit, offset)
    return ok_list(items, limit, offset, total)
