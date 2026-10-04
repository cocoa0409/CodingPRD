"""Commercial routes (PRD 3.4, 3.5): plans, accounts, subscriptions,
plan changes, lifecycle status, seat management, and subscriber users."""

from flask import Blueprint, g, request

from constants import (
    ACCOUNT_TYPES,
    BILLING_MODELS,
    DEFAULT_BULK_DAILY_LIMIT,
    DEFAULT_BULK_HOURLY_LIMIT,
    FIRM_SIZE_TIERS,
    JURISDICTION_SCOPES,
    PLAN_PRACTICE_AREAS,
    SCOPE_ENFORCEMENTS,
    SEAT_ACTIONS,
    SUBSCRIPTION_STATUSES,
    SUBSCRIPTION_TARGET_STATUSES,
)
from db import stamp_new, store, touch
from errors import raise_err
from middleware import require_roles
from response import list_response, ok_object
from serializers import (
    serialize_account,
    serialize_plan,
    serialize_subscription,
    serialize_user,
    seats_used,
)
from util import (
    get_body,
    opt_enum_query,
    opt_int,
    opt_number,
    opt_str,
    req_bool,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("commercial", __name__)

SUBSCRIPTION_READERS = ("LicensingManager", "FirmAdmin", "BillingAdmin")
USER_READERS = ("LicensingManager", "FirmAdmin")


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

@bp.post("/legal-research/plans")
@require_roles("LicensingManager")
def create_plan():
    body = get_body()
    name = req_str(body, "name")
    practice_area = req_enum(body, "practice_area", PLAN_PRACTICE_AREAS)
    jurisdiction_scope = req_enum(body, "jurisdiction_scope", JURISDICTION_SCOPES)
    firm_size_tier = req_enum(body, "firm_size_tier", FIRM_SIZE_TIERS)
    billing_model = req_enum(body, "billing_model", BILLING_MODELS)
    scope_enforcement = req_enum(body, "scope_enforcement", SCOPE_ENFORCEMENTS)
    government_only = req_bool(body, "government_only")
    cost_recovery_allowed = req_bool(body, "cost_recovery_allowed")

    monthly_fee = opt_int(body, "monthly_fee_cents")
    if billing_model == "FLAT_RATE" and monthly_fee is None:
        raise_err("ERR_INVALID_REQUEST", "monthly_fee_cents is required for FLAT_RATE plans")

    plan = stamp_new({
        "name": name,
        "practice_area": practice_area,
        "jurisdiction_scope": jurisdiction_scope,
        "firm_size_tier": firm_size_tier,
        "billing_model": billing_model,
        "monthly_fee_cents": monthly_fee,
        "included_searches": opt_int(body, "included_searches", 0),
        "included_doc_views": opt_int(body, "included_doc_views", 0),
        "overage_search_fee_cents": opt_int(body, "overage_search_fee_cents", 0),
        "overage_doc_view_fee_cents": opt_int(body, "overage_doc_view_fee_cents", 0),
        "volume_discount_pct": opt_number(body, "volume_discount_pct", 0),
        "discount_threshold_overage_units": opt_int(body, "discount_threshold_overage_units", 0),
        "per_search_fee_cents": opt_int(body, "per_search_fee_cents", 0),
        "per_doc_view_fee_cents": opt_int(body, "per_doc_view_fee_cents", 0),
        "scope_enforcement": scope_enforcement,
        "government_only": government_only,
        "cost_recovery_allowed": cost_recovery_allowed,
        "bulk_hourly_limit": opt_int(body, "bulk_hourly_limit", DEFAULT_BULK_HOURLY_LIMIT),
        "bulk_daily_limit": opt_int(body, "bulk_daily_limit", DEFAULT_BULK_DAILY_LIMIT),
    })
    store.plans[plan["id"]] = plan
    return ok_object(serialize_plan(plan), 201)


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

@bp.post("/legal-research/accounts")
@require_roles("LicensingManager")
def create_account():
    body = get_body()
    account = stamp_new({
        "org_name": req_str(body, "org_name"),
        "account_type": req_enum(body, "account_type", ACCOUNT_TYPES),
        "cost_recovery_enabled": req_bool(body, "cost_recovery_enabled"),
    })
    store.accounts[account["id"]] = account
    return ok_object(serialize_account(account), 201)


# --------------------------------------------------------------------------
# Subscriptions
# --------------------------------------------------------------------------

@bp.post("/legal-research/subscriptions")
@require_roles("LicensingManager")
def create_subscription():
    body = get_body()
    account_id = req_str(body, "account_id")
    plan_id = req_str(body, "plan_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    seats_total = req_int(body, "seats_total")
    if not (period_start < period_end):
        raise_err("ERR_INVALID_REQUEST", "period_start must be earlier than period_end")
    if seats_total <= 0:
        raise_err("ERR_INVALID_REQUEST", "seats_total must be a positive integer")

    # Body-referenced existence, in cascade order: plan (13) before account (14).
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_err("ERR_PLAN_NOT_FOUND", "plan %s does not exist" % plan_id)
    account = store.accounts.get(account_id)
    if account is None:
        raise_err("ERR_ACCOUNT_NOT_FOUND", "account %s does not exist" % account_id)

    # Overlap (priority 34) precedes eligibility (priority 37). Half-open
    # [period_start, period_end): adjacency is allowed.
    for other in store.subscriptions.values():
        if other["account_id"] != account_id or other["status"] == "CANCELLED":
            continue
        if period_start < _date(other["period_end"]) and _date(other["period_start"]) < period_end:
            raise_err("ERR_SUBSCRIPTION_OVERLAP", "period overlaps an existing subscription")

    if plan["government_only"] and account["account_type"] != "GOVERNMENT":
        raise_err("ERR_PLAN_ACCOUNT_INCOMPATIBLE", "government_only plan requires a GOVERNMENT account")

    subscription = stamp_new({
        "account_id": account_id,
        "plan_id": plan_id,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "seats_total": seats_total,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    store.subscriptions[subscription["id"]] = subscription
    return ok_object(serialize_subscription(subscription), 201)


def _date(text):
    from datetime import datetime
    return datetime.strptime(text, "%Y-%m-%d").date()


def _get_subscription_or_404(subscription_id):
    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        raise_err("ERR_SUBSCRIPTION_NOT_FOUND", "subscription %s does not exist" % subscription_id)
    return sub


@bp.get("/legal-research/subscriptions")
@require_roles(*SUBSCRIPTION_READERS)
def list_subscriptions():
    f_account = request.args.get("account_id")
    f_plan = request.args.get("plan_id")
    f_status = opt_enum_query("status", SUBSCRIPTION_STATUSES)

    rows = list(store.subscriptions.values())
    if f_account is not None:
        rows = [s for s in rows if s["account_id"] == f_account]
    if f_plan is not None:
        rows = [s for s in rows if s["plan_id"] == f_plan]
    if f_status is not None:
        rows = [s for s in rows if s["status"] == f_status]
    return list_response(rows, serialize_subscription)


@bp.get("/legal-research/subscriptions/<subscription_id>")
@require_roles(*SUBSCRIPTION_READERS)
def get_subscription(subscription_id):
    return ok_object(serialize_subscription(_get_subscription_or_404(subscription_id)))


@bp.patch("/legal-research/subscriptions/<subscription_id>/change-plan")
@require_roles("LicensingManager")
def change_plan(subscription_id):
    body = get_body()
    new_plan_id = req_str(body, "new_plan_id")
    expected_version = req_int(body, "expected_subscription_version")

    sub = _get_subscription_or_404(subscription_id)
    if new_plan_id not in store.plans:
        raise_err("ERR_PLAN_NOT_FOUND", "plan %s does not exist" % new_plan_id)
    if expected_version != sub["version"]:
        raise_err("ERR_STALE_VERSION", "expected_subscription_version %s does not match current version %s" % (expected_version, sub["version"]))

    sub["plan_id"] = new_plan_id
    touch(sub)
    return ok_object(serialize_subscription(sub), 200)


@bp.post("/legal-research/subscriptions/<subscription_id>/status")
@require_roles("LicensingManager")
def change_subscription_status(subscription_id):
    body = get_body()
    target = req_enum(body, "target_status", SUBSCRIPTION_TARGET_STATUSES)

    sub = _get_subscription_or_404(subscription_id)
    current = sub["status"]

    if target == "SUSPENDED":
        if current != "ACTIVE":
            raise_err("ERR_INVALID_STATE", "subscription %s cannot be suspended from %s" % (subscription_id, current))
        sub["status"] = "SUSPENDED"
        sub["suspension_reason"] = "MANUAL"
    elif target == "ACTIVE":
        if current != "SUSPENDED":
            raise_err("ERR_INVALID_STATE", "subscription %s cannot be resumed from %s" % (subscription_id, current))
        # Manual resume is always allowed (PRD 3.4).
        sub["status"] = "ACTIVE"
        sub["suspension_reason"] = None
    else:  # CANCELLED
        if current not in ("ACTIVE", "SUSPENDED"):
            raise_err("ERR_INVALID_STATE", "subscription %s cannot be cancelled from %s" % (subscription_id, current))
        sub["status"] = "CANCELLED"
        sub["suspension_reason"] = None
        # Compensation: release every seat and void every DRAFT invoice.
        for user in store.users.values():
            if user["seat_subscription_id"] == sub["id"]:
                user["seat_status"] = "NONE"
                user["seat_subscription_id"] = None
                touch(user)
        for inv in store.invoices.values():
            if inv["subscription_id"] == sub["id"] and inv["status"] == "DRAFT":
                inv["status"] = "VOID"
                touch(inv)

    touch(sub)
    return ok_object(serialize_subscription(sub), 200)


# --------------------------------------------------------------------------
# Seats
# --------------------------------------------------------------------------

@bp.post("/legal-research/subscriptions/<subscription_id>/seats")
@require_roles("FirmAdmin")
def manage_seats(subscription_id):
    # The path id must resolve before the ownership comparison can run.
    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        raise_err("ERR_SUBSCRIPTION_NOT_FOUND", "subscription %s does not exist" % subscription_id)

    # Ownership (priority 3): FirmAdmin's X-User-ID is the account id.
    if g.user_id != sub["account_id"]:
        raise_err("ERR_ACCOUNT_MISMATCH", "FirmAdmin may only manage seats of its own account")

    body = get_body()
    action = req_enum(body, "action", SEAT_ACTIONS)

    if action == "ASSIGN":
        email = req_str(body, "user_email")
        full_name = req_str(body, "user_full_name")
        # Shape: the supplied email must be unique within the account.
        for user in store.users.values():
            if user["account_id"] == sub["account_id"] and user["email"] == email:
                raise_err("ERR_INVALID_REQUEST", "email %s already exists within the account" % email)

        if sub["status"] != "ACTIVE":
            raise_err("ERR_SUBSCRIPTION_NOT_ACTIVE", "subscription %s is not ACTIVE" % subscription_id)
        for user in store.users.values():
            if (
                user["account_id"] == sub["account_id"]
                and user["email"] == email
                and user["seat_status"] == "ACTIVE"
            ):
                raise_err("ERR_SEAT_ALREADY_HELD", "email %s already holds an active seat" % email)
        # Fiscal capacity gate fires last, after every state and safety check.
        if seats_used(sub["id"]) >= sub["seats_total"]:
            raise_err("ERR_NO_SEATS_AVAILABLE", "subscription %s has no seats available" % subscription_id)

        user = stamp_new({
            "account_id": sub["account_id"],
            "email": email,
            "full_name": full_name,
            "seat_status": "ACTIVE",
            "seat_subscription_id": sub["id"],
        })
        store.users[user["id"]] = user
        touch(sub)
        return ok_object(serialize_subscription(sub), 200)

    # RELEASE
    user_id = req_str(body, "user_id")
    user = store.users.get(user_id)
    if user is None:
        raise_err("ERR_USER_NOT_FOUND", "user %s does not exist" % user_id)
    if user["seat_status"] != "ACTIVE" or user["seat_subscription_id"] != sub["id"]:
        raise_err("ERR_NO_SEAT_HELD", "user %s holds no active seat on this subscription" % user_id)

    user["seat_status"] = "NONE"
    user["seat_subscription_id"] = None
    touch(user)
    touch(sub)
    return ok_object(serialize_subscription(sub), 200)


# --------------------------------------------------------------------------
# Subscriber users
# --------------------------------------------------------------------------

@bp.get("/legal-research/users")
@require_roles(*USER_READERS)
def list_users():
    f_account = request.args.get("account_id")
    f_seat_sub = request.args.get("seat_subscription_id")

    rows = list(store.users.values())
    if f_account is not None:
        rows = [u for u in rows if u["account_id"] == f_account]
    if f_seat_sub is not None:
        rows = [u for u in rows if u["seat_subscription_id"] == f_seat_sub]
    return list_response(rows, serialize_user)


@bp.get("/legal-research/users/<user_id>")
@require_roles(*USER_READERS)
def get_user(user_id):
    user = store.users.get(user_id)
    if user is None:
        raise_err("ERR_USER_NOT_FOUND", "user %s does not exist" % user_id)
    return ok_object(serialize_user(user))
