"""Company users: invite, accept, disable, list."""
from flask import Blueprint
import db
from auth import require_role, require_company_scope
from errors import (ok, ok_list, duplicate, invalid_state, seat_limit,
                    needs_primary_admin, invalid_request, not_found,
                    forbidden_role, ApiError)
from helpers import (body_json, req_str, get_or_404, paginate, sort_by_created,
                     enum_check, filter_items, company_subscription)
import serializers

bp = Blueprint("users", __name__, url_prefix="/api/companies/<company_id>")

PERMISSIONS = ("PRIMARY_ADMIN", "COMPANY_ADMIN", "STANDARD", "REPORTS_ONLY", "TIME_TRACKING")


def _occupied_seats(company_id):
    return sum(1 for u in db.TABLES["CompanyUser"].values()
               if u["company_id"] == company_id
               and u["user_status"] in ("INVITED", "ACTIVE"))


def _check_seat_limit(company_id):
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"])
    max_seats = plan["max_seats"] if plan else 0
    if _occupied_seats(company_id) + 1 > max_seats:
        sub["pending_upgrade_prompt"] = True
        db.touch(sub)
        seat_limit()


@bp.post("/users")
def invite_user(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser"])
    company = get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    email = req_str(data, "email")
    display_name = req_str(data, "display_name")
    permission = enum_check(req_str(data, "permission_level"), PERMISSIONS, "permission_level")
    for u in db.TABLES["CompanyUser"].values():
        if u["company_id"] == company_id and u["email"] == email:
            duplicate("email already exists within company")
    sub = company_subscription(company_id)
    if sub is not None and sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        raise ApiError("ERR_SUBSCRIPTION_NOT_WRITABLE", 400, "Subscription not writable")
    _check_seat_limit(company_id)
    rec = {
        "company_id": company_id,
        "email": email,
        "display_name": display_name,
        "permission_level": permission,
        "user_status": "INVITED",
    }
    db.stamp_common(rec)
    db.TABLES["CompanyUser"][rec["id"]] = rec
    if company.get("primary_admin_user_id") is None:
        company["primary_admin_user_id"] = rec["id"]
        db.touch(company)
    return ok(serializers.serialize_company_user(rec), status=201)


@bp.get("/users")
def list_users(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [u for u in db.TABLES["CompanyUser"].values() if u["company_id"] == company_id]
    items = filter_items(items, [("user_status", "user_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_company_user(u) for u in page], limit, offset, total)


@bp.get("/users/<user_id>")
def get_user(company_id, user_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("CompanyUser", user_id)
    if rec["company_id"] != company_id:
        not_found("User not in company")
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_company_user(rec))


@bp.post("/users/<user_id>/accept")
def accept_user(company_id, user_id):
    role, identity = require_role(["CompanyUser"])
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("CompanyUser", user_id)
    if rec["company_id"] != company_id:
        not_found("User not in company")
    require_company_scope(identity, company_id)
    if identity["id"] != user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH", 403, "Invitee must accept themselves")
    if rec["user_status"] != "INVITED":
        invalid_state("User not INVITED")
    sub = company_subscription(company_id)
    if sub["lifecycle_status"] not in ("TRIAL", "ACTIVE", "PAST_DUE", "REACTIVATED"):
        raise ApiError("ERR_SUBSCRIPTION_NOT_WRITABLE", 400, "Subscription not writable")
    # seat re-check: the invitee already occupies a seat (INVITED counts),
    # so acceptance only fails if limit was already exceeded... per spec the
    # same check fires: occupied + 1 > max. Since this user is already counted,
    # we re-check excluding them then adding them.
    plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"])
    occupied = _occupied_seats(company_id)  # includes this user
    if plan is not None and occupied > plan["max_seats"]:
        sub["pending_upgrade_prompt"] = True
        db.touch(sub)
        seat_limit()
    rec["user_status"] = "ACTIVE"
    db.touch(rec)
    if sub.get("pending_upgrade_prompt"):
        sub["pending_upgrade_prompt"] = False
        db.touch(sub)
    return ok(serializers.serialize_company_user(rec))


@bp.post("/users/<user_id>/disable")
def disable_user(company_id, user_id):
    role, identity = require_role(["CompanyUser"])
    company = get_or_404("ClientCompany", company_id)
    rec = get_or_404("CompanyUser", user_id)
    if rec["company_id"] != company_id:
        not_found("User not in company")
    require_company_scope(identity, company_id)
    if identity["permission_level"] not in ("PRIMARY_ADMIN", "COMPANY_ADMIN"):
        forbidden_role()
    if identity["id"] == user_id:
        invalid_request("Cannot disable yourself")
    if company.get("primary_admin_user_id") == user_id:
        invalid_request("Cannot disable the PRIMARY_ADMIN")
    if rec["user_status"] != "ACTIVE":
        invalid_state("User not ACTIVE")
    rec["user_status"] = "DISABLED"
    db.touch(rec)
    return ok(serializers.serialize_company_user(rec))
