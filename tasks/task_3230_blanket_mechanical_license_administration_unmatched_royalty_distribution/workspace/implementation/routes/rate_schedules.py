"""RateSchedule endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_schedule
from response import ok_list, ok_object
from util import body_json, make_record, touch, parse_iso

bp = Blueprint("rate_schedules", __name__)

ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher")

# RateSchedule versions seed from a per-class sequence so that two different
# schedules can never share a version value; the DSP's
# accepted_rate_schedule_version tracks "the version of the ACTIVE schedule"
# (PRD §3.1/§2.8), which only strands stale acknowledgements if activation
# versions are distinct across schedules.
_schedule_version_seq = [0]


def _next_schedule_version():
    _schedule_version_seq[0] += 1
    return _schedule_version_seq[0]


def schedule_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.route("/mlc/rate-schedules", methods=["POST"])
@require_roles(*ADMIN)
def create_schedule(_user_id, _role):
    body = body_json(required=("effective_from", "rate_cents_under_5min",
                               "rate_cents_per_minute_over_5min"))
    ef = parse_iso(body["effective_from"], "effective_from")
    et = parse_iso(body["effective_to"], "effective_to") if body.get("effective_to") else None
    for f in ("rate_cents_under_5min", "rate_cents_per_minute_over_5min"):
        if not isinstance(body[f], int) or body[f] < 0:
            raise err("ERR_INVALID_REQUEST", f"{f} must be a non-negative integer")
    rec = make_record()
    rec["version"] = _next_schedule_version()
    rec.update({
        "effective_from": body["effective_from"],
        "effective_to": body.get("effective_to"),
        "rate_cents_under_5min": body["rate_cents_under_5min"],
        "rate_cents_per_minute_over_5min": body["rate_cents_per_minute_over_5min"],
        "status": "PENDING",
        "_effective_from_dt": ef,
        "_effective_to_dt": et,
    })
    db.rate_schedules[rec["id"]] = rec
    return ok_object(schedule_view(rec), 201)


@bp.route("/mlc/rate-schedules", methods=["GET"])
@require_roles(*READ)
def list_schedules(_user_id, _role):
    items = sorted(db.rate_schedules.values(), key=lambda s: s["created_at"])
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    return ok_list([schedule_view(s) for s in items])


@bp.route("/mlc/rate-schedules/<schedule_id>", methods=["GET"])
@require_roles(*READ)
def get_one_schedule(schedule_id, _user_id, _role):
    return ok_object(schedule_view(get_schedule(schedule_id)))


def _overlaps(a_from, a_to, b_from, b_to):
    """Half-open overlap of [a_from,a_to) and [b_from,b_to); None end = open."""
    if b_to is not None and not (a_from < b_to):
        return False
    if a_to is not None and not (b_from < a_to):
        return False
    return True


@bp.route("/mlc/rate-schedules/<schedule_id>/activate", methods=["POST"])
@require_roles(*ADMIN)
def activate_schedule(schedule_id, _user_id, _role):
    s = get_schedule(schedule_id)
    if s["status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    if s["_effective_from_dt"] > db.now():
        raise err("ERR_RATE_SCHEDULE_NOT_YET_EFFECTIVE")
    active = next(
        (x for x in db.rate_schedules.values() if x["status"] == "ACTIVE"), None)
    if active is not None and _overlaps(
            s["_effective_from_dt"], s["_effective_to_dt"],
            active["_effective_from_dt"], active["_effective_to_dt"]):
        raise err("ERR_RATE_SCHEDULE_OVERLAP")
    if active is not None:
        active["status"] = "SUPERSEDED"
        touch(active)
    s["status"] = "ACTIVE"
    touch(s)
    # Bubble up: bump accepted_rate_schedule_version on ACTIVE/SUSPENDED DSPs
    for sp in db.service_providers.values():
        if sp["participation_status"] in ("ACTIVE", "SUSPENDED"):
            sp["accepted_rate_schedule_version"] = s["version"]
            touch(sp)
    return ok_object(schedule_view(s))
