"""Routes: memberships, membership actions (hold/resume/cancel/reinstate), drafts."""
from datetime import timedelta

from flask import Blueprint, request

import db
from common import (
    ApiError, auth, require_role, require_member_owner, success_object, paginate,
    get_body, require_fields, today, parse_date,
)
from services import (
    recompute_branch, draft_amount_and_kind, reprice_pending_drafts,
    hold_days_used, expire_award, age_on,
)

bp = Blueprint("memberships", __name__)

MEMBERSHIP_FIELDS = [
    "id", "branch_id", "category_id", "primary_member_id", "member_ids",
    "status", "draft_status", "assistance_pct", "joining_fee_charged_cents",
    "anniversary_day", "hold_started_on", "hold_until", "lapsed_on",
    "delinquent_since", "hold_days_used_trailing_12mo", "lifetime_billed_cents",
    "created_at", "updated_at", "version",
]
DRAFT_FIELDS = [
    "id", "membership_id", "period_month", "amount_cents", "attempt_count",
    "status", "kind", "created_at", "updated_at", "version",
]


def serialize_membership(m):
    return db.serialize(m, MEMBERSHIP_FIELDS)


def serialize_draft(d):
    return db.serialize(d, DRAFT_FIELDS)


def _check_household_caps(category, member_ids):
    adults = 0
    dependents = 0
    for mid in member_ids:
        member = db.STORES["members"].get(mid)
        if member is None:
            raise ApiError("ERR_MEMBER_NOT_FOUND", f"Member {mid} not found")
        if age_on(member["birth_date"], today()) >= 18:
            adults += 1
        else:
            dependents += 1
    if adults > category["max_adults"] or dependents > category["max_dependents"]:
        raise ApiError("ERR_HOUSEHOLD_CAP_EXCEEDED",
                       "Household composition exceeds category caps")


def _joining_fee_waived(branch_id, primary_member_id, activation_date):
    """Fee waived when the primary member previously held a CANCELLED/LAPSED
    membership at this branch whose terminal date is within 30 days."""
    for m in db.STORES["memberships"].values():
        if m["branch_id"] != branch_id or m["primary_member_id"] != primary_member_id:
            continue
        if m["status"] == "CANCELLED":
            terminal = m["updated_at"].date()
        elif m["status"] == "LAPSED" and m.get("lapsed_on"):
            terminal = parse_date(m["lapsed_on"])
        else:
            continue
        if terminal is None:
            continue
        delta = (activation_date - terminal).days
        if 0 <= delta <= 30:
            return True
    return False


# ---------------------------------------------------------------------------
# Membership CRUD + actions
# ---------------------------------------------------------------------------

@bp.route("/memberships", methods=["POST"])
def create_membership():
    role, user_id = auth()
    require_role(role, ["FrontDesk", "Member", "BranchDirector", "AssociationAdmin"])
    body = get_body()
    require_fields(body, ["branch_id", "category_id", "primary_member_id", "member_ids"])
    branch = db.STORES["branches"].get(body["branch_id"])
    if branch is None:
        raise ApiError("ERR_BRANCH_NOT_FOUND", f"Branch {body['branch_id']} not found")
    category = db.STORES["categories"].get(body["category_id"])
    if category is None or category["branch_id"] != branch["id"]:
        raise ApiError("ERR_CATEGORY_NOT_FOUND", "Category not found for this branch")
    if body["primary_member_id"] not in db.STORES["members"]:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "Primary member not found")
    if role == "Member" and user_id != body["primary_member_id"]:
        raise ApiError("ERR_UNAUTHORIZED", "Member may only join themselves")
    member_ids = list(body.get("member_ids") or [])
    if body["primary_member_id"] not in member_ids:
        member_ids.insert(0, body["primary_member_id"])
    _check_household_caps(category, member_ids)

    activation = today()
    waived = _joining_fee_waived(branch["id"], body["primary_member_id"], activation)
    fee = 0 if waived else category["joining_fee_cents"]
    rec = db.new_record("memberships", {
        "branch_id": branch["id"],
        "category_id": category["id"],
        "primary_member_id": body["primary_member_id"],
        "member_ids": member_ids,
        "status": "ACTIVE",
        "draft_status": "CURRENT",
        "assistance_pct": 0,
        "joining_fee_charged_cents": fee,
        "anniversary_day": min(activation.day, 28),
        "hold_started_on": None,
        "hold_until": None,
        "lapsed_on": None,
        "delinquent_since": None,
        "hold_days_used_trailing_12mo": 0,
        "lifetime_billed_cents": 0,
        "hold_windows": [],
    })
    period = f"{activation.year:04d}-{activation.month:02d}"
    if fee > 0:
        db.new_record("drafts", {
            "membership_id": rec["id"],
            "period_month": period,
            "amount_cents": fee,
            "attempt_count": 0,
            "status": "PENDING",
            "kind": "JOINING_FEE",
        })
    amount, kind = draft_amount_and_kind(rec, category, prorate=True, activation_date=activation)
    db.new_record("drafts", {
        "membership_id": rec["id"],
        "period_month": period,
        "amount_cents": amount,
        "attempt_count": 0,
        "status": "PENDING",
        "kind": "REGULAR",
    })
    recompute_branch(branch)
    return success_object(serialize_membership(rec), 201)


@bp.route("/memberships/<membershipId>", methods=["GET"])
def get_membership(membershipId):
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "FrontDesk", "Member"])
    rec = db.get("memberships", membershipId)
    return success_object(serialize_membership(rec))


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    role, _ = auth()
    require_role(role, ["AssociationAdmin", "BranchDirector", "FrontDesk"])
    items = db.all_records("memberships")
    branch_id = request.args.get("branch_id")
    category_id = request.args.get("category_id")
    primary_member_id = request.args.get("primary_member_id")
    status = request.args.get("status")
    if branch_id:
        items = [m for m in items if m["branch_id"] == branch_id]
    if category_id:
        items = [m for m in items if m["category_id"] == category_id]
    if primary_member_id:
        items = [m for m in items if m["primary_member_id"] == primary_member_id]
    if status:
        items = [m for m in items if m["status"] == status]
    return paginate([serialize_membership(m) for m in items])


@bp.route("/memberships/<membershipId>", methods=["PATCH"])
def update_membership(membershipId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "FrontDesk"])
    rec = db.get("memberships", membershipId)
    body = get_body()
    if "category_id" in body:
        category = db.STORES["categories"].get(body["category_id"])
        if category is None or category["branch_id"] != rec["branch_id"]:
            raise ApiError("ERR_CATEGORY_NOT_FOUND", "Category not found for this branch")
    new_member_ids = body.get("member_ids")
    if new_member_ids is not None:
        category_for_caps = db.STORES["categories"].get(
            body.get("category_id") or rec["category_id"])
        _check_household_caps(category_for_caps, list(new_member_ids))
    expected = body.get("expected_membership_version")
    if expected is not None and expected != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_membership_version does not match")
    if "category_id" in body:
        rec["category_id"] = body["category_id"]
    if new_member_ids is not None:
        rec["member_ids"] = list(new_member_ids)
    db.touch(rec, bump=True)
    reprice_pending_drafts(rec)
    return success_object(serialize_membership(rec))


@bp.route("/memberships/<membershipId>/hold", methods=["POST"])
def hold_membership(membershipId):
    role, user_id = auth()
    require_role(role, ["Member", "BranchDirector"])
    rec = db.get("memberships", membershipId)
    require_member_owner(role, user_id, rec["primary_member_id"])
    body = get_body()
    require_fields(body, ["hold_until"])
    if rec["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Membership is cancelled")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE memberships can be held")
    hold_until = parse_date(body["hold_until"])
    current = today()
    if hold_until is None or hold_until <= current:
        raise ApiError("ERR_HOLD_WINDOW_INVALID", "hold_until must be a future ISO date")
    requested_days = (hold_until - current).days
    if requested_days < 30 or requested_days > 180:
        raise ApiError("ERR_HOLD_WINDOW_INVALID", "Hold must be 30..180 days")
    used = hold_days_used(rec, current)
    if used + requested_days > 120:
        raise ApiError("ERR_HOLD_ALLOWANCE_EXCEEDED", "Hold allowance exceeded")
    rec["status"] = "ON_HOLD"
    rec["hold_started_on"] = current.isoformat()
    rec["hold_until"] = hold_until.isoformat()
    db.touch(rec, bump=False)
    branch = db.STORES["branches"].get(rec["branch_id"])
    if branch is not None:
        recompute_branch(branch)
    return success_object(serialize_membership(rec))


@bp.route("/memberships/<membershipId>/resume", methods=["POST"])
def resume_membership(membershipId):
    role, user_id = auth()
    require_role(role, ["Member", "BranchDirector"])
    rec = db.get("memberships", membershipId)
    require_member_owner(role, user_id, rec["primary_member_id"])
    if rec["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Membership is cancelled")
    if rec["status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_STATE", "Only ON_HOLD memberships can resume")
    current = today()
    hs = parse_date(rec.get("hold_started_on"))
    if hs is not None:
        rec.setdefault("hold_windows", []).append((hs, current))
    rec["status"] = "ACTIVE"
    rec["hold_started_on"] = None
    rec["hold_until"] = None
    rec["hold_days_used_trailing_12mo"] = hold_days_used(rec, current)
    db.touch(rec, bump=False)
    return success_object(serialize_membership(rec))


@bp.route("/memberships/<membershipId>/cancel", methods=["POST"])
def cancel_membership(membershipId):
    role, user_id = auth()
    require_role(role, ["Member", "BranchDirector"])
    rec = db.get("memberships", membershipId)
    require_member_owner(role, user_id, rec["primary_member_id"])
    if rec["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Membership is cancelled")
    if rec["status"] == "LAPSED":
        raise ApiError("ERR_INVALID_STATE", "LAPSED memberships cannot be cancelled")
    rec["status"] = "CANCELLED"
    rec["assistance_pct"] = 0
    rec["hold_started_on"] = None
    rec["hold_until"] = None
    db.touch(rec, bump=False)
    for a in db.STORES["applications"].values():
        if a["membership_id"] == rec["id"] and a["status"] == "APPROVED":
            expire_award(a)
    branch = db.STORES["branches"].get(rec["branch_id"])
    if branch is not None:
        recompute_branch(branch)
    return success_object(serialize_membership(rec))


@bp.route("/memberships/<membershipId>/reinstate", methods=["POST"])
def reinstate_membership(membershipId):
    role, _ = auth()
    require_role(role, ["BranchDirector"])
    rec = db.get("memberships", membershipId)
    if rec["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Membership is cancelled")
    if rec["status"] != "LAPSED":
        raise ApiError("ERR_INVALID_STATE", "Only LAPSED memberships can be reinstated")
    lapsed_on = parse_date(rec.get("lapsed_on"))
    current = today()
    window_ok = lapsed_on is not None and (current - lapsed_on).days <= 90
    failed_remain = any(
        d["membership_id"] == rec["id"] and d["status"] == "FAILED"
        for d in db.STORES["drafts"].values()
    )
    if not window_ok or failed_remain:
        raise ApiError("ERR_REINSTATE_WINDOW_PASSED",
                       "Reinstate window passed or FAILED drafts remain")
    rec["status"] = "ACTIVE"
    rec["draft_status"] = "CURRENT"
    rec["delinquent_since"] = None
    rec["lapsed_on"] = None
    db.touch(rec, bump=False)
    branch = db.STORES["branches"].get(rec["branch_id"])
    if branch is not None:
        recompute_branch(branch)
    return success_object(serialize_membership(rec))


# ---------------------------------------------------------------------------
# Billing drafts
# ---------------------------------------------------------------------------

@bp.route("/memberships/<membershipId>/drafts", methods=["POST"])
def create_draft(membershipId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin"])
    rec = db.get("memberships", membershipId)
    if rec["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", "Membership is cancelled")
    current = today()
    period = f"{current.year:04d}-{current.month:02d}"
    for d in db.STORES["drafts"].values():
        if d["membership_id"] == rec["id"] and d["period_month"] == period:
            raise ApiError("ERR_DUPLICATE_DRAFT",
                           "A draft already exists for this membership and period")
    category = db.STORES["categories"].get(rec["category_id"])
    amount, kind = draft_amount_and_kind(rec, category)
    draft = db.new_record("drafts", {
        "membership_id": rec["id"],
        "period_month": period,
        "amount_cents": amount,
        "attempt_count": 0,
        "status": "PENDING",
        "kind": kind,
    })
    db.touch(rec, bump=True)  # creating a draft increments the membership version
    return success_object(serialize_draft(draft), 201)


@bp.route("/memberships/<membershipId>/drafts", methods=["GET"])
def list_membership_drafts(membershipId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "FrontDesk", "Member"])
    db.get("memberships", membershipId)
    items = [d for d in db.all_records("drafts") if d["membership_id"] == membershipId]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    return paginate([serialize_draft(d) for d in items])


@bp.route("/drafts/<draftId>", methods=["GET"])
def get_draft(draftId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "FrontDesk", "Member"])
    rec = db.get("drafts", draftId)
    return success_object(serialize_draft(rec))


@bp.route("/drafts", methods=["GET"])
def list_drafts():
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin", "FrontDesk"])
    items = db.all_records("drafts")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    if membership_id:
        items = [d for d in items if d["membership_id"] == membership_id]
    if status:
        items = [d for d in items if d["status"] == status]
    return paginate([serialize_draft(d) for d in items])


@bp.route("/drafts/<draftId>/settle", methods=["POST"])
def settle_draft(draftId):
    role, user_id = auth()
    require_role(role, ["Member", "BranchDirector", "FrontDesk"])
    rec = db.get("drafts", draftId)
    membership = db.STORES["memberships"].get(rec["membership_id"])
    if role == "Member" and membership is not None:
        require_member_owner(role, user_id, membership["primary_member_id"])
    if rec["status"] not in ("PENDING", "FAILED"):
        raise ApiError("ERR_INVALID_STATE", "Only PENDING or FAILED drafts can be settled")
    rec["status"] = "PAID"
    db.touch(rec, bump=False)
    if membership is not None:
        membership["lifetime_billed_cents"] = (
            membership.get("lifetime_billed_cents", 0) + rec["amount_cents"])
        still_failed = any(
            d["membership_id"] == membership["id"] and d["status"] == "FAILED"
            for d in db.STORES["drafts"].values()
        )
        if not still_failed:
            membership["draft_status"] = "CURRENT"
            membership["delinquent_since"] = None
        db.touch(membership, bump=False)
    return success_object(serialize_draft(rec))


@bp.route("/drafts/<draftId>/fail", methods=["POST"])
def fail_draft(draftId):
    role, _ = auth()
    require_role(role, ["BranchDirector", "AssociationAdmin"])
    rec = db.get("drafts", draftId)
    if rec["status"] not in ("PENDING", "FAILED") or rec["attempt_count"] >= 3:
        raise ApiError("ERR_INVALID_STATE",
                       "Draft cannot be failed (status/attempt_count)")
    rec["attempt_count"] += 1
    rec["status"] = "FAILED"
    db.touch(rec, bump=False)
    membership = db.STORES["memberships"].get(rec["membership_id"])
    if membership is not None:
        if rec["attempt_count"] >= 3:
            membership["draft_status"] = "DELINQUENT"
            membership["delinquent_since"] = today().isoformat()
        else:
            membership["draft_status"] = "RETRY_PENDING"
        db.touch(membership, bump=False)
    return success_object(serialize_draft(rec))
