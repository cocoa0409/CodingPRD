"""Clock, locals, out-of-work list groups, members, skill endorsements and
apprentice-ratio policies."""

from flask import Blueprint

from core import (
    CLASSIFICATIONS, GROUP_CODES, LOCAL_KINDS, ORDERING_POLICIES,
    POLICY_STATUSES, SKILL_CODES, STANDINGS, db, iso, new_id, now,
)
from envelope import ApiError, created, listing, ok
from guards import (
    body, check_pagination_shape, pagination, paginate, q_bool, q_enum, q_str,
    require, s_bool, s_dt, s_enum, s_int, s_str,
)
import domain
import serializers as S
import services

bp = Blueprint("admin", __name__)


def _new_record(extra):
    record = {"id": new_id(), "created_at": now(), "updated_at": now(),
              "version": 1, "_seq": db.seq()}
    record.update(extra)
    return record


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    current = s_dt(data, "current_utc", required=True)
    db.clock = current
    return ok({"current_utc": iso(current)})


# --------------------------------------------------------------------------
# locals
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/locals", methods=["POST"])
def create_local():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    local_number = s_int(data, "local_number", minimum=1, maximum=9999)
    name = s_str(data, "name", min_len=1, max_len=120)
    kind = s_enum(data, "kind", LOCAL_KINDS)
    factor = s_int(data, "reciprocity_factor_bp", required=False, minimum=0,
                   maximum=10000, default=0)
    record = _new_record({
        "local_number": local_number,
        "name": name,
        "kind": kind,
        "reciprocity_factor_bp": factor,
    })
    db.locals[record["id"]] = record
    return created(S.local_view(record))


@bp.route("/hiring-hall/locals/<local_id>", methods=["GET"])
def read_local(local_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    check_pagination_shape()
    record = db.locals.get(local_id)
    if record is None:
        raise ApiError("ERR_LOCAL_NOT_FOUND", "No local with id %s." % local_id)
    return ok(S.local_view(record))


@bp.route("/hiring-hall/locals", methods=["GET"])
def list_locals():
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep", "Member")
    kind = q_enum("kind", LOCAL_KINDS)
    limit, offset = pagination()
    rows = services.sort_default(db.locals.values())
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    page, meta = paginate(rows, limit, offset)
    return listing([S.local_view(r) for r in page], meta)


# --------------------------------------------------------------------------
# out-of-work list groups
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/out-of-work-lists", methods=["POST"])
def create_list():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    group_code = s_enum(data, "group_code", GROUP_CODES)
    priority_rank = s_int(data, "priority_rank", minimum=1, maximum=4)
    ordering_policy = s_enum(data, "ordering_policy", ORDERING_POLICIES)
    requires_local_hours = s_int(data, "requires_local_hours", minimum=0)
    accepts_travelers = s_bool(data, "accepts_travelers")
    record = _new_record({
        "group_code": group_code,
        "priority_rank": priority_rank,
        "ordering_policy": ordering_policy,
        "requires_local_hours": requires_local_hours,
        "accepts_travelers": accepts_travelers,
    })
    db.lists[record["id"]] = record
    return created(S.list_view(record))


@bp.route("/hiring-hall/out-of-work-lists/<list_id>", methods=["GET"])
def read_list(list_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    check_pagination_shape()
    record = db.lists.get(list_id)
    if record is None:
        raise ApiError("ERR_LIST_NOT_FOUND", "No out-of-work list with id %s." % list_id)
    return ok(S.list_view(record))


@bp.route("/hiring-hall/out-of-work-lists", methods=["GET"])
def list_lists():
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    ordering_policy = q_enum("ordering_policy", ORDERING_POLICIES)
    accepts_travelers = q_bool("accepts_travelers")
    limit, offset = pagination()
    rows = [r for r in db.lists.values()]
    if ordering_policy is not None:
        rows = [r for r in rows if r["ordering_policy"] == ordering_policy]
    if accepts_travelers is not None:
        rows = [r for r in rows if r["accepts_travelers"] is accepts_travelers]
    # documented exception: priority_rank ascending
    rows.sort(key=lambda r: (r["priority_rank"], r["created_at"], r["_seq"]))
    page, meta = paginate(rows, limit, offset)
    return listing([S.list_view(r) for r in page], meta)


# --------------------------------------------------------------------------
# members
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/members", methods=["POST"])
def create_member():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    full_name = s_str(data, "full_name", min_len=1, max_len=120)
    home_local_id = s_str(data, "home_local_id")
    classification = s_enum(data, "classification", CLASSIFICATIONS)
    local_hours = s_int(data, "local_hours_in_trade", minimum=0)
    apprentice_period = s_int(data, "apprentice_period", required=False,
                              minimum=1, maximum=4, default=None)
    standing = s_enum(data, "standing", STANDINGS, required=False,
                      default="GOOD_STANDING")
    if classification == "APPRENTICE" and apprentice_period is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "apprentice_period is required when classification is APPRENTICE.")
    if classification == "JOURNEYWORKER" and apprentice_period is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "apprentice_period must be null for a JOURNEYWORKER.")
    if home_local_id not in db.locals:
        raise ApiError("ERR_LOCAL_NOT_FOUND", "No local with id %s." % home_local_id)
    record = _new_record({
        "full_name": full_name,
        "home_local_id": home_local_id,
        "classification": classification,
        "apprentice_period": apprentice_period,
        "local_hours_in_trade": local_hours,
        "standing": standing,
        "re_registration_eligible_at": None,
    })
    db.members[record["id"]] = record
    return created(S.member_view(record))


@bp.route("/hiring-hall/members/<member_id>", methods=["GET"])
def read_member(member_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    check_pagination_shape()
    record = db.members.get(member_id)
    if record is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)
    return ok(S.member_view(record))


@bp.route("/hiring-hall/members", methods=["GET"])
def list_members():
    require("HallAdmin", "Dispatcher", "BusinessManager")
    home_local_id = q_str("home_local_id")
    classification = q_enum("classification", CLASSIFICATIONS)
    standing = q_enum("standing", STANDINGS)
    limit, offset = pagination()
    rows = services.sort_default(db.members.values())
    if home_local_id is not None:
        rows = [r for r in rows if r["home_local_id"] == home_local_id]
    if classification is not None:
        rows = [r for r in rows if r["classification"] == classification]
    if standing is not None:
        rows = [r for r in rows if r["standing"] == standing]
    page, meta = paginate(rows, limit, offset)
    return listing([S.member_view(r) for r in page], meta)


@bp.route("/hiring-hall/members/<member_id>/standing", methods=["PATCH"])
def patch_member_standing(member_id):
    require("HallAdmin", "BusinessManager")
    check_pagination_shape()
    data = body()
    standing = s_enum(data, "standing", STANDINGS)
    member = db.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)
    member["standing"] = standing
    from core import touch
    touch(member)
    if standing == "DELINQUENT":
        # Delinquency reaches into work in flight: outstanding referrals of this
        # member are withdrawn and each registration is made whole, no strike.
        outstanding = [r for r in db.referrals.values()
                       if r["member_id"] == member_id and r["status"] == "ISSUED"]
        outstanding.sort(key=lambda r: (r["acceptance_deadline"], r["created_at"], r["_seq"]))
        for referral in outstanding:
            services.withdraw_referral(referral, reason="MEMBER_DELINQUENT")
    return ok(S.member_view(member))


# --------------------------------------------------------------------------
# skill endorsements
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/members/<member_id>/skill-endorsements", methods=["POST"])
def create_endorsement(member_id):
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    skill_code = s_enum(data, "skill_code", SKILL_CODES)
    certified_until = s_dt(data, "certified_until")
    verified = s_bool(data, "verified", required=False, default=False)
    if member_id not in db.members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)
    record = {
        "id": new_id(),
        "member_id": member_id,
        "skill_code": skill_code,
        "certified_until": certified_until,
        "verified": verified,
        "created_at": now(),
        "_seq": db.seq(),
    }
    db.endorsements[record["id"]] = record
    return created(S.endorsement_view(record))


@bp.route("/hiring-hall/members/<member_id>/skill-endorsements", methods=["GET"])
def list_member_endorsements(member_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    skill_code = q_enum("skill_code", SKILL_CODES)
    limit, offset = pagination()
    if member_id not in db.members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)
    rows = [r for r in services.sort_default(db.endorsements.values())
            if r["member_id"] == member_id]
    if skill_code is not None:
        rows = [r for r in rows if r["skill_code"] == skill_code]
    page, meta = paginate(rows, limit, offset)
    return listing([S.endorsement_view(r) for r in page], meta)


@bp.route("/hiring-hall/skill-endorsements/<endorsement_id>", methods=["GET"])
def read_endorsement(endorsement_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    check_pagination_shape()
    record = db.endorsements.get(endorsement_id)
    if record is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND",
                       "No skill endorsement with id %s." % endorsement_id)
    return ok(S.endorsement_view(record))


# --------------------------------------------------------------------------
# ratio policies
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/ratio-policies", methods=["POST"])
def create_ratio_policy():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    policy_code = s_str(data, "policy_code", min_len=1, max_len=40)
    first_at = s_int(data, "first_apprentice_at_jw_count", minimum=1, maximum=10)
    then_every = s_int(data, "then_every_n_jw", minimum=1, maximum=10)
    effective_from = s_dt(data, "effective_from")
    record = _new_record({
        "policy_code": policy_code,
        "first_apprentice_at_jw_count": first_at,
        "then_every_n_jw": then_every,
        "effective_from": effective_from,
        "status": "ACTIVE",
    })
    from core import touch
    for existing in services.sort_default(db.ratio_policies.values()):
        if existing["status"] == "ACTIVE" and existing["effective_from"] < effective_from:
            existing["status"] = "SUPERSEDED"
            touch(existing)
    db.ratio_policies[record["id"]] = record
    return created(S.ratio_policy_view(record))


@bp.route("/hiring-hall/ratio-policies/<policy_id>", methods=["GET"])
def read_ratio_policy(policy_id):
    require("HallAdmin", "Dispatcher", "BusinessManager")
    check_pagination_shape()
    record = db.ratio_policies.get(policy_id)
    if record is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No ratio policy with id %s." % policy_id)
    return ok(S.ratio_policy_view(record))


@bp.route("/hiring-hall/ratio-policies", methods=["GET"])
def list_ratio_policies():
    require("HallAdmin", "Dispatcher", "BusinessManager")
    status = q_enum("status", POLICY_STATUSES)
    limit, offset = pagination()
    rows = services.sort_default(db.ratio_policies.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return listing([S.ratio_policy_view(r) for r in page], meta)
