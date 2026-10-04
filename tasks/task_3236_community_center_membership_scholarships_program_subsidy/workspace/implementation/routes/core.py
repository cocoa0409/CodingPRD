"""Routes: associations, branches, membership categories, members."""
from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, success_object, paginate, get_body,
    require_fields, today,
)
from services import recompute_branch, age_on

bp = Blueprint("core", __name__)

ASSOCIATION_FIELDS = ["id", "name", "reciprocity_enabled", "ami_base_cents",
                      "campaign_year", "created_at", "updated_at", "version"]
BRANCH_FIELDS = ["id", "association_id", "code", "name", "branch_goal_cents",
                 "scholarship_pool_received_cents", "scholarship_pool_obligated_cents",
                 "scholarship_pool_available_cents", "active_membership_count",
                 "created_at", "updated_at", "version"]
CATEGORY_FIELDS = ["id", "branch_id", "name", "household_type", "joining_fee_cents",
                   "monthly_dues_cents", "max_adults", "max_dependents", "hold_fee_cents",
                   "created_at", "updated_at", "version"]
MEMBER_FIELDS = ["id", "full_name", "email", "birth_date", "home_branch_id",
                 "visiting_association_name", "created_at", "updated_at", "version"]

HOUSEHOLD_TYPES = {"ADULT", "TWO_ADULT", "FAMILY", "SENIOR", "YOUNG_ADULT", "TEEN"}
READ_ROLES_CORE = ["AssociationAdmin", "BranchDirector", "ProgramCoordinator", "FrontDesk", "BoardMember"]


# ---------------------------------------------------------------------------
# Associations
# ---------------------------------------------------------------------------

@bp.route("/associations", methods=["POST"])
def create_association():
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    body = get_body()
    require_fields(body, ["name", "ami_base_cents", "campaign_year"])
    rec = db.new_record("associations", {
        "name": body["name"],
        "reciprocity_enabled": body.get("reciprocity_enabled", True),
        "ami_base_cents": body["ami_base_cents"],
        "campaign_year": body["campaign_year"],
    })
    return success_object(db.serialize(rec, ASSOCIATION_FIELDS), 201)


@bp.route("/associations/<associationId>", methods=["GET"])
def get_association(associationId):
    role, _ = auth()
    require_role(role, READ_ROLES_CORE)
    rec = db.get("associations", associationId)
    return success_object(db.serialize(rec, ASSOCIATION_FIELDS))


@bp.route("/associations/<associationId>/branches", methods=["GET"])
def list_association_branches(associationId):
    role, _ = auth()
    require_role(role, READ_ROLES_CORE)
    db.get("associations", associationId)
    items = [b for b in db.all_records("branches") if b["association_id"] == associationId]
    return paginate([db.serialize(b, BRANCH_FIELDS) for b in items])


@bp.route("/associations/<associationId>/campaigns", methods=["GET"])
def list_association_campaigns(associationId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "BoardMember", "FrontDesk"])
    db.get("associations", associationId)
    from routes.campaigns import CAMPAIGN_FIELDS
    items = [c for c in db.all_records("campaigns") if c["association_id"] == associationId]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return paginate([db.serialize(c, CAMPAIGN_FIELDS) for c in items])


# ---------------------------------------------------------------------------
# Branches
# ---------------------------------------------------------------------------

@bp.route("/branches", methods=["POST"])
def create_branch():
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    body = get_body()
    require_fields(body, ["association_id", "code", "name", "branch_goal_cents"])
    if body["association_id"] not in db.STORES["associations"]:
        raise ApiError("ERR_NOT_FOUND", f"Association {body['association_id']} not found")
    for b in db.STORES["branches"].values():
        if b["association_id"] == body["association_id"] and b["code"] == body["code"]:
            raise ApiError("ERR_DUPLICATE_BRANCH_CODE", "Branch code already used in this association")
    rec = db.new_record("branches", {
        "association_id": body["association_id"],
        "code": body["code"],
        "name": body["name"],
        "branch_goal_cents": body["branch_goal_cents"],
        "scholarship_pool_received_cents": 0,
        "scholarship_pool_obligated_cents": 0,
        "scholarship_pool_available_cents": 0,
        "active_membership_count": 0,
    })
    return success_object(db.serialize(rec, BRANCH_FIELDS), 201)


@bp.route("/branches/<branchId>", methods=["GET"])
def get_branch(branchId):
    role, _ = auth()
    require_role(role, READ_ROLES_CORE)
    rec = db.get("branches", branchId)
    recompute_branch(rec)
    return success_object(db.serialize(rec, BRANCH_FIELDS))


@bp.route("/branches", methods=["GET"])
def list_branches():
    role, _ = auth()
    require_role(role, READ_ROLES_CORE)
    items = db.all_records("branches")
    association_id = request.args.get("association_id")
    if association_id:
        items = [b for b in items if b["association_id"] == association_id]
    for b in items:
        recompute_branch(b)
    return paginate([db.serialize(b, BRANCH_FIELDS) for b in items])


# ---------------------------------------------------------------------------
# Membership categories
# ---------------------------------------------------------------------------

@bp.route("/categories", methods=["POST"])
def create_category():
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector"])
    body = get_body()
    require_fields(body, ["branch_id", "name", "household_type", "joining_fee_cents",
                          "monthly_dues_cents", "max_adults", "max_dependents"])
    if body["branch_id"] not in db.STORES["branches"]:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    if body["household_type"] not in HOUSEHOLD_TYPES:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid household_type")
    rec = db.new_record("categories", {
        "branch_id": body["branch_id"],
        "name": body["name"],
        "household_type": body["household_type"],
        "joining_fee_cents": body["joining_fee_cents"],
        "monthly_dues_cents": body["monthly_dues_cents"],
        "max_adults": body["max_adults"],
        "max_dependents": body["max_dependents"],
        "hold_fee_cents": body.get("hold_fee_cents", 1000),
    })
    return success_object(db.serialize(rec, CATEGORY_FIELDS), 201)


@bp.route("/categories/<categoryId>", methods=["GET"])
def get_category(categoryId):
    role, _ = auth()
    require_role(role, READ_ROLES_CORE + ["Member"])
    rec = db.get("categories", categoryId)
    return success_object(db.serialize(rec, CATEGORY_FIELDS))


@bp.route("/categories", methods=["GET"])
def list_categories():
    role, _ = auth()
    require_role(role, READ_ROLES_CORE + ["Member"])
    items = db.all_records("categories")
    branch_id = request.args.get("branch_id")
    household_type = request.args.get("household_type")
    if branch_id:
        items = [c for c in items if c["branch_id"] == branch_id]
    if household_type:
        items = [c for c in items if c["household_type"] == household_type]
    return paginate([db.serialize(c, CATEGORY_FIELDS) for c in items])


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@bp.route("/members", methods=["POST"])
def create_member():
    role, _ = auth()
    require_role(role, ["FrontDesk", "AssociationAdmin", "BranchDirector"])
    body = get_body()
    require_fields(body, ["full_name", "email", "birth_date", "home_branch_id"])
    if body["home_branch_id"] not in db.STORES["branches"]:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['home_branch_id']} not found")
    for m in db.STORES["members"].values():
        if m["email"] == body["email"]:
            raise ApiError("ERR_DUPLICATE_EMAIL", "Member email already registered")
    rec = db.new_record("members", {
        "full_name": body["full_name"],
        "email": body["email"],
        "birth_date": body["birth_date"],
        "home_branch_id": body["home_branch_id"],
        "visiting_association_name": body.get("visiting_association_name"),
    })
    return success_object(db.serialize(rec, MEMBER_FIELDS), 201)


@bp.route("/members/<memberId>", methods=["GET"])
def get_member(memberId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator", "FrontDesk", "Member"])
    rec = db.get("members", memberId)
    return success_object(db.serialize(rec, MEMBER_FIELDS))


@bp.route("/members", methods=["GET"])
def list_members():
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "ProgramCoordinator", "FrontDesk"])
    items = db.all_records("members")
    home_branch_id = request.args.get("home_branch_id")
    if home_branch_id:
        items = [m for m in items if m["home_branch_id"] == home_branch_id]
    return paginate([db.serialize(m, MEMBER_FIELDS) for m in items])
