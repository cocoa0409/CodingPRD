"""Reverse-reachability list endpoints (branch-scoped and member-scoped)."""
from flask import Blueprint, request

import db
from common import auth, require_role, paginate
from routes.core import BRANCH_FIELDS, CATEGORY_FIELDS, MEMBER_FIELDS
from routes.memberships import MEMBERSHIP_FIELDS
from routes.scholarships import APPLICATION_FIELDS, serialize_application
from routes.programs import PROGRAM_FIELDS, SESSION_FIELDS, REGISTRATION_FIELDS
from routes.facilities import SPACE_FIELDS, RESERVATION_FIELDS
from routes.campaigns import CAMPAIGN_FIELDS, DONATION_FIELDS
from services import recompute_branch

bp = Blueprint("lists", __name__)


def _branch_scoped(branchId, store, fields, role_list, extra_filters=()):
    role, _ = auth()
    require_role(role, role_list)
    db.get("branches", branchId)
    items = [x for x in db.all_records(store) if x.get("branch_id") == branchId]
    for param in extra_filters:
        value = request.args.get(param)
        if value:
            items = [x for x in items if x.get(param) == value]
    return paginate([db.serialize(x, fields) for x in items])


@bp.route("/branches/<branchId>/memberships", methods=["GET"])
def branch_memberships(branchId):
    return _branch_scoped(branchId, "memberships", MEMBERSHIP_FIELDS,
                          ["AssociationAdmin", "BranchDirector", "FrontDesk"],
                          extra_filters=("status",))


@bp.route("/branches/<branchId>/categories", methods=["GET"])
def branch_categories(branchId):
    return _branch_scoped(branchId, "categories", CATEGORY_FIELDS,
                          ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                           "FrontDesk", "Member", "BoardMember"],
                          extra_filters=("household_type",))


@bp.route("/branches/<branchId>/programs", methods=["GET"])
def branch_programs(branchId):
    return _branch_scoped(branchId, "programs", PROGRAM_FIELDS,
                          ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                           "FrontDesk", "Member", "BoardMember"],
                          extra_filters=("kind",))


@bp.route("/branches/<branchId>/spaces", methods=["GET"])
def branch_spaces(branchId):
    return _branch_scoped(branchId, "spaces", SPACE_FIELDS,
                          ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                           "FrontDesk", "Member"],
                          extra_filters=("kind",))


@bp.route("/branches/<branchId>/scholarship-applications", methods=["GET"])
def branch_applications(branchId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "Member"])
    db.get("branches", branchId)
    items = [a for a in db.all_records("applications") if a["branch_id"] == branchId]
    for param in ("membership_id", "status"):
        value = request.args.get(param)
        if value:
            items = [a for a in items if a.get(param) == value]
    return paginate([serialize_application(a) for a in items])


@bp.route("/branches/<branchId>/donations", methods=["GET"])
def branch_donations(branchId):
    return _branch_scoped(branchId, "donations", DONATION_FIELDS,
                          ["AssociationAdmin", "BranchDirector", "BoardMember"],
                          extra_filters=("status", "designation"))


@bp.route("/members/<memberId>/registrations", methods=["GET"])
def member_registrations(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator",
                        "FrontDesk", "Member"])
    db.get("members", memberId)
    items = [r for r in db.all_records("registrations") if r["member_id"] == memberId]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    return paginate([db.serialize(r, REGISTRATION_FIELDS) for r in items])


@bp.route("/members/<memberId>/memberships", methods=["GET"])
def member_memberships(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "FrontDesk", "Member"])
    db.get("members", memberId)
    items = [m for m in db.all_records("memberships")
             if m["primary_member_id"] == memberId]
    return paginate([db.serialize(m, MEMBERSHIP_FIELDS) for m in items])


@bp.route("/members/<memberId>/scholarship-applications", methods=["GET"])
def member_applications(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "Member"])
    db.get("members", memberId)
    items = [a for a in db.all_records("applications")
             if a["applicant_member_id"] == memberId]
    return paginate([serialize_application(a) for a in items])


@bp.route("/members/<memberId>/donations", methods=["GET"])
def member_donations(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "BoardMember", "Member"])
    db.get("members", memberId)
    items = [d for d in db.all_records("donations")
             if d.get("donor_member_id") == memberId]
    return paginate([db.serialize(d, DONATION_FIELDS) for d in items])


@bp.route("/members/<memberId>/reservations", methods=["GET"])
def member_reservations(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "FrontDesk", "Member"])
    db.get("members", memberId)
    items = [r for r in db.all_records("reservations")
             if r.get("renter_member_id") == memberId]
    return paginate([db.serialize(r, RESERVATION_FIELDS) for r in items])
