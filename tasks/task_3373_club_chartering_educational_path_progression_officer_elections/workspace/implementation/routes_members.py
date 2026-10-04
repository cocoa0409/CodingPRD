"""Member and membership endpoints: enrollment, dues payment and refunds."""

from flask import Blueprint, request

import auth
import calc
import db
import recompute
import serializers
from errors import ApiError
from response import array, ok

bp = Blueprint("members", __name__, url_prefix="/toastmasters")

MAX_BULK = 25


def _get_membership(membership_id):
    return db.get(db.MEMBERSHIPS, membership_id)


def _email_is_valid(value):
    if not isinstance(value, str):
        return False
    if value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain:
        return False
    return "." in domain and not domain.startswith(".") and not domain.endswith(".")


def _resolve_member(body):
    """Reuse an existing member row, else mint one (PRD section 3.3)."""
    member_id = db.optional(body, "member_id")
    email = db.optional(body, "email")
    if member_id is not None:
        member = db.get(db.MEMBERS, member_id)
        if email is None:
            return member
        return member
    if email is not None:
        for existing in db.MEMBERS.values():
            if existing.get("email") is not None and existing["email"] == email:
                return existing
    member = db.create(
        db.MEMBERS,
        {
            "full_name": db.optional(body, "full_name"),
            "email": email,
            "home_area_code": db.optional(body, "home_area_code"),
            "member_since": db.utcnow(),
            "total_speeches_delivered": 0,
            "highest_level_completed": 0,
        },
    )
    return member


def _enroll(club, member, join_date, first_time_member, pay_now):
    """Create one membership row with its opening quote."""
    membership = db.create(
        db.MEMBERSHIPS,
        {
            "member_id": member["id"],
            "club_id": club["id"],
            "status": "PENDING",
            "dues_status": "ISSUED",
            "join_date": join_date,
            "first_time_member": first_time_member,
            "dues_paid_through_cycle": -1,
            "consecutive_cycles_paid": 0,
            "quoted_total_cents": None,
            "officer_role": "NONE",
            "speeches_delivered_this_cycle": 0,
            "roles_completed_this_cycle": 0,
            "_paid_history": [],
        },
    )
    # The opening quote is assembled while the invoice is still unpaid and the
    # membership has never paid, so a first-time member carries the new-member
    # line (PRD section 3.2's pinned 10062 example).
    membership["quoted_total_cents"] = calc.dues_quote_total_cents(membership, club)
    if pay_now:
        membership["_paid_history"].append((-1, 0))
        membership["dues_status"] = "PAID"
        membership["dues_paid_through_cycle"] = club["dues_cycle_index"]
        membership["consecutive_cycles_paid"] = 1
        membership["status"] = "ACTIVE"
    return membership


@bp.get("/members/<member_id>")
def get_member(member_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    member = db.get(db.MEMBERS, member_id)
    return ok(serializers.render("member", member))


@bp.get("/memberships")
def list_memberships():
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    limit, offset = db.parse_pagination(request.args)

    memberships = list(db.MEMBERSHIPS.values())
    for query_name in ("member_id", "club_id", "status"):
        wanted = request.args.get(query_name)
        if wanted not in (None, ""):
            memberships = [m for m in memberships if m.get(query_name) == wanted]

    memberships.sort(key=lambda m: m["created_at"])
    window, total, _ = db.paginate(memberships, limit, offset)
    return array(serializers.render_all("membership", window), limit=limit, offset=offset,
                 total_count=total)


@bp.get("/memberships/<membership_id>")
def get_membership(membership_id):
    principal = auth.authenticate(request.headers)
    auth.require_role(
        principal, ("WorldHeadquarters", "ClubOfficer", "Member", "DistrictDirector")
    )
    return ok(serializers.render("membership", _get_membership(membership_id)))


@bp.post("/memberships")
def create_membership():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    club_id = db.require_str(body, "club_id")
    join_date = db.parse_dt(db.require(body, "join_date"), "join_date")
    first_time_member = db.require_bool(body, "first_time_member")
    member_id = db.optional(body, "member_id")
    email = db.optional(body, "email")
    if email is not None and not isinstance(email, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'email' must be a string.")
    if member_id is not None and not isinstance(member_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'member_id' must be a string.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer", "WorldHeadquarters"))
    # Priority 2: a ClubOfficer may only enroll into their own club.
    auth.require_officer_of_club(principal, club_id)

    # Priority 4: referenced entities exist, in body field order.
    club = db.get(db.CLUBS, club_id)
    if member_id is not None:
        db.get(db.MEMBERS, member_id)

    member = _resolve_member(body)
    membership = _enroll(club, member, join_date, first_time_member, False)
    recompute.touch_club(club)
    return ok(serializers.render("membership", membership), status=201)


@bp.post("/memberships/bulk")
def bulk_memberships():
    body = request.get_json(silent=True)
    if body is None:
        body = {}

    club_id = db.require_str(body, "club_id")
    rows = db.require(body, "members")
    if not isinstance(rows, list):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'members' must be an array.")
    if len(rows) > MAX_BULK:
        raise ApiError("ERR_INVALID_REQUEST", "At most 25 members may be enrolled per request.")
    pay_now = db.optional_bool(body, "pay_dues_immediately", False)

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer", "WorldHeadquarters"))
    auth.require_officer_of_club(principal, club_id)

    club = db.get(db.CLUBS, club_id)

    created = []
    failed = 0
    for row in rows:
        if not isinstance(row, dict) or not _email_is_valid(row.get("email")):
            failed += 1
            continue
        join_date = db.parse_dt(row.get("join_date"), "join_date") or db.utcnow()
        first_time_member = row.get("first_time_member")
        if not isinstance(first_time_member, bool):
            first_time_member = False
        member = _resolve_member(row)
        created.append(_enroll(club, member, join_date, first_time_member, pay_now))

    recompute.touch_club(club)
    payload = {
        "created_count": len(created),
        "failed_count": failed,
        "memberships": serializers.render_all("membership", created),
    }
    return ok(payload, status=201)


@bp.post("/memberships/<membership_id>/renew")
def renew_membership(membership_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("Member", "ClubOfficer"))

    membership = _get_membership(membership_id)
    auth.require_owns_membership(principal, membership)
    club = db.get(db.CLUBS, membership["club_id"])

    # Priority 16: dues payment admissibility.
    if membership["dues_status"] in ("PAID", "VOID"):
        raise ApiError("ERR_DUES_ALREADY_PAID")
    if club["charter_status"] == "REVOKED":
        raise ApiError("ERR_CLUB_REVOKED")
    if club["charter_status"] == "SUSPENDED":
        raise ApiError("ERR_CLUB_NOT_CHARTERED")

    # The state machine's own preconditions.
    if membership["status"] == "PENDING":
        if membership["dues_status"] not in ("ISSUED", "OVERDUE"):
            raise ApiError("ERR_INVALID_STATE")
    elif membership["status"] == "LAPSED":
        if membership["dues_status"] != "OVERDUE":
            raise ApiError("ERR_INVALID_STATE")
    elif membership["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    previous_paid = membership["dues_paid_through_cycle"]
    previous_consecutive = membership.get("consecutive_cycles_paid", 0)
    membership.setdefault("_paid_history", []).append(
        (previous_paid, previous_consecutive)
    )

    membership["quoted_total_cents"] = calc.dues_quote_total_cents(membership, club)
    membership["dues_status"] = "PAID"
    membership["dues_paid_through_cycle"] = club["dues_cycle_index"]
    if previous_paid == club["dues_cycle_index"] - 1:
        membership["consecutive_cycles_paid"] = previous_consecutive + 1
    else:
        membership["consecutive_cycles_paid"] = 1

    if membership["status"] in ("PENDING", "LAPSED"):
        recompute.activate_membership(membership)

    recompute.recompute_membership(membership)
    recompute.touch_club(club)
    db.touch(membership)
    return ok(serializers.render("membership", membership))


@bp.post("/memberships/<membership_id>/refund-dues")
def refund_dues(membership_id):
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    principal = auth.authenticate(request.headers)
    auth.require_role(principal, ("ClubOfficer",))

    membership = _get_membership(membership_id)
    auth.require_officer_of_club(principal, membership["club_id"])
    club = db.get(db.CLUBS, membership["club_id"])

    # Priority 6: a refund requires a PAID invoice.
    if membership["dues_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE")

    history = membership.get("_paid_history") or []
    if history:
        previous_paid, previous_consecutive = history.pop()
    else:
        previous_paid, previous_consecutive = -1, 0
    membership["dues_paid_through_cycle"] = previous_paid
    membership["consecutive_cycles_paid"] = previous_consecutive
    membership["dues_status"] = "VOID"

    recompute.recompute_membership(membership)
    recompute.touch_club(club)
    db.touch(membership)
    return ok(serializers.render("membership", membership))
