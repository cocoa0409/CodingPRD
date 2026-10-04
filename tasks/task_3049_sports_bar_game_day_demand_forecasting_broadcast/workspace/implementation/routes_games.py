"""Trivia sessions and fantasy contests."""
from decimal import Decimal, ROUND_FLOOR

from flask import Blueprint, request

import db
import errors
from errors import invalid_request
from util import (success, list_response, auth, body, require, req_int,
                  req_str, now_ts, bump)
import services
from util import serialize, serialize_list

bp = Blueprint("games", __name__)

READ_TRIVIA = ["PlatformAdmin", "VenueManager", "Host"]
READ_FANTASY = ["PlatformAdmin", "VenueManager", "Host", "Server"]


def get_session_or_404(session_id):
    s = db.trivia_sessions.get(session_id)
    if s is None:
        raise errors.not_found()
    return s


def get_trivia_entry_or_404(entry_id):
    e = db.trivia_entries.get(entry_id)
    if e is None:
        raise errors.not_found()
    return e


def get_contest_or_404(contest_id):
    c = db.fantasy_contests.get(contest_id)
    if c is None:
        raise errors.not_found()
    return c


# ---------------------------------------------------------------- trivia

@bp.post("/api/venues/<venue_id>/trivia-sessions")
def create_trivia_session(venue_id):
    auth(["Host"])
    if venue_id not in db.venues:
        raise errors.not_found()
    data = body()
    title = req_str(data, "title")
    ts = now_ts()
    session = {
        "id": services.new_id(), "venue_id": venue_id, "title": title,
        "status": "OPEN",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.trivia_sessions[session["id"]] = session
    return success(serialize(session), code=201)


@bp.get("/api/trivia-sessions/<session_id>")
def get_trivia_session(session_id):
    auth(READ_TRIVIA)
    return success(serialize(get_session_or_404(session_id)))


@bp.get("/api/venues/<venue_id>/trivia-sessions")
def list_venue_trivia(venue_id):
    auth(READ_TRIVIA)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([s for s in db.trivia_sessions.values()
                    if s["venue_id"] == venue_id],
                   key=lambda s: s["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(serialize_list(items))


@bp.post("/api/trivia-sessions/<session_id>/entries")
def create_trivia_entry(session_id):
    auth(["Host"])
    session = get_session_or_404(session_id)
    data = body()
    guest_id = require(data, "guest_id")
    if guest_id not in db.guests:
        raise errors.guest_not_found()
    if session["status"] != "OPEN":
        raise errors.invalid_state("Session is not OPEN")
    entry = {
        "id": services.new_id(), "session_id": session_id,
        "guest_id": guest_id, "points": 0, "correct_count": 0,
        "consecutive_correct": 0, "created_at": now_ts(),
    }
    db.trivia_entries[entry["id"]] = entry
    return success(serialize(entry), code=201)


@bp.get("/api/trivia-sessions/<session_id>/trivia-entries")
def list_session_entries(session_id):
    auth(READ_TRIVIA)
    get_session_or_404(session_id)
    items = sorted([e for e in db.trivia_entries.values()
                    if e["session_id"] == session_id],
                   key=lambda e: e["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/trivia-entries/<entry_id>")
def get_trivia_entry(entry_id):
    auth(READ_TRIVIA)
    return success(serialize(get_trivia_entry_or_404(entry_id)))


@bp.post("/api/trivia-entries/<entry_id>/answers")
def submit_answer(entry_id):
    auth(["Host"])
    entry = get_trivia_entry_or_404(entry_id)
    session = db.trivia_sessions.get(entry["session_id"])
    if session is None or session["status"] != "OPEN":
        raise errors.invalid_state("Session is not OPEN")
    data = body()
    is_correct = require(data, "is_correct")
    if not isinstance(is_correct, bool):
        raise invalid_request("is_correct must be a boolean")
    response_time_ms = require(data, "response_time_ms")
    if isinstance(response_time_ms, bool) or not isinstance(response_time_ms, int) \
            or response_time_ms < 0:
        raise invalid_request("response_time_ms must be a non-negative integer")

    if is_correct:
        base = 100
        speed = max(0, 50 - (response_time_ms // 1000) * 2.5)
        new_streak = entry["consecutive_correct"] + 1
        streak_bonus = 25 if new_streak % 3 == 0 else 0
        entry["points"] += int(base + speed + streak_bonus)
        entry["consecutive_correct"] = new_streak
        entry["correct_count"] += 1
    else:
        entry["consecutive_correct"] = 0
    return success(serialize(entry))


@bp.post("/api/trivia-sessions/<session_id>/close")
def close_trivia_session(session_id):
    auth(["Host"])
    session = get_session_or_404(session_id)
    if session["status"] != "OPEN":
        raise errors.invalid_state("Session is not OPEN")
    session["status"] = "CLOSED"
    bump(session)
    return success(serialize(session))


@bp.post("/api/trivia-sessions/<session_id>/settle")
def settle_trivia_session(session_id):
    auth(["VenueManager"])
    session = get_session_or_404(session_id)
    if session["status"] != "CLOSED":
        raise errors.invalid_state("Session is not CLOSED")
    session["status"] = "SETTLED"
    bump(session)
    return success(serialize(session))


# ---------------------------------------------------------------- fantasy

@bp.post("/api/venues/<venue_id>/fantasy-contests")
def create_fantasy_contest(venue_id):
    auth(["VenueManager"])
    if venue_id not in db.venues:
        raise errors.not_found()
    data = body()
    entry_fee = req_int(data, "entry_fee_cents", minimum=0)
    rake_pct = require(data, "rake_pct")
    if isinstance(rake_pct, bool) or not isinstance(rake_pct, (int, float)):
        raise invalid_request("rake_pct must be a number")
    prize_structure = require(data, "prize_structure")
    if not isinstance(prize_structure, list) or not prize_structure or \
            not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                    for x in prize_structure):
        raise invalid_request("prize_structure must be a non-empty array of numbers")
    ts = now_ts()
    contest = {
        "id": services.new_id(), "venue_id": venue_id,
        "entry_fee_cents": entry_fee, "rake_pct": rake_pct,
        "prize_structure": prize_structure, "status": "DRAFT",
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.fantasy_contests[contest["id"]] = contest
    return success(serialize(contest), code=201)


@bp.get("/api/fantasy-contests/<contest_id>")
def get_fantasy_contest(contest_id):
    auth(READ_FANTASY)
    return success(serialize(get_contest_or_404(contest_id)))


@bp.get("/api/venues/<venue_id>/fantasy-contests")
def list_venue_contests(venue_id):
    auth(READ_FANTASY)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([c for c in db.fantasy_contests.values()
                    if c["venue_id"] == venue_id],
                   key=lambda c: c["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(serialize_list(items))


@bp.post("/api/fantasy-contests/<contest_id>/open")
def open_contest(contest_id):
    auth(["VenueManager"])
    contest = get_contest_or_404(contest_id)
    if contest["status"] != "DRAFT":
        raise errors.invalid_state("Contest is not DRAFT")
    total = sum(contest["prize_structure"])
    if abs(total - 1.0) > 0.001:
        raise errors.prize_structure_invalid()
    contest["status"] = "OPEN"
    bump(contest)
    return success(serialize(contest))


@bp.post("/api/fantasy-contests/<contest_id>/entries")
def create_fantasy_entry(contest_id):
    auth(["Server", "Host"])
    contest = get_contest_or_404(contest_id)
    data = body()
    guest_id = require(data, "guest_id")
    if guest_id not in db.guests:
        raise errors.guest_not_found()
    lineup = require(data, "lineup")
    if contest["status"] != "OPEN":
        raise errors.contest_not_open()
    entry = {
        "id": services.new_id(), "contest_id": contest_id,
        "guest_id": guest_id, "lineup": lineup, "prize_cents": 0,
        "created_at": now_ts(),
    }
    db.fantasy_entries[entry["id"]] = entry
    bump(contest)
    return success(serialize(entry), code=201)


@bp.get("/api/fantasy-contests/<contest_id>/fantasy-entries")
def list_contest_entries(contest_id):
    auth(READ_FANTASY)
    get_contest_or_404(contest_id)
    items = sorted([e for e in db.fantasy_entries.values()
                    if e["contest_id"] == contest_id],
                   key=lambda e: e["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/fantasy-entries/<entry_id>")
def get_fantasy_entry(entry_id):
    auth(READ_FANTASY)
    e = db.fantasy_entries.get(entry_id)
    if e is None:
        raise errors.not_found()
    return success(serialize(e))


@bp.post("/api/fantasy-contests/<contest_id>/lock")
def lock_contest(contest_id):
    auth(["VenueManager"])
    contest = get_contest_or_404(contest_id)
    if contest["status"] != "OPEN":
        raise errors.invalid_state("Contest is not OPEN")
    entries = [e for e in db.fantasy_entries.values()
               if e["contest_id"] == contest_id]
    if not entries:
        raise errors.invalid_state("Contest must have at least one entry")
    contest["status"] = "LOCKED"
    bump(contest)
    return success(serialize(contest))


@bp.post("/api/fantasy-contests/<contest_id>/settle")
def settle_contest(contest_id):
    auth(["VenueManager"])
    contest = get_contest_or_404(contest_id)
    if contest["status"] != "LOCKED":
        raise errors.invalid_state("Contest is not LOCKED")
    data = body()
    expected = require(data, "expected_fantasy_contest_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_fantasy_contest_version must be an integer")
    if expected != contest["version"]:
        raise errors.stale_version()

    entries = sorted([e for e in db.fantasy_entries.values()
                      if e["contest_id"] == contest_id],
                     key=lambda e: e["created_at"])
    gross = len(entries) * contest["entry_fee_cents"]
    rake = int((Decimal(gross) * Decimal(str(contest["rake_pct"])))
               .quantize(Decimal("1"), rounding=ROUND_FLOOR))
    distributable = gross - rake

    shares = contest["prize_structure"]
    winners = entries[:len(shares)]
    prizes = []
    for entry, share in zip(winners, shares):
        raw = Decimal(distributable) * Decimal(str(share))
        prizes.append(int(raw.quantize(Decimal("1"), rounding=ROUND_FLOOR)))
    remainder = distributable - sum(prizes)
    i = 0
    while remainder > 0 and prizes:
        prizes[i % len(prizes)] += 1
        remainder -= 1
        i += 1
    for entry, prize in zip(winners, prizes):
        entry["prize_cents"] = prize
    contest["status"] = "SETTLED"
    bump(contest)
    return success(serialize(contest))


@bp.post("/api/fantasy-contests/<contest_id>/cancel")
def cancel_contest(contest_id):
    auth(["VenueManager"])
    contest = get_contest_or_404(contest_id)
    if contest["status"] not in ("DRAFT", "OPEN"):
        raise errors.invalid_state("Contest cannot be cancelled from this state")
    contest["status"] = "CANCELLED"
    bump(contest)
    return success(serialize(contest))
