"""Grassroots campaign and action alert endpoints (PRD 3.7)."""
from flask import Blueprint

import derive
from constants import ALL_ROLES, API_PREFIX, CHAMBERS, JURISDICTIONS
from core import (
    arg, authenticate, body, fail, filtered, format_instant, insert, now_dt, respond, touch,
)
from serializers import dump, listing
from validate import get_district, get_enum, get_int, get_str

bp = Blueprint("grassroots", __name__, url_prefix=API_PREFIX)


def _campaign(campaign_id):
    return derive.lookup("campaigns", campaign_id, "ERR_CAMPAIGN_NOT_FOUND")


@bp.post("/grassroots-campaigns")
def launch_campaign():
    authenticate(["GovAffairsDirector"])
    payload = body()
    position_id = get_str(payload, "position_id")
    name = get_str(payload, "name", max_len=200)
    target_jurisdiction_code = get_enum(payload, "target_jurisdiction_code", JURISDICTIONS)
    position = derive.lookup("positions", position_id, "ERR_POSITION_NOT_FOUND")
    if position["status"] != "ADOPTED":
        fail("ERR_POSITION_NOT_ADOPTED", "Only an ADOPTED position may be advanced.")
    if position["jurisdiction_code"] != target_jurisdiction_code:
        fail("ERR_JURISDICTION_SCOPE_MISMATCH",
             "The campaign must target the position's own jurisdiction.")
    campaign = insert("campaigns", {
        "position_id": position_id,
        "name": name,
        "target_jurisdiction_code": target_jurisdiction_code,
        "status": "PLANNED",
        "alert_count": 0,
        "matched_member_total": 0,
        "unmatched_alert_count": 0,
        "cumulative_cost_cents": 0,
        "disclosure_required": False,
        "last_alert_at": None,
    })
    return respond(dump("campaigns", campaign), status=201)


@bp.get("/grassroots-campaigns/<campaign_id>")
def read_campaign(campaign_id):
    authenticate(ALL_ROLES)
    return respond(dump("campaigns", _campaign(campaign_id)))


@bp.post("/grassroots-campaigns/<campaign_id>/alerts")
def dispatch_alert(campaign_id):
    authenticate(["GovAffairsDirector"])
    campaign = _campaign(campaign_id)
    payload = body()
    target_district_code = get_district(payload, "target_district_code")
    target_chamber = get_enum(payload, "target_chamber", CHAMBERS)
    message_subject = get_str(payload, "message_subject", max_len=200)
    unit_cost_cents = get_int(payload, "unit_cost_cents", minimum=0)
    if campaign["status"] == "CLOSED":
        fail("ERR_INVALID_CAMPAIGN_STATE", "A CLOSED campaign dispatches no further alert.")
    dispatch_dt = now_dt()
    if not derive.cooling_window_ok(campaign, dispatch_dt):
        fail("ERR_ALERT_COOLING_PERIOD",
             "An alert must follow the previous dispatch by at least 48 hours.")
    matched = derive.constituent_match_set(campaign, target_district_code)
    alert = insert("alerts", {
        "campaign_id": campaign_id,
        "target_district_code": target_district_code,
        "target_chamber": target_chamber,
        "message_subject": message_subject,
        "unit_cost_cents": unit_cost_cents,
        "matched_member_ids": matched,
        "matched_member_count": len(matched),
        "cost_cents": unit_cost_cents * len(matched),
        "status": "DISPATCHED" if matched else "NO_MATCH",
        "dispatched_at": format_instant(dispatch_dt),
    }, common=False)
    snap = derive.snapshot(campaign, derive.CAMPAIGN_TRACKED)
    derive.compute_campaign_accumulators(campaign)
    if alert["status"] == "DISPATCHED":
        campaign["last_alert_at"] = alert["dispatched_at"]
        if campaign["status"] == "PLANNED":
            campaign["status"] = "LIVE"
    derive.touch_if_changed(campaign, snap)
    return respond(dump("alerts", alert), status=201)


@bp.get("/grassroots-campaigns/<campaign_id>/alerts")
def list_alerts(campaign_id):
    authenticate(ALL_ROLES)
    _campaign(campaign_id)
    rows = filtered(derive.campaign_alerts(campaign_id), status=arg("status"))
    return listing("alerts", rows)


@bp.post("/grassroots-campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    authenticate(["GovAffairsDirector"])
    campaign = _campaign(campaign_id)
    if campaign["status"] not in ("PLANNED", "LIVE"):
        fail("ERR_INVALID_CAMPAIGN_STATE", "This campaign is already CLOSED.")
    campaign["status"] = "CLOSED"
    touch(campaign)
    return respond(dump("campaigns", campaign))
