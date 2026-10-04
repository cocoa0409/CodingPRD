"""PartnerCollege endpoints, including the reverse ranking-entries read and
the computed regular-pool ordering."""
from flask import Blueprint, request

import serializers
import store
from auth import ALL_AUTHENTICATED, forbid, identity, require_roles
from calculations import priority_score
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND
from response import ok_object, paginated
from validation import KIND_ENUM, KIND_INT, KIND_STR, get_body, validate

bp = Blueprint("colleges", __name__)

AID_POLICIES = ("NO_LOAN", "MINIMAL_LOAN")


def get_college_or_404(college_id):
    college = store.colleges.get(college_id)
    if college is None:
        raise ApiError(ERR_NOT_FOUND, "college not found")
    return college


@bp.post("/colleges")
def create_college():
    body = get_body()
    values = validate(body, [
        ("name", KIND_STR, True, None, None),
        ("aid_policy", KIND_ENUM, True, None, AID_POLICIES),
        ("min_academic_index", KIND_INT, True, None, None),
        ("match_slots", KIND_INT, True, None, None),
        ("coa_cents", KIND_INT, True, None, None),
    ])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    if values["match_slots"] < 0:
        raise ApiError(ERR_INVALID_REQUEST, "match_slots must be >= 0")
    college = store.create(store.colleges, {
        "name": values["name"],
        "aid_policy": values["aid_policy"],
        "min_academic_index": values["min_academic_index"],
        "match_slots": values["match_slots"],
        "coa_cents": values["coa_cents"],
        "status": "ACTIVE",
    })
    return ok_object(serializers.college(college), 201)


@bp.get("/colleges")
def list_colleges():
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    items = list(store.colleges.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: c["created_at"])
    return paginated(items, serializers.college)


@bp.get("/colleges/<college_id>")
def get_college(college_id):
    role, _ = identity()
    require_roles(role, ALL_AUTHENTICATED)
    return ok_object(serializers.college(get_college_or_404(college_id)))


@bp.post("/colleges/<college_id>/suspend")
def suspend_college(college_id):
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    college = get_college_or_404(college_id)
    if college["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "college is not ACTIVE")
    college["status"] = "SUSPENDED"
    store.touch(college)
    return ok_object(serializers.college(college))


@bp.post("/colleges/<college_id>/reinstate")
def reinstate_college(college_id):
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    college = get_college_or_404(college_id)
    if college["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "college is not SUSPENDED")
    college["status"] = "ACTIVE"
    store.touch(college)
    return ok_object(serializers.college(college))


@bp.get("/colleges/<college_id>/ranking-entries")
def college_ranking_entries(college_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "CollegeOfficer"))
    college = get_college_or_404(college_id)
    if role == "CollegeOfficer" and uid != college["id"]:
        forbid("a college officer may only view their own college")
    # Reverse reachability: every RankingEntry row naming this college, across
    # all submissions past and present (any list_seq).
    items = [e for e in store.ranking_entries.values() if e["college_id"] == college["id"]]
    items.sort(key=lambda e: e["created_at"])
    return paginated(items, serializers.ranking_entry)


@bp.get("/colleges/<college_id>/regular-pool")
def regular_pool(college_id):
    role, uid = identity()
    require_roles(role, ("ProgramAdmin", "CollegeOfficer"))
    college = get_college_or_404(college_id)
    if role == "CollegeOfficer" and uid != college["id"]:
        forbid("a college officer may only view their own college")
    cycle_id = request.args.get("cycle_id")
    if not cycle_id:
        raise ApiError(ERR_INVALID_REQUEST, "cycle_id query parameter is required")
    cycle = store.cycles.get(cycle_id)
    if cycle is None:
        raise ApiError(ERR_NOT_FOUND, "cycle not found")
    pool = [
        a for a in store.applications.values()
        if a["cycle_id"] == cycle["id"] and a["status"] == "REGULAR_POOL"
    ]

    def score(application):
        referral_converted = False
        if application["referral_id"]:
            referral = store.referrals.get(application["referral_id"])
            referral_converted = referral is not None and referral["status"] == "CONVERTED"
        return priority_score(application, college, referral_converted)

    # match_priority_score DESC, tie-break Application.created_at ASC; an
    # empty pool returns an empty array with 200, never an error.
    pool.sort(key=lambda a: (-score(a), a["created_at"]))
    return paginated(pool, serializers.application)
