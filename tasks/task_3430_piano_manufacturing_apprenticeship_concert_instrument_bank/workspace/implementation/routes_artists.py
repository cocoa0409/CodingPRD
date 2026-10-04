"""Artist endpoints (PRD 3.5): register, fetch, performances, annual review."""
from datetime import timedelta

from flask import Blueprint

from auth import ALL_ROLES, authenticate
from db import STORE, clock_now, new_entity, touch
from envelope import ok
from errors import raise_err
from serialize import artist as ser_artist
from validate import get_body, req_dt, req_enum, req_int, req_str

bp = Blueprint("artists", __name__, url_prefix="/piano-works")

TIERS = ("STANDARD", "PRIVILEGED")
LIAISON = ("ArtistLiaison",)
REVIEW_PERIOD = timedelta(days=365)


def _get_artist(aid):
    a = STORE["artists"].get(aid)
    if a is None:
        raise_err("ERR_NOT_FOUND", "artist %s not found" % aid)
    return a


@bp.post("/artists")
def create_artist():
    authenticate(LIAISON)
    body = get_body()
    name = req_str(body, "name")
    tier = req_enum(body, "tier", TIERS)
    quota = req_int(body, "performance_quota", minimum=1)
    now = clock_now()
    a = new_entity()
    a.update({
        "name": name,
        "tier": tier,
        "performance_quota": quota,
        "performances_logged": 0,
        "status": "ACTIVE",
        "next_review_date": now + REVIEW_PERIOD,
    })
    STORE["artists"][a["id"]] = a
    return ok(ser_artist(a), 201)


@bp.get("/artists/<aid>")
def get_artist(aid):
    authenticate(ALL_ROLES)
    return ok(ser_artist(_get_artist(aid)))


@bp.post("/artists/<aid>/performances")
def log_performance(aid):
    authenticate(LIAISON)
    a = _get_artist(aid)
    body = get_body()
    req_str(body, "venue")
    performed_at = req_dt(body, "performed_at")
    if performed_at > clock_now():
        raise_err("ERR_PERFORMANCE_IN_FUTURE", "performed_at is after the current logical clock")
    a["performances_logged"] += 1
    touch(a)
    return ok(ser_artist(a))


@bp.post("/artists/<aid>/review")
def review_artist(aid):
    authenticate(LIAISON)
    a = _get_artist(aid)
    get_body()
    now = clock_now()
    if now < a["next_review_date"]:
        raise_err("ERR_REVIEW_NOT_DUE", "review is not due until next_review_date")
    met = a["performances_logged"] >= a["performance_quota"]
    if a["status"] == "ACTIVE":
        if met:
            a["performances_logged"] = 0
            a["next_review_date"] = a["next_review_date"] + REVIEW_PERIOD
        else:
            # Suspension retains the count and the review date for catch-up.
            a["status"] = "SUSPENDED"
    else:  # SUSPENDED
        if met:
            a["status"] = "ACTIVE"
            a["performances_logged"] = 0
            a["next_review_date"] = now + REVIEW_PERIOD
        # else: stays SUSPENDED, no field changes except version.
    touch(a)
    return ok(ser_artist(a))
