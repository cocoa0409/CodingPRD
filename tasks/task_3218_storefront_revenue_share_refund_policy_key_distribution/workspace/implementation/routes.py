"""All /storefront routes for task 3218.

Validation order per request follows PRD §2.7 / scaffold §1.4:
auth (middleware) -> role -> existence -> ownership -> state -> OCC ->
field validity -> business gates (in scaffold priority order).
"""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import core
from core import (
    ApiError, STORE, body, check_dev_owner, check_user_owner, get_now, get_or_404,
    is_int, iso, list_page, new_record, parse_dt, pub, req_str, roles, touch,
)

bp = Blueprint("storefront", __name__, url_prefix="/storefront")


def register(app):
    app.register_blueprint(bp)
    # late import to avoid circularity
    from app import ok, ok_list  # noqa
    globals()["ok"] = ok
    globals()["ok_list"] = ok_list


def page_response(items, meta):
    from app import envelope
    return envelope([pub(r) for r in items], "array", 200, meta)


def paginate(items):
    items = sorted(items, key=lambda r: r["_seq"])
    limit, offset = core.pagination_params()
    total = len(items)
    return items[offset:offset + limit], {
        "limit": limit, "offset": offset,
        "total_count": total, "has_more": offset + min(limit, max(0, total - offset)) < total,
    }


def list_resp(items, serialize=None):
    page, meta = paginate(items)
    from app import envelope
    data = [(serialize or pub)(r) for r in page]
    return envelope(data, "array", 200, meta)


def err(error_id, status, message=None):
    raise ApiError(error_id, status, message or error_id)


def check_occ(title, data):
    """OCC gate (priority 6) on POST adjustments/reviews/regional-prices."""
    v = data.get("expected_title_version")
    if v is None:
        core.err_invalid_request("expected_title_version is required")
    if not is_int(v):
        core.err_invalid_request("expected_title_version must be an integer")
    if v != title["version"]:
        core.err_stale_version()


# ==========================================================================
# Clock
# ==========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
@roles("PlatformOps")
def set_clock():
    data = body()
    raw = data.get("to_iso8601")
    if not isinstance(raw, str) or not raw.strip():
        core.err_invalid_request("to_iso8601 is required")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        core.err_invalid_request("to_iso8601 is not a valid ISO 8601 datetime")
    core.set_now(dt)
    # Sweep: due scheduled releases auto-release (released_at = scheduled instant)
    for title in STORE["titles"].values():
        if title["status"] == "RELEASE_SCHEDULED" and title["scheduled_release_at"]:
            if parse_dt(title["scheduled_release_at"]) <= dt:
                title["status"] = "RELEASED"
                title["released_at"] = title["scheduled_release_at"]
                touch(title)
    # Re-evaluate bomb-window coverage at the new now
    for title in STORE["titles"].values():
        core.refresh_bomb_flag(title)
    from app import ok
    return ok({"now_iso8601": iso(dt)})


# ==========================================================================
# Developer accounts
# ==========================================================================
@bp.route("/developer-accounts", methods=["POST"])
@roles("PlatformOps")
def create_developer():
    data = body()
    company_name = data.get("company_name")
    contact_email = data.get("contact_email")
    if not isinstance(company_name, str) or not company_name.strip():
        core.err_invalid_request("company_name is required")
    if not isinstance(contact_email, str) or not contact_email.strip():
        core.err_invalid_request("contact_email is required")
    for d in STORE["developer_accounts"].values():
        if d["contact_email"] == contact_email:
            err("ERR_DUPLICATE", 409, "contact_email already registered")
    rec = new_record("developer_accounts", {
        "company_name": company_name,
        "contact_email": contact_email,
        "onboarding_fee_paid": False,
        "bank_details_submitted": False,
        "status": "PENDING",
    })
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/developer-accounts/<dev_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer", "TrustSafety")
def get_developer(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/developer-accounts", methods=["GET"])
@roles("PlatformOps", "StoreReviewer", "TrustSafety")
def list_developers():
    items = list(STORE["developer_accounts"].values())
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_resp(items)


@bp.route("/developer-accounts/<dev_id>/payment-info", methods=["POST"])
@roles("Developer")
def developer_payment_info(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    check_dev_owner(dev_id)
    data = body()
    if data.get("pay_fee") is True:
        rec["onboarding_fee_paid"] = True
    if data.get("submit_bank_details") is True:
        rec["bank_details_submitted"] = True
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/developer-accounts/<dev_id>/activate", methods=["POST"])
@roles("PlatformOps")
def developer_activate(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    if rec["status"] != "PENDING" or not (rec["onboarding_fee_paid"] and rec["bank_details_submitted"]):
        core.err_invalid_state("Activation requires PENDING with fee paid and bank details submitted")
    rec["status"] = "ACTIVE"
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/developer-accounts/<dev_id>/suspend", methods=["POST"])
@roles("PlatformOps")
def developer_suspend(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    if rec["status"] != "ACTIVE":
        core.err_invalid_state("Only ACTIVE developer accounts can be suspended")
    rec["status"] = "SUSPENDED"
    touch(rec)
    for title in STORE["titles"].values():
        if title["developer_account_id"] == dev_id and title["status"] in ("RELEASED", "RELEASE_SCHEDULED"):
            title["status"] = "DELISTED"
            touch(title)
    from app import ok
    return ok(pub(rec))


@bp.route("/developer-accounts/<dev_id>/unsuspend", methods=["POST"])
@roles("PlatformOps")
def developer_unsuspend(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    if rec["status"] != "SUSPENDED":
        core.err_invalid_state("Only SUSPENDED developer accounts can be unsuspended")
    rec["status"] = "ACTIVE"
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/developer-accounts/<dev_id>/terminate", methods=["POST"])
@roles("PlatformOps")
def developer_terminate(dev_id):
    rec = get_or_404("developer_accounts", dev_id)
    if rec["status"] not in ("PENDING", "ACTIVE", "SUSPENDED"):
        core.err_invalid_state("Developer account cannot be terminated from its current state")
    rec["status"] = "TERMINATED"
    touch(rec)
    for title in STORE["titles"].values():
        if title["developer_account_id"] == dev_id and title["status"] != "DELISTED":
            title["status"] = "DELISTED"
            touch(title)
    core.revoke_unused_keys_for_developer(dev_id)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Titles
# ==========================================================================
@bp.route("/titles", methods=["POST"])
@roles("Developer")
def create_title():
    data = body()
    dev_id = data.get("developer_account_id")
    if not isinstance(dev_id, str) or not dev_id.strip():
        core.err_invalid_request("developer_account_id is required")
    dev = get_or_404("developer_accounts", dev_id)
    check_dev_owner(dev_id)
    title_name = data.get("title_name")
    if not isinstance(title_name, str) or not title_name.strip():
        core.err_invalid_request("title_name is required")
    base_price = data.get("base_price_usd_cents")
    if not is_int(base_price) or base_price <= 0:
        core.err_invalid_request("base_price_usd_cents must be a positive integer")
    early_access = data.get("early_access", False)
    if not isinstance(early_access, bool):
        core.err_invalid_request("early_access must be a boolean")
    disclosure = data.get("early_access_disclosure_text")
    if disclosure is not None and not isinstance(disclosure, str):
        core.err_invalid_request("early_access_disclosure_text must be a string or null")
    for t in STORE["titles"].values():
        if t["developer_account_id"] == dev_id and t["title_name"] == title_name:
            err("ERR_DUPLICATE", 409, "title_name already exists for this developer")
    rec = new_record("titles", {
        "developer_account_id": dev_id,
        "title_name": title_name,
        "base_price_usd_cents": base_price,
        "early_access": early_access,
        "early_access_disclosure_text": disclosure,
        "status": "DRAFT",
        "review_notes": None,
        "scheduled_release_at": None,
        "released_at": None,
        "current_tier": 1,
        "lifetime_recognized_revenue_usd_cents": 0,
        "lifetime_refund_events": 0,
        "refund_abuse_flag": False,
        "review_score_bps": None,
        "recent_review_summary": None,
        "review_bomb_flag": False,
    })
    from app import ok
    return ok(core.serialize_title(rec), 201)


@bp.route("/titles/<title_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer", "TrustSafety", "User")
def get_title(title_id):
    rec = get_or_404("titles", title_id)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer", "TrustSafety", "User")
def list_titles():
    items = list(STORE["titles"].values())
    dev_id = request.args.get("developer_account_id")
    if dev_id is not None:
        items = [t for t in items if t["developer_account_id"] == dev_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    for t in items:
        core.maybe_auto_release(t)
    return list_resp(items)


@bp.route("/titles/<title_id>", methods=["PATCH"])
@roles("Developer")
def patch_title(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] != "DRAFT":
        core.err_invalid_state("Only DRAFT titles can be patched")
    data = body()
    if "title_name" in data:
        v = data["title_name"]
        if not isinstance(v, str) or not v.strip():
            core.err_invalid_request("title_name must be a non-empty string")
        for t in STORE["titles"].values():
            if (t["developer_account_id"] == rec["developer_account_id"]
                    and t["title_name"] == v and t["id"] != rec["id"]):
                err("ERR_DUPLICATE", 409, "title_name already exists for this developer")
        rec["title_name"] = v
    if "base_price_usd_cents" in data:
        v = data["base_price_usd_cents"]
        if not is_int(v) or v <= 0:
            core.err_invalid_request("base_price_usd_cents must be a positive integer")
        rec["base_price_usd_cents"] = v
    if "early_access" in data:
        v = data["early_access"]
        if not isinstance(v, bool):
            core.err_invalid_request("early_access must be a boolean")
        rec["early_access"] = v
    if "early_access_disclosure_text" in data:
        v = data["early_access_disclosure_text"]
        if v is not None and not isinstance(v, str):
            core.err_invalid_request("early_access_disclosure_text must be a string or null")
        rec["early_access_disclosure_text"] = v
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/submit-review", methods=["POST"])
@roles("Developer")
def title_submit_review(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] != "DRAFT":
        core.err_invalid_state("Only DRAFT titles can be submitted for review")
    dev = core.developer_of_title(rec)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    open_reviews = [
        r for r in STORE["store_page_reviews"].values()
        if r["title_id"] == title_id and r["status"] == "SUBMITTED"
    ]
    if open_reviews:
        err("ERR_REVIEW_ALREADY_OPEN", 409, "Another SUBMITTED store-page review exists")
    prior_count = sum(1 for r in STORE["store_page_reviews"].values() if r["title_id"] == title_id)
    new_record("store_page_reviews", {
        "title_id": title_id,
        "submission_seq": prior_count + 1,
        "submitted_at": iso(get_now()),
        "status": "SUBMITTED",
    })
    rec["status"] = "PENDING_REVIEW"
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/schedule-release", methods=["POST"])
@roles("Developer")
def title_schedule_release(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] != "APPROVED":
        core.err_invalid_state("Only APPROVED titles can be scheduled")
    data = body()
    raw = data.get("release_at")
    if not isinstance(raw, str) or not raw.strip():
        core.err_invalid_request("release_at is required")
    try:
        release_at = parse_dt(raw)
    except (ValueError, TypeError):
        core.err_invalid_request("release_at is not a valid ISO 8601 datetime")
    dev = core.developer_of_title(rec)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    if release_at <= get_now():
        err("ERR_INVALID_SCHEDULE", 422, "release_at must be strictly in the future")
    if rec["early_access"] and rec["early_access_disclosure_text"] is None:
        err("ERR_MISSING_DISCLOSURE", 422, "Early-access titles require disclosure text before scheduling")
    rec["status"] = "RELEASE_SCHEDULED"
    rec["scheduled_release_at"] = iso(release_at)
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/cancel-release", methods=["POST"])
@roles("Developer")
def title_cancel_release(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] != "RELEASE_SCHEDULED":
        core.err_invalid_state("Only RELEASE_SCHEDULED titles can be cancelled")
    rec["status"] = "APPROVED"
    rec["scheduled_release_at"] = None
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/release-now", methods=["POST"])
@roles("Developer")
def title_release_now(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] != "APPROVED":
        core.err_invalid_state("Only APPROVED titles can be released")
    dev = core.developer_of_title(rec)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    if rec["early_access"] and rec["early_access_disclosure_text"] is None:
        err("ERR_MISSING_DISCLOSURE", 422, "Early-access titles require disclosure text before release")
    rec["status"] = "RELEASED"
    rec["released_at"] = iso(get_now())
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/delist", methods=["POST"])
@roles("Developer")
def title_delist(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    check_dev_owner(rec["developer_account_id"])
    if rec["status"] not in ("APPROVED", "RELEASE_SCHEDULED", "RELEASED"):
        core.err_invalid_state("Title cannot be delisted from its current state")
    rec["status"] = "DELISTED"
    touch(rec)
    core.revoke_unused_keys_for_title(title_id)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/adjustments", methods=["POST"])
@roles("PlatformOps")
def title_adjustments(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    data = body()
    check_occ(rec, data)
    delta = data.get("delta_usd_cents")
    if not is_int(delta):
        core.err_invalid_request("delta_usd_cents must be an integer")
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        core.err_invalid_request("reason is required")
    new_value = rec["lifetime_recognized_revenue_usd_cents"] + delta
    if new_value < 0:
        err("ERR_NEGATIVE_REVENUE", 422, "Adjustment would drive recognized revenue below zero")
    rec["lifetime_recognized_revenue_usd_cents"] = new_value
    core.recompute_tier(rec)
    touch(rec)
    from app import ok
    return ok(core.serialize_title(rec))


@bp.route("/titles/<title_id>/pricing-recommendation", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer", "TrustSafety")
def title_pricing_recommendation(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    currency = request.args.get("currency")
    if currency is not None and currency not in core.OVERRIDE_CURRENCIES:
        core.err_invalid_request("currency must be one of EUR, GBP, JPY, BRL")

    def one(cur):
        recommended = core.recommended_price_cents(rec["base_price_usd_cents"], cur)
        effective = recommended
        for ov in STORE["regional_prices"].values():
            if ov["title_id"] == title_id and ov["currency"] == cur and ov["status"] == "ACTIVE":
                effective = ov["price_cents"]
                break
        return {
            "currency": cur,
            "recommended_cents": recommended,
            "effective_cents": effective,
            "usd_recognized_per_unit": core.rhu(Decimal(effective) / core.FX[cur]),
        }

    from app import envelope
    if currency is not None:
        return envelope(one(currency), "object", 200)
    return envelope([one(c) for c in core.OVERRIDE_CURRENCIES], "array", 200)


@bp.route("/titles/<title_id>/reviews", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer", "TrustSafety", "User")
def title_reviews(title_id):
    rec = get_or_404("titles", title_id)
    core.maybe_auto_release(rec)
    items = [r for r in STORE["reviews"].values() if r["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    off_topic = core.parse_bool_param("off_topic")
    if off_topic is not None:
        items = [r for r in items if r["off_topic"] == off_topic]
    return list_resp(items)


@bp.route("/titles/<title_id>/key-batches", methods=["GET"])
@roles("PlatformOps", "Developer")
def title_key_batches(title_id):
    get_or_404("titles", title_id)
    items = [b for b in STORE["key_batches"].values() if b["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_resp(items)


@bp.route("/titles/<title_id>/workshop-items", methods=["GET"])
@roles("PlatformOps", "Developer", "TrustSafety", "User")
def title_workshop_items(title_id):
    get_or_404("titles", title_id)
    items = [i for i in STORE["workshop_items"].values() if i["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_resp(items)


@bp.route("/titles/<title_id>/review-bomb-windows", methods=["GET"])
@roles("PlatformOps", "Developer", "TrustSafety")
def title_bomb_windows(title_id):
    get_or_404("titles", title_id)
    items = [w for w in STORE["review_bomb_windows"].values() if w["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_resp(items)


@bp.route("/titles/<title_id>/regional-prices", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer")
def title_regional_prices(title_id):
    get_or_404("titles", title_id)
    items = [o for o in STORE["regional_prices"].values() if o["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_resp(items)


@bp.route("/titles/<title_id>/store-page-reviews", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer")
def title_store_page_reviews(title_id):
    get_or_404("titles", title_id)
    items = [r for r in STORE["store_page_reviews"].values() if r["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_resp(items)


# ==========================================================================
# Store-page reviews
# ==========================================================================
@bp.route("/store-page-reviews", methods=["GET"])
@roles("PlatformOps", "StoreReviewer")
def list_store_page_reviews():
    items = list(STORE["store_page_reviews"].values())
    title_id = request.args.get("title_id")
    if title_id is not None:
        items = [r for r in items if r["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_resp(items)


@bp.route("/store-page-reviews/<review_id>", methods=["GET"])
@roles("PlatformOps", "StoreReviewer", "Developer")
def get_store_page_review(review_id):
    rec = get_or_404("store_page_reviews", review_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/store-page-reviews/<review_id>/approve", methods=["POST"])
@roles("StoreReviewer")
def store_page_review_approve(review_id):
    rec = get_or_404("store_page_reviews", review_id)
    if rec["status"] != "SUBMITTED":
        core.err_invalid_state("Only SUBMITTED store-page reviews can be approved")
    rec["status"] = "APPROVED"
    touch(rec)
    title = STORE["titles"][rec["title_id"]]
    title["status"] = "APPROVED"
    touch(title)
    from app import ok
    return ok(pub(rec))


@bp.route("/store-page-reviews/<review_id>/reject", methods=["POST"])
@roles("StoreReviewer")
def store_page_review_reject(review_id):
    rec = get_or_404("store_page_reviews", review_id)
    if rec["status"] != "SUBMITTED":
        core.err_invalid_state("Only SUBMITTED store-page reviews can be rejected")
    data = body()
    notes = data.get("review_notes")
    if notes is not None and not isinstance(notes, str):
        core.err_invalid_request("review_notes must be a string")
    rec["status"] = "REJECTED"
    touch(rec)
    title = STORE["titles"][rec["title_id"]]
    title["status"] = "DRAFT"
    title["review_notes"] = notes
    touch(title)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Regional price overrides
# ==========================================================================
@bp.route("/regional-prices", methods=["POST"])
@roles("Developer")
def create_regional_price():
    data = body()
    title_id = data.get("title_id")
    if not isinstance(title_id, str) or not title_id.strip():
        core.err_invalid_request("title_id is required")
    title = get_or_404("titles", title_id)
    core.maybe_auto_release(title)
    check_dev_owner(title["developer_account_id"])
    check_occ(title, data)
    currency = data.get("currency")
    if currency not in core.OVERRIDE_CURRENCIES:
        core.err_invalid_request("currency must be one of EUR, GBP, JPY, BRL")
    price_cents = data.get("price_cents")
    if not is_int(price_cents) or price_cents <= 0:
        core.err_invalid_request("price_cents must be a positive integer")
    dev = core.developer_of_title(title)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    recommended = core.recommended_price_cents(title["base_price_usd_cents"], currency)
    deviation = core.rhu(Decimal(price_cents - recommended) * 10000 / Decimal(recommended))
    if abs(deviation) > core.MAX_DEVIATION_BPS:
        err("ERR_PRICE_DEVIATION", 422, "Override deviates more than 2500 bps from recommendation")
    for ov in STORE["regional_prices"].values():
        if ov["title_id"] == title_id and ov["currency"] == currency and ov["status"] == "ACTIVE":
            err("ERR_OVERRIDE_EXISTS", 409, "An ACTIVE override already exists for this currency")
    rec = new_record("regional_prices", {
        "title_id": title_id,
        "currency": currency,
        "price_cents": price_cents,
        "status": "ACTIVE",
        "deviation_bps": deviation,
    })
    touch(title)
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/regional-prices/<ov_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "StoreReviewer")
def get_regional_price(ov_id):
    rec = get_or_404("regional_prices", ov_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/regional-prices/<ov_id>/withdraw", methods=["POST"])
@roles("Developer")
def withdraw_regional_price(ov_id):
    rec = get_or_404("regional_prices", ov_id)
    title = STORE["titles"][rec["title_id"]]
    core.maybe_auto_release(title)
    check_dev_owner(title["developer_account_id"])
    if rec["status"] != "ACTIVE":
        core.err_invalid_state("Only ACTIVE overrides can be withdrawn")
    if title["status"] not in ("DRAFT", "PENDING_REVIEW", "APPROVED", "RELEASE_SCHEDULED", "RELEASED"):
        core.err_invalid_state("Override cannot be withdrawn while the title is delisted")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Key batches and keys
# ==========================================================================
@bp.route("/key-batches", methods=["POST"])
@roles("Developer")
def create_key_batch():
    data = body()
    title_id = data.get("title_id")
    if not isinstance(title_id, str) or not title_id.strip():
        core.err_invalid_request("title_id is required")
    title = get_or_404("titles", title_id)
    core.maybe_auto_release(title)
    check_dev_owner(title["developer_account_id"])
    qty = data.get("requested_quantity")
    if not is_int(qty) or qty < 1 or qty > 10000:
        core.err_invalid_request("requested_quantity must be in 1..10000")
    free_keys = data.get("free_keys_in_batch")
    if not is_int(free_keys) or free_keys < 0 or free_keys > qty:
        core.err_invalid_request("free_keys_in_batch must be in 0..requested_quantity")
    dev = core.developer_of_title(title)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    if title["status"] == "DELISTED":
        core.err_invalid_state("Key requests are blocked for delisted titles")
    allowance = max(core.FREE_KEY_BASE, core.completed_sales_count(title_id))
    rec = new_record("key_batches", {
        "title_id": title_id,
        "requested_quantity": qty,
        "free_keys_in_batch": free_keys,
        "status": "REQUESTED",
        "free_key_allowance_at_request": allowance,
        "allocated_keys": 0,
    })
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/key-batches/<batch_id>", methods=["GET"])
@roles("PlatformOps", "Developer")
def get_key_batch(batch_id):
    rec = get_or_404("key_batches", batch_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/key-batches", methods=["GET"])
@roles("PlatformOps")
def list_key_batches():
    items = list(STORE["key_batches"].values())
    title_id = request.args.get("title_id")
    if title_id is not None:
        items = [b for b in items if b["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_resp(items)


@bp.route("/key-batches/<batch_id>/keys", methods=["GET"])
@roles("PlatformOps", "Developer")
def list_batch_keys(batch_id):
    get_or_404("key_batches", batch_id)
    items = [k for k in STORE["keys"].values() if k["batch_id"] == batch_id]
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k["status"] == status]
    return list_resp(items)


@bp.route("/keys/<key_id>", methods=["GET"])
@roles("PlatformOps", "Developer")
def get_key(key_id):
    rec = get_or_404("keys", key_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/keys", methods=["GET"])
@roles("PlatformOps", "Developer")
def list_keys():
    items = list(STORE["keys"].values())
    batch_id = request.args.get("batch_id")
    if batch_id is not None:
        items = [k for k in items if k["batch_id"] == batch_id]
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k["status"] == status]
    return list_resp(items)


@bp.route("/user-accounts/<user_id>/keys", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def list_user_keys(user_id):
    get_or_404("user_accounts", user_id)
    items = [k for k in STORE["keys"].values() if k.get("redeemed_by_account_id") == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [k for k in items if k["status"] == status]
    return list_resp(items)


@bp.route("/key-batches/<batch_id>/approve", methods=["POST"])
@roles("PlatformOps")
def approve_key_batch(batch_id):
    rec = get_or_404("key_batches", batch_id)
    if rec["status"] != "REQUESTED":
        core.err_invalid_state("Only REQUESTED key batches can be approved")
    title = STORE["titles"][rec["title_id"]]
    core.maybe_auto_release(title)
    if title["status"] != "RELEASED":
        core.err_invalid_state("Key batches may only be approved for RELEASED titles")
    dev = core.developer_of_title(title)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_DEVELOPER_NOT_ACTIVE", 409, "Developer account is not ACTIVE")
    granted = sum(
        b["free_keys_in_batch"]
        for b in STORE["key_batches"].values()
        if b["title_id"] == rec["title_id"] and b["status"] == "APPROVED"
    )
    if granted + rec["free_keys_in_batch"] > rec["free_key_allowance_at_request"]:
        err("ERR_FREE_KEY_ALLOWANCE_EXCEEDED", 422, "Free keys requested exceed allowance")
    if title["refund_abuse_flag"]:
        err("ERR_GRAY_MARKET_RISK", 422, "Key-batch approval blocked by title refund-abuse flag")
    rec["status"] = "APPROVED"
    rec["allocated_keys"] = rec["requested_quantity"]
    touch(rec)
    for i in range(rec["requested_quantity"]):
        new_record("keys", {
            "batch_id": batch_id,
            "key_code": core.new_id(),
            "is_free": i < rec["free_keys_in_batch"],
            "status": "UNUSED",
            "redeemed_by_account_id": None,
            "redeemed_at": None,
        })
    from app import ok
    return ok(pub(rec))


@bp.route("/key-batches/<batch_id>/reject", methods=["POST"])
@roles("PlatformOps")
def reject_key_batch(batch_id):
    rec = get_or_404("key_batches", batch_id)
    if rec["status"] != "REQUESTED":
        core.err_invalid_state("Only REQUESTED key batches can be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/keys/redeem", methods=["POST"])
@roles("User")
def redeem_key():
    data = body()
    code = data.get("key_code")
    if not isinstance(code, str) or not code.strip():
        core.err_invalid_request("key_code is required")
    key = None
    for k in STORE["keys"].values():
        if k["key_code"] == code:
            key = k
            break
    if key is None:
        core.err_not_found("No key with that key_code")
    title = core.title_of_key(key)
    if key["status"] != "UNUSED" or title is None or title["status"] != "RELEASED":
        err("ERR_KEY_NOT_REDEEMABLE", 409, "Key is not redeemable in its current state")
    dev = core.developer_of_title(title)
    if dev is None or dev["status"] != "ACTIVE":
        err("ERR_KEY_NOT_REDEEMABLE", 409, "Key is not redeemable: developer not ACTIVE")
    user = STORE["user_accounts"].get(g.user_id)
    if user is None:
        core.err_not_found("User account not found")
    if user["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    now = get_now()
    window_start = now - core.REDEEM_WINDOW
    recent = [
        k for k in STORE["keys"].values()
        if k["status"] == "REDEEMED" and k["redeemed_at"] is not None
        and window_start <= parse_dt(k["redeemed_at"]) <= now
    ]
    mine = sum(1 for k in recent if k["redeemed_by_account_id"] == user["id"])
    if mine >= core.REDEEM_ACCOUNT_LIMIT or len(recent) >= core.REDEEM_GLOBAL_LIMIT:
        err("ERR_REDEEM_VELOCITY", 422, "Redemption velocity guard tripped")
    key["status"] = "REDEEMED"
    key["redeemed_by_account_id"] = user["id"]
    key["redeemed_at"] = iso(now)
    touch(key)
    from app import ok
    return ok(pub(key))


# ==========================================================================
# User accounts
# ==========================================================================
@bp.route("/user-accounts", methods=["POST"])
@roles("PlatformOps")
def create_user():
    data = body()
    email = data.get("email")
    if not isinstance(email, str) or not email.strip():
        core.err_invalid_request("email is required")
    for u in STORE["user_accounts"].values():
        if u["email"] == email:
            err("ERR_DUPLICATE", 409, "email already registered")
    rec = new_record("user_accounts", {
        "email": email,
        "status": "ACTIVE",
        "refund_abuse_score": 0,
        "refund_restricted": False,
    })
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/user-accounts/<user_id>", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def get_user(user_id):
    rec = get_or_404("user_accounts", user_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/user-accounts", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_users():
    items = list(STORE["user_accounts"].values())
    status = request.args.get("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return list_resp(items)


@bp.route("/user-accounts/<user_id>/restrict", methods=["POST"])
@roles("TrustSafety")
def restrict_user(user_id):
    rec = get_or_404("user_accounts", user_id)
    if rec["status"] != "ACTIVE":
        core.err_invalid_state("Only ACTIVE accounts can be restricted")
    rec["status"] = "RESTRICTED"
    rec["refund_restricted"] = True
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/user-accounts/<user_id>/unrestrict", methods=["POST"])
@roles("TrustSafety")
def unrestrict_user(user_id):
    rec = get_or_404("user_accounts", user_id)
    if rec["status"] != "RESTRICTED":
        core.err_invalid_state("Only RESTRICTED accounts can be unrestricted")
    rec["status"] = "ACTIVE"
    rec["refund_restricted"] = False
    core.recompute_abuse_score(rec)
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/user-accounts/<user_id>/ban", methods=["POST"])
@roles("TrustSafety")
def ban_user(user_id):
    rec = get_or_404("user_accounts", user_id)
    if rec["status"] not in ("ACTIVE", "RESTRICTED"):
        core.err_invalid_state("Account cannot be banned from its current state")
    rec["status"] = "BANNED"
    touch(rec)
    affected_titles = set()
    for r in STORE["reviews"].values():
        if r["user_account_id"] == user_id and r["status"] == "PUBLISHED":
            r["status"] = "REMOVED"
            touch(r)
            affected_titles.add(r["title_id"])
    for tid in affected_titles:
        title = STORE["titles"][tid]
        core.recompute_review_stats(title)
        touch(title)
    from app import ok
    return ok(pub(rec))


@bp.route("/user-accounts/<user_id>/purchases", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def list_user_purchases(user_id):
    get_or_404("user_accounts", user_id)
    items = [p for p in STORE["purchases"].values() if p["user_account_id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_resp(items)


@bp.route("/user-accounts/<user_id>/reviews", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def list_user_reviews(user_id):
    get_or_404("user_accounts", user_id)
    items = [r for r in STORE["reviews"].values() if r["user_account_id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_resp(items)


# ==========================================================================
# Purchases
# ==========================================================================
@bp.route("/purchases", methods=["POST"])
@roles("User")
def create_purchase():
    data = body()
    user_id = data.get("user_account_id")
    if not isinstance(user_id, str) or not user_id.strip():
        core.err_invalid_request("user_account_id is required")
    title_id = data.get("title_id")
    if not isinstance(title_id, str) or not title_id.strip():
        core.err_invalid_request("title_id is required")
    user = get_or_404("user_accounts", user_id)
    title = get_or_404("titles", title_id)
    core.maybe_auto_release(title)
    check_user_owner(user_id)
    currency = data.get("currency")
    if currency not in core.PURCHASE_CURRENCIES:
        core.err_invalid_request("currency must be one of USD, EUR, GBP, JPY, BRL")
    if user["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    if title["status"] != "RELEASED":
        core.err_invalid_state("Only RELEASED titles can be purchased")
    if currency == "USD":
        gross = title["base_price_usd_cents"]
        usd_recognized = gross
    else:
        gross = core.recommended_price_cents(title["base_price_usd_cents"], currency)
        for ov in STORE["regional_prices"].values():
            if ov["title_id"] == title_id and ov["currency"] == currency and ov["status"] == "ACTIVE":
                gross = ov["price_cents"]
                break
        usd_recognized = core.rhu(Decimal(gross) / core.FX[currency])
    # DEVELOPER_FIRST split pinned: fee rounded half-up, developer gets remainder
    rate = core.TIER_RATES[title["current_tier"]]
    platform_fee = core.rhu(Decimal(gross) * rate)
    developer_share = gross - platform_fee
    rec = new_record("purchases", {
        "user_account_id": user_id,
        "title_id": title_id,
        "currency": currency,
        "gross_price_cents": gross,
        "platform_fee_cents": platform_fee,
        "developer_share_cents": developer_share,
        "usd_recognized_cents": usd_recognized,
        "status": "COMPLETED",
        "refunded_amount_usd_cents": 0,
        "playtime_minutes": 0,
        "refunded_cents": 0,
        "purchased_at": iso(get_now()),
    })
    title["lifetime_recognized_revenue_usd_cents"] += usd_recognized
    core.recompute_tier(title)
    touch(title)
    core.bump_abuse_score(user, -1)
    touch(user)
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/purchases/<purchase_id>", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def get_purchase(purchase_id):
    rec = get_or_404("purchases", purchase_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/purchases", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_purchases():
    items = list(STORE["purchases"].values())
    title_id = request.args.get("title_id")
    if title_id is not None:
        items = [p for p in items if p["title_id"] == title_id]
    user_id = request.args.get("user_account_id")
    if user_id is not None:
        items = [p for p in items if p["user_account_id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_resp(items)


@bp.route("/purchases/<purchase_id>/playtime", methods=["POST"])
@roles("User")
def record_playtime(purchase_id):
    rec = get_or_404("purchases", purchase_id)
    check_user_owner(rec["user_account_id"])
    data = body()
    minutes = data.get("minutes")
    if not is_int(minutes) or minutes < 0:
        core.err_invalid_request("minutes must be a non-negative integer")
    rec["playtime_minutes"] += minutes
    touch(rec)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Refund requests
# ==========================================================================
@bp.route("/refund-requests", methods=["POST"])
@roles("User")
def create_refund_request():
    data = body()
    purchase_id = data.get("purchase_id")
    if not isinstance(purchase_id, str) or not purchase_id.strip():
        core.err_invalid_request("purchase_id is required")
    purchase = get_or_404("purchases", purchase_id)
    check_user_owner(purchase["user_account_id"])
    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        core.err_invalid_request("reason is required")
    amount = data.get("amount_cents")
    if amount is None:
        amount = 0
    if not is_int(amount) or amount < 0:
        core.err_invalid_request("amount_cents must be a non-negative integer")
    user = STORE["user_accounts"][purchase["user_account_id"]]
    if user["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    if user["refund_restricted"]:
        err("ERR_REFUND_ABUSE", 422, "Account is refund-restricted")
    remaining = purchase["gross_price_cents"] - purchase["refunded_cents"]
    if purchase["status"] not in ("COMPLETED", "PARTIALLY_REFUNDED") or amount > remaining:
        err("ERR_REFUND_AMOUNT", 422, "Refund amount exceeds remaining gross or purchase fully refunded")
    for rr in STORE["refund_requests"].values():
        if rr["purchase_id"] == purchase_id and rr["status"] == "REQUESTED":
            err("ERR_REFUND_ALREADY_PENDING", 409, "Another refund request is pending for this purchase")
    now = get_now()
    rec = new_record("refund_requests", {
        "purchase_id": purchase_id,
        "user_account_id": purchase["user_account_id"],
        "amount_cents": amount,
        "reason": reason,
        "status": "REQUESTED",
        "decision_reason": None,
        "approved_amount_cents": 0,
        "decided_at": None,
    })
    # Auto-decision (not an error path): policy pass -> immediate APPROVED.
    effective = remaining if amount == 0 else amount
    policy_ok = (
        purchase["status"] in ("COMPLETED", "PARTIALLY_REFUNDED")
        and purchase["playtime_minutes"] < core.PLAYTIME_LIMIT
        and now - parse_dt(purchase["purchased_at"]) <= core.PURCHASE_AGE_LIMIT
        and 0 <= effective <= remaining
        and not user["refund_restricted"]
    )
    if policy_ok:
        rec["status"] = "APPROVED"
        rec["approved_amount_cents"] = effective
        rec["decided_at"] = iso(now)
        touch(rec)
        core.apply_refund_cascade(purchase, effective)
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/refund-requests/<rr_id>", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def get_refund_request(rr_id):
    rec = get_or_404("refund_requests", rr_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/refund-requests", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_refund_requests():
    items = list(STORE["refund_requests"].values())
    purchase_id = request.args.get("purchase_id")
    if purchase_id is not None:
        items = [r for r in items if r["purchase_id"] == purchase_id]
    user_id = request.args.get("user_account_id")
    if user_id is not None:
        items = [r for r in items if r["user_account_id"] == user_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_resp(items)


@bp.route("/refund-requests/<rr_id>/approve", methods=["POST"])
@roles("TrustSafety")
def approve_refund_request(rr_id):
    rec = get_or_404("refund_requests", rr_id)
    if rec["status"] != "REQUESTED":
        core.err_invalid_state("Only REQUESTED refunds can be approved")
    purchase = STORE["purchases"][rec["purchase_id"]]
    user = STORE["user_accounts"][rec["user_account_id"]]
    now = get_now()
    if now - parse_dt(purchase["purchased_at"]) > core.PURCHASE_AGE_LIMIT:
        err("ERR_REFUND_WINDOW_EXPIRED", 422, "Purchase is older than 14 days")
    # NOTE: playtime >= 120 does not block manual approval (PRD §3.5 — the
    # over-limit case arises only through manual TrustSafety approval and is
    # priced into the buyer's abuse score).
    if user["refund_restricted"]:
        err("ERR_REFUND_ABUSE", 422, "Account is refund-restricted")
    remaining = purchase["gross_price_cents"] - purchase["refunded_cents"]
    if purchase["status"] not in ("COMPLETED", "PARTIALLY_REFUNDED") or rec["amount_cents"] > remaining:
        err("ERR_REFUND_AMOUNT", 422, "Refund amount exceeds remaining gross or purchase fully refunded")
    effective = remaining if rec["amount_cents"] == 0 else rec["amount_cents"]
    rec["status"] = "APPROVED"
    rec["approved_amount_cents"] = effective
    rec["decided_at"] = iso(now)
    touch(rec)
    core.apply_refund_cascade(purchase, effective)
    from app import ok
    return ok(pub(rec))


@bp.route("/refund-requests/<rr_id>/deny", methods=["POST"])
@roles("TrustSafety")
def deny_refund_request(rr_id):
    rec = get_or_404("refund_requests", rr_id)
    if rec["status"] != "REQUESTED":
        core.err_invalid_state("Only REQUESTED refunds can be denied")
    purchase = STORE["purchases"][rec["purchase_id"]]
    now = get_now()
    if now - parse_dt(purchase["purchased_at"]) > core.PURCHASE_AGE_LIMIT:
        err("ERR_REFUND_WINDOW_EXPIRED", 422, "Purchase is older than 14 days")
    data = body()
    decision_reason = data.get("decision_reason")
    if decision_reason is not None and not isinstance(decision_reason, str):
        core.err_invalid_request("decision_reason must be a string")
    rec["status"] = "DENIED"
    rec["decision_reason"] = decision_reason
    rec["decided_at"] = iso(now)
    touch(rec)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Reviews
# ==========================================================================
@bp.route("/reviews", methods=["POST"])
@roles("User")
def create_review():
    data = body()
    title_id = data.get("title_id")
    if not isinstance(title_id, str) or not title_id.strip():
        core.err_invalid_request("title_id is required")
    user_id = data.get("user_account_id")
    if not isinstance(user_id, str) or not user_id.strip():
        core.err_invalid_request("user_account_id is required")
    title = get_or_404("titles", title_id)
    core.maybe_auto_release(title)
    user = get_or_404("user_accounts", user_id)
    check_user_owner(user_id)
    check_occ(title, data)
    is_positive = data.get("is_positive")
    if not isinstance(is_positive, bool):
        core.err_invalid_request("is_positive must be a boolean")
    review_body = data.get("body")
    if not isinstance(review_body, str) or not (1 <= len(review_body) <= 8000):
        core.err_invalid_request("body must be 1..8000 characters")
    if user["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    owns = any(
        p["user_account_id"] == user_id and p["title_id"] == title_id
        and p["status"] in ("COMPLETED", "PARTIALLY_REFUNDED")
        for p in STORE["purchases"].values()
    )
    if not owns:
        owns = any(
            k.get("redeemed_by_account_id") == user_id and k["status"] == "REDEEMED"
            and (lambda t: t is not None and t["id"] == title_id)(core.title_of_key(k))
            for k in STORE["keys"].values()
        )
    if not owns:
        err("ERR_REVIEW_NOT_OWNED", 422, "Reviewer owns no completed purchase or redeemed key for the title")
    for r in STORE["reviews"].values():
        if r["title_id"] == title_id and r["user_account_id"] == user_id:
            err("ERR_DUPLICATE", 409, "This account has already reviewed this title")
    playtime = sum(
        p["playtime_minutes"]
        for p in STORE["purchases"].values()
        if p["user_account_id"] == user_id and p["title_id"] == title_id
        and p["status"] in ("COMPLETED", "PARTIALLY_REFUNDED")
    )
    now = get_now()
    off_topic = any(core.window_covers(w, now) for w in core.active_windows_of_title(title_id))
    rec = new_record("reviews", {
        "title_id": title_id,
        "user_account_id": user_id,
        "is_positive": is_positive,
        "body": review_body,
        "author_playtime_minutes": playtime,
        "status": "PUBLISHED",
        "off_topic": off_topic,
    })
    touch(title)
    core.run_bomb_detection(title, triggering_review_id=rec["id"])
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/reviews/<review_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "TrustSafety", "User")
def get_review(review_id):
    rec = get_or_404("reviews", review_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/reviews/<review_id>/remove", methods=["POST"])
@roles("TrustSafety")
def remove_review(review_id):
    rec = get_or_404("reviews", review_id)
    if rec["status"] != "PUBLISHED":
        core.err_invalid_state("Only PUBLISHED reviews can be removed")
    rec["status"] = "REMOVED"
    touch(rec)
    title = STORE["titles"][rec["title_id"]]
    core.recompute_review_stats(title)
    touch(title)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Review bomb windows
# ==========================================================================
@bp.route("/review-bomb-windows/<window_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "TrustSafety")
def get_bomb_window(window_id):
    rec = get_or_404("review_bomb_windows", window_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/review-bomb-windows", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_bomb_windows():
    items = list(STORE["review_bomb_windows"].values())
    title_id = request.args.get("title_id")
    if title_id is not None:
        items = [w for w in items if w["title_id"] == title_id]
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_resp(items)


@bp.route("/review-bomb-windows/<window_id>/close", methods=["POST"])
@roles("TrustSafety")
def close_bomb_window(window_id):
    rec = get_or_404("review_bomb_windows", window_id)
    if rec["status"] != "ACTIVE":
        core.err_invalid_state("Only ACTIVE windows can be closed")
    rec["status"] = "CLOSED"
    touch(rec)
    title = STORE["titles"][rec["title_id"]]
    core.refresh_off_topic(title)
    core.refresh_bomb_flag(title)
    core.recompute_review_stats(title)
    from app import ok
    return ok(pub(rec))


# ==========================================================================
# Workshop items and sales
# ==========================================================================
@bp.route("/workshop-items", methods=["POST"])
@roles("User")
def create_workshop_item():
    data = body()
    title_id = data.get("title_id")
    if not isinstance(title_id, str) or not title_id.strip():
        core.err_invalid_request("title_id is required")
    creator_id = data.get("creator_account_id")
    if not isinstance(creator_id, str) or not creator_id.strip():
        core.err_invalid_request("creator_account_id is required")
    title = get_or_404("titles", title_id)
    core.maybe_auto_release(title)
    creator = get_or_404("user_accounts", creator_id)
    check_user_owner(creator_id)
    item_name = data.get("item_name")
    if not isinstance(item_name, str) or not item_name.strip():
        core.err_invalid_request("item_name is required")
    price_cents = data.get("price_cents")
    if not is_int(price_cents) or price_cents <= 0:
        core.err_invalid_request("price_cents must be a positive integer")
    share_bps = data.get("creator_share_bps")
    if not is_int(share_bps) or share_bps < 1 or share_bps > 5000:
        core.err_invalid_request("creator_share_bps must be in 1..5000")
    if creator["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    rec = new_record("workshop_items", {
        "title_id": title_id,
        "creator_account_id": creator_id,
        "item_name": item_name,
        "price_cents": price_cents,
        "creator_share_bps": share_bps,
        "status": "PENDING",
    })
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/workshop-items/<item_id>", methods=["GET"])
@roles("PlatformOps", "Developer", "TrustSafety", "User")
def get_workshop_item(item_id):
    rec = get_or_404("workshop_items", item_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/workshop-items", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_workshop_items():
    items = list(STORE["workshop_items"].values())
    title_id = request.args.get("title_id")
    if title_id is not None:
        items = [i for i in items if i["title_id"] == title_id]
    creator_id = request.args.get("creator_account_id")
    if creator_id is not None:
        items = [i for i in items if i["creator_account_id"] == creator_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return list_resp(items)


@bp.route("/workshop-items/<item_id>/publish", methods=["POST"])
@roles("User")
def publish_workshop_item(item_id):
    rec = get_or_404("workshop_items", item_id)
    check_user_owner(rec["creator_account_id"])
    if rec["status"] != "PENDING":
        core.err_invalid_state("Only PENDING workshop items can be published")
    title = STORE["titles"][rec["title_id"]]
    core.maybe_auto_release(title)
    if title["status"] != "RELEASED":
        core.err_invalid_state("Host title must be RELEASED to publish")
    rec["status"] = "PUBLISHED"
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/workshop-items/<item_id>/remove", methods=["POST"])
@roles("User", "TrustSafety")
def remove_workshop_item(item_id):
    rec = get_or_404("workshop_items", item_id)
    if g.role == "User":
        check_user_owner(rec["creator_account_id"])
    if rec["status"] not in ("PENDING", "PUBLISHED"):
        core.err_invalid_state("Workshop item cannot be removed from its current state")
    rec["status"] = "REMOVED"
    touch(rec)
    from app import ok
    return ok(pub(rec))


@bp.route("/workshop-sales", methods=["POST"])
@roles("User")
def create_workshop_sale():
    data = body()
    item_id = data.get("workshop_item_id")
    if not isinstance(item_id, str) or not item_id.strip():
        core.err_invalid_request("workshop_item_id is required")
    buyer_id = data.get("buyer_account_id")
    if not isinstance(buyer_id, str) or not buyer_id.strip():
        core.err_invalid_request("buyer_account_id is required")
    item = get_or_404("workshop_items", item_id)
    buyer = get_or_404("user_accounts", buyer_id)
    check_user_owner(buyer_id)
    if buyer["status"] != "ACTIVE":
        err("ERR_ACCOUNT_RESTRICTED", 409, "User account is not ACTIVE")
    title = STORE["titles"][item["title_id"]]
    core.maybe_auto_release(title)
    if item["status"] != "PUBLISHED" or title["status"] != "RELEASED":
        err("ERR_ITEM_NOT_PURCHASABLE", 422, "Workshop item is not purchasable")
    gross = item["price_cents"]
    creator_share = (gross * item["creator_share_bps"]) // 10000
    rec = new_record("workshop_sales", {
        "workshop_item_id": item_id,
        "buyer_account_id": buyer_id,
        "gross_cents": gross,
        "creator_share_cents": creator_share,
        "platform_share_cents": gross - creator_share,
        "sold_at": iso(get_now()),
    })
    core.bump_abuse_score(buyer, -1)
    touch(buyer)
    from app import ok
    return ok(pub(rec), 201)


@bp.route("/workshop-sales/<sale_id>", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def get_workshop_sale(sale_id):
    rec = get_or_404("workshop_sales", sale_id)
    from app import ok
    return ok(pub(rec))


@bp.route("/workshop-sales", methods=["GET"])
@roles("PlatformOps", "TrustSafety")
def list_workshop_sales():
    items = list(STORE["workshop_sales"].values())
    item_id = request.args.get("workshop_item_id")
    if item_id is not None:
        items = [s for s in items if s["workshop_item_id"] == item_id]
    buyer_id = request.args.get("buyer_account_id")
    if buyer_id is not None:
        items = [s for s in items if s["buyer_account_id"] == buyer_id]
    return list_resp(items)


@bp.route("/user-accounts/<user_id>/workshop-sales", methods=["GET"])
@roles("PlatformOps", "TrustSafety", "User")
def list_user_workshop_sales(user_id):
    get_or_404("user_accounts", user_id)
    items = [s for s in STORE["workshop_sales"].values() if s["buyer_account_id"] == user_id]
    return list_resp(items)
