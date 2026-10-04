"""Flask entry point: route registration and error handlers."""
import os
import re
from datetime import datetime, timezone

from flask import Flask, request, jsonify

from db import store, _parse_iso, _fmt_iso
from errors import ApiError, err
from middleware import require_roles, check_owner
from response import ok_object, ok_no_content, error_response, paginate
import services as svc

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc)


@app.errorhandler(404)
def handle_404(exc):
    return error_response(ApiError("ERR_NOT_FOUND", "Route not found"))


@app.errorhandler(405)
def handle_405(exc):
    return error_response(ApiError("ERR_NOT_FOUND", "Route not found"))


@app.errorhandler(Exception)
def handle_generic(exc):
    if isinstance(exc, ApiError):
        return error_response(exc)
    import traceback
    traceback.print_exc()
    return error_response(ApiError("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc))


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_field(data, name, types, enum=None):
    if name not in data or data[name] is None:
        err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    v = data[name]
    if not isinstance(v, types) or (types is int and isinstance(v, bool)):
        err("ERR_INVALID_REQUEST", "Field %s has wrong type" % name)
    if enum is not None and v not in enum:
        err("ERR_INVALID_REQUEST", "Field %s has bad value" % name)
    return v


def opt_field(data, name, types, default=None, enum=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, types) or (types is int and isinstance(v, bool)):
        err("ERR_INVALID_REQUEST", "Field %s has wrong type" % name)
    if enum is not None and v not in enum:
        err("ERR_INVALID_REQUEST", "Field %s has bad value" % name)
    return v


def parse_dt_field(data, name, required=True):
    raw = data.get(name)
    if raw is None:
        if required:
            err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return None
    if not isinstance(raw, str):
        err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 string" % name)
    try:
        return _parse_iso(raw)
    except Exception:
        err("ERR_INVALID_REQUEST", "Field %s is not valid ISO 8601" % name)


def get_account_or_404(account_id):
    a = store.accounts.get(account_id)
    if a is None:
        err("ERR_NOT_FOUND", "SubscriberAccount not found")
    return a


def get_profile_or_404(profile_id):
    p = store.profiles.get(profile_id)
    if p is None:
        err("ERR_NOT_FOUND", "ServiceProfile not found")
    return p


def get_subscription_or_404(sub_id):
    s = store.subscriptions.get(sub_id)
    if s is None:
        err("ERR_NOT_FOUND", "Subscription not found")
    return s


def get_billing_or_404(bid):
    b = store.billing_accounts.get(bid)
    if b is None:
        err("ERR_NOT_FOUND", "BillingAccount not found")
    return b


def get_invoice_or_404(iid):
    i = store.invoices.get(iid)
    if i is None:
        err("ERR_NOT_FOUND", "Invoice not found")
    return i


def get_migration_or_404(mid):
    m = store.migrations.get(mid)
    if m is None:
        err("ERR_NOT_FOUND", "Migration not found")
    return m


def reject_if_account_closed(account):
    if account["account_status"] == "CLOSED":
        err("ERR_ACCOUNT_CLOSED", "Account is closed")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.route("/streaming/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("PlatformAdmin")
    data = body()
    target = parse_dt_field(data, "to_iso8601")
    if target < store.now():
        err("ERR_CLOCK_REGRESSION", "Clock may not move backwards")
    store.clock = target
    svc.fire_scheduled_cancellations()
    return ok_object({"current_utc": _fmt_iso(store.now())})


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

PLAN_KINDS = ("STANDALONE", "BUNDLE")
AD_TIERS = ("AD_SUPPORTED", "AD_FREE")
SERVICES = ("DPLUS", "HULU")


@app.route("/streaming/plans", methods=["POST"])
def create_plan():
    require_roles("PlatformAdmin")
    data = body()
    plan_code = req_field(data, "plan_code", str)
    plan_kind = req_field(data, "plan_kind", str, enum=PLAN_KINDS)
    service_scope = req_field(data, "service_scope", list)
    ad_tier = req_field(data, "ad_tier", str, enum=AD_TIERS)
    price = req_field(data, "monthly_price_cents", int)
    weights = data.get("component_weights")
    if weights is not None and not isinstance(weights, dict):
        err("ERR_INVALID_REQUEST", "component_weights must be an object")
    allow_app = opt_field(data, "allow_app_store_billing", bool, default=False)
    allow_dist = opt_field(data, "allow_distributor_billing", bool, default=False)
    is_legacy = opt_field(data, "is_legacy", bool, default=False)
    for s in service_scope:
        if s not in SERVICES:
            err("ERR_INVALID_REQUEST", "service_scope contains unknown service")
    if plan_kind == "BUNDLE":
        if sorted(service_scope) != ["DPLUS", "HULU"]:
            err("ERR_INVALID_PLAN_SHAPE", "BUNDLE plan must cover both DPLUS and HULU")
        if not isinstance(weights, dict) or "DPLUS" not in weights or "HULU" not in weights:
            err("ERR_INVALID_PLAN_SHAPE", "BUNDLE plan requires component_weights for both services")
        for k in ("DPLUS", "HULU"):
            w = weights[k]
            if not isinstance(w, (int, float)) or isinstance(w, bool) or not (0 < w < 1):
                err("ERR_INVALID_PLAN_SHAPE", "component weights must each be in (0, 1)")
        if abs(float(weights["DPLUS"]) + float(weights["HULU"]) - 1.0) > 1e-9:
            err("ERR_INVALID_PLAN_SHAPE", "component weights must sum to 1.0")
        if price <= 0:
            err("ERR_INVALID_PLAN_SHAPE", "BUNDLE price must be positive")
    else:
        if len(service_scope) != 1:
            err("ERR_INVALID_PLAN_SHAPE", "STANDALONE plan must cover exactly one service")
        if weights is not None:
            err("ERR_INVALID_PLAN_SHAPE", "STANDALONE plan component_weights must be null")
    if price < svc.MIN_PRICE_CENTS:
        err("ERR_INVALID_PRICING", "monthly_price_cents must be >= 100")
    plan = {
        "id": svc.new_id(),
        "plan_code": plan_code,
        "plan_kind": plan_kind,
        "service_scope": service_scope,
        "ad_tier": ad_tier,
        "monthly_price_cents": price,
        "component_weights": weights,
        "allow_app_store_billing": allow_app,
        "allow_distributor_billing": allow_dist,
        "is_legacy": is_legacy,
        "created_at": store.now_iso(),
    }
    store.plans[plan_code] = plan
    return ok_object(svc.plan_out(plan), status=201)


@app.route("/streaming/plans", methods=["GET"])
def list_plans():
    require_roles("PlatformAdmin", "Support", "DistributorOps", "Subscriber")
    kind = request.args.get("plan_kind")
    legacy = request.args.get("is_legacy")
    items = []
    for p in store.plans.values():
        if kind is not None and p["plan_kind"] != kind:
            continue
        if legacy is not None:
            want = legacy.lower() in ("true", "1", "yes")
            if p.get("is_legacy", False) != want:
                continue
        items.append(svc.plan_out(p))
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/plans/<plan_code>", methods=["GET"])
def get_plan(plan_code):
    require_roles("PlatformAdmin", "Support", "DistributorOps", "Subscriber")
    p = store.plans.get(plan_code)
    if p is None:
        err("ERR_NOT_FOUND", "Plan not found")
    return ok_object(svc.plan_out(p))


# ---------------------------------------------------------------------------
# Subscriber accounts
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.route("/streaming/subscriber-accounts", methods=["POST"])
def create_account():
    require_roles("Anonymous")
    data = body()
    email = req_field(data, "email", str)
    full_name = req_field(data, "full_name", str)
    if not EMAIL_RE.match(email):
        err("ERR_INVALID_REQUEST", "email is malformed")
    for a in store.accounts.values():
        if a["email"] == email:
            err("ERR_DUPLICATE_EMAIL", "Email already registered")
    account = {
        "id": svc.new_id(),
        "email": email,
        "full_name": full_name,
        "account_status": "ACTIVE",
        "grandfathered_price_cents": None,
        "grandfathered_plan_code": None,
        "account_credit_cents": 0,
    }
    svc._stamp(account)
    store.accounts[account["id"]] = account
    return ok_object(svc.account_out(account), status=201)


@app.route("/streaming/subscriber-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    return ok_object(svc.account_out(account))


@app.route("/streaming/subscriber-accounts", methods=["GET"])
def list_accounts():
    require_roles("Support", "PlatformAdmin")
    status = request.args.get("account_status")
    items = [svc.account_out(a) for a in store.accounts.values()
             if status is None or a["account_status"] == status]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


def _account_subscriptions(account_id):
    return [s for s in store.subscriptions.values() if s["subscriber_account_id"] == account_id]


def _has_non_terminal_subs(account_id):
    return any(
        s["lifecycle_status"] in ("PENDING_ENTITLEMENT", "ACTIVE", "PAST_DUE", "CANCEL_SCHEDULED")
        for s in _account_subscriptions(account_id)
    )


@app.route("/streaming/subscriber-accounts/<account_id>/suspend", methods=["POST"])
def suspend_account(account_id):
    require_roles("Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    if account["account_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Only ACTIVE accounts can be suspended")
    account["account_status"] = "SUSPENDED"
    svc.touch(account)
    profiles_touched = set()
    for s in _account_subscriptions(account_id):
        if s["lifecycle_status"] in ("ACTIVE", "PAST_DUE"):
            for e in store.entitlements.values():
                if e["subscription_id"] == s["id"] and e["entitlement_status"] == "ACTIVE":
                    svc.ent_set_status(e, "SUSPENDED")
                    profiles_touched.add(e["service_profile_id"])
    for pid in profiles_touched:
        svc.profile_bubble(store.profiles[pid])
    svc.reevaluate_mismatch(account_id)
    return ok_object(svc.account_out(account))


@app.route("/streaming/subscriber-accounts/<account_id>/reactivate", methods=["POST"])
def reactivate_account(account_id):
    require_roles("Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    if account["account_status"] != "SUSPENDED":
        err("ERR_INVALID_STATE", "Only SUSPENDED accounts can be reactivated")
    if any(s["lifecycle_status"] == "PAST_DUE" for s in _account_subscriptions(account_id)):
        err("ERR_INVALID_STATE", "Account has PAST_DUE subscriptions; recover payment first")
    account["account_status"] = "ACTIVE"
    svc.touch(account)
    profiles_touched = set()
    for s in _account_subscriptions(account_id):
        if s["lifecycle_status"] == "ACTIVE":
            for e in store.entitlements.values():
                if e["subscription_id"] == s["id"] and e["entitlement_status"] == "SUSPENDED":
                    profile = store.profiles[e["service_profile_id"]]
                    if profile["profile_status"] != "UNLINKED":
                        svc.ent_set_status(e, "ACTIVE")
                        profiles_touched.add(e["service_profile_id"])
    for pid in profiles_touched:
        svc.profile_bubble(store.profiles[pid])
    svc.reevaluate_mismatch(account_id)
    return ok_object(svc.account_out(account))


@app.route("/streaming/subscriber-accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    if account["account_status"] == "CLOSED":
        err("ERR_INVALID_STATE", "Account is already closed")
    if _has_non_terminal_subs(account_id):
        err("ERR_ACTIVE_SUBSCRIPTIONS_REMAIN", "All subscriptions must be terminal before close")
    account["account_status"] = "CLOSED"
    svc.touch(account)
    for p in store.profiles.values():
        if p["subscriber_account_id"] == account_id and p["profile_status"] in ("LINKED", "SUSPENDED"):
            p["profile_status"] = "UNLINKED"
            svc.touch(p)
    for r in store.redemptions.values():
        if r["subscriber_account_id"] == account_id and r["redemption_status"] == "ACTIVE":
            r["redemption_status"] = "VOIDED"
            svc.touch(r)
            sub = store.subscriptions.get(r["subscription_id"])
            if sub is not None:
                svc.recompute_price(sub)
    return ok_object(svc.account_out(account))


# ---------------------------------------------------------------------------
# Service profiles
# ---------------------------------------------------------------------------

MATURITIES = ("TV_Y", "TV_G", "TV_PG", "TV_14", "TV_MA")


@app.route("/streaming/subscriber-accounts/<account_id>/service-profiles", methods=["POST"])
def create_profile(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    if account["account_status"] != "ACTIVE":
        if account["account_status"] == "CLOSED":
            err("ERR_ACCOUNT_CLOSED", "Account is closed")
        err("ERR_ACCOUNT_NOT_ACTIVE", "Account must be ACTIVE to create profiles")
    data = body()
    service = req_field(data, "service", str, enum=SERVICES)
    kids_mode = opt_field(data, "kids_mode", bool, default=False)
    cap = opt_field(data, "maturity_rating_cap", str, default="TV_MA", enum=MATURITIES)
    for p in store.profiles.values():
        if (p["subscriber_account_id"] == account_id and p["service"] == service
                and p["profile_status"] != "UNLINKED"):
            err("ERR_DUPLICATE_PROFILE", "A non-UNLINKED profile already exists for this service")
    if kids_mode:
        cap = "TV_PG"
    profile = {
        "id": svc.new_id(),
        "subscriber_account_id": account_id,
        "service": service,
        "profile_status": "LINKED",
        "maturity_rating_cap": cap,
        "kids_mode": kids_mode,
        "watchlist_count": 0,
    }
    svc._stamp(profile)
    store.profiles[profile["id"]] = profile
    svc.reevaluate_mismatch(account_id)
    return ok_object(svc.profile_out(profile), status=201)


@app.route("/streaming/subscriber-accounts/<account_id>/service-profiles", methods=["GET"])
def list_profiles(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    service = request.args.get("service")
    status = request.args.get("profile_status")
    items = []
    for p in store.profiles.values():
        if p["subscriber_account_id"] != account_id:
            continue
        if service is not None and p["service"] != service:
            continue
        if status is not None and p["profile_status"] != status:
            continue
        items.append(svc.profile_out(p))
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/service-profiles/<profile_id>", methods=["GET"])
def get_profile(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    return ok_object(svc.profile_out(p))


@app.route("/streaming/service-profiles/<profile_id>/unlink", methods=["POST"])
def unlink_profile(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[p["subscriber_account_id"]])
    if p["profile_status"] == "UNLINKED":
        err("ERR_INVALID_STATE", "Profile is already UNLINKED")
    for e in store.entitlements.values():
        if e["service_profile_id"] == profile_id and e["entitlement_status"] in ("PROVISIONING", "ACTIVE"):
            err("ERR_PROFILE_HAS_ACTIVE_ENTITLEMENTS", "Profile has PROVISIONING or ACTIVE entitlements")
    for e in store.entitlements.values():
        if e["service_profile_id"] == profile_id and e["entitlement_status"] == "SUSPENDED":
            svc.ent_set_status(e, "REVOKED")
    p["profile_status"] = "UNLINKED"
    svc.touch(p)
    svc.reevaluate_mismatch(p["subscriber_account_id"])
    return ok_object(svc.profile_out(p))


@app.route("/streaming/service-profiles/<profile_id>", methods=["PATCH"])
def update_profile(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[p["subscriber_account_id"]])
    data = body()
    kids_mode = data.get("kids_mode", p["kids_mode"])
    if not isinstance(kids_mode, bool):
        err("ERR_INVALID_REQUEST", "kids_mode must be boolean")
    cap = data.get("maturity_rating_cap", p["maturity_rating_cap"])
    if cap is not None and cap not in MATURITIES:
        err("ERR_INVALID_REQUEST", "maturity_rating_cap has bad value")
    p["kids_mode"] = kids_mode
    p["maturity_rating_cap"] = "TV_PG" if kids_mode else (cap or p["maturity_rating_cap"])
    svc.touch(p)
    return ok_object(svc.profile_out(p))


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

@app.route("/streaming/service-profiles/<profile_id>/watchlist-items", methods=["POST"])
def add_watchlist_item(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[p["subscriber_account_id"]])
    data = body()
    title_id = req_field(data, "title_id", str)
    title_maturity = req_field(data, "title_maturity", str, enum=MATURITIES)
    effective_cap = "TV_PG" if p["kids_mode"] else p["maturity_rating_cap"]
    if svc.MATURITY_RANK[title_maturity] > svc.MATURITY_RANK[effective_cap]:
        err("ERR_MATURITY_RATING_EXCEEDED", "Title exceeds the profile's maturity cap")
    for w in store.watchlist_items.values():
        if w["service_profile_id"] == profile_id and w["title_id"] == title_id:
            err("ERR_DUPLICATE_WATCHLIST_ITEM", "title_id already on this watchlist")
    item = {
        "id": svc.new_id(),
        "service_profile_id": profile_id,
        "title_id": title_id,
        "title_maturity": title_maturity,
        "created_at": store.now_iso(),
    }
    store.watchlist_items[item["id"]] = item
    p["watchlist_count"] = p.get("watchlist_count", 0) + 1
    svc.touch(p)
    return ok_object(svc.watchlist_item_out(item), status=201)


@app.route("/streaming/service-profiles/<profile_id>/watchlist-items", methods=["GET"])
def list_watchlist(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    maturity = request.args.get("title_maturity")
    items = [svc.watchlist_item_out(w) for w in store.watchlist_items.values()
             if w["service_profile_id"] == profile_id and (maturity is None or w["title_maturity"] == maturity)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/service-profiles/<profile_id>/watchlist-items/<item_id>", methods=["DELETE"])
def delete_watchlist_item(profile_id, item_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[p["subscriber_account_id"]])
    item = store.watchlist_items.get(item_id)
    if item is None or item["service_profile_id"] != profile_id:
        err("ERR_NOT_FOUND", "WatchlistItem not found")
    del store.watchlist_items[item_id]
    p["watchlist_count"] = max(0, p.get("watchlist_count", 0) - 1)
    svc.touch(p)
    return ok_no_content()


# ---------------------------------------------------------------------------
# Billing accounts
# ---------------------------------------------------------------------------

BILLER_TYPES = ("PLATFORM", "APP_STORE", "DISTRIBUTOR")


@app.route("/streaming/subscriber-accounts/<account_id>/billing-accounts", methods=["POST"])
def create_billing_account(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    reject_if_account_closed(account)
    data = body()
    biller_type = req_field(data, "biller_type", str, enum=BILLER_TYPES)
    biller_reference = req_field(data, "biller_reference", str)
    for b in store.billing_accounts.values():
        if b["subscriber_account_id"] == account_id:
            err("ERR_DUPLICATE_BILLING_ACCOUNT", "Subscriber already has a BillingAccount")
    b = {
        "id": svc.new_id(),
        "subscriber_account_id": account_id,
        "biller_type": biller_type,
        "biller_reference": biller_reference,
        "billing_status": "CURRENT",
        "period_start": None,
        "period_end": None,
        "consecutive_failure_count": 0,
    }
    svc._stamp(b)
    store.billing_accounts[b["id"]] = b
    return ok_object(svc.billing_account_out(b), status=201)


@app.route("/streaming/subscriber-accounts/<account_id>/billing-accounts", methods=["GET"])
def list_billing_accounts(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    status = request.args.get("billing_status")
    items = [svc.billing_account_out(b) for b in store.billing_accounts.values()
             if b["subscriber_account_id"] == account_id and (status is None or b["billing_status"] == status)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/billing-accounts/<bid>", methods=["GET"])
def get_billing_account(bid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    b = get_billing_or_404(bid)
    check_owner(b["subscriber_account_id"], role, uid)
    return ok_object(svc.billing_account_out(b))


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------

def _check_biller_plan_allowed(biller_type, plan):
    if biller_type == "APP_STORE" and not plan.get("allow_app_store_billing", False):
        err("ERR_BILLER_PLAN_NOT_ALLOWED", "Plan not sellable through APP_STORE")
    if biller_type == "DISTRIBUTOR" and not plan.get("allow_distributor_billing", False):
        err("ERR_BILLER_PLAN_NOT_ALLOWED", "Plan not sellable through DISTRIBUTOR")


def _check_legacy_plan(plan, account):
    if plan.get("is_legacy", False) and account.get("grandfathered_plan_code") != plan["plan_code"]:
        err("ERR_PLAN_LEGACY_ONLY", "Plan is legacy-only")


@app.route("/streaming/subscriptions", methods=["POST"])
def create_subscription():
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    data = body()
    account_id = req_field(data, "subscriber_account_id", str)
    billing_id = req_field(data, "billing_account_id", str)
    plan_code = req_field(data, "plan_code", str)
    account = store.accounts.get(account_id)
    if account is None:
        err("ERR_REFERENCE_NOT_FOUND", "subscriber_account_id does not exist")
    check_owner(account["id"], role, uid)
    billing = store.billing_accounts.get(billing_id)
    if billing is None:
        err("ERR_REFERENCE_NOT_FOUND", "billing_account_id does not exist")
    plan = store.plans.get(plan_code)
    if plan is None:
        err("ERR_REFERENCE_NOT_FOUND", "plan_code does not exist")
    if account["account_status"] == "CLOSED":
        err("ERR_ACCOUNT_CLOSED", "Account is closed")
    if account["account_status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", "Account must be ACTIVE")
    if billing["subscriber_account_id"] != account_id:
        err("ERR_INVALID_REQUEST", "billing_account_id does not belong to subscriber_account_id")
    # Resolve target profiles per service scope
    profile_by_service = {}
    for service in plan["service_scope"]:
        field = "dplus_service_profile_id" if service == "DPLUS" else "hulu_service_profile_id"
        pid = data.get(field)
        if pid is None:
            err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        if not isinstance(pid, str):
            err("ERR_INVALID_REQUEST", "%s must be a string" % field)
        profile = store.profiles.get(pid)
        if profile is None:
            err("ERR_REFERENCE_NOT_FOUND", "%s does not exist" % field)
        if profile["subscriber_account_id"] != account_id:
            err("ERR_INVALID_REQUEST", "%s does not belong to subscriber" % field)
        if profile["service"] != service:
            err("ERR_INVALID_REQUEST", "%s service mismatch" % field)
        profile_by_service[service] = profile
    # Duplicate active subscription per plan_code
    for s in store.subscriptions.values():
        if (s["subscriber_account_id"] == account_id and s["plan_code"] == plan_code
                and s["lifecycle_status"] in ("PENDING_ENTITLEMENT", "ACTIVE", "PAST_DUE", "CANCEL_SCHEDULED")):
            err("ERR_DUPLICATE_ACTIVE_SUBSCRIPTION", "Account already holds a non-terminal subscription for this plan")
    _check_biller_plan_allowed(billing["biller_type"], plan)
    _check_legacy_plan(plan, account)
    now = store.now()
    sub = {
        "id": svc.new_id(),
        "subscriber_account_id": account_id,
        "billing_account_id": billing_id,
        "plan_code": plan_code,
        "lifecycle_status": "PENDING_ENTITLEMENT",
        "billing_dimension": "PAID_UP",
        "price_cents": plan["monthly_price_cents"],
        "retention_discount_cents": 0,
        "migration_id": None,
        "pending_plan_code": None,
        "cancel_effective_at": None,
    }
    svc._stamp(sub)
    store.subscriptions[sub["id"]] = sub
    svc.provision_entitlements(sub, profile_by_service)
    # Entitlements that could not provision because their profile was not
    # LINKED stay in PROVISIONING; retry them against current profile state
    # (the bubble rule of §2.9 lets a suspended profile rise back to LINKED
    # once any entitlement on it returns to ACTIVE).
    for service in plan["service_scope"]:
        profile = profile_by_service[service]
        if profile["profile_status"] == "LINKED":
            continue
        for e in store.entitlements.values():
            if (e["subscription_id"] == sub["id"] and e["service"] == service
                    and e["entitlement_status"] == "PROVISIONING"):
                if profile["profile_status"] == "SUSPENDED":
                    svc.ent_set_status(e, "ACTIVE")
                    svc.profile_bubble(profile)
    svc.maybe_activate_subscription(sub)
    # INITIAL invoice issued and immediately PAID
    if billing["period_start"] is None:
        billing["period_start"] = now
        from datetime import timedelta as _td
        billing["period_end"] = now + _td(days=svc.period_days(billing))
        svc.touch(billing)
    inv = svc.issue_invoice(billing, sub, "INITIAL", sub["price_cents"], 0,
                            billing["period_start"], billing["period_end"])
    svc.mark_invoice_paid(inv, advance_period=False)
    return ok_object(svc.subscription_out(sub), status=201)


@app.route("/streaming/subscriptions/<sub_id>", methods=["GET"])
def get_subscription(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    return ok_object(svc.subscription_out(s))


@app.route("/streaming/subscriptions", methods=["GET"])
def list_subscriptions():
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    if role == "Subscriber":
        check_owner(request.args.get("subscriber_account_id", uid), role, uid)
    items = []
    for s in store.subscriptions.values():
        for key in ("subscriber_account_id", "billing_account_id", "plan_code", "lifecycle_status", "migration_id"):
            v = request.args.get(key)
            if v is not None and str(s.get(key)) != v:
                break
        else:
            if role == "Subscriber" and s["subscriber_account_id"] != uid:
                continue
            items.append(svc.subscription_out(s))
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/subscriptions/<sub_id>/plan-change", methods=["POST"])
def plan_change(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[s["subscriber_account_id"]])
    data = body()
    new_plan_code = req_field(data, "new_plan_code", str)
    expected = req_field(data, "expected_subscription_version", int)
    new_plan = store.plans.get(new_plan_code)
    if new_plan is None:
        err("ERR_REFERENCE_NOT_FOUND", "new_plan_code does not exist")
    if s["lifecycle_status"] not in ("ACTIVE", "PAST_DUE"):
        err("ERR_INVALID_STATE", "Plan change requires ACTIVE or PAST_DUE lifecycle")
    account = store.accounts[s["subscriber_account_id"]]
    billing = store.billing_accounts[s["billing_account_id"]]
    _check_biller_plan_allowed(billing["biller_type"], new_plan)
    if billing["biller_type"] == "APP_STORE":
        old_plan = store.plans[s["plan_code"]]
        if old_plan["plan_kind"] != new_plan["plan_kind"]:
            err("ERR_BILLER_UPGRADE_PATH_BLOCKED", "APP_STORE biller permits same-kind changes only")
    _check_legacy_plan(new_plan, account)
    if expected != s["version"]:
        err("ERR_STALE_VERSION", "Subscription version mismatch")
    old_plan = store.plans[s["plan_code"]]
    s["plan_code"] = new_plan_code
    svc.touch(s)
    svc.recompute_price(s)
    # Reconcile entitlements to new scope
    old_scope = set(old_plan["service_scope"])
    new_scope = set(new_plan["service_scope"])
    profiles_touched = set()
    for service in old_scope - new_scope:
        for e in store.entitlements.values():
            if (e["subscription_id"] == s["id"] and e["service"] == service
                    and e["entitlement_status"] in ("PROVISIONING", "ACTIVE", "SUSPENDED")):
                profiles_touched.add(e["service_profile_id"])
                svc.ent_set_status(e, "REVOKED")
    for service in new_scope - old_scope:
        profile = None
        for p in store.profiles.values():
            if (p["subscriber_account_id"] == s["subscriber_account_id"]
                    and p["service"] == service and p["profile_status"] == "LINKED"):
                profile = p
                break
        if profile is not None:
            ent = {
                "id": svc.new_id(),
                "subscription_id": s["id"],
                "service_profile_id": profile["id"],
                "service": service,
                "entitlement_status": "ACTIVE",
                "mismatch_flag": False,
            }
            svc._stamp(ent)
            store.entitlements[ent["id"]] = ent
            profiles_touched.add(profile["id"])
    for pid in profiles_touched:
        svc.profile_bubble(store.profiles[pid])
    svc.reevaluate_mismatch(s["subscriber_account_id"])
    return ok_object(svc.subscription_out(s))


@app.route("/streaming/subscriptions/<sub_id>/cancel", methods=["POST"])
def cancel_subscription(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[s["subscriber_account_id"]])
    data = body()
    immediate = data.get("immediate_effect", False)
    if not isinstance(immediate, bool):
        err("ERR_INVALID_REQUEST", "immediate_effect must be boolean")
    if s["lifecycle_status"] not in ("ACTIVE", "PAST_DUE"):
        err("ERR_INVALID_STATE", "Cancel requires ACTIVE or PAST_DUE lifecycle")
    billing = store.billing_accounts[s["billing_account_id"]]
    if billing["biller_type"] == "APP_STORE" and immediate:
        err("ERR_IMMEDIATE_CANCEL_NOT_ALLOWED", "APP_STORE-billed subscriptions may not cancel immediately")
    if s["lifecycle_status"] == "PAST_DUE" and immediate:
        err("ERR_INVALID_REQUEST", "A past-due subscription cancels only at period end")
    now = store.now()
    if immediate:
        # Immediate cancellation takes effect at the current logical instant and
        # finalizes right away.
        s["cancel_effective_at"] = now
        s["lifecycle_status"] = "CANCEL_SCHEDULED"
        svc.touch(s)
        s["cancel_effective_at"] = None
        svc.subscription_cascade_to_cancelled(s)
    else:
        # Period-end cancellation: scheduled now, finalized when the logical
        # clock is advanced to cancel_effective_at (see set_clock).
        s["cancel_effective_at"] = billing["period_end"]
        s["lifecycle_status"] = "CANCEL_SCHEDULED"
        svc.touch(s)
    return ok_object(svc.subscription_out(s))


@app.route("/streaming/subscriptions/<sub_id>/rescind-cancellation", methods=["POST"])
def rescind_cancellation(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[s["subscriber_account_id"]])
    if s["lifecycle_status"] != "CANCEL_SCHEDULED":
        err("ERR_INVALID_STATE", "Rescind requires CANCEL_SCHEDULED lifecycle")
    if s["billing_dimension"] == "UNPAID":
        err("ERR_INVALID_STATE", "Cannot rescind an UNPAID subscription")
    now = store.now()
    if s.get("cancel_effective_at") is not None and now >= s["cancel_effective_at"]:
        svc.fire_scheduled_cancellations()
        err("ERR_INVALID_STATE", "Cancellation already finalized")
    s["cancel_effective_at"] = None
    s["lifecycle_status"] = "ACTIVE"
    svc.touch(s)
    return ok_object(svc.subscription_out(s))


# ---------------------------------------------------------------------------
# Entitlements
# ---------------------------------------------------------------------------

@app.route("/streaming/subscriptions/<sub_id>/entitlements", methods=["GET"])
def list_subscription_entitlements(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    service = request.args.get("service")
    status = request.args.get("entitlement_status")
    items = [svc.entitlement_out(e) for e in store.entitlements.values()
             if e["subscription_id"] == sub_id
             and (service is None or e["service"] == service)
             and (status is None or e["entitlement_status"] == status)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/service-profiles/<profile_id>/entitlements", methods=["GET"])
def list_profile_entitlements(profile_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    p = get_profile_or_404(profile_id)
    check_owner(p["subscriber_account_id"], role, uid)
    status = request.args.get("entitlement_status")
    items = [svc.entitlement_out(e) for e in store.entitlements.values()
             if e["service_profile_id"] == profile_id
             and (status is None or e["entitlement_status"] == status)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/entitlements/<ent_id>", methods=["GET"])
def get_entitlement(ent_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    e = store.entitlements.get(ent_id)
    if e is None:
        err("ERR_NOT_FOUND", "Entitlement not found")
    s = store.subscriptions[e["subscription_id"]]
    check_owner(s["subscriber_account_id"], role, uid)
    return ok_object(svc.entitlement_out(e))


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------

def _proration_base(subscription):
    """floor(monthly * days_remaining / days_total) against the logical clock."""
    billing = store.billing_accounts[subscription["billing_account_id"]]
    days_total = (billing["period_end"] - billing["period_start"]).days
    monthly = subscription["price_cents"] + subscription.get("retention_discount_cents", 0)
    # effective monthly figure: base price (grandfathered if locked, else list)
    monthly = svc.base_price(subscription)
    now = store.now()
    days_elapsed = (now - billing["period_start"]).days
    days_remaining = days_total - days_elapsed
    if days_remaining < 0:
        days_remaining = 0
    return (monthly * days_remaining) // days_total


@app.route("/streaming/migrations", methods=["POST"])
def create_migration():
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    data = body()
    from_sub_id = req_field(data, "from_subscription_id", str)
    target_plan_code = req_field(data, "target_plan_code", str)
    from_sub = store.subscriptions.get(from_sub_id)
    if from_sub is None:
        err("ERR_REFERENCE_NOT_FOUND", "from_subscription_id does not exist")
    check_owner(from_sub["subscriber_account_id"], role, uid)
    target_plan = store.plans.get(target_plan_code)
    if target_plan is None:
        err("ERR_REFERENCE_NOT_FOUND", "target_plan_code does not exist")
    account = store.accounts[from_sub["subscriber_account_id"]]
    if account["account_status"] == "CLOSED":
        err("ERR_ACCOUNT_CLOSED", "Account is closed")
    if account["account_status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", "Account must be ACTIVE")
    from_plan = store.plans[from_sub["plan_code"]]
    if from_plan["plan_kind"] != "STANDALONE" or target_plan["plan_kind"] != "BUNDLE":
        err("ERR_MIGRATION_SHAPE", "Migration must be STANDALONE -> BUNDLE")
    if from_sub["lifecycle_status"] != "ACTIVE":
        err("ERR_MIGRATION_SOURCE_NOT_ACTIVE", "From-subscription must be ACTIVE at quote time")
    billing = store.billing_accounts[from_sub["billing_account_id"]]
    _check_biller_plan_allowed(billing["biller_type"], target_plan)
    m = {
        "id": svc.new_id(),
        "subscriber_account_id": from_sub["subscriber_account_id"],
        "from_subscription_id": from_sub_id,
        "to_subscription_id": None,
        "target_plan_code": target_plan_code,
        "migration_status": "QUOTED",
        "proration_credit_cents": _proration_base(from_sub),
        "proration_method_used": "CHRONOLOGICAL_REMAINING",
    }
    svc._stamp(m)
    store.migrations[m["id"]] = m
    return ok_object(svc.migration_out(m), status=201)


@app.route("/streaming/migrations/<mid>", methods=["GET"])
def get_migration(mid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    m = get_migration_or_404(mid)
    check_owner(m["subscriber_account_id"], role, uid)
    return ok_object(svc.migration_out(m))


@app.route("/streaming/migrations", methods=["GET"])
def list_migrations():
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    items = []
    for m in store.migrations.values():
        if role == "Subscriber" and m["subscriber_account_id"] != uid:
            continue
        ok = True
        for key in ("subscriber_account_id", "from_subscription_id", "to_subscription_id", "migration_status"):
            v = request.args.get(key)
            if v is not None and str(m.get(key)) != v:
                ok = False
                break
        if ok:
            items.append(svc.migration_out(m))
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/migrations/<mid>/confirm", methods=["POST"])
def confirm_migration(mid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    m = get_migration_or_404(mid)
    check_owner(m["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[m["subscriber_account_id"]])
    data = body()
    expected = req_field(data, "expected_migration_version", int)
    if m["migration_status"] != "QUOTED":
        err("ERR_INVALID_STATE", "Migration is not QUOTED")
    from_sub = store.subscriptions[m["from_subscription_id"]]
    if from_sub["lifecycle_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "From-subscription is no longer ACTIVE")
    billing = store.billing_accounts[from_sub["billing_account_id"]]
    now = store.now()
    if not (now < billing["period_end"]):
        err("ERR_MIGRATION_WINDOW_CLOSED", "Confirm must occur strictly before period_end")
    target_plan = store.plans[m["target_plan_code"]]
    _check_biller_plan_allowed(billing["biller_type"], target_plan)
    if expected != m["version"]:
        err("ERR_STALE_VERSION", "Migration version mismatch")
    # FORWARD_LOOKING_PERIOD recompute
    base = _proration_base(from_sub)
    consumed = 0
    for inv in store.invoices.values():
        if (inv["subscription_id"] == from_sub["id"]
                and inv["invoice_status"] in ("ISSUED", "PAID")
                and inv.get("period_start") is not None
                and inv["period_start"] >= _parse_iso(m["created_at"])):
            consumed += inv["credit_applied_cents"]
    credit = max(0, base - consumed)
    m["proration_credit_cents"] = credit
    m["proration_method_used"] = "FORWARD_LOOKING_PERIOD"
    m["migration_status"] = "CONFIRMED"
    account = store.accounts[m["subscriber_account_id"]]
    # from-subscription MIGRATED_OUT; entitlements revoked
    profiles_touched = set()
    for e in store.entitlements.values():
        if e["subscription_id"] == from_sub["id"] and e["entitlement_status"] in ("ACTIVE", "SUSPENDED", "PROVISIONING"):
            profiles_touched.add(e["service_profile_id"])
            svc.ent_set_status(e, "REVOKED")
    for r in store.redemptions.values():
        if r["subscription_id"] == from_sub["id"] and r["redemption_status"] == "ACTIVE":
            r["redemption_status"] = "VOIDED"
            svc.touch(r)
    from_sub["lifecycle_status"] = "MIGRATED_OUT"
    from_sub["migration_id"] = m["id"]
    svc.touch(from_sub)
    # New bundle subscription on the same billing account
    profile_by_service = {}
    for service in target_plan["service_scope"]:
        profile = None
        for p in store.profiles.values():
            if (p["subscriber_account_id"] == account["id"] and p["service"] == service
                    and p["profile_status"] == "LINKED"):
                profile = p
                break
        if profile is None:
            err("ERR_REFERENCE_NOT_FOUND", "No LINKED %s profile on the account" % service)
        profile_by_service[service] = profile
    new_sub = {
        "id": svc.new_id(),
        "subscriber_account_id": account["id"],
        "billing_account_id": billing["id"],
        "plan_code": target_plan["plan_code"],
        "lifecycle_status": "PENDING_ENTITLEMENT",
        "billing_dimension": "PAID_UP",
        "price_cents": target_plan["monthly_price_cents"],
        "retention_discount_cents": 0,
        "migration_id": m["id"],
        "pending_plan_code": None,
        "cancel_effective_at": None,
    }
    svc._stamp(new_sub)
    store.subscriptions[new_sub["id"]] = new_sub
    svc.provision_entitlements(new_sub, profile_by_service)
    m["to_subscription_id"] = new_sub["id"]
    svc.touch(m)
    for pid in profiles_touched:
        svc.profile_bubble(store.profiles[pid])
    # Post proration credit to the account
    account["account_credit_cents"] = account.get("account_credit_cents", 0) + credit
    svc.touch(account)
    # Audit-anchor invoice; any still-ISSUED invoice of the source
    # subscription is superseded by the adjustment and is VOIDED (PRD §3.12).
    for inv in store.invoices.values():
        if (inv["subscription_id"] == from_sub["id"]
                and inv["invoice_status"] == "ISSUED"):
            inv["invoice_status"] = "VOIDED"
            svc.touch(inv)
    svc.issue_invoice(billing, from_sub, "MIGRATION_ADJUSTMENT", 0, 0,
                      billing["period_start"], billing["period_end"])
    svc.reevaluate_mismatch(account["id"])
    return ok_object(svc.migration_out(m))


@app.route("/streaming/migrations/<mid>/void", methods=["POST"])
def void_migration(mid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    m = get_migration_or_404(mid)
    check_owner(m["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[m["subscriber_account_id"]])
    if m["migration_status"] != "QUOTED":
        err("ERR_INVALID_STATE", "Migration is not QUOTED")
    m["migration_status"] = "VOIDED"
    svc.touch(m)
    return ok_object(svc.migration_out(m))


# ---------------------------------------------------------------------------
# Retention offers and redemptions
# ---------------------------------------------------------------------------

PLAN_KIND_LIST = ("STANDALONE", "BUNDLE")


@app.route("/streaming/retention-offers", methods=["POST"])
def create_offer():
    require_roles("PlatformAdmin")
    data = body()
    offer_code = req_field(data, "offer_code", str)
    discount = req_field(data, "discount_cents", int)
    duration = req_field(data, "duration_months", int)
    max_red = req_field(data, "max_redemptions_per_account", int)
    billers = req_field(data, "eligible_biller_types", list)
    kinds = req_field(data, "eligible_plan_kinds", list)
    status = opt_field(data, "offer_status", str, default="OPEN", enum=("OPEN", "RETIRED"))
    for b in billers:
        if b not in BILLER_TYPES:
            err("ERR_INVALID_REQUEST", "eligible_biller_types has bad value")
    for k in kinds:
        if k not in PLAN_KIND_LIST:
            err("ERR_INVALID_REQUEST", "eligible_plan_kinds has bad value")
    if discount < 1 or duration < 1:
        err("ERR_INVALID_PRICING", "discount_cents and duration_months must be >= 1")
    if max_red < 1:
        err("ERR_INVALID_PRICING", "max_redemptions_per_account must be >= 1")
    offer = {
        "id": svc.new_id(),
        "offer_code": offer_code,
        "discount_cents": discount,
        "duration_months": duration,
        "max_redemptions_per_account": max_red,
        "eligible_biller_types": billers,
        "eligible_plan_kinds": kinds,
        "offer_status": status,
        "created_at": store.now_iso(),
    }
    store.offers[offer_code] = offer
    return ok_object(svc.offer_out(offer), status=201)


@app.route("/streaming/retention-offers", methods=["GET"])
def list_offers():
    require_roles("PlatformAdmin", "Support")
    status = request.args.get("offer_status")
    items = [svc.offer_out(o) for o in store.offers.values()
             if status is None or o["offer_status"] == status]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/retention-offers/<offer_code>", methods=["GET"])
def get_offer(offer_code):
    require_roles("PlatformAdmin", "Support")
    o = store.offers.get(offer_code)
    if o is None:
        err("ERR_NOT_FOUND", "RetentionOffer not found")
    return ok_object(svc.offer_out(o))


@app.route("/streaming/subscriptions/<sub_id>/retention-redemptions", methods=["POST"])
def redeem_offer(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    account = store.accounts[s["subscriber_account_id"]]
    reject_if_account_closed(account)
    data = body()
    offer_code = req_field(data, "offer_code", str)
    offer = store.offers.get(offer_code)
    if offer is None:
        err("ERR_REFERENCE_NOT_FOUND", "offer_code does not exist")
    if account["account_status"] != "ACTIVE":
        err("ERR_ACCOUNT_NOT_ACTIVE", "Account must be ACTIVE")
    # Six-clause eligibility conjunction
    if offer["offer_status"] != "OPEN":
        err("ERR_RETENTION_NOT_ELIGIBLE", "Offer is not OPEN")
    if s["lifecycle_status"] != "ACTIVE":
        err("ERR_RETENTION_NOT_ELIGIBLE", "Subscription must be ACTIVE")
    billing = store.billing_accounts[s["billing_account_id"]]
    if billing["biller_type"] not in offer["eligible_biller_types"]:
        err("ERR_RETENTION_NOT_ELIGIBLE", "Biller type not eligible")
    plan = store.plans[s["plan_code"]]
    if plan["plan_kind"] not in offer["eligible_plan_kinds"]:
        err("ERR_RETENTION_NOT_ELIGIBLE", "Plan kind not eligible")
    count = sum(
        1 for r in store.redemptions.values()
        if r["subscriber_account_id"] == s["subscriber_account_id"]
        and r["offer_code"] == offer_code
        and r["redemption_status"] in ("ACTIVE", "EXPIRED")
    )
    if count >= offer["max_redemptions_per_account"]:
        err("ERR_RETENTION_NOT_ELIGIBLE", "Redemption cap reached for this offer")
    for r in store.redemptions.values():
        if r["subscription_id"] == sub_id and r["redemption_status"] == "ACTIVE":
            err("ERR_RETENTION_NOT_ELIGIBLE", "Subscription already has an ACTIVE redemption")
    red = {
        "id": svc.new_id(),
        "subscription_id": sub_id,
        "subscriber_account_id": s["subscriber_account_id"],
        "offer_code": offer_code,
        "redemption_status": "ACTIVE",
        "months_remaining": offer["duration_months"],
    }
    svc._stamp(red)
    store.redemptions[red["id"]] = red
    svc.recompute_price(s)
    svc.touch(s)
    return ok_object(svc.redemption_out(red), status=201)


@app.route("/streaming/subscriptions/<sub_id>/retention-redemptions", methods=["GET"])
def list_subscription_redemptions(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    status = request.args.get("redemption_status")
    items = [svc.redemption_out(r) for r in store.redemptions.values()
             if r["subscription_id"] == sub_id and (status is None or r["redemption_status"] == status)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/subscriber-accounts/<account_id>/retention-redemptions", methods=["GET"])
def list_account_redemptions(account_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin")
    account = get_account_or_404(account_id)
    check_owner(account["id"], role, uid)
    status = request.args.get("redemption_status")
    offer_code = request.args.get("offer_code")
    items = [svc.redemption_out(r) for r in store.redemptions.values()
             if r["subscriber_account_id"] == account_id
             and (status is None or r["redemption_status"] == status)
             and (offer_code is None or r["offer_code"] == offer_code)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


# ---------------------------------------------------------------------------
# Invoices & revenue
# ---------------------------------------------------------------------------

@app.route("/streaming/subscriptions/<sub_id>/invoices", methods=["GET"])
def list_subscription_invoices(sub_id):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    s = get_subscription_or_404(sub_id)
    check_owner(s["subscriber_account_id"], role, uid)
    return _invoice_list([i for i in store.invoices.values() if i["subscription_id"] == sub_id])


@app.route("/streaming/billing-accounts/<bid>/invoices", methods=["GET"])
def list_billing_invoices(bid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    b = get_billing_or_404(bid)
    check_owner(b["subscriber_account_id"], role, uid)
    return _invoice_list([i for i in store.invoices.values() if i["billing_account_id"] == bid])


def _invoice_list(invoices):
    status = request.args.get("invoice_status")
    kind = request.args.get("invoice_kind")
    items = [svc.invoice_out(i) for i in invoices
             if (status is None or i["invoice_status"] == status)
             and (kind is None or i["invoice_kind"] == kind)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    inv = get_invoice_or_404(iid)
    billing = store.billing_accounts[inv["billing_account_id"]]
    check_owner(billing["subscriber_account_id"], role, uid)
    return ok_object(svc.invoice_out(inv))


@app.route("/streaming/invoices/<iid>/revenue-allocations", methods=["GET"])
def list_allocations(iid):
    require_roles("Support", "PlatformAdmin", "DistributorOps")
    get_invoice_or_404(iid)
    service = request.args.get("service")
    items = [svc.allocation_out(a) for a in store.revenue_allocations.values()
             if a["invoice_id"] == iid and (service is None or a["service"] == service)]
    items.sort(key=lambda x: x["created_at"])
    return paginate(items)


@app.route("/streaming/invoices/<iid>/retry-payment", methods=["POST"])
def retry_payment(iid):
    role, uid = require_roles("Subscriber", "Support", "PlatformAdmin", "DistributorOps")
    inv = get_invoice_or_404(iid)
    billing = store.billing_accounts[inv["billing_account_id"]]
    check_owner(billing["subscriber_account_id"], role, uid)
    reject_if_account_closed(store.accounts[billing["subscriber_account_id"]])
    if inv["invoice_status"] != "FAILED":
        err("ERR_INVALID_STATE", "Only FAILED invoices can be retried")
    if billing["billing_status"] == "HARD_FAILED":
        err("ERR_INVALID_STATE", "Billing account is HARD_FAILED")
    from datetime import timedelta as _td
    now = store.now()
    if not (now < billing["period_end"] + _td(days=svc.GRACE_DAYS)):
        err("ERR_GRACE_WINDOW_CLOSED", "Grace window closed")
    sub = store.subscriptions[inv["subscription_id"]]
    svc.mark_invoice_paid(inv, advance_period=False)
    svc.payment_recovery_cascade(billing, sub)
    return ok_object(svc.invoice_out(inv))


@app.route("/streaming/revenue-report", methods=["GET"])
def revenue_report():
    require_roles("Support", "PlatformAdmin", "DistributorOps")
    raw_from = request.args.get("from_iso8601")
    raw_to = request.args.get("to_iso8601")
    service = request.args.get("service")
    if raw_from is None or raw_to is None:
        err("ERR_INVALID_REQUEST", "from_iso8601 and to_iso8601 are required")
    try:
        start = _parse_iso(raw_from)
        end = _parse_iso(raw_to)
    except Exception:
        err("ERR_INVALID_REQUEST", "from_iso8601/to_iso8601 must be ISO 8601")
    total = 0
    per_service = {}
    contributing = set()
    for a in store.revenue_allocations.values():
        inv = store.invoices[a["invoice_id"]]
        if inv["invoice_status"] != "PAID":
            continue
        t = _parse_iso(inv["created_at"])
        if not (start <= t < end):
            continue
        if service is not None and a["service"] != service:
            continue
        total += a["allocated_cents"]
        per_service[a["service"]] = per_service.get(a["service"], 0) + a["allocated_cents"]
        contributing.add(a["invoice_id"])
    return ok_object({
        "total_cents": total,
        "per_service": per_service,
        "invoice_count": len(contributing),
    })


# ---------------------------------------------------------------------------
# Billing run (test-driving)
# ---------------------------------------------------------------------------

@app.route("/streaming/_billing/run_renewal", methods=["POST"])
def run_renewal_endpoint():
    require_roles("PlatformAdmin")
    data = body()
    billing_id = req_field(data, "billing_account_id", str)
    outcome = req_field(data, "outcome", str, enum=("SUCCEEDED", "FAILED"))
    billing = store.billing_accounts.get(billing_id)
    if billing is None:
        err("ERR_REFERENCE_NOT_FOUND", "billing_account_id does not exist")
    now = store.now()
    if billing["period_end"] is None or not (billing["period_end"] <= now):
        err("ERR_RENEWAL_NOT_DUE", "Billing period is not due")
    inv = svc.run_renewal(billing, outcome)
    if inv is None:
        err("ERR_RENEWAL_NOT_DUE", "No due subscriptions on this billing account")
    return ok_object({
        "invoice_id": inv["id"],
        "invoice_status": inv["invoice_status"],
        "billing_status": billing["billing_status"],
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
