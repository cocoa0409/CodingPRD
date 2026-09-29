"""The replay centre: booths, decision windows and late decisions (PRD 3.5)."""

from datetime import timedelta

from flask import Blueprint

import errors
import validation as v
from db import base_row, db, now, touch
from errors import fail
from middleware import ANY_ROLE, ROLE_DIRECTOR, ROLE_REPLAY_OFFICIAL, endpoint
from response import list_response, object_response
from services import calc, derive

bp = Blueprint("replay", __name__)

STATION_STATUSES = ["ONLINE", "OFFLINE"]


@bp.route("/replay-stations", methods=["POST"])
@endpoint([ROLE_DIRECTOR])
def register_station():
    """"An `OfficiatingDirector` registers each booth as a replay station with a
    `station_code` between 1 and 20 characters that must be unique across all
    booths ... Replay booths are department infrastructure with no season program
    reference at all, so a booth may be registered at any time.\""""
    data = v.body()
    station_code = v.req_str(data, "station_code", 1, 20)
    concurrent_capacity = v.opt_int(data, "concurrent_capacity", minimum=1, default=1)
    status = v.opt_enum(data, "status", STATION_STATUSES, "ONLINE")
    for existing in db.replay_stations.values():
        if existing["station_code"] == station_code:
            fail(errors.ERR_INVALID_REQUEST,
                 "station_code '%s' is already registered." % station_code)

    row = base_row()
    row.update({
        "station_code": station_code,
        "concurrent_capacity": concurrent_capacity,
        "status": status,
        "active_review_count": 0,
    })
    db.replay_stations[row["id"]] = row
    return object_response(row, 201)


@bp.route("/replay-stations/<station_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_station(station_id):
    return object_response(derive.get_station(station_id))


@bp.route("/replay-reviews", methods=["POST"])
@endpoint([ROLE_REPLAY_OFFICIAL])
def open_review():
    data = v.body()
    game_id = v.req_str(data, "game_id")
    station_id = v.req_str(data, "station_id")
    play_ref = v.req_str(data, "play_ref", 1, 40)
    category = v.req_enum(data, "category", calc.REVIEW_CATEGORIES)

    game = derive.get_game(game_id)
    station = derive.get_station(station_id)
    program = derive.program_of_game(game)
    derive.require_program_open(program)
    if game["status"] != "IN_PROGRESS":
        fail(errors.ERR_GAME_STATE_INVALID,
             "A replay review may only be opened on an IN_PROGRESS game.")

    if category not in program["reviewable_categories"]:
        fail(errors.ERR_CATEGORY_NOT_REVIEWABLE,
             "Category %s is not reviewable in this season program." % category)
    if station["status"] != "ONLINE":
        fail(errors.ERR_REPLAY_STATION_OFFLINE, "The replay booth is OFFLINE.")

    window_open = now()
    window_close = window_open + timedelta(
        seconds=program["replay_decision_limit_seconds"])
    # "This is an aggregate capacity test, not pairwise exclusion": count the
    # booth's INITIATED reviews whose windows conflict on the inclusive test.
    overlapping = 0
    for existing in derive.rows_of(db.replay_reviews, station_id=station["id"]):
        if existing["status"] != "INITIATED":
            continue
        if calc.review_windows_conflict(window_open, window_close,
                                        existing["window_open_utc"],
                                        existing["window_close_utc"]):
            overlapping += 1
    if overlapping >= station["concurrent_capacity"]:
        fail(errors.ERR_REPLAY_STATION_AT_CAPACITY,
             "The replay booth has no spare concurrent capacity.")

    row = base_row()
    row.update({
        "game_id": game["id"],
        "station_id": station["id"],
        "play_ref": play_ref,
        "category": category,
        "status": "INITIATED",
        "decision": None,
        "elapsed_seconds": None,
        "window_open_utc": window_open,
        "window_close_utc": window_close,
    })
    db.replay_reviews[row["id"]] = row
    station["active_review_count"] = station["active_review_count"] + 1
    touch(station)
    return object_response(row, 201)


@bp.route("/replay-reviews/<review_id>/decide", methods=["POST"])
@endpoint([ROLE_REPLAY_OFFICIAL])
def decide_review(review_id):
    """"when `elapsed_seconds` is less than or equal to the program's
    `replay_decision_limit_seconds` the review moves `INITIATED -> DECIDED` and
    stores the supplied `decision`; when it exceeds that limit the review moves
    `INITIATED -> EXPIRED`, the supplied `decision` is discarded and `decision` is
    stored as null. A late submission is not an error.\""""
    data = v.body()
    decision = v.req_enum(data, "decision", calc.REPLAY_DECISIONS)

    review = derive.get_review(review_id)
    game = db.games.get(review["game_id"])
    program = derive.program_of_game(game) if game else None
    derive.require_program_open(program)
    if review["status"] != "INITIATED":
        fail(errors.ERR_REVIEW_STATE_INVALID,
             "Only an INITIATED review may be decided.")

    elapsed = calc.elapsed_whole_seconds(review["window_open_utc"], now())
    review["elapsed_seconds"] = elapsed
    if elapsed <= program["replay_decision_limit_seconds"]:
        review["status"] = "DECIDED"
        review["decision"] = decision
    else:
        review["status"] = "EXPIRED"
        review["decision"] = None
    touch(review)
    station = db.replay_stations.get(review["station_id"])
    if station is not None:
        station["active_review_count"] = max(
            0, station["active_review_count"] - 1)
        touch(station)
    return object_response(review)


@bp.route("/replay-reviews/<review_id>", methods=["GET"])
@endpoint(ANY_ROLE)
def read_review(review_id):
    return object_response(derive.get_review(review_id))


@bp.route("/replay-reviews", methods=["GET"])
@endpoint(ANY_ROLE)
def list_reviews():
    limit, offset = v.pagination()
    rows = derive.rows_of(db.replay_reviews)
    for name in ("game_id", "station_id", "status", "category"):
        wanted = v.query_filter(name)
        if wanted is not None:
            rows = [r for r in rows if r.get(name) == wanted]
    return list_response(v.paginate(rows, limit, offset), limit, offset, len(rows))
