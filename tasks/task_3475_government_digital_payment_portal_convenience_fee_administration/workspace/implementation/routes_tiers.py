"""Absorbed-model contract pricing tiers (PRD section 3.2): closed-interval
volume bands per agency and effective month."""
from flask import Blueprint, request

import clock
import envelope
import helpers
import serialize
import store
from auth import caller
from errors import raise_err
from validate import as_int, as_month, as_str, body, req_field

bp = Blueprint("tiers", __name__)


@bp.route("/portal/pricing-tiers", methods=["POST"])
def create_tier():
    caller({"PlatformAdmin"})
    data = body()
    agency_id = as_str(req_field(data, "agency_id"), "agency_id")
    volume_min = as_int(req_field(data, "volume_min_cents"), "volume_min_cents")
    volume_max = data.get("volume_max_cents")  # null = unbounded top band
    if volume_max is not None:
        volume_max = as_int(volume_max, "volume_max_cents")
    rate_bp = as_int(req_field(data, "rate_bp"), "rate_bp")
    per_txn = as_int(req_field(data, "per_txn_cents"), "per_txn_cents")
    month = as_month(req_field(data, "effective_month"), "effective_month")
    # priority 3: body foreign key
    helpers.get_agency(agency_id)
    # priority 8: closed-interval bands of the same agency and month must
    # not overlap; shared boundary cents count as overlap
    new_lo = volume_min
    new_hi = volume_max if volume_max is not None else float("inf")
    for t in store.tiers.values():
        if t["agency_id"] != agency_id or t["effective_month"] != month:
            continue
        lo = t["volume_min_cents"]
        hi = t["volume_max_cents"] if t["volume_max_cents"] is not None else float("inf")
        if new_lo <= hi and lo <= new_hi:
            raise_err(
                "ERR_TIER_BAND_OVERLAP",
                409,
                "Pricing band overlaps another band of the same agency and month",
            )
    rec = {
        "id": store.new_id(),
        "agency_id": agency_id,
        "volume_min_cents": volume_min,
        "volume_max_cents": volume_max,
        "rate_bp": rate_bp,
        "per_txn_cents": per_txn,
        "effective_month": month,
        "created_at": clock.now(),
        "created_seq": store.next_seq(),
    }
    store.tiers[rec["id"]] = rec
    return envelope.obj(serialize.tier(rec), 201)


@bp.route("/portal/agencies/<rid>/pricing-tiers", methods=["GET"])
def list_tiers(rid):
    caller({"PlatformAdmin", "AgencyAdmin", "TreasuryOfficer"})
    helpers.get_agency(rid)
    month = request.args.get("effective_month")
    items = [t for t in store.tiers.values() if t["agency_id"] == rid]
    if month is not None:
        items = [t for t in items if t["effective_month"] == month]
    items.sort(key=lambda t: (t["created_at"], t["created_seq"]))
    return envelope.page([serialize.tier(t) for t in items], request.args)
