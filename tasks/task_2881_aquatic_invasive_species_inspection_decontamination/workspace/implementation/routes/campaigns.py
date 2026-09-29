"""Public education campaigns: allocation and evaluation (PRD 3.9)."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from calc import rhu
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, now, parse_iso, serialize, touch
from validate import (arg_filter, opt_enum, opt_int, opt_str, read_body,
                      req_dt, req_enum, req_int, req_ref, req_str,
                      require_auth)

bp = Blueprint("campaigns", __name__)

METHODS = ("PRE_POST", "CONTROL_CORRIDOR")
CAMPAIGN_STATUSES = ("PLANNED", "RUNNING", "EVALUATED", "CANCELLED")


@bp.post("/education-campaigns")
def create_campaign():
    require_auth(("ProgramAdmin",))
    body = read_body()
    name = req_str(body, "name")
    target_id = req_ref(body, "target_water_body_id")
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    budget_cents = req_int(body, "budget_cents", exclusive_min=0)
    method = opt_enum(body, "evaluation_method", METHODS)
    impressions = opt_int(body, "impressions", 0, minimum=0)
    if not (end_at > start_at):
        raise ApiError("ERR_INVALID_REQUEST",
                       "end_at must be strictly later than start_at.")

    services.water_body_or_404(target_id)

    if budget_cents > calc.CAMPAIGN_BUDGET_CAP_CENTS:
        raise ApiError("ERR_CAMPAIGN_BUDGET_EXCEEDED")

    row = base_row()
    row.update({
        "name": name,
        "target_water_body_id": target_id,
        "start_at": fmt_iso(start_at),
        "end_at": fmt_iso(end_at),
        "budget_cents": budget_cents,
        "impressions": impressions,
        "status": "PLANNED",
        "evaluation_method": method,
        "window_compliance_rate": None,
        "baseline_compliance_rate": None,
        "effectiveness_score": None,
        "alternate_effectiveness_score": None,
        "station_allocations": [],
    })
    db.campaigns[row["id"]] = row
    return created(serialize(row))


@bp.get("/education-campaigns/<cid>")
def get_campaign(cid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.campaign_or_404(cid)))


@bp.get("/education-campaigns")
def list_campaigns():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "target_water_body_id": arg_filter("target_water_body_id"),
        "status": arg_filter("status"),
        "evaluation_method": arg_filter("evaluation_method"),
    }
    rows = [r for r in db.campaigns.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/education-campaigns/<cid>/status")
def set_campaign_status(cid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    target = req_enum(body, "target_status", CAMPAIGN_STATUSES)
    opt_str(body, "reason", min_len=None)

    campaign = services.campaign_or_404(cid)
    current = campaign["status"]

    if target == "RUNNING" and current == "PLANNED":
        if campaign["budget_cents"] > calc.CAMPAIGN_BUDGET_CAP_CENTS:
            raise ApiError("ERR_CAMPAIGN_BUDGET_EXCEEDED")
        services.allocate_campaign(campaign)
        campaign["status"] = "RUNNING"
    elif target == "CANCELLED" and current == "PLANNED":
        campaign["status"] = "CANCELLED"
    elif target == "CANCELLED" and current == "RUNNING":
        services.deallocate_campaign(campaign)
        campaign["status"] = "CANCELLED"
    else:
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    touch(campaign)
    return ok(serialize(campaign))


@bp.post("/education-campaigns/<cid>/evaluation")
def evaluate_campaign(cid):
    require_auth(("ProgramAdmin",))
    body = read_body()
    method = opt_enum(body, "evaluation_method", METHODS)
    impressions = opt_int(body, "impressions", None, minimum=0)

    campaign = services.campaign_or_404(cid)

    if campaign["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_CAMPAIGN_STATE")

    start = parse_iso(campaign["start_at"])
    end = parse_iso(campaign["end_at"])
    if now() < end:
        raise ApiError("ERR_EVALUATION_WINDOW_NOT_ENDED")

    target_id = campaign["target_water_body_id"]
    measured = services.compliance_rate(target_id, start, end)
    if measured is None:
        raise ApiError("ERR_NO_INSPECTIONS_IN_WINDOW")
    window_rate = rhu(measured, 4)

    length = end - start
    pre_post = services.compliance_rate(target_id, start - length, start)
    if pre_post is None:
        pre_post = Decimal("0")
    control = services.compliance_rate(None, start, end)
    if control is None:
        control = Decimal("0")

    if impressions is not None:
        campaign["impressions"] = impressions
    bonus = calc.impressions_bonus(campaign["impressions"])

    pre_post_score = calc.effectiveness_score(window_rate, pre_post, bonus)
    control_score = calc.effectiveness_score(window_rate, control, bonus)

    chosen = method or campaign["evaluation_method"] or "PRE_POST"
    if chosen == "PRE_POST":
        baseline, score, alternate = pre_post, pre_post_score, control_score
    else:
        baseline, score, alternate = control, control_score, pre_post_score

    campaign["evaluation_method"] = chosen
    campaign["window_compliance_rate"] = float(window_rate)
    campaign["baseline_compliance_rate"] = float(rhu(baseline, 4))
    campaign["effectiveness_score"] = float(score)
    campaign["alternate_effectiveness_score"] = float(alternate)
    campaign["status"] = "EVALUATED"
    touch(campaign)
    return ok(serialize(campaign))
