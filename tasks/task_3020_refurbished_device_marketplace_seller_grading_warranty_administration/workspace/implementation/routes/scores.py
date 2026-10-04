"""Service-score section routes."""

from flask import request

from db import store, public, parse_iso
from errors import fail
from requtils import (
    as_str, body, created_asc, filter_eq, pagination, paginate, required,
)
from response import ok, ok_list
from routes.common import guard
from services import scoring


def register(app):
    @app.post("/v1/service-scores")
    def create_section():
        guard("POST", "/v1/service-scores", ["PlatformAdmin"])
        data = body()
        seller_id = as_str(required(data, "seller_id"), "seller_id")
        if seller_id not in store.sellers:
            raise fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        opened = parse_iso(as_str(required(data, "section_opened_on"), "section_opened_on"))
        if opened is None:
            raise fail("ERR_INVALID_REQUEST", "section_opened_on must be an ISO 8601 instant.")
        if opened > store.clock:
            raise fail("ERR_INVALID_REQUEST",
                       "section_opened_on must not be later than the logical clock.")
        section = scoring.create_section(seller_id, opened, store.clock)
        return ok(public(section), 201)

    @app.get("/v1/service-scores")
    def list_sections():
        guard("GET", "/v1/service-scores", ["PlatformAdmin", "ComplianceReviewer", "Seller"])
        limit, offset = pagination()
        rows = created_asc(list(store.service_scores.values()))
        rows = filter_eq(rows, {
            "seller_id": request.args.get("seller_id"),
            "section_state": request.args.get("section_state"),
        })
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/service-scores/<section_id>")
    def read_section(section_id):
        guard("GET", "/v1/service-scores/{id}",
              ["PlatformAdmin", "ComplianceReviewer", "Seller"])
        section = _section_or_404(section_id)
        # An OPEN section is scored continuously on every read.
        if section["section_state"] == "OPEN":
            scoring.recompute_section(section, store.clock)
        return ok(public(section))

    @app.post("/v1/service-scores/<section_id>/close")
    def close_section(section_id):
        guard("POST", "/v1/service-scores/{id}/close", ["System"])
        section = _section_or_404(section_id)
        data = body()
        seller = store.sellers.get(section["seller_id"])
        if seller is None:
            raise fail("ERR_RESOURCE_NOT_FOUND")
        expected = data.get("expected_seller_version")
        if expected is None:
            raise fail("ERR_INVALID_REQUEST", "expected_seller_version is required.")
        if expected != seller["version"]:
            raise fail("ERR_STALE_VERSION")
        scoring.close_section(section, store.clock)
        return ok(public(section))


def _section_or_404(section_id):
    row = store.service_scores.get(section_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row