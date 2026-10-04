"""Club, membership, challenge, participation routes."""
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden,
                    err_invalid_state, err_club_archived, err_window,
                    err_dup_membership, err_already_joined)
from middleware import require_roles, check_self_or_admin
from response import (ok_object, ok_list, init_common, touch, parse_pagination,
                      parse_iso_date)
from serializers import (club_view, membership_view, challenge_view, participation_view)
from services import (archive_club_cascade, membership_exit_cascade,
                      lazy_close_challenge, logical_today, logical_now_iso_ms,
                      retroactive_join_progress)

bp = Blueprint("clubs", __name__)


def _get_club_or_404(cid):
    c = db.clubs.get(cid)
    if not c:
        raise err_not_found("Club not found")
    return c


def _is_club_admin(user_id, role, club_id):
    if role in ("PlatformAdmin", "Moderator"):
        return True
    if role != "Athlete":
        return False
    for m in db.memberships.values():
        if (m["club_id"] == club_id and m["athlete_id"] == user_id
                and m["status"] == "ACTIVE" and m["role"] == "ADMIN"):
            return True
    return False


def _require_club_admin(user_id, role, club_id):
    if role == "PlatformAdmin":
        return
    if not _is_club_admin(user_id, role, club_id):
        raise err_forbidden("Club admin required")


# ---------------------------------------------------------------- clubs ----

@bp.post("/v1/clubs")
def create_club():
    require_roles("Athlete", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    owner_id = body.get("owner_id")
    name = body.get("name")
    sport_type = body.get("sport_type")
    join_policy = body.get("join_policy")
    if not isinstance(name, str) or not (3 <= len(name) <= 60):
        raise err_validation("name must be 3..60 chars")
    if sport_type not in ("RIDE", "RUN", "SWIM", "MULTI"):
        raise err_validation("sport_type must be RIDE, RUN, SWIM or MULTI")
    if join_policy not in ("OPEN", "APPROVAL"):
        raise err_validation("join_policy must be OPEN or APPROVAL")
    if not isinstance(owner_id, str) or owner_id not in db.athletes:
        raise err_validation("owner_id does not reference an existing athlete")
    for c in db.clubs.values():
        if c["status"] != "ARCHIVED" and c["name"] == name:
            raise err_unique("club name taken")
    club = init_common({
        "owner_id": owner_id,
        "name": name,
        "sport_type": sport_type,
        "join_policy": join_policy,
        "status": "ACTIVE",
    })
    db.clubs[club["id"]] = club
    # owner joins as ACTIVE ADMIN
    m = init_common({
        "club_id": club["id"],
        "athlete_id": owner_id,
        "role": "ADMIN",
        "status": "ACTIVE",
    })
    db.memberships[m["id"]] = m
    return ok_object(club_view(club), 201)


@bp.get("/v1/clubs/<cid>")
def get_club(cid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    return ok_object(club_view(_get_club_or_404(cid)))


@bp.get("/v1/clubs")
def list_clubs():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    owner_f = request.args.get("owner_id")
    status_f = request.args.get("status")
    sport_f = request.args.get("sport_type")
    items = list(db.clubs.values())
    if owner_f:
        items = [c for c in items if c["owner_id"] == owner_f]
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    if sport_f:
        items = [c for c in items if c["sport_type"] == sport_f]
    items.sort(key=lambda c: c["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([club_view(c) for c in items], limit, offset)


@bp.post("/v1/clubs/<cid>/archive")
def archive_club(cid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    c = _get_club_or_404(cid)
    if role == "Athlete" and user_id != c["owner_id"]:
        raise err_forbidden("Only the owner may archive")
    if c["status"] == "ARCHIVED":
        raise err_invalid_state("Club already ARCHIVED")
    archive_club_cascade(c)
    return ok_object(club_view(c))


# ----------------------------------------------------------- memberships ----

@bp.post("/v1/clubs/<cid>/memberships")
def join_club(cid):
    require_roles("Athlete", "PlatformAdmin")
    c = _get_club_or_404(cid)
    body = request.get_json(silent=True) or {}
    athlete_id = body.get("athlete_id")
    if not isinstance(athlete_id, str) or athlete_id not in db.athletes:
        raise err_validation("athlete_id does not reference an existing athlete")
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    for m in db.memberships.values():
        if m["club_id"] == cid and m["athlete_id"] == athlete_id and m["status"] in ("PENDING", "ACTIVE"):
            raise err_dup_membership()
    status = "ACTIVE" if c["join_policy"] == "OPEN" else "PENDING"
    m = init_common({
        "club_id": cid,
        "athlete_id": athlete_id,
        "role": "MEMBER",
        "status": status,
    })
    db.memberships[m["id"]] = m
    return ok_object(membership_view(m), 201)


@bp.get("/v1/clubs/<cid>/memberships")
def list_memberships(cid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    _get_club_or_404(cid)
    status_f = request.args.get("status")
    athlete_f = request.args.get("athlete_id")
    items = [m for m in db.memberships.values() if m["club_id"] == cid]
    if status_f:
        items = [m for m in items if m["status"] == status_f]
    if athlete_f:
        items = [m for m in items if m["athlete_id"] == athlete_f]
    items.sort(key=lambda m: m["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([membership_view(m) for m in items], limit, offset)


@bp.get("/v1/memberships")
def list_memberships_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    club_f = request.args.get("club_id")
    athlete_f = request.args.get("athlete_id")
    status_f = request.args.get("status")
    items = list(db.memberships.values())
    if club_f:
        items = [m for m in items if m["club_id"] == club_f]
    if athlete_f:
        items = [m for m in items if m["athlete_id"] == athlete_f]
    if status_f:
        items = [m for m in items if m["status"] == status_f]
    items.sort(key=lambda m: m["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([membership_view(m) for m in items], limit, offset)


@bp.get("/v1/memberships/<mid>")
def get_membership(mid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    m = db.memberships.get(mid)
    if not m:
        raise err_not_found("Membership not found")
    return ok_object(membership_view(m))


def _get_membership_scoped(cid, mid):
    _get_club_or_404(cid)
    m = db.memberships.get(mid)
    if not m or m["club_id"] != cid:
        raise err_not_found("Membership not found")
    return m


@bp.post("/v1/clubs/<cid>/memberships/<mid>/approve")
def approve_membership(cid, mid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    m = _get_membership_scoped(cid, mid)
    _require_club_admin(user_id, role, cid)
    if m["status"] != "PENDING":
        raise err_invalid_state("Only PENDING memberships may be approved")
    m["status"] = "ACTIVE"
    touch(m)
    return ok_object(membership_view(m))


@bp.post("/v1/clubs/<cid>/memberships/<mid>/remove")
def remove_membership(cid, mid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    m = _get_membership_scoped(cid, mid)
    _require_club_admin(user_id, role, cid)
    c = db.clubs[cid]
    if m["athlete_id"] == c["owner_id"]:
        raise err_forbidden("Cannot remove the club owner's membership")
    if m["status"] not in ("PENDING", "ACTIVE"):
        raise err_invalid_state("Membership is not PENDING or ACTIVE")
    m["status"] = "REMOVED"
    touch(m)
    membership_exit_cascade(cid, m["athlete_id"])
    return ok_object(membership_view(m))


@bp.post("/v1/clubs/<cid>/memberships/<mid>/leave")
def leave_membership(cid, mid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    m = _get_membership_scoped(cid, mid)
    check_self_or_admin(user_id, role, m["athlete_id"])
    if m["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE memberships may be left")
    m["status"] = "LEFT"
    touch(m)
    membership_exit_cascade(cid, m["athlete_id"])
    return ok_object(membership_view(m))


# ------------------------------------------------------------ challenges ----

@bp.post("/v1/clubs/<cid>/challenges")
def create_challenge(cid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    c = _get_club_or_404(cid)
    _require_club_admin(user_id, role, cid)
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    goal_type = body.get("goal_type")
    goal_target = body.get("goal_target")
    start_date = body.get("start_date")
    end_date = body.get("end_date")
    join_mode = body.get("join_mode")
    if not isinstance(name, str) or not (3 <= len(name) <= 80):
        raise err_validation("name must be 3..80 chars")
    if goal_type not in ("DISTANCE_M", "ELEVATION_M", "ACTIVE_DAYS"):
        raise err_validation("goal_type invalid")
    if not isinstance(goal_target, (int, float)) or isinstance(goal_target, bool) or goal_target <= 0:
        raise err_validation("goal_target must be > 0")
    sd = parse_iso_date(start_date); ed = parse_iso_date(end_date)
    if sd is None or ed is None:
        raise err_validation("start_date/end_date must be YYYY-MM-DD")
    if ed < sd:
        raise err_window("end_date must be >= start_date")
    if join_mode not in ("OPEN", "INVITE"):
        raise err_validation("join_mode must be OPEN or INVITE")
    ch = init_common({
        "club_id": cid,
        "name": name,
        "goal_type": goal_type,
        "goal_target": goal_target,
        "start_date": start_date,
        "end_date": end_date,
        "join_mode": join_mode,
        "status": "DRAFT",
    })
    db.challenges[ch["id"]] = ch
    return ok_object(challenge_view(ch), 201)


@bp.get("/v1/clubs/<cid>/challenges")
def list_challenges(cid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    _get_club_or_404(cid)
    status_f = request.args.get("status")
    items = [c for c in db.challenges.values() if c["club_id"] == cid]
    for ch in items:
        lazy_close_challenge(ch)
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([challenge_view(c) for c in items], limit, offset)


@bp.get("/v1/challenges")
def list_challenges_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    club_f = request.args.get("club_id")
    status_f = request.args.get("status")
    items = list(db.challenges.values())
    for ch in items:
        lazy_close_challenge(ch)
    if club_f:
        items = [c for c in items if c["club_id"] == club_f]
    if status_f:
        items = [c for c in items if c["status"] == status_f]
    items.sort(key=lambda c: c["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([challenge_view(c) for c in items], limit, offset)


@bp.get("/v1/challenges/<chid>")
def get_challenge(chid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    ch = db.challenges.get(chid)
    if not ch:
        raise err_not_found("Challenge not found")
    lazy_close_challenge(ch)
    return ok_object(challenge_view(ch))


def _get_challenge_scoped(cid, chid):
    _get_club_or_404(cid)
    ch = db.challenges.get(chid)
    if not ch or ch["club_id"] != cid:
        raise err_not_found("Challenge not found")
    return ch


@bp.post("/v1/clubs/<cid>/challenges/<chid>/start")
def start_challenge(cid, chid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ch = _get_challenge_scoped(cid, chid)
    _require_club_admin(user_id, role, cid)
    c = db.clubs[cid]
    if ch["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT challenges may be started")
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    ed = parse_iso_date(ch["end_date"])
    if logical_today() > ed:
        raise err_window("Cannot start a challenge after end_date")
    ch["status"] = "ACTIVE"
    touch(ch)
    return ok_object(challenge_view(ch))


@bp.post("/v1/clubs/<cid>/challenges/<chid>/cancel")
def cancel_challenge(cid, chid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ch = _get_challenge_scoped(cid, chid)
    _require_club_admin(user_id, role, cid)
    c = db.clubs[cid]
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    if ch["status"] not in ("DRAFT", "ACTIVE"):
        raise err_invalid_state("Only DRAFT or ACTIVE challenges may be cancelled")
    ch["status"] = "CANCELLED"
    touch(ch)
    for p in db.participations.values():
        if p["challenge_id"] == chid and p["status"] == "JOINED":
            p["status"] = "WITHDRAWN"
            touch(p)
    return ok_object(challenge_view(ch))


# --------------------------------------------------------- participations ----

@bp.post("/v1/challenges/<chid>/participations")
def join_challenge(chid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ch = db.challenges.get(chid)
    if not ch:
        raise err_not_found("Challenge not found")
    lazy_close_challenge(ch)
    body = request.get_json(silent=True) or {}
    athlete_id = body.get("athlete_id")
    if not isinstance(athlete_id, str) or athlete_id not in db.athletes:
        raise err_validation("athlete_id does not reference an existing athlete")
    if ch["status"] != "ACTIVE":
        raise err_invalid_state("Challenge is not ACTIVE")
    # membership gate: must be ACTIVE member of the club (OPEN mode)
    membership = None
    for m in db.memberships.values():
        if m["club_id"] == ch["club_id"] and m["athlete_id"] == athlete_id and m["status"] == "ACTIVE":
            membership = m
            break
    if ch["join_mode"] == "OPEN":
        if membership is None:
            raise err_forbidden("Only ACTIVE club members may join")
    else:  # INVITE: invitation modeled as admin pre-joining the athlete
        _require_club_admin(user_id, role, ch["club_id"])
    for p in db.participations.values():
        if p["challenge_id"] == chid and p["athlete_id"] == athlete_id and p["status"] in ("JOINED", "COMPLETED"):
            raise err_already_joined()
    part = init_common({
        "challenge_id": chid,
        "athlete_id": athlete_id,
        "status": "JOINED",
        "progress_value": 0,
        "joined_at": logical_now_iso_ms(),
    })
    db.participations[part["id"]] = part
    retroactive_join_progress(part, ch)
    return ok_object(participation_view(part), 201)


@bp.get("/v1/challenges/<chid>/participations")
def list_participations(chid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.challenges.get(chid):
        raise err_not_found("Challenge not found")
    status_f = request.args.get("status")
    athlete_f = request.args.get("athlete_id")
    items = [p for p in db.participations.values() if p["challenge_id"] == chid]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    if athlete_f:
        items = [p for p in items if p["athlete_id"] == athlete_f]
    items.sort(key=lambda p: p["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([participation_view(p) for p in items], limit, offset)


@bp.get("/v1/participations")
def list_participations_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    ch_f = request.args.get("challenge_id")
    athlete_f = request.args.get("athlete_id")
    status_f = request.args.get("status")
    items = list(db.participations.values())
    if ch_f:
        items = [p for p in items if p["challenge_id"] == ch_f]
    if athlete_f:
        items = [p for p in items if p["athlete_id"] == athlete_f]
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    items.sort(key=lambda p: p["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([participation_view(p) for p in items], limit, offset)


@bp.get("/v1/participations/<pid>")
def get_participation(pid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    p = db.participations.get(pid)
    if not p:
        raise err_not_found("Participation not found")
    return ok_object(participation_view(p))


@bp.post("/v1/challenges/<chid>/participations/<pid>/withdraw")
def withdraw_participation(chid, pid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ch = db.challenges.get(chid)
    if not ch:
        raise err_not_found("Challenge not found")
    p = db.participations.get(pid)
    if not p or p["challenge_id"] != chid:
        raise err_not_found("Participation not found")
    check_self_or_admin(user_id, role, p["athlete_id"])
    if p["status"] != "JOINED":
        raise err_invalid_state("Only JOINED participations may be withdrawn")
    p["status"] = "WITHDRAWN"
    touch(p)
    return ok_object(participation_view(p))
