"""Plan templates, promotional pricing, members and corporate accounts."""
from decimal import Decimal

from flask import Blueprint

import calc
import config
import validate as v
from auth import guard, require_owner
from envelope import ok, created
from errors import ApiError
from helpers import (ALL_ROLES, get_corporate, get_franchisee, get_member, get_promotion,
                     get_template, paged)
from store import db, common_fields, clock_date, parse_date, days_between, touch

bp = Blueprint("plans", __name__)

ADMIN = ["BrandAdministrator"]
OWNER = ["FranchiseOwner"]
CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


# --------------------------------------------------------------------------
# plan templates
# --------------------------------------------------------------------------
@bp.post("/franchise/plan-templates")
def create_template():
    guard(ADMIN)
    b = v.body()
    code = v.req_str(b, "code", min_len=2, max_len=24)
    if any(ch not in CODE_CHARS for ch in code):
        raise v.bad("Field 'code' must use uppercase letters, digits and underscore only.")
    monthly = v.req_int(b, "monthly_dues_cents", minimum=100)
    initiation = v.req_int(b, "initiation_fee_cents", minimum=0)
    term_months = v.req_int(b, "term_months", minimum=1, maximum=36)
    notice_days = v.req_int(b, "cancellation_notice_days", minimum=0, maximum=60)
    floor = v.req_int(b, "floor_price_cents", minimum=0)

    if any(t["code"] == code for t in db.plan_templates.values()):
        raise v.bad("Field 'code' must be unique across all plan templates.")

    record = common_fields()
    record.update({
        "code": code,
        "monthly_dues_cents": monthly,
        "initiation_fee_cents": initiation,
        "term_months": term_months,
        "cancellation_notice_days": notice_days,
        "floor_price_cents": floor,
        "status": "DRAFT",
    })
    db.plan_templates[record["id"]] = record
    return created(record)


@bp.post("/franchise/plan-templates/<pid>/publish")
def publish_template(pid):
    guard(ADMIN)
    b = v.body()
    v.opt_str(b, "note")
    record = get_template(pid)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_PLAN_STATE")
    if record["floor_price_cents"] > record["monthly_dues_cents"]:
        raise ApiError("ERR_PRICE_BELOW_FLOOR")
    record["status"] = "PUBLISHED"
    touch(record)
    return ok(record)


@bp.get("/franchise/plan-templates/<pid>")
def read_template(pid):
    guard(ALL_ROLES)
    return ok(get_template(pid))


@bp.get("/franchise/plan-templates")
def list_templates():
    guard(ALL_ROLES)
    return paged(db.plan_templates, "status")


# --------------------------------------------------------------------------
# promotions
# --------------------------------------------------------------------------
def _window_conflict(franchisee_id, plan_template_id, starts_on, ends_on, exclude_id=None):
    new_start = parse_date(starts_on)
    new_end = parse_date(ends_on)
    for promo in db.promotions.values():
        if promo["id"] == exclude_id:
            continue
        if promo["franchisee_id"] != franchisee_id or promo["plan_template_id"] != plan_template_id:
            continue
        if promo["status"] not in ("PENDING_REVIEW", "APPROVED"):
            continue
        other_start = parse_date(promo["starts_on"])
        other_end = parse_date(promo["ends_on"])
        if new_start > other_end:
            gap = days_between(new_start, other_end)
        elif other_start > new_end:
            gap = days_between(other_start, new_end)
        else:
            return True
        if gap < config.PROMO_COOLING_GAP_DAYS:
            return True
    return False


@bp.post("/franchise/promotions")
def create_promotion():
    uid, role = guard(OWNER)
    b = v.body()

    raw = b.get("franchisee_id")
    if isinstance(raw, str) and raw in db.franchisees:
        require_owner(raw == uid)

    franchisee_id = v.req_id(b, "franchisee_id")
    plan_template_id = v.req_id(b, "plan_template_id")
    code = v.req_str(b, "code")
    discount = v.req_decimal(b, "discount_pct", minimum=Decimal("0"), maximum=Decimal("0.500"))
    starts_on = v.req_date(b, "starts_on")
    ends_on = v.req_date(b, "ends_on")

    get_franchisee(franchisee_id)
    template = get_template(plan_template_id)

    if template["status"] != "PUBLISHED":
        raise ApiError("ERR_PLAN_NOT_PUBLISHED")
    if discount > config.MAX_FRANCHISE_DISCOUNT_PCT:
        raise ApiError("ERR_DISCOUNT_CAP_EXCEEDED")
    if parse_date(starts_on) > parse_date(ends_on):
        raise v.bad("Field 'starts_on' may not be later than 'ends_on'.")
    if _window_conflict(franchisee_id, plan_template_id, starts_on, ends_on):
        raise ApiError("ERR_PROMO_WINDOW_CONFLICT")

    record = common_fields()
    record.update({
        "franchisee_id": franchisee_id,
        "plan_template_id": plan_template_id,
        "code": code,
        "discount_pct": float(discount),
        "starts_on": starts_on,
        "ends_on": ends_on,
        "status": "PENDING_REVIEW",
        "reviewed_by_user_id": None,
        "withdrawn_reason": None,
    })
    db.promotions[record["id"]] = record
    return created(record)


@bp.post("/franchise/promotions/<pid>/review")
def review_promotion(pid):
    uid, role = guard(ADMIN)
    b = v.body()
    decision = v.req_enum(b, "decision", ("APPROVE", "REJECT"))
    v.opt_str(b, "note")
    record = get_promotion(pid)

    if record["status"] != "PENDING_REVIEW":
        raise ApiError("ERR_INVALID_PROMOTION_STATE")

    if decision == "APPROVE":
        if Decimal(str(record["discount_pct"])) > config.MAX_FRANCHISE_DISCOUNT_PCT:
            raise ApiError("ERR_DISCOUNT_CAP_EXCEEDED")
        franchisee = db.franchisees.get(record["franchisee_id"])
        if franchisee is not None and franchisee["status"] != "ACTIVE":
            raise ApiError("ERR_FRANCHISEE_ON_PROBATION")
        if _window_conflict(record["franchisee_id"], record["plan_template_id"],
                            record["starts_on"], record["ends_on"], exclude_id=record["id"]):
            raise ApiError("ERR_PROMO_WINDOW_CONFLICT")
        record["status"] = "APPROVED"
    else:
        record["status"] = "REJECTED"

    record["reviewed_by_user_id"] = uid
    touch(record)
    return ok(record)


@bp.get("/franchise/promotions/<pid>")
def read_promotion(pid):
    guard(ALL_ROLES)
    return ok(get_promotion(pid))


@bp.get("/franchise/promotions")
def list_promotions():
    guard(ALL_ROLES)
    return paged(db.promotions, "franchisee_id", "plan_template_id", "status")


# --------------------------------------------------------------------------
# members
# --------------------------------------------------------------------------
@bp.post("/franchise/members")
def create_member():
    guard(["BrandAdministrator", "ClubManager"])
    b = v.body()
    full_name = v.req_str(b, "full_name")
    email = v.req_str(b, "email")
    home_state_code = v.req_enum(b, "home_state_code", config.STATE_CODES)

    if any(m["email"] == email for m in db.members.values()):
        raise v.bad("Field 'email' must be unique across members.")

    record = common_fields()
    record.update({
        "full_name": full_name,
        "email": email,
        "home_state_code": home_state_code,
        "status": "ACTIVE",
        "agreement_count": 0,
    })
    db.members[record["id"]] = record
    return created(record)


@bp.get("/franchise/members/<mid>")
def read_member(mid):
    guard(ALL_ROLES)
    return ok(get_member(mid))


@bp.get("/franchise/members")
def list_members():
    guard(ALL_ROLES)
    return paged(db.members, "status", "home_state_code")


# --------------------------------------------------------------------------
# corporate accounts
# --------------------------------------------------------------------------
def _eligible_weights(account):
    counts = {}
    for agreement in db.agreements.values():
        if agreement.get("corporate_account_id") != account["id"]:
            continue
        if agreement["agreement_status"] not in config.ENROLLED_AGREEMENT_STATES:
            continue
        club = db.clubs.get(agreement["home_club_id"])
        if club is None:
            continue
        counts[club["franchisee_id"]] = counts.get(club["franchisee_id"], 0) + 1

    eligible = []
    for franchisee_id, weight in counts.items():
        franchisee = db.franchisees.get(franchisee_id)
        if franchisee is None:
            continue
        if franchisee["status"] != "ACTIVE" or not franchisee["national_account_eligible"]:
            continue
        if weight < 1:
            continue
        if account["allocation_method"] == "EQUAL_SPLIT":
            weight = 1
        eligible.append({"franchisee": franchisee, "weight": weight})
    return eligible


@bp.post("/franchise/corporate-accounts")
def create_corporate():
    guard(ADMIN)
    b = v.body()
    name = v.req_str(b, "name")
    credit = v.req_decimal(b, "corporate_credit_pct", minimum=Decimal("0"),
                           maximum=Decimal("0.100"))
    method = v.opt_enum(b, "allocation_method", ("USAGE_SHARE", "EQUAL_SPLIT"),
                        default="USAGE_SHARE")

    record = common_fields()
    record.update({
        "name": name,
        "corporate_credit_pct": float(credit),
        "allocation_method": method,
        "status": "ACTIVE",
        "pool_balance_cents": 0,
        "allocated_cents": 0,
        "lifetime_funded_cents": 0,
        "enrolled_agreement_count": 0,
    })
    db.corporate_accounts[record["id"]] = record
    return created(record)


@bp.post("/franchise/corporate-accounts/<cid>/fund")
def fund_corporate(cid):
    guard(ADMIN)
    b = v.body()
    amount = v.req_money(b, "amount_cents")
    account = get_corporate(cid)
    account["pool_balance_cents"] += amount
    account["lifetime_funded_cents"] += amount
    touch(account)
    return ok(account)


@bp.post("/franchise/corporate-accounts/<cid>/allocate")
def allocate_corporate(cid):
    guard(ADMIN)
    b = v.body()
    v.opt_str(b, "note")
    account = get_corporate(cid)

    if account["pool_balance_cents"] == 0:
        raise ApiError("ERR_INVALID_ALLOCATION_STATE")
    eligible = _eligible_weights(account)
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_FRANCHISEE")

    pool = account["pool_balance_cents"]
    shares = calc.allocate_pool(pool, eligible)
    for entry in eligible:
        franchisee = entry["franchisee"]
        franchisee["corporate_allocation_cents"] += shares[franchisee["id"]]
        touch(franchisee)
    account["allocated_cents"] += pool
    account["pool_balance_cents"] = 0
    touch(account)
    return ok(account)


@bp.post("/franchise/corporate-accounts/<cid>/recall-allocation")
def recall_corporate(cid):
    guard(ADMIN)
    b = v.body()
    v.req_str(b, "reason")
    account = get_corporate(cid)

    if account["allocated_cents"] == 0:
        raise ApiError("ERR_INVALID_ALLOCATION_STATE")

    allocated = account["allocated_cents"]
    eligible = _eligible_weights(account)
    if eligible:
        shares = calc.allocate_pool(allocated, eligible)
        for entry in eligible:
            franchisee = entry["franchisee"]
            franchisee["corporate_allocation_cents"] -= shares[franchisee["id"]]
            touch(franchisee)
    account["pool_balance_cents"] += allocated
    account["allocated_cents"] = 0
    touch(account)
    return ok(account)


@bp.post("/franchise/corporate-accounts/<cid>/suspend")
def suspend_corporate(cid):
    guard(ADMIN)
    b = v.body()
    v.req_str(b, "reason")
    account = get_corporate(cid)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_CORPORATE_ACCOUNT_SUSPENDED")
    account["status"] = "SUSPENDED"
    touch(account)
    return ok(account)


@bp.get("/franchise/corporate-accounts/<cid>")
def read_corporate(cid):
    guard(ALL_ROLES)
    return ok(get_corporate(cid))


@bp.get("/franchise/corporate-accounts")
def list_corporate():
    guard(ALL_ROLES)
    return paged(db.corporate_accounts, "status", "allocation_method")
