"""Routes: campaigns, donations, and the test-driving logical clock."""
from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, success_object, paginate, get_body,
    require_fields, parse_datetime, set_clock, now_dt,
)
from services import recompute_campaign, recompute_branch, tick_clock

bp = Blueprint("campaigns", __name__)

CAMPAIGN_FIELDS = ["id", "association_id", "name", "goal_cents", "base_raised_cents",
                   "match_pct", "matched_raised_cents", "status",
                   "created_at", "updated_at", "version"]
DONATION_FIELDS = ["id", "campaign_id", "branch_id", "donor_member_id", "amount_cents",
                   "designation", "status", "created_at", "updated_at", "version"]

DESIGNATIONS = {"SCHOLARSHIP", "GENERAL"}
READ_ROLES_CAMPAIGN = ["AssociationAdmin", "BranchDirector", "BoardMember", "FrontDesk"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    body = get_body()
    require_fields(body, ["current_utc"])
    dt = parse_datetime(body["current_utc"])
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO datetime")
    set_clock(dt)
    tick_clock()
    return success_object({"current_utc": body["current_utc"]})


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@bp.route("/campaigns", methods=["POST"])
def create_campaign():
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    body = get_body()
    require_fields(body, ["association_id", "name", "goal_cents"])
    if body["association_id"] not in db.STORES["associations"]:
        raise ApiError("ERR_NOT_FOUND", f"Association {body['association_id']} not found")
    rec = db.new_record("campaigns", {
        "association_id": body["association_id"],
        "name": body["name"],
        "goal_cents": body["goal_cents"],
        "base_raised_cents": 0,
        "match_pct": 0,
        "matched_raised_cents": 0,
        "status": "DRAFT",
    })
    return success_object(db.serialize(rec, CAMPAIGN_FIELDS), 201)


@bp.route("/campaigns/<campaignId>", methods=["GET"])
def get_campaign(campaignId):
    role, _ = auth()
    require_role(role, READ_ROLES_CAMPAIGN)
    rec = db.get("campaigns", campaignId)
    return success_object(db.serialize(rec, CAMPAIGN_FIELDS))


@bp.route("/campaigns", methods=["GET"])
def list_campaigns():
    role, _ = auth()
    require_role(role, READ_ROLES_CAMPAIGN)
    items = db.all_records("campaigns")
    association_id = request.args.get("association_id")
    status = request.args.get("status")
    if association_id:
        items = [c for c in items if c["association_id"] == association_id]
    if status:
        items = [c for c in items if c["status"] == status]
    return paginate([db.serialize(c, CAMPAIGN_FIELDS) for c in items])


@bp.route("/campaigns/<campaignId>/activate", methods=["POST"])
def activate_campaign(campaignId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    rec = db.get("campaigns", campaignId)
    if rec["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Campaign is closed")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only DRAFT campaigns can be activated")
    for other in db.STORES["campaigns"].values():
        if (other["id"] != rec["id"]
                and other["association_id"] == rec["association_id"]
                and other["status"] == "ACTIVE"):
            raise ApiError("ERR_CAMPAIGN_ALREADY_ACTIVE",
                           "Association already has an ACTIVE campaign")
    rec["status"] = "ACTIVE"
    db.touch(rec, bump=False)
    return success_object(db.serialize(rec, CAMPAIGN_FIELDS))


@bp.route("/campaigns/<campaignId>/close", methods=["POST"])
def close_campaign(campaignId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    rec = db.get("campaigns", campaignId)
    if rec["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Campaign is closed")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE campaigns can be closed")
    body = get_body()
    expected = body.get("expected_campaign_version")
    if expected is not None and expected != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_campaign_version does not match")
    recompute_campaign(rec)  # finalize attainment before freezing
    rec["status"] = "CLOSED"
    db.touch(rec, bump=True)  # close increments the campaign version
    return success_object(db.serialize(rec, CAMPAIGN_FIELDS))


@bp.route("/campaigns/<campaignId>/donations", methods=["GET"])
def list_campaign_donations(campaignId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "BoardMember"])
    db.get("campaigns", campaignId)
    items = [d for d in db.all_records("donations") if d["campaign_id"] == campaignId]
    branch_id = request.args.get("branch_id")
    status = request.args.get("status")
    designation = request.args.get("designation")
    if branch_id:
        items = [d for d in items if d["branch_id"] == branch_id]
    if status:
        items = [d for d in items if d["status"] == status]
    if designation:
        items = [d for d in items if d["designation"] == designation]
    return paginate([db.serialize(d, DONATION_FIELDS) for d in items])


# ---------------------------------------------------------------------------
# Donations
# ---------------------------------------------------------------------------

@bp.route("/donations", methods=["POST"])
def create_donation():
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "FrontDesk"])
    body = get_body()
    require_fields(body, ["campaign_id", "branch_id", "amount_cents", "designation"])
    if body["campaign_id"] not in db.STORES["campaigns"]:
        raise ApiError("ERR_NOT_FOUND", f"Campaign {body['campaign_id']} not found")
    if body["branch_id"] not in db.STORES["branches"]:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    donor = body.get("donor_member_id")
    if donor is not None and donor not in db.STORES["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "donor_member_id not found")
    if body["designation"] not in DESIGNATIONS:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid designation")
    if not isinstance(body["amount_cents"], int) or body["amount_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    rec = db.new_record("donations", {
        "campaign_id": body["campaign_id"],
        "branch_id": body["branch_id"],
        "donor_member_id": donor,
        "amount_cents": body["amount_cents"],
        "designation": body["designation"],
        "status": "PLEDGED",
    })
    return success_object(db.serialize(rec, DONATION_FIELDS), 201)


@bp.route("/donations/<donationId>", methods=["GET"])
def get_donation(donationId):
    role, _ = auth()
    require_role(role, READ_ROLES_CAMPAIGN + ["Member"])
    rec = db.get("donations", donationId)
    return success_object(db.serialize(rec, DONATION_FIELDS))


@bp.route("/donations", methods=["GET"])
def list_donations():
    role, _ = auth()
    require_role(role, READ_ROLES_CAMPAIGN)
    items = db.all_records("donations")
    campaign_id = request.args.get("campaign_id")
    branch_id = request.args.get("branch_id")
    donor_member_id = request.args.get("donor_member_id")
    status = request.args.get("status")
    designation = request.args.get("designation")
    if campaign_id:
        items = [d for d in items if d["campaign_id"] == campaign_id]
    if branch_id:
        items = [d for d in items if d["branch_id"] == branch_id]
    if donor_member_id:
        items = [d for d in items if d.get("donor_member_id") == donor_member_id]
    if status:
        items = [d for d in items if d["status"] == status]
    if designation:
        items = [d for d in items if d["designation"] == designation]
    return paginate([db.serialize(d, DONATION_FIELDS) for d in items])


@bp.route("/donations/<donationId>/receive", methods=["POST"])
def receive_donation(donationId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin"])
    rec = db.get("donations", donationId)
    campaign = db.STORES["campaigns"].get(rec["campaign_id"])
    if campaign is None:
        raise ApiError("ERR_NOT_FOUND", "Campaign not found")
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE", "Campaign is not ACTIVE")
    if rec["status"] == "REFUNDED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Donation is refunded")
    if rec["status"] != "PLEDGED":
        raise ApiError("ERR_INVALID_STATE", "Only PLEDGED donations can be received")
    rec["status"] = "RECEIVED"
    db.touch(rec, bump=False)
    recompute_campaign(campaign)
    db.touch(campaign, bump=True)  # receipt increments the campaign version
    branch = db.STORES["branches"].get(rec["branch_id"])
    if branch is not None:
        recompute_branch(branch)
    return success_object(db.serialize(rec, DONATION_FIELDS))


@bp.route("/donations/<donationId>/refund", methods=["POST"])
def refund_donation(donationId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin"])
    rec = db.get("donations", donationId)
    if rec["status"] == "REFUNDED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Donation is already refunded")
    if rec["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Only RECEIVED donations can be refunded")
    campaign = db.STORES["campaigns"].get(rec["campaign_id"])
    branch = db.STORES["branches"].get(rec["branch_id"])
    if rec["designation"] == "SCHOLARSHIP" and branch is not None:
        recompute_branch(branch)
        if branch["scholarship_pool_available_cents"] - rec["amount_cents"] < 0:
            raise ApiError("ERR_POOL_WOULD_GO_NEGATIVE",
                           "Refund would make the branch pool negative")
    rec["status"] = "REFUNDED"
    db.touch(rec, bump=False)
    if campaign is not None:
        recompute_campaign(campaign)
        db.touch(campaign, bump=True)  # refund increments the campaign version
    if branch is not None:
        recompute_branch(branch)
    return success_object(db.serialize(rec, DONATION_FIELDS))
