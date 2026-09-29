"""Member roster endpoints (PRD 3.1)."""
from flask import Blueprint

import derive
from constants import (
    ALL_ROLES, API_PREFIX, JURISDICTIONS, MEMBERSHIP_TIERS, MEMBER_STATUSES, STAFF_ROLES,
)
from core import arg, authenticate, body, filtered, member_scope, respond
from serializers import dump, listing
from validate import get_bool, get_district, get_enum, get_int, get_str

bp = Blueprint("members", __name__, url_prefix=API_PREFIX)

NOTICE_ROLES = ["AssociationAdmin", "ComplianceOfficer", "MemberDelegate"]
APPROVAL_LIST_ROLES = [
    "AssociationAdmin", "ComplianceOfficer", "BoardTrustee", "MemberDelegate",
]


@bp.post("/members")
def enroll_member():
    authenticate(["AssociationAdmin"])
    payload = body()
    legal_name = get_str(payload, "legal_name", max_len=200)
    membership_tier = get_enum(payload, "membership_tier", MEMBERSHIP_TIERS)
    home_jurisdiction_code = get_enum(payload, "home_jurisdiction_code", JURISDICTIONS)
    home_district_code = get_district(payload, "home_district_code")
    annual_dues_cents = get_int(payload, "annual_dues_cents", minimum=0)
    dues_year = get_int(payload, "dues_year", minimum=2020, maximum=2100)
    restricted_class_size = get_int(payload, "restricted_class_size", minimum=0)
    status = get_enum(payload, "status", MEMBER_STATUSES, required=False, default="ACTIVE")
    advocacy_optout = get_bool(payload, "advocacy_optout", required=False, default=False)
    engagement_score = get_int(payload, "engagement_score", required=False, default=50,
                               minimum=0, maximum=100)
    from core import insert
    member = insert("members", {
        "legal_name": legal_name,
        "membership_tier": membership_tier,
        "status": status,
        "home_jurisdiction_code": home_jurisdiction_code,
        "home_district_code": home_district_code,
        "annual_dues_cents": annual_dues_cents,
        "dues_year": dues_year,
        "restricted_class_size": restricted_class_size,
        "advocacy_optout": advocacy_optout,
        "engagement_score": engagement_score,
        "recorded_dissent_count": 0,
        # notice_method is resolved from the jurisdiction rule book, never accepted.
        "notice_method": derive.rule(home_jurisdiction_code)["deductibility_method"],
        "pac_solicitable": False,
    })
    return respond(dump("members", member), status=201)


def _member(member_id):
    member = derive.lookup("members", member_id, "ERR_MEMBER_NOT_FOUND")
    member_scope(member_id)
    return member


@bp.get("/members/<member_id>")
def read_member(member_id):
    authenticate(ALL_ROLES)
    return respond(dump("members", _member(member_id)))


@bp.get("/members/<member_id>/deductibility-notice")
def read_notice(member_id):
    authenticate(NOTICE_ROLES)
    return respond(derive.deductibility_notice(_member(member_id)))


@bp.get("/members/<member_id>/committee-seats")
def list_member_seats(member_id):
    authenticate(ALL_ROLES)
    _member(member_id)
    rows = filtered(derive.where("seats", member_id=member_id), status=arg("status"))
    return listing("seats", rows)


@bp.get("/members/<member_id>/position-votes")
def list_member_votes(member_id):
    authenticate(ALL_ROLES)
    _member(member_id)
    rows = derive.where("votes", member_id=member_id)
    rows = filtered(rows, position_id=arg("position_id"),
                    ballot_status=arg("ballot_status") or arg("status"))
    return listing("votes", rows)


@bp.get("/members/<member_id>/prior-approvals")
def list_member_approvals(member_id):
    authenticate(APPROVAL_LIST_ROLES)
    _member(member_id)
    rows = filtered(derive.where("approvals", member_id=member_id), status=arg("status"))
    return listing("approvals", rows)
