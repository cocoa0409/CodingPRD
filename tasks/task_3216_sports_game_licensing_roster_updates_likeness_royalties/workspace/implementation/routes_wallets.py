"""Player wallet and ledger endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import (err_insufficient_vc, err_invalid_input, err_invalid_state,
                    err_reference_state, err_wallet_frozen)
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      require_enum, require_fields, require_int, require_str,
                      stamp_new, touch)

bp = Blueprint("wallets", __name__)

LOM = ("LiveOpsManager",)
REASON_CODES = {"GRANT", "PURCHASE", "SPEND_DROP", "REFUND", "CLAWBACK", "PRIZE_PAYOUT"}
DIRECTIONS = {"CREDIT", "DEBIT"}


@bp.post("/licensing/wallets")
def create_wallet():
    require_roles(*LOM)
    body = body_json()
    require_fields(body, ["season_id", "owner_tag"])
    season = H.get_season(body["season_id"])
    tag = require_str(body, "owner_tag")
    rec = {
        "season_id": season["id"],
        "owner_tag": tag,
        "vc_balance": 0,
        "wallet_status": "OPEN",
    }
    stamp_new(rec)
    db.wallets[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/wallets/<wallet_id>")
def get_wallet(wallet_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    w = H.get_wallet(wallet_id)
    return ok_obj(H.serialize(w))


@bp.post("/licensing/wallets/<wallet_id>/freeze")
def freeze_wallet(wallet_id):
    require_roles(*LOM)
    w = H.get_wallet(wallet_id)
    if w["wallet_status"] != "OPEN":
        raise err_invalid_state("Wallet must be OPEN to freeze")
    w["wallet_status"] = "FROZEN"
    touch(w)
    return ok_obj(H.serialize(w))


@bp.post("/licensing/wallets/<wallet_id>/unfreeze")
def unfreeze_wallet(wallet_id):
    require_roles(*LOM)
    w = H.get_wallet(wallet_id)
    if w["wallet_status"] != "FROZEN":
        raise err_invalid_state("Wallet must be FROZEN to unfreeze")
    season = H.get_season(w["season_id"])
    if season["season_status"] != "LIVE":
        raise err_reference_state("Parent season is not LIVE")
    w["wallet_status"] = "OPEN"
    touch(w)
    return ok_obj(H.serialize(w))


@bp.post("/licensing/wallets/<wallet_id>/ledger-entries")
def post_entry(wallet_id):
    require_roles("LiveOpsManager", "FinanceController")
    w = H.get_wallet(wallet_id)
    body = body_json()
    require_fields(body, ["direction", "amount_vc", "reason_code"])
    direction = require_enum(body, "direction", DIRECTIONS)
    amount = require_int(body, "amount_vc", 1)
    reason = require_enum(body, "reason_code", REASON_CODES)
    ref = body.get("reference_id")
    if ref is not None and not isinstance(ref, str):
        raise err_invalid_input("reference_id must be a string")
    if direction == "DEBIT":
        if w["wallet_status"] == "FROZEN":
            raise err_wallet_frozen()
        if w["wallet_status"] != "OPEN":
            raise err_invalid_state("Wallet is not OPEN")
        if w["vc_balance"] < amount:
            raise err_insufficient_vc()
    le = S.post_ledger(w["id"], direction, amount, reason, ref)
    return ok_obj(H.serialize(le), 201)


@bp.get("/licensing/wallets/<wallet_id>/ledger-entries")
def list_entries(wallet_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    w = H.get_wallet(wallet_id)
    limit, offset = pagination_params()
    reason = request.args.get("reason_code")
    rows = [le for le in db.ledger_entries.values() if le["wallet_id"] == w["id"]]
    items, total = H.list_paginated(rows, [(reason, "reason_code")], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/licensing/wallets/<wallet_id>/tournament-entries")
def list_tournament_entries(wallet_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    w = H.get_wallet(wallet_id)
    limit, offset = pagination_params()
    rows = [e for e in db.tournament_entries.values() if e["wallet_id"] == w["id"]]
    items, total = H.list_paginated(rows, [], limit, offset)
    return ok_list(items, limit, offset, total)
