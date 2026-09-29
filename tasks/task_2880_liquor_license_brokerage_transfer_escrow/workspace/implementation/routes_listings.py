"""Listings, the frozen market valuation and the preview (PRD 3.3)."""

from flask import Blueprint

import calc
import domain
from authz import (ALL_ROLES, BROKER, PLATFORM_ADMIN, REGULATOR, authenticate,
                   brokerage_or_404, county_or_404, license_or_404, listing_or_404,
                   require_brokerage)
from envelope import apply_filters, created, ok, ok_list, pagination_args, paginate
from errors import ApiError
from store import bump, db, make_record, now, public, public_list, sorted_by_created
from validation import F, json_body, validate

bp = Blueprint("listings", __name__)

VALUATION_BASES = ("COMPARABLE_SALES", "INCOME_MULTIPLE")
LISTING_TERMINAL = ("WITHDRAWN", "SOLD")


def county_snapshot(county):
    """A non-persisted recomputation of the county's counters, for live reads."""
    snapshot = dict(county)
    calc.county_quota_position(snapshot)
    return snapshot


@bp.route("/listings", methods=["POST"])
def create_listing():
    authenticate((BROKER,))
    data = validate(json_body(), [
        F("license_id", "string"),
        F("brokerage_id", "string"),
        F("ask_price_cents", "integer", minimum=100000),
    ])
    lic = license_or_404(data["license_id"])
    brokerage = brokerage_or_404(data["brokerage_id"])
    listing = make_record({
        "license_id": lic["id"],
        "brokerage_id": brokerage["id"],
        "ask_price_cents": data["ask_price_cents"],
        "status": "DRAFT",
        "valuation_basis": None,
        "market_price_cents": None,
        "scarcity_bps_at_activation": None,
        "comp_count_at_activation": None,
        "open_offer_count": 0,
        "activated_at": None,
    })
    db.listings[listing["id"]] = listing
    return created(public(listing))


@bp.route("/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    authenticate(ALL_ROLES)
    return ok(public(listing_or_404(listing_id)))


@bp.route("/listings", methods=["GET"])
def list_listings():
    authenticate(ALL_ROLES)
    limit, offset = pagination_args()
    rows = apply_filters(db.listings.values(), {
        "license_id": "license_id",
        "brokerage_id": "brokerage_id",
        "status": "status",
    })
    rows = sorted_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.route("/listings/<listing_id>/valuation-preview", methods=["GET"])
def valuation_preview(listing_id):
    authenticate((PLATFORM_ADMIN, BROKER, REGULATOR))
    listing = listing_or_404(listing_id)
    lic = license_or_404(listing["license_id"])
    county = county_or_404(lic["county_id"])
    snapshot = county_snapshot(county)
    result = calc.listing_market_valuation(lic, snapshot, county["default_valuation_basis"])
    return ok({
        "listing_id": listing["id"],
        "license_id": lic["id"],
        "default_valuation_basis": county["default_valuation_basis"],
        "comp_count": result["comp_count"],
        "comp_median_cents": result["comp_median_cents"],
        "scarcity_bps": result["scarcity_bps"],
        "comparable_sales_price_cents": result["comparable_sales_price_cents"],
        "income_multiple_price_cents": result["income_multiple_price_cents"],
        "divergence_cents": result["divergence_cents"],
    })


@bp.route("/listings/<listing_id>/activate", methods=["POST"])
def activate_listing(listing_id):
    user_id, role = authenticate((BROKER,))
    data = validate(json_body(required=False), [
        F("valuation_basis", "enum", required=False, default=None, values=VALUATION_BASES),
    ])
    listing = listing_or_404(listing_id)
    require_brokerage(user_id, role, listing["brokerage_id"])
    # 10: state precondition on the target record
    if listing["status"] not in ("DRAFT",) and listing["status"] not in LISTING_TERMINAL:
        raise ApiError("ERR_INVALID_LISTING_STATE",
                       "Only a DRAFT listing can be activated.")
    # 11: terminal record
    if listing["status"] in LISTING_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The listing is already in a terminal state.")
    lic = license_or_404(listing["license_id"])
    county = county_or_404(lic["county_id"])
    if lic["status"] not in ("ACTIVE", "SAFEKEEPING"):
        raise ApiError("ERR_INVALID_LICENSE_STATE",
                       "The license must be ACTIVE or SAFEKEEPING to be listed.")
    for other in db.listings.values():
        if other["id"] == listing["id"]:
            continue
        if other["license_id"] == listing["license_id"] and other["status"] in ("ACTIVE", "UNDER_CONTRACT"):
            raise ApiError("ERR_INVALID_LISTING_STATE",
                           "Another listing on this license is already live.")
    seller = db.sellers.get(lic["owner_seller_id"])
    if seller is None or seller["tax_clearance_status"] != "CLEARED":
        raise ApiError("ERR_SELLER_TAX_CLEARANCE_MISSING",
                       "The selling licensee's tax clearance is not CLEARED.")
    if domain.pending_filing_on(lic["id"]) is not None:
        raise ApiError("ERR_SAFEKEEPING_FILING_PENDING",
                       "A safekeeping filing on this license is awaiting decision.")
    basis = data["valuation_basis"] or county["default_valuation_basis"]
    snapshot = county_snapshot(county)
    result = calc.listing_market_valuation(lic, snapshot, basis)
    listing["status"] = "ACTIVE"
    listing["valuation_basis"] = basis
    listing["scarcity_bps_at_activation"] = result["scarcity_bps"]
    listing["market_price_cents"] = result["market_price_cents"]
    listing["comp_count_at_activation"] = result["comp_count"]
    listing["activated_at"] = now()
    bump(listing)
    return ok(public(listing))


@bp.route("/listings/<listing_id>/withdraw", methods=["POST"])
def withdraw_listing(listing_id):
    user_id, role = authenticate((BROKER,))
    validate(json_body(required=False), [F("reason", "string", required=False, default=None)])
    listing = listing_or_404(listing_id)
    require_brokerage(user_id, role, listing["brokerage_id"])
    if listing["status"] not in ("DRAFT", "ACTIVE") and listing["status"] not in LISTING_TERMINAL:
        raise ApiError("ERR_INVALID_LISTING_STATE",
                       "Only a DRAFT or ACTIVE listing can be withdrawn.")
    if listing["status"] in LISTING_TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL", "The listing is already in a terminal state.")
    if listing["open_offer_count"] > 0:
        raise ApiError("ERR_LISTING_HAS_OPEN_OFFERS",
                       "Outstanding draft offers must be terminated before withdrawal.")
    listing["status"] = "WITHDRAWN"
    bump(listing)
    return ok(public(listing))
