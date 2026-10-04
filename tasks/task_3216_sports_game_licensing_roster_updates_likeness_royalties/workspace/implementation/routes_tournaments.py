"""Tournament program, entry, and prize endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import helpers as H
import services as S
from db import db
from errors import (err_insufficient_vc, err_invalid_input, err_invalid_state,
                    err_not_found, err_prize_shares, err_reference_state,
                    err_stale_program, err_temporal, err_unsanctioned,
                    err_wallet_frozen)
from middleware import require_roles
from response import (body_json, ok_list, ok_obj, pagination_params,
                      parse_datetime, require_fields, require_int, require_str,
                      stamp_new, touch)

bp = Blueprint("tournaments", __name__)

LOM = ("LiveOpsManager",)
FC = ("FinanceController",)


@bp.post("/licensing/tournaments")
def create_program():
    require_roles(*LOM)
    body = body_json()
    require_fields(body, ["season_id", "program_label", "league_sanctioned",
                          "entry_fee_vc", "registration_opens_at",
                          "registration_closes_at"])
    season = H.get_season(body["season_id"])
    label = require_str(body, "program_label")
    sanctioned = body["league_sanctioned"]
    if not isinstance(sanctioned, bool):
        raise err_invalid_input("league_sanctioned must be boolean")
    fee = require_int(body, "entry_fee_vc", 0)
    opens = parse_datetime(body["registration_opens_at"], "registration_opens_at")
    closes = parse_datetime(body["registration_closes_at"], "registration_closes_at")
    rec = {
        "season_id": season["id"],
        "program_label": label,
        "league_sanctioned": sanctioned,
        "entry_fee_vc": fee,
        "registration_opens_at": body["registration_opens_at"],
        "registration_closes_at": body["registration_closes_at"],
        "program_status": "ANNOUNCED",
        "prize_pool_vc": 0,
        "_reg_opens": opens,
        "_reg_closes": closes,
    }
    stamp_new(rec)
    db.tournaments[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/tournaments/<program_id>")
def get_program(program_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    p = H.get_program(program_id)
    return ok_obj(H.serialize(p))


@bp.post("/licensing/tournaments/<program_id>/open-registration")
def open_registration(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    if p["program_status"] != "ANNOUNCED":
        raise err_invalid_state("Program must be ANNOUNCED to open registration")
    season = H.get_season(p["season_id"])
    if season["season_status"] != "LIVE":
        raise err_reference_state("Parent season is not LIVE")
    now = db.now()
    if not (p["_reg_opens"] <= now < p["_reg_closes"]):
        raise err_temporal("Clock outside registration window")
    p["program_status"] = "REGISTRATION_OPEN"
    touch(p)
    return ok_obj(H.serialize(p))


@bp.post("/licensing/tournaments/<program_id>/entries")
def register_entry(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    body = body_json()
    require_fields(body, ["wallet_id"])
    wallet = H.get_wallet(body["wallet_id"])
    if p["program_status"] != "REGISTRATION_OPEN":
        raise err_invalid_state("Program registration is not open")
    fee = p["entry_fee_vc"]
    fee_paid = False
    if fee > 0:
        if wallet["wallet_status"] == "FROZEN":
            raise err_wallet_frozen()
        if wallet["wallet_status"] != "OPEN":
            raise err_invalid_state("Wallet is not OPEN")
        if wallet["vc_balance"] < fee:
            raise err_insufficient_vc()
        S.post_ledger(wallet["id"], "DEBIT", fee, "PURCHASE", p["id"])
        fee_paid = True
    else:
        fee_paid = True
    rec = {
        "program_id": p["id"],
        "wallet_id": wallet["id"],
        "fee_paid": fee_paid,
        "placement": None,
        "entry_status": "REGISTERED",
    }
    stamp_new(rec, common=False)
    db.tournament_entries[rec["id"]] = rec
    # prize rows PLANNED -> PROJECTED and recompute projections
    S.recompute_projections(p)
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/tournaments/<program_id>/entries")
def list_program_entries(program_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    p = H.get_program(program_id)
    limit, offset = pagination_params()
    status = request.args.get("entry_status")
    items, total = H.list_paginated(S.entries_of_program(p["id"]),
                                    [(status, "entry_status")], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/licensing/tournaments/<program_id>/prizes")
def create_prize(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    body = body_json()
    require_fields(body, ["placement", "share_bps"])
    placement = require_int(body, "placement", 1)
    share = require_int(body, "share_bps", 0)
    rec = {
        "program_id": p["id"],
        "placement": placement,
        "share_bps": share,
        "prize_status": "PLANNED",
        "projected_amount_vc": None,
        "final_amount_vc": None,
    }
    stamp_new(rec)
    db.tournament_prizes[rec["id"]] = rec
    return ok_obj(H.serialize(rec), 201)


@bp.get("/licensing/tournaments/<program_id>/prizes")
def list_prizes(program_id):
    require_roles("LicensingAdmin", "LiveOpsManager", "FinanceController")
    p = H.get_program(program_id)
    limit, offset = pagination_params()
    items, total = H.list_paginated(S.prizes_of_program(p["id"]), [], limit, offset)
    return ok_list(items, limit, offset, total)


@bp.post("/licensing/tournaments/<program_id>/close-registration")
def close_registration_ep(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    if p["program_status"] != "REGISTRATION_OPEN":
        raise err_invalid_state("Program must be REGISTRATION_OPEN")
    S.close_registration(p)
    return ok_obj(H.serialize(p))


@bp.post("/licensing/tournaments/<program_id>/record-results")
def record_results(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    body = body_json()
    placements = body.get("placements")
    if not isinstance(placements, list):
        raise err_invalid_input("placements must be an array")
    if p["program_status"] != "REGISTRATION_CLOSED":
        raise err_invalid_state("Program must be REGISTRATION_CLOSED")
    confirmed = {e["id"]: e for e in S.entries_of_program(p["id"])
                 if e["entry_status"] == "CONFIRMED"}
    seen = set()
    for item in placements:
        if not isinstance(item, dict):
            raise err_invalid_input("Each placement must be an object")
        eid = item.get("entry_id")
        plc = item.get("placement")
        if not isinstance(eid, str) or eid not in db.tournament_entries:
            raise err_not_found(f"TournamentEntry not found: {eid}")
        entry = db.tournament_entries[eid]
        if entry["program_id"] != p["id"]:
            raise err_not_found(f"TournamentEntry {eid} not in program {p['id']}")
        if isinstance(plc, bool) or not isinstance(plc, int) or plc < 1:
            raise err_invalid_input("placement must be an integer >= 1")
        seen.add(eid)
    for eid in confirmed:
        if eid not in seen:
            raise err_invalid_input("Every CONFIRMED entry must have a placement")
    prizes = S.prizes_of_program(p["id"])
    total_share = sum(pr["share_bps"] for pr in prizes)
    if total_share != 10000:
        raise err_prize_shares()
    for item in placements:
        entry = db.tournament_entries[item["entry_id"]]
        if entry["entry_status"] == "CONFIRMED":
            entry["placement"] = item["placement"]
    p["program_status"] = "COMPLETED"
    pool = S.compute_pool(p, "FINAL")
    p["prize_pool_vc"] = pool
    amounts = S.allocate_pool(pool, [pr for pr in prizes if pr["prize_status"] == "PROJECTED"])
    for pr in prizes:
        if pr["prize_status"] == "PROJECTED":
            pr["prize_status"] = "PAYABLE"
            pr["final_amount_vc"] = amounts.get(pr["id"], 0)
            touch(pr)
    touch(p)
    return ok_obj(H.serialize(p))


@bp.post("/licensing/tournaments/<program_id>/finalize-payout")
def finalize_payout(program_id):
    require_roles(*FC)
    p = H.get_program(program_id)
    body = body_json()
    epv = body.get("expected_program_version")
    if isinstance(epv, bool) or not isinstance(epv, int):
        raise err_invalid_input("expected_program_version is required and must be an integer")
    if p["program_status"] != "COMPLETED":
        raise err_invalid_state("Program must be COMPLETED to finalize payout")
    if not p["league_sanctioned"]:
        raise err_unsanctioned()
    prizes = [pr for pr in S.prizes_of_program(p["id"]) if pr["prize_status"] == "PAYABLE"]
    winners = {e["placement"]: e for e in S.entries_of_program(p["id"])
               if e["entry_status"] == "CONFIRMED" and e["placement"] is not None}
    for pr in prizes:
        if pr["placement"] not in winners:
            raise err_invalid_state(
                f"No CONFIRMED entry at placement {pr['placement']}")
    if epv != p["version"]:
        raise err_stale_program()
    for pr in prizes:
        winner = winners[pr["placement"]]
        S.post_ledger(winner["wallet_id"], "CREDIT", pr["final_amount_vc"],
                      "PRIZE_PAYOUT", pr["id"])
        pr["prize_status"] = "PAID"
        touch(pr)
    p["program_status"] = "PAYOUT_FINALIZED"
    touch(p)
    return ok_obj(H.serialize(p))


@bp.post("/licensing/tournaments/<program_id>/cancel")
def cancel_program_ep(program_id):
    require_roles(*LOM)
    p = H.get_program(program_id)
    if p["program_status"] not in ("ANNOUNCED", "REGISTRATION_OPEN"):
        raise err_invalid_state("Program must be ANNOUNCED or REGISTRATION_OPEN to cancel")
    S.cancel_program(p)
    return ok_obj(H.serialize(p))
