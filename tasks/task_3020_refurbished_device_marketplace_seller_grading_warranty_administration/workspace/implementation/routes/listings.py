"""Device listing routes."""

from flask import request

from db import store, public
from errors import fail
from requtils import (
    as_int, as_str, body, check_enum, created_asc, filter_eq, hex64, opt_str,
    pagination, paginate, range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import listings as listing_svc
from services import reservations as resv
from middleware import ensure_owner
from vocab import (
    CARRIER_LOCK_STATUSES,
    COSMETIC_GRADES,
    DELIST_REASON_CODES,
    FUNCTIONAL_GRADES,
    LISTING_STATES,
    PART_PROVENANCES,
)

READERS = ["PlatformAdmin", "ComplianceReviewer", "ClaimAdjudicator", "Seller"]


def register(app):
    @app.post("/v1/sellers/<seller_id>/listings")
    def create_listing(seller_id):
        principal = guard("POST", "/v1/sellers/{id}/listings", ["Seller"])
        seller = _seller_or_404(seller_id)
        ensure_owner(principal, seller_id)
        data = _listing_body(body(), require_all=True)
        listing = listing_svc.create_listing(seller, data, store.clock)
        return ok(public(listing), 201)

    @app.get("/v1/listings")
    def list_listings():
        principal = guard("GET", "/v1/listings", READERS)
        limit, offset = pagination()
        rows = created_asc(list(store.listings.values()))
        if principal.role == "Seller":
            rows = [r for r in rows if r.get("seller_id") == principal.user_id]
        rows = filter_eq(rows, {
            "servicing_seller_id": request.args.get("servicing_seller_id"),
            "listing_state": request.args.get("listing_state"),
            "model_code": request.args.get("model_code"),
            "servicing_reservation_id": request.args.get("servicing_reservation_id"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/listings/<listing_id>")
    def read_listing(listing_id):
        guard("GET", "/v1/listings/{id}", READERS)
        listing = _listing_or_404(listing_id)
        return ok(public(listing))

    @app.post("/v1/listings/<listing_id>/submit")
    def resubmit_listing(listing_id):
        principal = guard("POST", "/v1/listings/{id}/submit", ["Seller"])
        listing = _listing_or_404(listing_id)
        ensure_owner(principal, listing.get("seller_id"))
        seller = _seller_or_404(listing.get("seller_id"))
        data = body()
        expected = data.get("expected_seller_version")
        if expected is None:
            raise fail("ERR_INVALID_REQUEST", "expected_seller_version is required.")
        merged = _merged_listing_body(listing, data)
        listing_svc.resubmit_listing(listing, seller, merged, expected, store.clock)
        return ok(public(listing))

    @app.post("/v1/listings/<listing_id>/review")
    def review_listing(listing_id):
        principal = guard("POST", "/v1/listings/{id}/review", ["ComplianceReviewer"])
        listing = _listing_or_404(listing_id)
        data = body()
        decision = as_str(required(data, "decision"), "decision")
        check_enum(decision, ["APPROVED", "REJECTED"], "decision")
        reviewer = as_str(required(data, "reviewer_user_id"), "reviewer_user_id")
        _sod_listing_review(listing, reviewer)
        listing_svc.review_listing(listing, decision, store.clock)
        return ok(public(listing))

    @app.post("/v1/listings/<listing_id>/suspend")
    def delist_listing(listing_id):
        guard("POST", "/v1/listings/{id}/suspend", ["ComplianceReviewer"])
        listing = _listing_or_404(listing_id)
        data = body()
        reason = as_str(required(data, "reason_code"), "reason_code")
        check_enum(reason, DELIST_REASON_CODES, "reason_code")
        _price_screen(listing)
        listing_svc.delist_listing(listing, reason, store.clock)
        return ok(public(listing))

    @app.post("/v1/listings/<listing_id>/withdraw")
    def withdraw_listing(listing_id):
        principal = guard("POST", "/v1/listings/{id}/withdraw", ["Seller"])
        listing = _listing_or_404(listing_id)
        ensure_owner(principal, listing.get("seller_id"))
        listing_svc.withdraw_listing(listing, store.clock)
        return ok(public(listing))

    @app.get("/v1/listings/<listing_id>/buy-box")
    def buy_box(listing_id):
        guard("GET", "/v1/listings/{id}/buy-box",
              ["PlatformAdmin", "Seller", "ComplianceReviewer"])
        listing = _listing_or_404(listing_id)
        # Priority 25: the selector must find a servicing reservation.
        resv.select_servicing_reservation(listing)
        return ok(listing_svc.buy_box(listing, store.clock))

    @app.get("/v1/listings/<listing_id>/warranty-reservations")
    def list_listing_reservations(listing_id):
        guard("GET", "/v1/listings/{id}/warranty-reservations",
              ["PlatformAdmin", "ClaimAdjudicator", "Seller", "ComplianceReviewer"])
        listing = _listing_or_404(listing_id)
        limit, offset = pagination()
        rows = created_asc([r for r in store.reservations.values() if r["listing_id"] == listing["id"]])
        rows = filter_eq(rows, {"warranty_state": request.args.get("warranty_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.post("/v1/listings/<listing_id>/warranty-reservations")
    def create_reservation(listing_id):
        guard("POST", "/v1/listings/{id}/warranty-reservations",
              ["ComplianceReviewer", "ClaimAdjudicator"])
        listing = _listing_or_404(listing_id)
        data = body()
        activated_raw = as_str(required(data, "activated_on"), "activated_on")
        from db import parse_iso
        activated = parse_iso(activated_raw)
        if activated is None:
            raise fail("ERR_INVALID_REQUEST", "activated_on must be an ISO 8601 instant.")
        if activated > store.clock:
            raise fail("ERR_INVALID_REQUEST",
                       "activated_on must not be later than the logical clock.")
        period = range_int(required(data, "warranty_period_days"), "warranty_period_days", low=1)
        units = range_int(required(data, "reserved_units"), "reserved_units", low=0)
        per_day = range_int(required(data, "unit_reserve_per_day_cents"),
                            "unit_reserve_per_day_cents", low=0)
        payload = {
            "_activated_on": activated,
            "warranty_period_days": period,
            "reserved_units": units,
            "unit_reserve_per_day_cents": per_day,
            "originated_claim_id": data.get("originated_claim_id"),
        }
        reservation = listing_svc.create_reservation(listing, payload, store.clock)
        return ok(public(reservation), 201)

    @app.get("/v1/listings/<listing_id>/warranty-claims")
    def list_listing_claims(listing_id):
        guard("GET", "/v1/listings/{id}/warranty-claims",
              ["PlatformAdmin", "ClaimAdjudicator", "Seller", "Consumer"])
        listing = _listing_or_404(listing_id)
        limit, offset = pagination()
        rows = created_asc([c for c in store.claims.values() if c["listing_id"] == listing["id"]])
        rows = filter_eq(rows, {
            "routed_seller_id": request.args.get("routed_seller_id"),
            "claim_state": request.args.get("claim_state"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/listings/<listing_id>/mystery-shop-verifications")
    def list_listing_verifications(listing_id):
        guard("GET", "/v1/listings/{id}/mystery-shop-verifications",
              ["ComplianceReviewer", "PlatformAdmin"])
        listing = _listing_or_404(listing_id)
        limit, offset = pagination()
        rows = created_asc([v for v in store.verifications.values() if v["listing_id"] == listing["id"]])
        rows = filter_eq(rows, {"verification_state": request.args.get("verification_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


# ------------------------------------------------------------------ helpers
def _listing_or_404(listing_id):
    listing = store.listings.get(listing_id)
    if listing is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return listing


def _seller_or_404(seller_id):
    seller = store.sellers.get(seller_id)
    if seller is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return seller


def _listing_body(data, require_all):
    out = {}
    out["model_code"] = as_str(required(data, "model_code"), "model_code")
    imei = as_str(required(data, "imei"), "imei")
    from requtils import IMEI15
    if not IMEI15.match(imei):
        raise fail("ERR_INVALID_REQUEST", "imei must be exactly fifteen digits.")
    out["imei"] = imei
    out["cosmetic_grade"] = check_enum(
        as_str(required(data, "cosmetic_grade"), "cosmetic_grade"), COSMETIC_GRADES, "cosmetic_grade")
    out["functional_grade"] = check_enum(
        as_str(required(data, "functional_grade"), "functional_grade"),
        FUNCTIONAL_GRADES, "functional_grade")
    out["battery_health_pct"] = range_int(
        required(data, "battery_health_pct"), "battery_health_pct", low=1, high=100)
    out["carrier_lock_status"] = check_enum(
        as_str(required(data, "carrier_lock_status"), "carrier_lock_status"),
        CARRIER_LOCK_STATUSES, "carrier_lock_status")
    out["part_provenance"] = check_enum(
        as_str(required(data, "part_provenance"), "part_provenance"),
        PART_PROVENANCES, "part_provenance")
    digest = opt_str(data, "provenance_doc_digest")
    out["provenance_doc_digest"] = digest
    out["list_price_cents"] = range_int(
        required(data, "list_price_cents"), "list_price_cents", low=0)
    return out


def _merged_listing_body(listing, data):
    """Re-submission re-runs the ladder over the listing's current attributes,
    overridden by any field the client re-supplies.
    """
    merged = {
        "model_code": listing["model_code"],
        "imei": listing["imei"],
        "cosmetic_grade": listing["cosmetic_grade"],
        "functional_grade": listing["functional_grade"],
        "battery_health_pct": listing["battery_health_pct"],
        "carrier_lock_status": listing["carrier_lock_status"],
        "part_provenance": listing["part_provenance"],
        "provenance_doc_digest": listing.get("provenance_doc_digest"),
        "list_price_cents": listing["list_price_cents"],
    }
    for key in merged:
        if key in data and data[key] is not None:
            merged[key] = data[key]
    return merged


def _sod_listing_review(listing, reviewer_user_id):
    """§2.9: the auditor who recorded the seller's audit outcome may not review
    that seller's listing.
    """
    seller_id = listing.get("serving_seller_id")
    for record in store.audit_records.values():
        if record.get("seller_id") != seller_id:
            continue
        if record.get("auditor_user_id") and record["auditor_user_id"] == reviewer_user_id:
            raise fail("ERR_SOD_VIOLATION")


def _price_screen(listing):
    """Priority 9 price-pattern screen, re-applied against a live listing."""
    catalog_floor = store.model_floor(listing["model_code"])
    if catalog_floor is None or catalog_floor <= 0:
        return
    from vocab import PRICE_DEVIATION_PCT
    if listing["list_price_cents"] < catalog_floor * (1 - PRICE_DEVIATION_PCT):
        raise fail("ERR_COUNTERFEIT_PRICE_SIGNAL")