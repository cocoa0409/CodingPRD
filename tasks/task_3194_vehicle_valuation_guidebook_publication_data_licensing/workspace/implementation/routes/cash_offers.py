"""CashOffer endpoints."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from db import DB, CLOCK
from errors import (
    not_found, invalid_input, invalid_state, invalid_funding_source,
    offer_expired, license_inactive, use_not_permitted, quota_exceeded,
)
from middleware import require_roles
from response import success
from services.calculations import (
    parse_iso8601, compute_offer_amount, apply_inspect_cap, to_iso8601_ms,
)
from services.entity import stamp_new, stamp_new_log, touch
from routes.editions import _record_license_event


bp = Blueprint("cash_offers", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")
TIERS = ("EXCELLENT", "GOOD", "FAIR", "POOR")


def _offer_view(o):
    return {
        "id": o["id"],
        "edition_id": o["edition_id"],
        "offer_amount_cents": o["offer_amount_cents"],
        "funding_dealer_id": o["funding_dealer_id"],
        "consumer_id": o["consumer_id"],
        "mileage": o["mileage"],
        "age_years": o["age_years"],
        "declared_condition_tier": o["declared_condition_tier"],
        "option_ids": o["option_ids"],
        "expires_at": o["expires_at"],
        "status": o["status"],
        "final_amount_cents": o.get("final_amount_cents"),
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _check_license_for_offer(agreement_id: str, purpose: str):
    """Run license gates for POST /cash-offers as Licensee: UNDERWRITING required."""
    agreement = DB.license_agreements.get(agreement_id)
    if agreement is None:
        raise not_found("license agreement not found")
    if agreement["status"] != "ACTIVE":
        raise license_inactive("license agreement not ACTIVE")
    if purpose != "UNDERWRITING":
        raise use_not_permitted("offer creation requires UNDERWRITING purpose")
    if "UNDERWRITING" not in agreement["permitted_uses"]:
        raise use_not_permitted("UNDERWRITING not in permitted_uses")
    # Quota
    now = CLOCK.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = 0
    for ev in DB.license_events.values():
        if ev["agreement_id"] != agreement_id:
            continue
        occ = parse_iso8601(ev["occurred_at"])
        if occ >= month_start:
            count += 1
    if count >= agreement["monthly_event_quota"]:
        raise quota_exceeded("monthly event quota exceeded")
    return agreement


@bp.route("/cash-offers", methods=["POST"])
def create_cash_offer():
    role, user_id = require_roles("DealerPartner", "Consumer", "Licensee")
    body = request.get_json(silent=True) or {}
    edition_id = body.get("edition_id")
    funding_dealer_id = body.get("funding_dealer_id")
    consumer_id = body.get("consumer_id")
    mileage = body.get("mileage")
    age_years = body.get("age_years")
    declared_tier = body.get("declared_condition_tier")
    option_ids = body.get("option_ids") or []
    purpose = body.get("purpose") or request.args.get("purpose")

    # Priority 3: existence of FKs
    edition = DB.editions.get(edition_id) if isinstance(edition_id, str) else None
    if edition is None:
        raise not_found("edition not found")
    funding = DB.sources.get(funding_dealer_id) if isinstance(funding_dealer_id, str) else None
    if funding is None:
        raise not_found("funding_dealer_id not found")
    consumer = DB.consumer_profiles.get(consumer_id) if isinstance(consumer_id, str) else None
    if consumer is None:
        raise not_found("consumer not found")
    if not isinstance(option_ids, list):
        raise invalid_input("option_ids must be a list")
    for oid in option_ids:
        if DB.option_packages.get(oid) is None:
            raise not_found("option id not found")

    # Priority 5: state — edition must be PUBLISHED
    if edition["status"] != "PUBLISHED":
        raise invalid_state("edition not PUBLISHED")

    # Priority 6/12/11 for licensee flow
    if role == "Licensee":
        agreement = _check_license_for_offer(user_id, purpose or "UNDERWRITING")

    # Priority 7: funding source must be DEALER
    if funding["source_type"] != "DEALER":
        raise invalid_funding_source("funding_dealer_id must reference a DEALER source")

    # Priority 14: input shape
    if not isinstance(mileage, int) or isinstance(mileage, bool) or mileage < 0:
        raise invalid_input("mileage must be a non-negative integer")
    if not isinstance(age_years, int) or isinstance(age_years, bool) or age_years < 0:
        raise invalid_input("age_years must be a non-negative integer")
    if declared_tier not in TIERS:
        raise invalid_input("declared_condition_tier invalid")

    series = DB.series.get(edition["series_id"])
    config = DB.configurations.get(series["configuration_id"]) if series else None

    offer_amount = compute_offer_amount(edition, config, mileage, age_years,
                                        declared_tier, option_ids)

    pub_dt = parse_iso8601(edition["published_at"])
    expires_dt = pub_dt + timedelta(days=7)
    expires_at = to_iso8601_ms(expires_dt)

    o = stamp_new({
        "edition_id": edition_id,
        "offer_amount_cents": offer_amount,
        "funding_dealer_id": funding_dealer_id,
        "consumer_id": consumer_id,
        "mileage": mileage,
        "age_years": age_years,
        "declared_condition_tier": declared_tier,
        "option_ids": list(option_ids),
        "expires_at": expires_at,
        "expires_at_dt": expires_dt,
        "status": "QUOTED",
        "final_amount_cents": None,
    })
    DB.cash_offers[o["id"]] = o

    if role == "Licensee":
        _record_license_event(agreement["id"], "OFFER_CREATED")

    return success(_offer_view(o), 201)


@bp.route("/cash-offers", methods=["GET"])
def list_cash_offers():
    require_roles(*ALL_ROLES)
    items = list(DB.cash_offers.values())
    edition_id = request.args.get("edition_id")
    funding_dealer_id = request.args.get("funding_dealer_id")
    consumer_id = request.args.get("consumer_id")
    status_filter = request.args.get("status")
    if edition_id:
        items = [o for o in items if o["edition_id"] == edition_id]
    if funding_dealer_id:
        items = [o for o in items if o["funding_dealer_id"] == funding_dealer_id]
    if consumer_id:
        items = [o for o in items if o["consumer_id"] == consumer_id]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_offer_view(o) for o in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/cash-offers/<offer_id>", methods=["GET"])
def get_cash_offer(offer_id):
    require_roles(*ALL_ROLES)
    o = DB.cash_offers.get(offer_id)
    if o is None:
        raise not_found("offer not found")
    return success(_offer_view(o), 200)


@bp.route("/cash-offers/<offer_id>/disputes", methods=["GET"])
def list_offer_disputes(offer_id):
    require_roles("ValuationAdmin", "Consumer", "DealerPartner")
    o = DB.cash_offers.get(offer_id)
    if o is None:
        raise not_found("offer not found")
    items = [d for d in DB.disputes.values() if d["offer_id"] == offer_id]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda d: d["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    from routes.disputes import _dispute_view
    return success([_dispute_view(d) for d in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/cash-offers/<offer_id>/inspect", methods=["POST"])
def inspect_cash_offer(offer_id):
    require_roles("DealerPartner")
    o = DB.cash_offers.get(offer_id)
    if o is None:
        raise not_found("offer not found")
    body = request.get_json(silent=True) or {}
    inspected_tier = body.get("inspected_condition_tier")

    # Priority 5: state — must be QUOTED
    if o["status"] != "QUOTED":
        raise invalid_state("offer not in QUOTED")
    # Priority 10: not expired
    if CLOCK.now() > o["expires_at_dt"]:
        raise offer_expired("offer expired")
    # Priority 14: tier valid
    if inspected_tier not in TIERS:
        raise invalid_input("inspected_condition_tier invalid")

    edition = DB.editions.get(o["edition_id"])
    series = DB.series.get(edition["series_id"]) if edition else None
    config = DB.configurations.get(series["configuration_id"]) if series else None

    raw = compute_offer_amount(edition, config, o["mileage"], o["age_years"],
                               inspected_tier, o["option_ids"])
    final = apply_inspect_cap(raw, o["offer_amount_cents"])
    o["final_amount_cents"] = final
    o["status"] = "INSPECTED"
    touch(o)
    return success(_offer_view(o), 200)


@bp.route("/cash-offers/<offer_id>/redeem", methods=["POST"])
def redeem_cash_offer(offer_id):
    require_roles("DealerPartner")
    o = DB.cash_offers.get(offer_id)
    if o is None:
        raise not_found("offer not found")
    # Priority 5: state — must be INSPECTED, and funding source must be ACTIVE
    if o["status"] != "INSPECTED":
        raise invalid_state("offer not in INSPECTED")
    funding = DB.sources.get(o["funding_dealer_id"])
    if funding is None:
        raise not_found("funding source not found")
    if funding["status"] != "ACTIVE":
        raise invalid_state("funding source not ACTIVE")
    # Priority 10: not expired
    if CLOCK.now() > o["expires_at_dt"]:
        raise offer_expired("offer expired")
    o["status"] = "REDEEMED"
    o["redeemed_at"] = to_iso8601_ms(CLOCK.now())
    touch(o)
    return success(_offer_view(o), 200)


@bp.route("/cash-offers/<offer_id>/void", methods=["POST"])
def void_cash_offer(offer_id):
    require_roles("DealerPartner", "ValuationAdmin")
    o = DB.cash_offers.get(offer_id)
    if o is None:
        raise not_found("offer not found")
    if o["status"] != "QUOTED":
        raise invalid_state("offer not in QUOTED")
    o["status"] = "VOID"
    touch(o)
    return success(_offer_view(o), 200)
