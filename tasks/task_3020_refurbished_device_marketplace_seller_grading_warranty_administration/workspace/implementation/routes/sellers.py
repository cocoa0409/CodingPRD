"""Seller routes: registration, onboarding, suspension, blocklisting, exposure."""

from db import store, public, touch, iso
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, opt_str, pagination,
    paginate, range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import exposure as expo
from services import sellers as seller_svc
from vocab import BLOCKLIST_FINDINGS
from middleware import ensure_owner

import re

ADMIN_READERS = ["PlatformAdmin", "ComplianceReviewer", "ClaimAdjudicator"]
COUNTRY2 = re.compile(r"\A[A-Z]{2}\Z")


def register(app):
    @app.post("/v1/sellers")
    def create_seller():
        guard("POST", "/v1/sellers", ["PlatformAdmin"], credentials_optional=True)
        data = body()
        legal_name = as_str(required(data, "legal_name"), "legal_name")
        country_code = as_str(required(data, "country_code"), "country_code")
        if not COUNTRY2.match(country_code):
            raise fail("ERR_INVALID_REQUEST",
                       "country_code must be exactly two uppercase letters.")
        capacity = range_int(required(data, "refurbishment_capacity_units"),
                             "refurbishment_capacity_units", low=1)
        seller = seller_svc.create_seller(legal_name, country_code, capacity, store.clock)
        return ok(public(seller), 201)

    @app.get("/v1/sellers")
    def list_sellers():
        guard("GET", "/v1/sellers", ADMIN_READERS)
        limit, offset = pagination()
        rows = created_asc(list(store.sellers.values()))
        rows = filter_eq(rows, {
            "onboarding_state": _q("onboarding_state"),
            "performance_tier": _q("performance_tier"),
            "latest_score_id": _q("latest_score_id"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/sellers/<seller_id>")
    def read_seller(seller_id):
        principal = guard("GET", "/v1/sellers/{id}",
                          ADMIN_READERS + ["Seller"])
        seller = _seller_or_404(seller_id)
        ensure_owner(principal, seller_id)
        return ok(public(seller))

    @app.post("/v1/sellers/<seller_id>/verify-documents")
    def verify_documents(seller_id):
        guard("POST", "/v1/sellers/{id}/verify-documents", ["ComplianceReviewer"])
        seller = _seller_or_404(seller_id)
        data = body()
        _occ_seller(seller, data)
        seller_svc.verify_documents(seller, store.clock)
        return ok(public(seller))

    @app.post("/v1/sellers/<seller_id>/audit-records")
    def book_audit(seller_id):
        guard("POST", "/v1/sellers/{id}/audit-records", ["ComplianceReviewer"])
        seller = _seller_or_404(seller_id)
        data = body()
        scheduled_raw = as_str(required(data, "audit_scheduled_for"), "audit_scheduled_for")
        from db import parse_iso
        scheduled = parse_iso(scheduled_raw)
        if scheduled is None:
            raise fail("ERR_INVALID_REQUEST", "audit_scheduled_for must be an ISO 8601 instant.")
        if scheduled <= store.clock:
            raise fail("ERR_INVALID_REQUEST",
                       "audit_scheduled_for must be strictly later than the logical clock.")
        note = as_str(required(data, "audit_scope_note"), "audit_scope_note")
        if not (1 <= len(note) <= 500):
            raise fail("ERR_INVALID_REQUEST", "audit_scope_note must be 1..500 characters.")
        throughput = range_int(required(data, "declared_monthly_throughput"),
                               "declared_monthly_throughput", low=1)
        record = seller_svc.book_audit_record(seller, scheduled, note, throughput, store.clock)
        return ok(public(record), 201)

    @app.get("/v1/sellers/<seller_id>/audit-records")
    def list_audit_records(seller_id):
        guard("GET", "/v1/sellers/{id}/audit-records", ["ComplianceReviewer", "PlatformAdmin"])
        _seller_or_404(seller_id)
        limit, offset = pagination()
        rows = created_asc([r for r in store.audit_records.values() if r["seller_id"] == seller_id])
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.post("/v1/sellers/<seller_id>/suspend")
    def suspend_seller(seller_id):
        guard("POST", "/v1/sellers/{id}/suspend", ["ComplianceReviewer"])
        seller = _seller_or_404(seller_id)
        data = body()
        # The seller-level suspension reason is not enumerated by the PRD or the
        # scaffold, so any non-empty code is accepted here.
        guard_reason = as_str(required(data, "reason_code"), "reason_code")
        _occ_seller(seller, data)
        seller_svc.suspend_seller(seller, guard_reason, store.clock)
        return ok(public(seller))

    @app.post("/v1/sellers/<seller_id>/blocklist")
    def blocklist_seller(seller_id):
        guard("POST", "/v1/sellers/{id}/blocklist", ["ComplianceReviewer"])
        seller = _seller_or_404(seller_id)
        data = body()
        finding = as_str(required(data, "finding"), "finding")
        check_enum(finding, BLOCKLIST_FINDINGS, "finding")
        evidence = as_str(required(data, "evidence_digest"), "evidence_digest")
        seller_svc.blocklist_seller(seller, finding, evidence, store.clock)
        return ok(public(seller))

    @app.get("/v1/sellers/<seller_id>/exposure-floor")
    def exposure_floor(seller_id):
        principal = guard("GET", "/v1/sellers/{id}/exposure-floor",
                          ["PlatformAdmin", "ClaimAdjudicator", "Seller"])
        seller = _seller_or_404(seller_id)
        ensure_owner(principal, seller_id)
        clock = store.clock
        live = expo.resv.live_cells(seller_id, clock)
        return ok({
            "seller_id": seller_id,
            "published_exposure_floor_cents": seller.get("exposure_floor_cents", 0),
            "traced_exposure_cents": expo.traced_exposure_cents(seller_id, clock),
            "cell_count": len(live),
            "reserved_claim_cents": expo.reserved_claim_cents(seller_id),
        })

    @app.get("/v1/sellers/<seller_id>/listings")
    def list_seller_listings(seller_id):
        principal = guard("GET", "/v1/sellers/{id}/listings",
                          ["PlatformAdmin", "ComplianceReviewer", "Seller"])
        _seller_or_404(seller_id)
        ensure_owner(principal, seller_id)
        limit, offset = pagination()
        rows = created_asc([r for r in store.listings.values() if r.get("seller_id") == seller_id])
        rows = filter_eq(rows, {"listing_state": _q("listing_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/sellers/<seller_id>/mystery-shop-verifications")
    def list_seller_verifications(seller_id):
        guard("GET", "/v1/sellers/{id}/mystery-shop-verifications",
              ["ComplianceReviewer", "PlatformAdmin"])
        _seller_or_404(seller_id)
        limit, offset = pagination()
        rows = created_asc([r for r in store.verifications.values() if r["seller_id"] == seller_id])
        rows = filter_eq(rows, {"verification_state": _q("verification_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/sellers/<seller_id>/service-scores")
    def list_seller_scores(seller_id):
        principal = guard("GET", "/v1/sellers/{id}/service-scores",
                          ["PlatformAdmin", "Seller", "ComplianceReviewer"])
        _seller_or_404(seller_id)
        ensure_owner(principal, seller_id)
        limit, offset = pagination()
        rows = created_asc([r for r in store.service_scores.values() if r["seller_id"] == seller_id])
        rows = filter_eq(rows, {"section_state": _q("section_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


# ------------------------------------------------------------------ helpers
def _q(name):
    from flask import request
    return request.args.get(name)


def _seller_or_404(seller_id):
    seller = store.sellers.get(seller_id)
    if seller is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return seller


def _occ_seller(seller, data):
    """Optional expected_seller_version guard on action endpoints."""
    if "expected_seller_version" in data and data["expected_seller_version"] is not None:
        if data["expected_seller_version"] != seller["version"]:
            raise fail("ERR_STALE_VERSION")