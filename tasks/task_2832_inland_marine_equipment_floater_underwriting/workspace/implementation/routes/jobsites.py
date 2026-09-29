from flask import Blueprint

import cascades
import rating
import store
import views
from common import (API_PREFIX, body, clock_now, envelope_object, get_bool,
                    get_enum, get_str, require)

bp = Blueprint("jobsites", __name__)


@bp.post(API_PREFIX + "/jobsites")
def create_jobsite():
    require("Underwriter")
    b = body()
    name = get_str(b, "name", max_len=200)
    territory_code = get_enum(b, "territory_code", rating.TERRITORIES)
    row = store.make({
        "name": name,
        "territory_code": territory_code,
        "fenced": False,
        "lighting": False,
        "alarm_monitored": False,
        "guarded_24h": False,
        "security_score": 0,
        "security_tier": "TIER_0",
        "status": "UNSURVEYED",
        "active_floater_count": 0,
        "surveyed_at": None,
    })
    store.jobsites[row["id"]] = row
    return envelope_object(views.jobsite_view(row), 201)


@bp.get(API_PREFIX + "/jobsites/<jobsite_id>")
def get_jobsite(jobsite_id):
    require("Underwriter", "UnderwritingManager", "ClaimsAdjuster")
    jobsite = store.find(store.jobsites, jobsite_id, "ERR_JOBSITE_NOT_FOUND")
    return envelope_object(views.jobsite_view(jobsite), 200)


@bp.post(API_PREFIX + "/jobsites/<jobsite_id>/security-survey")
def survey_jobsite(jobsite_id):
    require("Underwriter")
    jobsite = store.find(store.jobsites, jobsite_id, "ERR_JOBSITE_NOT_FOUND")
    b = body()
    fenced = get_bool(b, "fenced")
    lighting = get_bool(b, "lighting")
    alarm_monitored = get_bool(b, "alarm_monitored")
    guarded_24h = get_bool(b, "guarded_24h")
    score = rating.jobsite_security_score(fenced, lighting, alarm_monitored, guarded_24h)
    tier = rating.jobsite_security_tier(score)

    # A re-survey that would strand a grade-A unit without a tracker is
    # rejected wholesale; nothing changes.
    for item in store.order(list(store.equipment_items.values())):
        if item.get("assigned_jobsite_id") != jobsite_id:
            continue
        if item["status"] not in rating.ON_SCHEDULE_STATUSES:
            continue
        cascades.check_geo_tracking(item, None, jobsite, tier=tier)

    jobsite["fenced"] = fenced
    jobsite["lighting"] = lighting
    jobsite["alarm_monitored"] = alarm_monitored
    jobsite["guarded_24h"] = guarded_24h
    jobsite["security_score"] = score
    jobsite["security_tier"] = tier
    jobsite["status"] = "SURVEYED"
    jobsite["surveyed_at"] = clock_now()
    store.touch(jobsite)
    cascades.rerate_items_on_jobsite(jobsite)
    return envelope_object(views.jobsite_view(jobsite), 200)
