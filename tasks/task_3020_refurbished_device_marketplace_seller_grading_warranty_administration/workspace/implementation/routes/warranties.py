"""Warranty reservation and buyer claim routes."""

from flask import request

from db import store, public, touch
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, pagination, paginate,
    range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import claims as claim_svc
from services import exposure as expo
from services import reservations as resv
from services import sellers as seller_svc
from vocab import CLAIM_REASON_CODES, RESOLUTION_TYPES, RETURN_CARRIERS, WARRANTY_STATES


def register(app):
    # ------------------------------------------------------- reservations
    @app.get("/v1/warranty-reservations")
    def list_reservations():
        guard("GET", "/v1/warranty-reservations",
              ["PlatformAdmin", "ClaimAdjudicator", "Seller"])
        limit, offset = pagination()
        rows = created_asc(list(store.reservations.values()))
        rows = filter_eq(rows, {
            "warranty_state": request.args.get("warranty_state"),
            "originated_claim_id": request.args.get("originated_claim_id"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/warranty-reservations/<reservation_id>")
    def read_reservation(reservation_id):
        guard("GET", "/v1/warranty-reservations/{id}",
              ["PlatformAdmin", "ClaimAdjudicator", "Seller"])
        return ok(public(_reservation_or_404(reservation_id)))

    @app.post("/v1/warranty-reservations/<reservation_id>/remediate")
    def remediate(reservation_id):
        guard("POST", "/v1/warranty-reservations/{id}/remediate", ["ClaimAdjudicator"])
        reservation = _reservation_or_404(reservation_id)
        data = body()
        state = reservation["warranty_state"]
        if state not in ("REPAIRING", "REPLACED"):
            raise fail("ERR_INVALID_STATE")

        if "expected_reservation_version" in data and \
                data["expected_reservation_version"] is not None:
            if data["expected_reservation_version"] != reservation["version"]:
                raise fail("ERR_STALE_VERSION")

        if state == "REPAIRING":
            if "repair_estimate_cents" not in data or data["repair_estimate_cents"] is None:
                raise fail("ERR_INVALID_REQUEST", "repair_estimate_cents is required.")
            range_int(data["repair_estimate_cents"], "repair_estimate_cents", low=0)
        else:
            if "replacement_listing_id" not in data or data["replacement_listing_id"] is None:
                raise fail("ERR_INVALID_REQUEST", "replacement_listing_id is required.")
            if data["replacement_listing_id"] not in store.listings:
                raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")

        listing = store.listings.get(reservation["listing_id"])
        clock = store.clock
        reservation["warranty_state"] = "ACTIVE"
        touch(reservation, clock)
        if listing is not None:
            listing["active_reservation_days"] = 0
            touch(listing, clock)

        seller_id = listing.get("servicing_seller_id") if listing else None
        if seller_id in store.sellers:
            seller = store.sellers[seller_id]
            seller_svc.remap_tier_from_open_sections(seller, clock)
            expo.recompute_exposure_floor(seller_id, clock)
        return ok(public(reservation))

    # ------------------------------------------------------------- claims
    @app.post("/v1/sellers/<seller_id>/warranty-claims")
    def create_claim(seller_id):
        # PRD §2.1 names seller registration and trade-in submission as the only
        # two credential-free endpoints, so claim filing requires credentials.
        guard("POST", "/v1/sellers/{id}/warranty-claims", ["Consumer"])
        seller = store.sellers.get(seller_id)
        if seller is None:
            raise fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        listing_id = as_str(required(data, "listing_id"), "listing_id")
        listing = store.listings.get(listing_id)
        if listing is None:
            raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        reason = check_enum(as_str(required(data, "claim_reason_code"), "claim_reason_code"),
                            CLAIM_REASON_CODES, "claim_reason_code")
        evidence_included = data.get("evidence_included", False)
        if not isinstance(evidence_included, bool):
            raise fail("ERR_INVALID_REQUEST", "evidence_included must be a boolean.")
        payload = {
            "claim_reason_code": reason,
            "evidence_included": evidence_included,
        }
        claim = claim_svc.create_claim(listing, seller, payload, store.clock)
        return ok(public(claim), 201)

    @app.get("/v1/warranty-claims")
    def list_claims():
        guard("GET", "/v1/warranty-claims", ["PlatformAdmin", "ClaimAdjudicator", "Seller"])
        limit, offset = pagination()
        rows = created_asc(list(store.claims.values()))
        rows = filter_eq(rows, {
            "routed_seller_id": request.args.get("routed_seller_id"),
            "claim_state": request.args.get("claim_state"),
            "resolution_type": request.args.get("resolution_type"),
            "replacement_listing_id": request.args.get("replacement_listing_id"),
        })
        total = len(rows)
        return ok_list([_claim_view(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/warranty-claims/<claim_id>")
    def read_claim(claim_id):
        guard("GET", "/v1/warranty-claims/{id}",
              ["PlatformAdmin", "ClaimAdjudicator", "Seller", "Consumer"])
        return ok(_claim_view(_claim_or_404(claim_id)))

    @app.post("/v1/warranty-claims/<claim_id>/evidence")
    def attach_evidence(claim_id):
        principal = guard("POST", "/v1/warranty-claims/{id}/evidence", ["ClaimAdjudicator"])
        claim = _claim_or_404(claim_id)
        data = body()
        digest = data.get("diagnostic_evidence_digest")
        claim_svc.attach_evidence(claim, "diagnostic_evidence_digest" in data, digest,
                                  principal.user_id, store.clock)
        return ok(_claim_view(claim))

    @app.post("/v1/warranty-claims/<claim_id>/adjudicate")
    def adjudicate(claim_id):
        guard("POST", "/v1/warranty-claims/{id}/adjudicate", ["ClaimAdjudicator"])
        claim = _claim_or_404(claim_id)
        data = body()
        decision = as_str(required(data, "decision"), "decision")
        check_enum(decision, ["APPROVED", "REJECTED"], "decision")
        adjudicator = as_str(required(data, "adjudicator_user_id"), "adjudicator_user_id")
        payload = {
            "resolution_type": data.get("resolution_type"),
            "resolution_obligation_cents": data.get("resolution_obligation_cents"),
            "return_shipment_cents": data.get("return_shipment_cents"),
            "replacement_listing_id": data.get("replacement_listing_id"),
            "adjudicator_user_id": adjudicator,
        }
        if payload["replacement_listing_id"] is not None and \
                payload["replacement_listing_id"] not in store.listings:
            raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        claim_svc.adjudicate(claim, decision, payload, store.clock)
        return ok(_claim_view(claim))

    @app.post("/v1/warranty-claims/<claim_id>/route-return")
    def route_return(claim_id):
        guard("POST", "/v1/warranty-claims/{id}/route-return", ["ClaimAdjudicator"])
        claim = _claim_or_404(claim_id)
        data = body()
        if "expected_claim_version" in data and data["expected_claim_version"] is not None:
            if data["expected_claim_version"] != claim["version"]:
                raise fail("ERR_STALE_VERSION")
        claim_svc.route_return(claim, data, store.clock)
        return ok(_claim_view(claim))


# ------------------------------------------------------------------ helpers
def _reservation_or_404(reservation_id):
    row = store.reservations.get(reservation_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row


def _claim_or_404(claim_id):
    row = store.claims.get(claim_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row


def _claim_view(claim):
    view = public(claim)
    view.update(claim_svc.settlement_view(claim))
    return view