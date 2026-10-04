"""Subscriptions: purchase, list, get, cancel, suspend/restore entitlement,
features, payments."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err_season_closed, err_offer_not_available, err_student_not_verified,
    err_account_kind_mismatch, err_not_owner, err_already_terminal,
    err_invalid_state,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, compute_charged_price,
    week_index_for_instant, withdraw_entitlements, find_slate,
)
from validate import body_json, req_string

bp = Blueprint("subscriptions", __name__)


def _check_owner(auth, account_id):
    user_id, role = auth
    if role in ("Subscriber", "VenueManager") and user_id != account_id:
        raise err_not_owner()


@bp.post("/subscriptions")
@require_roles("Subscriber", "VenueManager")
def create_subscription(auth):
    body = body_json()
    account_id = req_string(body, "account_id")
    offer_id = req_string(body, "offer_id")
    account = get_or_404(db.accounts, account_id)
    offer = get_or_404(db.offers, offer_id)
    season = get_or_404(db.seasons, offer["season_id"])

    # Priority 5: season phase gate
    if season["phase"] == "POST":
        raise err_season_closed()
    # Priority 7: offer availability window
    now = db.clock.now()
    if (
        offer["status"] != "ACTIVE"
        or now < parse_iso(offer["valid_from"])
        or now >= parse_iso(offer["valid_until"])
    ):
        raise err_offer_not_available()
    # Priority 8: student-tier verification gate
    if offer["plan_tier"] == "STUDENT":
        verified = any(
            sv["account_id"] == account["id"]
            and sv["status"] == "VERIFIED"
            and parse_iso(sv["valid_through"]) > now
            for sv in db.student_verifications.values()
        )
        if not verified:
            raise err_student_not_verified()
    # Priority 9: account-kind gate
    if account["account_kind"] == "COMMERCIAL":
        raise err_account_kind_mismatch()
    # Priority 21: ownership
    _check_owner(auth, account["id"])

    purchase_week_index = week_index_for_instant(season, now)
    price = compute_charged_price(offer, season, purchase_week_index)

    sub = new_resource()
    sub.update({
        "account_id": account["id"],
        "offer_id": offer["id"],
        "season_id": season["id"],
        "plan_tier": offer["plan_tier"],
        "purchase_week_index": purchase_week_index,
        "price_charged_cents": price,
        "paid_amount_cents": 0,
        "status": "PENDING_PAYMENT",
        "entitlement_state": "ENABLED",
        "cancelled_at": None,
    })
    db.subscriptions[sub["id"]] = sub
    return success(sub, status=201)


@bp.get("/subscriptions")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_subscriptions(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    season_id = request.args.get("season_id")
    status = request.args.get("status")
    entitlement_state = request.args.get("entitlement_state")
    offer_id = request.args.get("offer_id")
    items = sorted(db.subscriptions.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [s for s in items if s["account_id"] == account_id]
    if season_id is not None:
        items = [s for s in items if s["season_id"] == season_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if entitlement_state is not None:
        items = [s for s in items if s["entitlement_state"] == entitlement_state]
    if offer_id is not None:
        items = [s for s in items if s["offer_id"] == offer_id]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/subscriptions/<sid>")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor", "Subscriber", "VenueManager")
def get_subscription(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    return success(sub)


@bp.post("/subscriptions/<sid>/cancel")
@require_roles("Subscriber", "VenueManager")
def cancel_subscription(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] in ("CANCELLED", "EXPIRED"):
        raise err_already_terminal()
    if sub["status"] != "ACTIVE":
        raise err_invalid_state()
    _check_owner(auth, sub["account_id"])
    sub["status"] = "CANCELLED"
    sub["cancelled_at"] = db.clock.now_iso()
    sub["entitlement_state"] = "REVOKED"
    touch(sub)
    withdraw_entitlements(sub, "SUBSCRIPTION_CANCELLED")
    return success(sub)


@bp.post("/subscriptions/<sid>/suspend-entitlement")
@require_roles("PlatformAdmin")
def suspend_entitlement(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] in ("CANCELLED", "EXPIRED"):
        raise err_already_terminal()
    if sub["status"] != "ACTIVE" or sub["entitlement_state"] != "ENABLED":
        raise err_invalid_state()
    sub["entitlement_state"] = "SUSPENDED"
    touch(sub)
    return success(sub)


@bp.post("/subscriptions/<sid>/restore-entitlement")
@require_roles("PlatformAdmin")
def restore_entitlement(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    if sub["status"] in ("CANCELLED", "EXPIRED"):
        raise err_already_terminal()
    if sub["status"] != "ACTIVE" or sub["entitlement_state"] != "SUSPENDED":
        raise err_invalid_state()
    sub["entitlement_state"] = "ENABLED"
    touch(sub)
    return success(sub)


@bp.get("/subscriptions/<sid>/features")
@require_roles("PlatformAdmin", "SupportAgent", "Subscriber", "VenueManager")
def subscription_features(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    offer = db.offers.get(sub["offer_id"])
    account = db.accounts.get(sub["account_id"])
    season = db.seasons.get(sub["season_id"])
    enabled = sub["entitlement_state"] == "ENABLED"
    multiview = bool(offer and offer["includes_multiview"]) and enabled
    companion = bool(offer and offer["includes_companion"]) and enabled
    current_week = week_index_for_instant(season, db.clock.now()) if season else None
    billing_market = account["billing_market_code"] if account else None
    count = 0
    for ent in db.game_entitlements.values():
        if ent["subscription_id"] != sub["id"]:
            continue
        if ent["status"] != "GRANTED" or ent["week_index"] != current_week:
            continue
        game = db.games.get(ent["game_id"])
        if game is not None and game["home_market_code"] == billing_market:
            continue
        count += 1
    return success({
        "multiview": multiview,
        "companion": companion,
        "package_games_available_this_week": count,
    })


@bp.get("/subscriptions/<sid>/payments")
@require_roles("PlatformAdmin", "SupportAgent", "ComplianceAuditor")
def list_payments(sid, auth):
    sub = get_or_404(db.subscriptions, sid)
    limit, offset = parse_pagination()
    items = sorted(
        [p for p in db.payments.values() if p["subscription_id"] == sub["id"]],
        key=lambda r: r["created_at"],
    )
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)
