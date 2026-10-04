"""Content drop endpoints."""
from __future__ import annotations

from flask import Blueprint

import helpers as H
import services as S
from db import db
from errors import (err_athlete_not_eligible, err_censorship, err_drop_window,
                    err_insufficient_vc, err_invalid_input, err_invalid_state,
                    err_not_found, err_reference_state, err_wallet_frozen)
from middleware import require_roles
from response import (body_json, ok_obj, parse_datetime, require_enum,
                      require_fields, require_int, require_str, stamp_new, touch)

bp = Blueprint("drops", __name__)

DROP_KINDS = {"ITEM_PACK", "PLAYER_CARD", "VANITY", "STADIUM_THEME"}
LOM = ("LiveOpsManager",)


@bp.post("/licensing/content-drops")
def create_drop():
    require_roles(*LOM)
    body = body_json()
    require_fields(body, ["season_id", "drop_kind", "drop_label", "price_vc",
                          "scheduled_start_at", "scheduled_end_at"])
    season = H.get_season(body["season_id"])
    kind = require_enum(body, "drop_kind", DROP_KINDS)
    label = require_str(body, "drop_label")
    price = require_int(body, "price_vc", 0)
    start = parse_datetime(body["scheduled_start_at"], "scheduled_start_at")
    end = parse_datetime(body["scheduled_end_at"], "scheduled_end_at")
    featured = body.get("featured_athlete_id")
    if kind == "PLAYER_CARD":
        if featured is None:
            raise err_invalid_input("featured_athlete_id required for PLAYER_CARD")
        athlete = H.get_athlete(featured)
        featured = athlete["id"]
    else:
        if featured is not None:
            raise err_invalid_input("featured_athlete_id must be null unless drop_kind is PLAYER_CARD")
    rec = {
        "season_id": season["id"],
        "drop_kind": kind,
        "drop_label": label,
        "featured_athlete_id": featured,
        "price_vc": price,
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "drop_status": "SCHEDULED",
        "_sched_start": start,
        "_sched_end": end,
        "_held_reason": None,
    }
    stamp_new(rec)
    db.content_drops[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/content-drops/<drop_id>")
def get_drop(drop_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController", "ComplianceReviewer")
    d = H.get_drop(drop_id)
    return ok_obj(H.serialize(d))


def _censorship_conflict(drop) -> bool:
    """A PLAYER_CARD drop conflicts with a RELEASED edition carrying
    NO_REAL_PLAYER_NAMES."""
    if drop["drop_kind"] != "PLAYER_CARD":
        return False
    for ed in S.editions_of_season(drop["season_id"]):
        if ed["edition_status"] == "RELEASED" and "NO_REAL_PLAYER_NAMES" in (ed.get("censorship_flags") or []):
            return True
    return False


@bp.post("/licensing/content-drops/<drop_id>/release")
def release_drop(drop_id):
    require_roles(*LOM)
    d = H.get_drop(drop_id)
    if d["drop_status"] != "SCHEDULED":
        raise err_invalid_state("Drop must be SCHEDULED to release")
    season = H.get_season(d["season_id"])
    if season["season_status"] != "LIVE":
        raise err_reference_state("Parent season is not LIVE")
    if d["drop_kind"] == "PLAYER_CARD":
        athlete = H.get_athlete(d["featured_athlete_id"])
        if athlete["athlete_status"] != "ELIGIBLE":
            raise err_athlete_not_eligible("Featured athlete is not ELIGIBLE")
    now = db.now()
    if not (d["_sched_start"] <= now < d["_sched_end"]):
        raise err_drop_window()
    if _censorship_conflict(d):
        raise err_censorship()
    d["drop_status"] = "RELEASED"
    touch(d)
    return ok_obj(H.serialize(d))


@bp.post("/licensing/content-drops/<drop_id>/cancel")
def cancel_drop(drop_id):
    require_roles(*LOM)
    d = H.get_drop(drop_id)
    if d["drop_status"] not in ("SCHEDULED", "HELD"):
        raise err_invalid_state("Drop must be SCHEDULED or HELD to cancel")
    d["drop_status"] = "CANCELED"
    d["_held_reason"] = None
    touch(d)
    return ok_obj(H.serialize(d))


@bp.post("/licensing/content-drops/<drop_id>/purchase")
def purchase_drop(drop_id):
    require_roles(*LOM)
    d = H.get_drop(drop_id)
    body = body_json()
    require_fields(body, ["wallet_id"])
    wallet = H.get_wallet(body["wallet_id"])
    if d["drop_status"] != "RELEASED":
        raise err_invalid_state("Drop must be RELEASED to purchase")
    if wallet["wallet_status"] == "FROZEN":
        raise err_wallet_frozen()
    if wallet["wallet_status"] != "OPEN":
        raise err_invalid_state("Wallet is not OPEN")
    if wallet["vc_balance"] < d["price_vc"]:
        raise err_insufficient_vc()
    le = S.post_ledger(wallet["id"], "DEBIT", d["price_vc"], "SPEND_DROP", d["id"])
    return ok_obj(H.serialize(le))
