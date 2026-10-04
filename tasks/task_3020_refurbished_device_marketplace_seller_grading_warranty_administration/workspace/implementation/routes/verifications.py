"""Mystery-shop verification routes."""

from flask import request

from db import store, public, touch, iso, stamp_new, parse_iso
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, pagination, paginate,
    range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import exposure as expo
from services import sellers as seller_svc
from vocab import COSMETIC_GRADES, VERIFICATION_RATIONALES


def register(app):
    @app.post("/v1/mystery-shop-verifications")
    def create_verification():
        guard("POST", "/v1/mystery-shop-verifications", ["ComplianceReviewer"])
        data = body()
        seller = store.sellers.get(as_str(required(data, "seller_id"), "seller_id"))
        if seller is None:
            raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        listing = store.listings.get(as_str(required(data, "listing_id"), "listing_id"))
        if listing is None:
            raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        rationale = check_enum(as_str(required(data, "rationale_code"), "rationale_code"),
                               VERIFICATION_RATIONALES, "rationale_code")
        ordered = check_enum(as_str(required(data, "ordered_cosmetic_grade"),
                                    "ordered_cosmetic_grade"), COSMETIC_GRADES,
                             "ordered_cosmetic_grade")

        start = parse_iso(as_str(required(data, "verification_start"), "verification_start"))
        end = parse_iso(as_str(required(data, "verification_end"), "verification_end"))
        if start is None or end is None:
            raise fail("ERR_INVALID_REQUEST", "verification_start and verification_end must be ISO 8601 instants.")
        if not end > start:
            raise fail("ERR_INVALID_REQUEST", "verification_end must be strictly later than verification_start.")

        # Priority 16: strict overlap against another still-OPEN window.
        for other in store.verifications.values():
            if other["listing_id"] != listing["id"]:
                continue
            if other["verification_state"] != "OPEN":
                continue
            if start < other["_end_dt"] and end > other["_start_dt"]:
                raise fail("ERR_VERIFICATION_OVERLAP")

        payload = {
            "seller_id": seller["id"],
            "listing_id": listing["id"],
            "verification_state": "OPEN",
            "rationale_code": rationale,
            "ordered_cosmetic_grade": ordered,
            "received_cosmetic_grade": None,
            "measured_battery_health_pct": None,
            "value_at_risk": 0,
            "reserved_units_delta": 0,
            "exposure_floor_delta_cents": 0,
            "verification_start": iso(start),
            "verification_end": iso(end),
            "verifier_user_id": None,
            "_start_dt": start,
            "_end_dt": end,
        }
        stamp_new("verifications", payload, store.clock)
        store.verifications[payload["id"]] = payload
        return ok(public(payload), 201)

    @app.get("/v1/mystery-shop-verifications")
    def list_verifications():
        guard("GET", "/v1/mystery-shop-verifications", ["ComplianceReviewer", "PlatformAdmin"])
        limit, offset = pagination()
        rows = created_asc(list(store.verifications.values()))
        rows = filter_eq(rows, {
            "seller_id": request.args.get("seller_id"),
            "listing_id": request.args.get("listing_id"),
            "verification_state": request.args.get("verification_state"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/mystery-shop-verifications/<verification_id>")
    def read_verification(verification_id):
        guard("GET", "/v1/mystery-shop-verifications/{id}", ["ComplianceReviewer", "PlatformAdmin"])
        return ok(public(_verification_or_404(verification_id)))

    @app.post("/v1/mystery-shop-verifications/<verification_id>/disclose")
    def disclose(verification_id):
        guard("POST", "/v1/mystery-shop-verifications/{id}/disclose", ["ComplianceReviewer"])
        verification = _verification_or_404(verification_id)
        data = body()
        received = check_enum(as_str(required(data, "received_cosmetic_grade"),
                                     "received_cosmetic_grade"), COSMETIC_GRADES,
                              "received_cosmetic_grade")
        health = range_int(required(data, "measured_battery_health_pct"),
                           "measured_battery_health_pct", low=1, high=100)
        verifier = as_str(required(data, "verifier_user_id"), "verifier_user_id")

        if verification["verification_state"] != "OPEN":
            raise fail("ERR_INVALID_STATE")

        # Disclosure is not idempotent.
        for other in store.verifications.values():
            if other["id"] == verification["id"]:
                continue
            if other["listing_id"] == verification["listing_id"] and \
                    other["verification_state"] == "DISCLOSED":
                raise fail("ERR_VERIFICATION_ALREADY_DISCLOSED")

        clock = store.clock
        listing = store.listings.get(verification["listing_id"])
        verification["verification_state"] = "DISCLOSED"
        verification["received_cosmetic_grade"] = received
        verification["measured_battery_health_pct"] = health
        verification["verifier_user_id"] = verifier
        verification["value_at_risk"] = 1
        verification["reserved_units_delta"] = 1
        verification["exposure_floor_delta_cents"] = expo.CONSTRAINT_VIOLATION_UNIT_CENTS
        touch(verification, clock)

        if listing is not None:
            listing["mystery_shop_disclosed"] = True
            listing["active_reservation_days"] = listing.get("active_reservation_days", 0) + 1
            touch(listing, clock)

        seller = store.sellers.get(verification["seller_id"])
        if seller is not None:
            seller_svc.remap_tier_from_open_sections(seller, clock)
            expo.recompute_exposure_floor(seller["id"], clock)
        return ok(public(verification))

    @app.post("/v1/mystery-shop-verifications/<verification_id>/void")
    def void(verification_id):
        guard("POST", "/v1/mystery-shop-verifications/{id}/void", ["ComplianceReviewer"])
        verification = _verification_or_404(verification_id)
        body()
        if verification["verification_state"] != "OPEN":
            raise fail("ERR_INVALID_STATE")
        verification["verification_state"] = "VOIDED"
        touch(verification, store.clock)
        return ok(public(verification))


def _verification_or_404(verification_id):
    row = store.verifications.get(verification_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row