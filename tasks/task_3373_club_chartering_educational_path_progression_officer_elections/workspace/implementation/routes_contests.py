"""Contest, contest entry and judge ballot endpoints."""

from flask import Blueprint, request

import auth
import calc
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("contests", __name__, url_prefix="/toastmasters")

CONTEST_LEVELS = ("CLUB", "AREA", "DIVISION", "DISTRICT")
CONTEST_TYPES = ("INTERNATIONAL_SPEECH", "TALL_TALES", "EVALUATION", "HUMOROUS")
SCORE_MIN = 0
SCORE_MAX = 100


def _get_contest(contest_id):
    return db.get(db.CONTESTS, contest_id)


def _get_entry(entry_id):
    return db.get(db.ENTRIES, entry_id)


@bp.get("/contests")
def list_contests():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    contests = list(db.CONTESTS.values())
    for query_name in ("club_id", "contest_level", "contest_type"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            contests = [c for c in contests if c.get(query_name) == wanted]

    contests.sort(key=lambda c: c["created_at"])
    window, total, _ = db.paginate(contests, limit, offset)
    return array(serializers.render_all("contest", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/contests/<contest_id>")
def get_contest(contest_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("contest", _get_contest(contest_id)))


@bp.post("/contests")
def create_contest():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    contest_level = db.require_enum(body, "contest_level", CONTEST_LEVELS)
    contest_type = db.require_enum(body, "contest_type", CONTEST_TYPES)
    district_number = db.require_str(body, "district_number")
    division_code = db.require_str(body, "division_code")
    scheduled_at = db.parse_dt(db.require(body, "scheduled_at"), "scheduled_at")
    club_id = db.optional(body, "club_id")
    area_code = db.optional(body, "area_code")
    if club_id is not None and not isinstance(club_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'club_id' must be a string.")
    if area_code is not None and not isinstance(area_code, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'area_code' must be a string.")
    if contest_level == "CLUB" and not club_id:
        raise ApiError("ERR_INVALID_REQUEST", "A CLUB-level contest requires a club_id.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector", "WorldHeadquarters"))

    # Priority 4: the referenced club exists.
    if club_id:
        db.get(db.CLUBS, club_id)

    contest = db.create(
        db.CONTESTS,
        {
            "club_id": club_id,
            "contest_level": contest_level,
            "contest_type": contest_type,
            "district_number": district_number,
            "division_code": division_code,
            "area_code": area_code,
            "scheduled_at": scheduled_at,
            "status": "SCHEDULED",
            "entry_count": 0,
            "judged_entry_count": 0,
            "winner_entry_id": None,
            "completed_at": None,
        },
    )
    return ok(serializers.render("contest", contest), status=201)


@bp.post("/contests/<contest_id>/complete")
def complete_contest(contest_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector",))

    contest = _get_contest(contest_id)

    # The candidate set is the entries in status JUDGED.  A contest that has
    # already completed holds none, so it falls out here (PRD section 3.8).
    candidates = [e for e in recompute.entries_of_contest(contest_id) if e["status"] == "JUDGED"]
    if not candidates:
        raise ApiError("ERR_NO_JUDGED_ENTRIES")
    for entry in candidates:
        if entry["ballot_count"] < calc.BALLOTS_REQUIRED:
            raise ApiError("ERR_CONTEST_NOT_OPEN")

    ranked = calc.rank_entries(candidates)
    winner = ranked[0]
    winner["status"] = "ADVANCED"
    winner["placement"] = 1
    db.touch(winner)
    contest["winner_entry_id"] = winner["id"]

    for position, entry in enumerate(ranked[1:], start=2):
        entry["status"] = "ELIMINATED"
        entry["placement"] = position
        db.touch(entry)

    # The next contest level opens for a club-level winner.
    if contest["contest_level"] == "CLUB":
        for upper in db.CONTESTS.values():
            if upper["status"] != "SCHEDULED":
                continue
            if upper["contest_level"] != "AREA":
                continue
            if upper["contest_type"] != contest["contest_type"]:
                continue
            if upper["district_number"] != contest["district_number"]:
                continue
            if upper["area_code"] != contest["area_code"]:
                continue
            db.create(
                db.ENTRIES,
                {
                    "contest_id": upper["id"],
                    "member_id": winner["member_id"],
                    "club_id": winner["club_id"],
                    "speech_title": winner["speech_title"],
                    "status": "ENTERED",
                    "ballot_count": 0,
                    "judge_score_total": 0,
                    "placement": None,
                    "_judges": [],
                },
            )
            recompute.recompute_contest(upper)
            db.touch(upper)
            break

    contest["status"] = "COMPLETED"
    contest["completed_at"] = db.utcnow()

    touched_clubs = {}
    for entry in ranked:
        club = db.CLUBS.get(entry["club_id"])
        if club is not None:
            touched_clubs[club["id"]] = club
    for club in touched_clubs.values():
        recompute.touch_club(club)

    recompute.recompute_contest(contest)
    db.touch(contest)
    return ok(serializers.render("contest", contest))


@bp.get("/contest-entries")
def list_entries():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    entries = list(db.ENTRIES.values())
    for query_name in ("contest_id", "member_id", "club_id", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            entries = [e for e in entries if e.get(query_name) == wanted]

    entries.sort(key=lambda e: e["created_at"])
    window, total, _ = db.paginate(entries, limit, offset)
    return array(serializers.render_all("contest_entry", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/contest-entries/<entry_id>")
def get_entry(entry_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("contest_entry", _get_entry(entry_id)))


@bp.post("/contest-entries")
def create_entry():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    contest_id = db.require_str(body, "contest_id")
    member_id = db.require_str(body, "member_id")
    club_id = db.require_str(body, "club_id")
    speech_title = db.require_str(body, "speech_title")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member",))
    # Priority 2: Member ownership runs through the competing member.
    auth.require_member_identity(principal, member_id)

    # Priority 4: references resolved in body field order.
    contest = db.get(db.CONTESTS, contest_id)
    db.get(db.MEMBERS, member_id)
    club = db.get(db.CLUBS, club_id)

    # Priority 13: entries are accepted only while the contest is SCHEDULED.
    if contest["status"] != "SCHEDULED":
        raise ApiError("ERR_CONTEST_NOT_OPEN")

    # Priority 17: the claiming club must be in GOOD standing.
    recompute.require_club_good_standing(club)

    # Priority 18: the membership must be ACTIVE and paid through the cycle.
    membership = None
    for candidate in db.MEMBERSHIPS.values():
        if candidate["member_id"] == member_id and candidate["club_id"] == club_id:
            membership = candidate
            break
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    recompute.require_membership_paid_active(membership, club)

    entry = db.create(
        db.ENTRIES,
        {
            "contest_id": contest_id,
            "member_id": member_id,
            "club_id": club_id,
            "speech_title": speech_title,
            "status": "ENTERED",
            "ballot_count": 0,
            "judge_score_total": 0,
            "placement": None,
            "_judges": [],
        },
    )
    recompute.recompute_contest(contest)
    db.touch(contest)
    return ok(serializers.render("contest_entry", entry), status=201)


@bp.post("/contest-entries/<entry_id>/ballots")
def record_ballot(entry_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    judge_member_id = db.require_str(body, "judge_member_id")
    content_score = db.require_int(body, "content_score")
    delivery_score = db.require_int(body, "delivery_score")
    language_score = db.require_int(body, "language_score")
    for name, value in (
        ("content_score", content_score),
        ("delivery_score", delivery_score),
        ("language_score", language_score),
    ):
        if value < SCORE_MIN or value > SCORE_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field '%s' must lie between 0 and 100." % name
            )

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("DistrictDirector",))

    # Priority 3: the entry named in the path exists.
    entry = _get_entry(entry_id)
    # Priority 4: the referenced judge exists.
    db.get(db.MEMBERS, judge_member_id)

    # Priority 7: one ballot per judge and entry.
    if judge_member_id in (entry.get("_judges") or []):
        raise ApiError("ERR_DUPLICATE_BALLOT")

    # Priority 12: judge independence.
    if judge_member_id == entry["member_id"]:
        raise ApiError("ERR_JUDGE_CONFLICT")
    for membership in db.MEMBERSHIPS.values():
        if membership["member_id"] == judge_member_id and membership["club_id"] == entry["club_id"]:
            raise ApiError("ERR_JUDGE_CONFLICT")

    contest = db.get(db.CONTESTS, entry["contest_id"])
    # Priority 13: ballots are accepted while SCHEDULED or IN_PROGRESS, so a
    # ballot attempted on a COMPLETED contest is ERR_CONTEST_NOT_OPEN.
    if contest["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_CONTEST_NOT_OPEN")

    # A slot that has already reached its final status collects no more ballots.
    if entry["status"] != "ENTERED":
        raise ApiError("ERR_INVALID_STATE")

    total = calc.ballot_total(content_score, delivery_score, language_score)
    entry.setdefault("_judges", []).append(judge_member_id)
    entry["ballot_count"] += 1
    entry["judge_score_total"] += total
    if entry["ballot_count"] >= calc.BALLOTS_REQUIRED:
        entry["status"] = "JUDGED"

    if contest["status"] == "SCHEDULED":
        contest["status"] = "IN_PROGRESS"
        db.touch(contest)
    recompute.recompute_contest(contest)
    db.touch(entry)
    return ok(serializers.render("contest_entry", entry))
