"""AdCampaign lifecycle."""
import clock
import util
from db import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE


def create_campaign(body):
    util.require_fields(body, [
        "advertiser_code", "flight_start", "flight_end",
        "frequency_cap_per_viewer", "frequency_window_hours",
        "cpm_cents", "region_target",
    ])
    util.req_str(body["advertiser_code"], "advertiser_code")
    flight_start = util.req_dt(body["flight_start"], "flight_start")
    flight_end = util.req_dt(body["flight_end"], "flight_end")
    if not flight_end > flight_start:
        raise_err(ERR_INVALID_REQUEST, "flight_end must be strictly after flight_start")
    cap = util.req_int(body["frequency_cap_per_viewer"], "frequency_cap_per_viewer", minimum=1)
    win_hours = util.req_int(body["frequency_window_hours"], "frequency_window_hours", minimum=1)
    cpm = util.req_int(body["cpm_cents"], "cpm_cents", minimum=1)
    region_target = util.req_str_list(body["region_target"], "region_target", allow_empty=True)
    now_iso = clock.now_iso()
    camp = {
        "id": util.new_id(),
        "advertiser_code": body["advertiser_code"],
        "campaign_status": "DRAFT",
        "flight_start": flight_start,
        "flight_end": flight_end,
        "frequency_cap_per_viewer": cap,
        "frequency_window_hours": win_hours,
        "cpm_cents": cpm,
        "region_target": region_target,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }
    db.ad_campaigns[camp["id"]] = camp
    return camp


def book(camp):
    if camp["campaign_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "campaign not DRAFT")
    if not camp["flight_start"] < camp["flight_end"]:
        raise_err(ERR_INVALID_STATE, "invalid flight")
    if not camp["flight_end"] >= clock.now():
        raise_err(ERR_INVALID_STATE, "flight already ended")
    camp["campaign_status"] = "BOOKED"
    util.touch(camp)
    return camp


def pause(camp):
    if camp["campaign_status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "campaign not BOOKED")
    camp["campaign_status"] = "PAUSED"
    util.touch(camp)
    return camp


def resume(camp):
    if camp["campaign_status"] != "PAUSED":
        raise_err(ERR_INVALID_STATE, "campaign not PAUSED")
    if not camp["flight_end"] >= clock.now():
        raise_err(ERR_INVALID_STATE, "flight already ended")
    camp["campaign_status"] = "BOOKED"
    util.touch(camp)
    return camp
