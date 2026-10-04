"""Advertisement, bid opening, and award with DBE review (PRD §3.6)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from calculations import MIN_ADVERTISEMENT_DAYS, select_winning_bid
from db import STORE, clock, new_id, now_bookkeeping, touch
from errors import err
from helpers import as_bool, as_int, as_number, as_str, get_body, paginate, req_field
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from routes_projects import _resolve_project
from serializers import serialize_bid, serialize_project

bp = Blueprint("bidding", __name__)


@bp.route("/federal-aid/projects/<pid>/advertise", methods=["POST"])
@require_roles("StateDOTEngineer")
def advertise_project(pid, user_id, user_role):
    project = _resolve_project(pid)
    get_body()
    if project["status"] != "AUTHORIZED":
        raise err("ERR_INVALID_STATE", "Project is not in AUTHORIZED")
    project["advertised_on_date"] = clock.raw
    project["_advertised_dt"] = clock.dt
    project["status"] = "BIDDING"
    touch(project)
    return success_object(serialize_project(project))


@bp.route("/federal-aid/projects/<pid>/open-bids", methods=["POST"])
@require_roles("StateDOTEngineer")
def open_bids(pid, user_id, user_role):
    project = _resolve_project(pid)
    body = get_body()
    bids_payload = req_field(body, "bids")
    if not isinstance(bids_payload, list) or len(bids_payload) == 0:
        raise err("ERR_INVALID_REQUEST", "bids must be a non-empty array")
    for entry in bids_payload:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "each bid must be an object")
        as_str(req_field(entry, "contractor_name"), "contractor_name")
        amount = as_int(req_field(entry, "bid_amount_cents"), "bid_amount_cents")
        if amount <= 0:
            raise err("ERR_INVALID_REQUEST", "bid_amount_cents must be greater than 0")
        as_bool(req_field(entry, "is_responsive"), "is_responsive")
    if project["status"] != "BIDDING":
        raise err("ERR_INVALID_STATE", "Project is not in BIDDING")
    if clock.dt < project["_advertised_dt"] + timedelta(days=MIN_ADVERTISEMENT_DAYS):
        raise err(
            "ERR_ADVERTISEMENT_PERIOD_SHORT",
            "The 21-day advertisement period has not elapsed",
        )
    now = now_bookkeeping()
    for seq, entry in enumerate(bids_payload):
        rec = {
            "id": new_id(),
            "project_id": pid,
            "contractor_name": entry["contractor_name"],
            "bid_amount_cents": entry["bid_amount_cents"],
            "is_responsive": entry["is_responsive"],
            "submission_seq": seq,
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        STORE["bids"][rec["id"]] = rec
    project["status"] = "BIDS_OPENED"
    touch(project)
    return success_object(serialize_project(project))


@bp.route("/federal-aid/projects/<pid>/award", methods=["POST"])
@require_roles("FHWAReviewer")
def award_project(pid, user_id, user_role):
    project = _resolve_project(pid)
    body = get_body()
    bid_id = as_str(req_field(body, "bid_id"), "bid_id")
    commitment = as_number(req_field(body, "dbe_commitment_pct"), "dbe_commitment_pct")
    gfe = body.get("good_faith_effort_documented", False)
    if gfe is None:
        gfe = False
    if not isinstance(gfe, bool):
        raise err(
            "ERR_INVALID_REQUEST", "good_faith_effort_documented must be a boolean"
        )
    # State gate (priority 6) precedes the body-FK resolution on action
    # endpoints (PRD §2.9).
    if project["status"] != "BIDS_OPENED":
        raise err("ERR_INVALID_STATE", "Project is not in BIDS_OPENED")
    bid = STORE["bids"].get(bid_id)
    if bid is None:
        raise err("ERR_NOT_FOUND", "bid_id does not resolve to an existing Bid")
    # DBE check (priority 14) outranks the entire bid-pool family (25-27).
    if not gfe and Decimal(str(commitment)) < Decimal(str(project["dbe_goal_pct"])):
        raise err(
            "ERR_DBE_GOAL_NOT_MET",
            "DBE commitment below the project goal without documented good-faith effort",
        )
    project_bids = [b for b in STORE["bids"].values() if b["project_id"] == pid]
    winner = select_winning_bid(project_bids)
    if winner is None:
        raise err("ERR_NO_RESPONSIVE_BIDS", "The project has no responsive bids")
    if bid["project_id"] != pid or not bid["is_responsive"]:
        raise err(
            "ERR_BID_NOT_RESPONSIVE",
            "The named bid does not belong to this project or is not responsive",
        )
    if bid["id"] != winner["id"]:
        raise err(
            "ERR_AWARD_NOT_LOWEST_RESPONSIVE",
            "The named bid is not the lowest responsive bid",
        )
    for b in project_bids:
        b["status"] = "AWARDED" if b["id"] == bid["id"] else "NOT_AWARDED"
        touch(b)
    project["awarded_bid_id"] = bid["id"]
    project["status"] = "UNDER_CONSTRUCTION"
    touch(project)
    return success_object(serialize_project(project))


@bp.route("/federal-aid/projects/<pid>/bids", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_bids(pid, user_id, user_role):
    _resolve_project(pid)
    items = [b for b in STORE["bids"].values() if b["project_id"] == pid]
    items.sort(key=lambda b: b["submission_seq"])  # submission order
    page, total, limit, offset = paginate(items)
    return success_list([serialize_bid(b) for b in page], total, limit, offset)
