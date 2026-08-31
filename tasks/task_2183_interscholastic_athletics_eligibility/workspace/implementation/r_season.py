"""Season calendar, advancement, and the seeding run."""
from flask import Blueprint

from core import (
    DB, ALL_ROLES, SPORTS, CLASSIFICATIONS, SPORT_TIERS, SEASON_STATUSES,
    auth, body, ok, ok_list, fail, req_str, req_enum, req_date, req_int, opt_int,
    new_record, touch, now_date, pagination, paginate, by_created,
    get_season, ser_season, ser_seed,
)
import calc

bp = Blueprint("seasons", __name__)


@bp.post("/athletics/sport-seasons")
def create_season():
    auth(["AssociationAdmin"])
    b = body()
    rec = new_record({
        "sport": req_enum(b, "sport", SPORTS),
        "classification": req_enum(b, "classification", CLASSIFICATIONS),
        "school_year": req_str(b, "school_year"),
        "sport_tier": req_enum(b, "sport_tier", SPORT_TIERS),
        "practice_start_date": req_date(b, "practice_start_date"),
        "first_contest_date": req_date(b, "first_contest_date"),
        "season_end_date": req_date(b, "season_end_date"),
        "age_cutoff_date": req_date(b, "age_cutoff_date"),
        "residency_deadline": req_date(b, "residency_deadline"),
        "grading_lock_date": req_date(b, "grading_lock_date"),
        "contest_limit": req_int(b, "contest_limit", minimum=1),
        "required_officials": opt_int(b, "required_officials", 2, minimum=1),
        "status": "PLANNED",
        "scheduled_contest_count": 0,
        "seeded_school_count": 0,
        "unseeded_school_count": 0,
    })
    DB.seasons[rec["id"]] = rec
    return ok(ser_season(rec), 201)


@bp.post("/athletics/sport-seasons/<sid>/advance")
def advance_season(sid):
    auth(["AssociationAdmin"])
    season = get_season(sid)
    b = body()
    to_status = req_enum(b, "to_status", SEASON_STATUSES)
    cur = season["status"]
    today = now_date()

    ok_move = False
    if cur == "PLANNED" and to_status == "PRACTICE_OPEN":
        ok_move = today >= season["practice_start_date"]
    elif cur == "PRACTICE_OPEN" and to_status == "REGULAR_SEASON":
        ok_move = today >= season["first_contest_date"]
    elif cur == "SEEDING_LOCKED" and to_status == "PLAYOFFS":
        if season["seeded_school_count"] < calc.MIN_BRACKET_SCHOOLS:
            fail("ERR_BRACKET_TOO_SMALL",
                 "the bracket holds fewer than %d seeded schools" % calc.MIN_BRACKET_SCHOOLS)
        ok_move = True
    elif cur == "PLAYOFFS" and to_status == "COMPLETED":
        ok_move = today >= season["season_end_date"]
    elif cur == "REGULAR_SEASON" and to_status == "ABANDONED":
        ok_move = True

    if not ok_move:
        fail("ERR_INVALID_STATE", "a season in %s may not move to %s" % (cur, to_status))

    season["status"] = to_status
    touch(season)
    return ok(ser_season(season))


@bp.post("/athletics/sport-seasons/<sid>/seed")
def seed_season(sid):
    auth(["AssociationAdmin"])
    season = get_season(sid)
    if season["status"] != "REGULAR_SEASON":
        fail("ERR_INVALID_STATE", "seeding is declared only from REGULAR_SEASON")
    contests = [c for c in DB.contests.values() if c["sport_season_id"] == season["id"]]
    if any(c["status"] not in ("PLAYED", "FORFEITED") for c in contests):
        fail("ERR_SEASON_HAS_OPEN_CONTESTS", "the season still holds open contests")
    if not any(c["status"] in ("PLAYED", "FORFEITED") for c in contests):
        fail("ERR_SEEDING_EMPTY_SNAPSHOT", "the seeding snapshot is empty")

    rows, unseeded = calc.playoff_seed_assignment(season)
    for row in rows:
        rec = new_record(row, versioned=False)
        DB.seeds[rec["id"]] = rec
    season["seeded_school_count"] = len(rows)
    season["unseeded_school_count"] = unseeded
    season["status"] = "SEEDING_LOCKED"
    touch(season)
    return ok(ser_season(season))


@bp.get("/athletics/sport-seasons/<sid>")
def read_season(sid):
    auth(ALL_ROLES)
    return ok(ser_season(get_season(sid)))


@bp.get("/athletics/sport-seasons/<sid>/playoff-seeds")
def list_season_seeds(sid):
    auth(ALL_ROLES)
    season = get_season(sid)
    limit, offset = pagination()
    rows = [s for s in DB.seeds.values() if s["sport_season_id"] == season["id"]]
    rows.sort(key=lambda r: (r["seed_number"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_seed(s) for s in page], limit, offset, total)
