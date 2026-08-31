"""Schools: registration, reads, credential listing, seed listing."""
import re
from flask import Blueprint

from core import (
    DB, ALL_ROLES, CLASSIFICATIONS, SPORTS, auth, body, ok, ok_list, fail,
    req_str, req_enum, opt_str, opt_int, new_record, pagination, paginate,
    by_created, get_school, ser_school, ser_credential, ser_seed,
)
from flask import request

bp = Blueprint("schools", __name__)

HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
CREDENTIAL_STATUSES = ["BACKGROUND_PENDING", "CLEARED", "DENIED", "EXPIRED", "REVOKED"]


@bp.post("/athletics/schools")
def create_school():
    auth(["AssociationAdmin"])
    b = body()
    name = req_str(b, "name")
    classification = req_enum(b, "classification", CLASSIFICATIONS)
    region_code = req_str(b, "region_code")
    hhmm = opt_str(b, "school_day_end_utc_hhmm", "20:30")
    if not HHMM_RE.match(hhmm or ""):
        fail("ERR_INVALID_REQUEST", "school_day_end_utc_hhmm must be HH:MM 24-hour UTC")
    bus_fleet_size = opt_int(b, "bus_fleet_size", 4, minimum=1)
    max_release = opt_int(b, "max_release_minutes_per_request", 240, minimum=0)
    fee_cap = opt_int(b, "fee_cap_cents", 20000, minimum=0)
    venue_cap = opt_int(b, "venue_concurrent_capacity", 1, minimum=1)

    rec = new_record({
        "name": name,
        "classification": classification,
        "region_code": region_code,
        "school_day_end_utc_hhmm": hhmm,
        "bus_fleet_size": bus_fleet_size,
        "max_release_minutes_per_request": max_release,
        "fee_cap_cents": fee_cap,
        "venue_concurrent_capacity": venue_cap,
        "sanction_status": "GOOD_STANDING",
        "forfeit_count": 0,
        "release_minutes_used": 0,
        "fee_collected_cents": 0,
        "credential_gap_sports": [],
    })
    DB.schools[rec["id"]] = rec
    return ok(ser_school(rec), 201)


@bp.get("/athletics/schools/<sid>")
def read_school(sid):
    auth(ALL_ROLES)
    return ok(ser_school(get_school(sid)))


@bp.get("/athletics/schools/<sid>/staff-credentials")
def list_school_credentials(sid):
    auth(ALL_ROLES)
    school = get_school(sid)
    limit, offset = pagination()
    rows = [c for c in DB.credentials.values() if c["school_id"] == school["id"]]
    sport = request.args.get("sport")
    if sport is not None:
        rows = [c for c in rows if c["sport"] == sport]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows = by_created(rows, reverse=True)
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_credential(c) for c in page], limit, offset, total)


@bp.get("/athletics/schools/<sid>/playoff-seeds")
def list_school_seeds(sid):
    auth(ALL_ROLES)
    school = get_school(sid)
    limit, offset = pagination()
    rows = by_created([s for s in DB.seeds.values() if s["school_id"] == school["id"]])
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_seed(s) for s in page], limit, offset, total)
