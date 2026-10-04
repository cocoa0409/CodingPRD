"""ValuationEdition endpoints (create/list/get/publish/withdraw)."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import DB, CLOCK
from errors import (
    not_found, invalid_input, invalid_state, low_confidence,
    cadence_violation, edition_has_open_offers, license_inactive,
    use_not_permitted, quota_exceeded, insufficient_data,
)
from middleware import require_roles
from response import success
from services.calculations import (
    parse_iso8601, compute_reference_price, compute_tier_values,
    CONFIDENCE_GATE, to_iso8601_ms,
)
from services.entity import stamp_new, stamp_new_log, touch, new_uuid


bp = Blueprint("editions", __name__)

ALL_ROLES = ("ValuationAdmin", "DataOps", "DealerPartner", "Consumer", "Licensee")


def _edition_view(e):
    return {
        "id": e["id"],
        "series_id": e["series_id"],
        "effective_at": e["effective_at"],
        "reference_price_cents": e["reference_price_cents"],
        "trade_in_cents": e["trade_in_cents"],
        "private_party_cents": e["private_party_cents"],
        "retail_cents": e["retail_cents"],
        "status": e["status"],
        "published_at": e.get("published_at"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _record_license_event(agreement_id: str, event_type: str):
    ev = stamp_new_log({
        "agreement_id": agreement_id,
        "event_type": event_type,
        "occurred_at": to_iso8601_ms(CLOCK.now()),
    })
    DB.license_events[ev["id"]] = ev
    return ev


def _check_license_gate(agreement_id: str, purpose: str, allowed_uses_for_purpose):
    """Run the three license gates in priority order: ACTIVE -> permitted_uses -> quota.
    Raises the appropriate ApiError. Returns the agreement on success."""
    agreement = DB.license_agreements.get(agreement_id)
    if agreement is None:
        raise not_found("license agreement not found")
    if agreement["status"] != "ACTIVE":
        raise license_inactive("license agreement not ACTIVE")
    if purpose not in allowed_uses_for_purpose:
        raise use_not_permitted(f"purpose {purpose} not permitted")
    for use in allowed_uses_for_purpose:
        if purpose == use and use not in agreement["permitted_uses"]:
            raise use_not_permitted(f"use {use} not permitted")
    # Quota check: current calendar month (logical clock) count vs monthly_event_quota
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


@bp.route("/valuation-editions", methods=["POST"])
def create_edition():
    require_roles("ValuationAdmin")
    body = request.get_json(silent=True) or {}
    series_id = body.get("series_id")
    effective_at = body.get("effective_at")

    series = DB.series.get(series_id) if isinstance(series_id, str) else None
    if series is None:
        raise not_found("series not found")

    if not isinstance(effective_at, str):
        raise invalid_input("effective_at is required")
    try:
        eff_dt = parse_iso8601(effective_at)
    except Exception:
        raise invalid_input("effective_at must be ISO 8601")

    # effective_at uniqueness among PENDING/PUBLISHED editions of this series
    for other in DB.editions.values():
        if (other["series_id"] == series_id
                and other["status"] in ("PENDING", "PUBLISHED")
                and other["effective_at_dt"] == eff_dt):
            raise invalid_input("effective_at already used in this series")

    ref = compute_reference_price(series["configuration_id"],
                                  series["region_id"], eff_dt)
    if ref is None:
        raise insufficient_data("no accepted items in trailing window")

    ti, pp, rt = compute_tier_values(ref)
    e = stamp_new({
        "series_id": series_id,
        "effective_at": effective_at,
        "effective_at_dt": eff_dt,
        "reference_price_cents": ref,
        "trade_in_cents": ti,
        "private_party_cents": pp,
        "retail_cents": rt,
        "status": "PENDING",
        "published_at": None,
    })
    DB.editions[e["id"]] = e
    return success(_edition_view(e), 201)


@bp.route("/valuation-editions", methods=["GET"])
def list_editions():
    require_roles(*ALL_ROLES)
    items = list(DB.editions.values())
    series_id = request.args.get("series_id")
    status_filter = request.args.get("status")
    if series_id:
        items = [e for e in items if e["series_id"] == series_id]
    if status_filter:
        items = [e for e in items if e["status"] == status_filter]
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise invalid_input("limit/offset must be integers")
    if limit < 1 or limit > 100 or offset < 0:
        raise invalid_input("pagination out of range")
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success([_edition_view(e) for e in page], 200,
                   response_type="array",
                   limit=limit, offset=offset, total_count=total,
                   has_more=(offset + limit) < total)


@bp.route("/valuation-editions/<edition_id>", methods=["GET"])
def get_edition(edition_id):
    role, user_id = require_roles(*ALL_ROLES)
    e = DB.editions.get(edition_id)
    if e is None:
        raise not_found("edition not found")
    if role == "Licensee":
        # Three gates in order: ACTIVE -> permitted -> quota
        purpose = request.args.get("purpose", "DISPLAY")
        # Allowed purposes for edition reads: SETTLEMENT or DISPLAY
        if purpose not in ("SETTLEMENT", "DISPLAY"):
            raise use_not_permitted("purpose must be SETTLEMENT or DISPLAY")
        agreement = _check_license_gate(user_id, purpose, (purpose,))
        _record_license_event(agreement["id"], "EDITION_READ")
    return success(_edition_view(e), 200)


@bp.route("/valuation-editions/<edition_id>/publish", methods=["POST"])
def publish_edition(edition_id):
    require_roles("ValuationAdmin")
    e = DB.editions.get(edition_id)
    if e is None:
        raise not_found("edition not found")
    if e["status"] != "PENDING":
        raise invalid_state("edition not in PENDING")
    series = DB.series.get(e["series_id"])
    if series is None:
        raise not_found("series not found")
    if series["status"] != "ACTIVE":
        raise invalid_state("series not ACTIVE")

    # Confidence gate (priority 8)
    if series.get("confidence_score", 0.0) < float(CONFIDENCE_GATE):
        raise low_confidence("series confidence below 0.25")

    # Cadence (priority 9)
    # effective_at >= series.effective_from
    if e["effective_at_dt"] < series["effective_from_dt"]:
        raise cadence_violation("effective_at earlier than series effective_from")
    # First published edition must equal effective_from
    published_others = [o for o in DB.editions.values()
                        if o["series_id"] == series["id"]
                        and o["status"] == "PUBLISHED"]
    if not published_others:
        # first publication must satisfy effective_at == series.effective_from
        if e["effective_at_dt"] != series["effective_from_dt"]:
            raise cadence_violation("first edition must equal series effective_from")
    else:
        # no other PUBLISHED edition within 7 days
        seven_days = timedelta(days=7)
        for o in published_others:
            delta = abs(e["effective_at_dt"] - o["effective_at_dt"])
            if delta < seven_days:
                raise cadence_violation("another PUBLISHED edition within 7 days")

    # Dispute guard: no ACTIVE or PENDING dispute references an offer built on this edition.
    # Dispute statuses are OPEN / RESOLVED_UPHELD / RESOLVED_ADJUSTED / WITHDRAWN.
    # Only OPEN blocks.
    for offer in DB.cash_offers.values():
        if offer["edition_id"] != e["id"]:
            continue
        for dispute in DB.disputes.values():
            if dispute["offer_id"] == offer["id"] and dispute["status"] == "OPEN":
                raise invalid_state("an OPEN dispute references this edition's offer")

    e["status"] = "PUBLISHED"
    e["published_at"] = to_iso8601_ms(CLOCK.now())
    touch(e)
    return success(_edition_view(e), 200)


@bp.route("/valuation-editions/<edition_id>/withdraw", methods=["POST"])
def withdraw_edition(edition_id):
    require_roles("ValuationAdmin")
    e = DB.editions.get(edition_id)
    if e is None:
        raise not_found("edition not found")
    if e["status"] == "PENDING":
        e["status"] = "WITHDRAWN"
        touch(e)
        return success(_edition_view(e), 200)
    if e["status"] != "PUBLISHED":
        raise invalid_state("edition not in PUBLISHED or PENDING")

    # Open-offer guard: any offer in non-terminal state blocks withdrawal.
    # PRD says "non-terminal state (QUOTED or INSPECTED)". QUOTED cascade-voids;
    # the guard binds only on INSPECTED (and any other non-terminal) per the
    # corner design: with QUOTED the cascade voids them.
    blocking = []
    quoted = []
    for offer in DB.cash_offers.values():
        if offer["edition_id"] != e["id"]:
            continue
        if offer["status"] == "INSPECTED":
            blocking.append(offer)
        elif offer["status"] == "QUOTED":
            quoted.append(offer)
    if blocking:
        raise edition_has_open_offers("edition has INSPECTED offers")

    # Cascade: QUOTED -> VOID
    for offer in quoted:
        offer["status"] = "VOID"
        touch(offer)

    e["status"] = "WITHDRAWN"
    touch(e)
    return success(_edition_view(e), 200)
