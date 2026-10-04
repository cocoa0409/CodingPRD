"""Marketplace grading-definition routes."""

from flask import request

from db import store, public, touch, iso, stamp_new, parse_iso
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, opt_str, pagination,
    paginate, range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import listings as listing_svc
from vocab import (
    COSMETIC_GRADES,
    DEFINITION_STATES,
    FUNCTIONAL_GRADES,
)

READERS = ["PlatformAdmin", "ComplianceReviewer", "Seller"]


def register(app):
    @app.post("/v1/grading-definitions")
    def create_definition():
        guard("POST", "/v1/grading-definitions", ["ComplianceReviewer"])
        data = body()
        as_str(required(data, "definition_code"), "definition_code")
        cosmetic = required(data, "cosmetic_thresholds")
        functional = required(data, "functional_thresholds")
        _check_threshold_map(cosmetic, COSMETIC_GRADES, "cosmetic_thresholds")
        _check_threshold_map(functional, FUNCTIONAL_GRADES, "functional_thresholds")
        floor = range_int(required(data, "battery_floor_pct"), "battery_floor_pct",
                          low=1, high=100)
        effective_from = parse_iso(as_str(required(data, "effective_from"), "effective_from"))
        if effective_from is None:
            raise fail("ERR_INVALID_REQUEST", "effective_from must be an ISO 8601 instant.")
        payload = {
            "definition_code": data["definition_code"],
            "definition_state": "DRAFT",
            "cosmetic_thresholds": cosmetic,
            "functional_thresholds": functional,
            "battery_floor_pct": floor,
            "effective_from": iso(effective_from),
            "retired_on": None,
            "binding_definition_id": None,
            "_effective_dt": effective_from,
        }
        stamp_new("grading_definitions", payload, store.clock)
        store.grading_definitions[payload["id"]] = payload
        return ok(public(payload), 201)

    @app.get("/v1/grading-definitions")
    def list_definitions():
        guard("GET", "/v1/grading-definitions", READERS)
        limit, offset = pagination()
        rows = created_asc(list(store.grading_definitions.values()))
        rows = filter_eq(rows, {"definition_state": request.args.get("definition_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.get("/v1/grading-definitions/<definition_id>")
    def read_definition(definition_id):
        guard("GET", "/v1/grading-definitions/{id}", READERS)
        return ok(public(_definition_or_404(definition_id)))

    @app.get("/v1/grading-definitions/<definition_id>/device-listings")
    def list_bound_listings(definition_id):
        guard("GET", "/v1/grading-definitions/{id}/device-listings",
              ["PlatformAdmin", "ComplianceReviewer"])
        definition = _definition_or_404(definition_id)
        limit, offset = pagination()
        rows = created_asc([
            row for row in store.listings.values()
            if row.get("binding_definition_id") == definition["id"]
        ])
        rows = filter_eq(rows, {"listing_state": request.args.get("listing_state")})
        total = len(rows)
        return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)

    @app.post("/v1/grading-definitions/<definition_id>/activate")
    def activate(definition_id):
        guard("POST", "/v1/grading-definitions/{id}/activate", ["ComplianceReviewer"])
        definition = _definition_or_404(definition_id)
        data = body()
        _check_expected_version(definition, data)
        if definition["definition_state"] != "DRAFT":
            raise fail("ERR_INVALID_STATE")
        clock = store.clock
        previous = listing_svc.active_grading_definition()
        for other in store.grading_definitions.values():
            if other["id"] == definition["id"]:
                continue
            if other["definition_state"] == "ACTIVE" and \
                    other.get("_effective_dt") == definition.get("_effective_dt"):
                raise fail("ERR_INVALID_STATE",
                           "Another grading definition is already ACTIVE at this effective_from instant.")
        definition["definition_state"] = "ACTIVE"
        definition["binding_definition_id"] = definition["id"]
        touch(definition, clock)

        # Cascade: listings UNDER_REVIEW bound to the previously ACTIVE
        # definition are re-flagged for re-review.
        if previous is not None and previous["id"] != definition["id"]:
            for listing in store.listings.values():
                if listing["listing_state"] != "UNDER_REVIEW":
                    continue
                if listing.get("binding_definition_id") == previous["id"]:
                    listing["binding_definition_id"] = definition["id"]
                    listing["_binding_definition_id"] = definition["id"]
                    touch(listing, clock)
        return ok(public(definition))

    @app.post("/v1/grading-definitions/<definition_id>/retire")
    def retire(definition_id):
        guard("POST", "/v1/grading-definitions/{id}/retire", ["ComplianceReviewer"])
        definition = _definition_or_404(definition_id)
        data = body()
        as_str(required(data, "retirement_note"), "retirement_note")
        if definition["definition_state"] != "ACTIVE":
            raise fail("ERR_INVALID_STATE")
        clock = store.clock
        if clock < definition["_effective_dt"]:
            raise fail("ERR_INVALID_STATE",
                       "The definition may not be retired before its effective_from instant.")
        definition["definition_state"] = "RETIRED"
        definition["retired_on"] = iso(clock)
        touch(definition, clock)
        return ok(public(definition))

    @app.post("/v1/grading-definitions/<definition_id>/reinstate")
    def reinstate(definition_id):
        guard("POST", "/v1/grading-definitions/{id}/reinstate", ["ComplianceReviewer"])
        definition = _definition_or_404(definition_id)
        data = body()
        _check_expected_version(definition, data)
        if definition["definition_state"] != "RETIRED":
            raise fail("ERR_INVALID_STATE")
        clock = store.clock
        if not clock > definition["_effective_dt"]:
            raise fail("ERR_INVALID_STATE",
                       "effective_from must be strictly before the logical clock.")
        for other in store.grading_definitions.values():
            if other["id"] != definition["id"] and other["definition_state"] == "ACTIVE":
                raise fail("ERR_INVALID_STATE", "Another grading definition is already ACTIVE.")
        definition["definition_state"] = "ACTIVE"
        definition["retired_on"] = None
        touch(definition, clock)
        return ok(public(definition))


# ------------------------------------------------------------------ helpers
def _definition_or_404(definition_id):
    row = store.grading_definitions.get(definition_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row


def _check_threshold_map(value, expected_keys, field):
    if not isinstance(value, dict) or set(value.keys()) != set(expected_keys):
        raise fail("ERR_INVALID_REQUEST",
                   "The field '%s' must have exactly the keys %s." % (field, ", ".join(expected_keys)))
    for key, item in value.items():
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise fail("ERR_INVALID_REQUEST",
                       "The field '%s' must map %s to a number." % (field, key))


def _check_expected_version(definition, data):
    if "expected_definition_version" in data and data["expected_definition_version"] is not None:
        if data["expected_definition_version"] != definition["version"]:
            raise fail("ERR_STALE_VERSION")