"""Campaign routes."""
import uuid
from flask import Blueprint

import db
from errors import err
from response import (ok, list_response, require_role, require_auth, get_body,
                      req_str, req_enum, req_int, parse_dt)
from services import (get_mill, get_campaign, get_heat, new_common, bump,
                      campaign_lines_for, recompute_roll_changes, check_occ)

bp = Blueprint("campaigns", __name__)


@bp.route("/mills/<millId>/campaigns", methods=["POST"])
def create_campaign(millId):
    require_role("Scheduler")
    get_mill(millId)
    body = get_body()
    name = req_str(body, "name")
    family = req_enum(body, "product_family", {"REBAR", "BEAM", "PLATE", "WIRE_ROD"})
    group = req_enum(body, "grade_group", {"GROUP_A", "GROUP_B"})
    start = parse_dt(req_str(body, "planned_start"), "planned_start")
    end = parse_dt(req_str(body, "planned_end"), "planned_end")
    budget = req_int(body, "roll_change_budget", ge=0)
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "planned_end must be after planned_start")
    camp = {
        "id": str(uuid.uuid4()),
        "mill_id": millId,
        "name": name,
        "product_family": family,
        "grade_group": group,
        "planned_start": start,
        "planned_end": end,
        "roll_changes_used": 0,
        "roll_change_budget": budget,
        "status": "OPEN",
        **new_common(),
    }
    db.campaigns[camp["id"]] = camp
    return ok(camp, 201)


@bp.route("/mills/<millId>/campaigns", methods=["GET"])
def list_campaigns(millId):
    require_auth()
    get_mill(millId)
    rows = [c for c in db.campaigns.values() if c["mill_id"] == millId]
    return list_response(rows, {"status": "status", "product_family": "product_family"})


@bp.route("/mills/<millId>/campaigns/<campaignId>", methods=["GET"])
def get_campaign_route(millId, campaignId):
    require_auth()
    get_mill(millId)
    return ok(get_campaign(campaignId, millId))


@bp.route("/mills/<millId>/campaigns/<campaignId>/lines", methods=["POST"])
def add_line(millId, campaignId):
    require_role("Scheduler")
    get_mill(millId)
    camp = get_campaign(campaignId, millId)
    body = get_body()
    heat_id = req_str(body, "heat_id")
    heat = get_heat(heat_id, millId)
    if camp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "campaign is not OPEN")
    if heat["status"] != "CAST":
        raise err("ERR_HEAT_NOT_CAST", "heat is not CAST")
    line = {
        "id": str(uuid.uuid4()),
        "campaign_id": campaignId,
        "heat_id": heat_id,
        "campaign_grade_group": camp["grade_group"],
        "created_at": db.ts_now(),
    }
    db.campaign_lines[line["id"]] = line
    recompute_roll_changes(camp)
    bump(camp)
    return ok(line, 201)


@bp.route("/mills/<millId>/campaigns/<campaignId>/lines", methods=["GET"])
def list_lines(millId, campaignId):
    require_auth()
    get_mill(millId)
    get_campaign(campaignId, millId)
    rows = campaign_lines_for(campaignId)
    return list_response(rows, {"heat_id": "heat_id"})


@bp.route("/mills/<millId>/campaigns/<campaignId>/commit", methods=["POST"])
def commit_campaign(millId, campaignId):
    require_role("Scheduler")
    get_mill(millId)
    camp = get_campaign(campaignId, millId)
    body = get_body()
    if "expected_campaign_version" not in body:
        raise err("ERR_INVALID_REQUEST", "expected_campaign_version is required")
    expected = body.get("expected_campaign_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_campaign_version must be an integer")
    if camp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "campaign is not OPEN")
    check_occ(camp, expected)
    lines = campaign_lines_for(campaignId)
    if len(lines) == 0:
        raise err("ERR_CAMPAIGN_EMPTY", "campaign has no lines")
    for line in lines:
        heat = db.heats[line["heat_id"]]
        if heat["status"] != "CAST":
            raise err("ERR_HEAT_NOT_CAST", "line heat is not CAST")
        if not (camp["planned_start"] <= heat["planned_tap_at"] <= camp["planned_end"]):
            raise err("ERR_CAMPAIGN_WINDOW_VIOLATION",
                      "line heat planned_tap_at outside campaign window")
    for other in db.campaigns.values():
        if (other["mill_id"] == millId and other["id"] != campaignId
                and other["product_family"] == camp["product_family"]
                and other["status"] == "COMMITTED"):
            if (camp["planned_start"] < other["planned_end"]
                    and other["planned_start"] < camp["planned_end"]):
                raise err("ERR_CAMPAIGN_OVERLAP",
                          "overlaps a COMMITTED same-family campaign")
    used = recompute_roll_changes(camp)
    if used > camp["roll_change_budget"]:
        raise err("ERR_ROLL_CHANGE_BUDGET_EXCEEDED", "roll change budget exceeded")
    camp["status"] = "COMMITTED"
    bump(camp)
    return ok(camp)


@bp.route("/mills/<millId>/campaigns/<campaignId>/close", methods=["POST"])
def close_campaign(millId, campaignId):
    require_role("Scheduler")
    get_mill(millId)
    camp = get_campaign(campaignId, millId)
    if camp["status"] != "COMMITTED":
        raise err("ERR_INVALID_STATE", "campaign is not COMMITTED")
    lines = campaign_lines_for(campaignId)
    for line in lines:
        heat = db.heats[line["heat_id"]]
        for order in db.orders.values():
            if (order["mill_id"] == millId
                    and order["grade_id"] == heat["grade_id"]
                    and order["product_family"] == camp["product_family"]
                    and order["status"] in ("CONFIRMED", "ALLOCATED")):
                raise err("ERR_UNRESOLVED_ORDERS",
                          "served orders are still CONFIRMED or ALLOCATED")
    camp["status"] = "CLOSED"
    bump(camp)
    return ok(camp)


@bp.route("/mills/<millId>/campaigns/<campaignId>/cancel", methods=["POST"])
def cancel_campaign(millId, campaignId):
    require_role("Scheduler")
    get_mill(millId)
    camp = get_campaign(campaignId, millId)
    if camp["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "campaign is not OPEN")
    for lid in [l["id"] for l in db.campaign_lines.values() if l["campaign_id"] == campaignId]:
        del db.campaign_lines[lid]
    camp["roll_changes_used"] = 0
    camp["status"] = "CANCELLED"
    bump(camp)
    return ok(camp)


# --- flat reads ---------------------------------------------------------------

@bp.route("/mills/campaigns", methods=["GET"])
def flat_list_campaigns():
    require_auth()
    return list_response(list(db.campaigns.values()),
                         {"mill_id": "mill_id", "status": "status",
                          "product_family": "product_family"})


@bp.route("/mills/campaigns/<campaignId>", methods=["GET"])
def flat_get_campaign(campaignId):
    require_auth()
    return ok(get_campaign(campaignId))


@bp.route("/mills/campaign-lines", methods=["GET"])
def flat_list_lines():
    require_auth()
    return list_response(list(db.campaign_lines.values()),
                         {"campaign_id": "campaign_id", "heat_id": "heat_id"})


@bp.route("/mills/campaign-lines/<lineId>", methods=["GET"])
def flat_get_line(lineId):
    require_auth()
    line = db.campaign_lines.get(lineId)
    if line is None:
        raise err("ERR_INVALID_REQUEST", "campaign line not found")
    return ok(line)
