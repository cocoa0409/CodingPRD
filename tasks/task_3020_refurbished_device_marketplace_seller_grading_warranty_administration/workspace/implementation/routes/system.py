"""Audit records, the logical clock, and the governance catalog endpoints."""

from flask import request

from db import store, public, parse_iso, iso
from errors import fail
from requtils import (
    as_str, body, check_enum, created_asc, filter_eq, opt_str, pagination,
    paginate, range_int, required,
)
from response import ok, ok_list
from routes.common import guard
from services import reservations as resv
from services import sellers as seller_svc
from services import tradeins as tradein_svc


def register(app):
    # ---------------------------------------------------- audit records
    @app.get("/v1/audit-records/<record_id>")
    def read_audit_record(record_id):
        guard("GET", "/v1/audit-records/{id}", ["ComplianceReviewer", "PlatformAdmin"])
        return ok(public(_audit_or_404(record_id)))

    @app.post("/v1/audit-records/<record_id>/transition")
    def transition_audit_record(record_id):
        guard("POST", "/v1/audit-records/{id}/transition", ["ComplianceReviewer"])
        record = _audit_or_404(record_id)
        data = body()
        target = as_str(required(data, "target_state"), "target_state")
        check_enum(target, ["PASSED", "FAILED"], "target_state")
        score = range_int(required(data, "audit_score"), "audit_score", low=0, high=100)
        auditor = as_str(required(data, "auditor_user_id"), "auditor_user_id")
        seller_svc.transition_audit_record(record, target, score, auditor, store.clock)
        return ok(public(record))

    # ------------------------------------------------------ logical clock
    @app.post("/v1/_clock/set_current_utc")
    def set_clock():
        guard("POST", "/v1/_clock/set_current_utc", ["PlatformAdmin"])
        data = body()
        instant = parse_iso(as_str(required(data, "to_iso8601"), "to_iso8601"))
        if instant is None:
            raise fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
        store.set_clock(instant)
        # Moving the clock is not inert: every clock-guarded system transition
        # is evaluated here.
        resv.sweep_expiries(instant)
        tradein_svc.sweep_deadlines(instant)
        return ok({})

    # --------------------------------------------------- supported models
    @app.get("/v1/supported-models")
    def list_supported_models():
        guard("GET", "/v1/supported-models",
              ["PlatformAdmin", "ComplianceReviewer", "Seller"])
        return ok([
            {
                "model_code": code,
                "catalog_floor_cents": row["floor_cents"],
                "restricted": code in store.restricted_models,
                "restriction_effective_from": (
                    store.restricted_models[code]["effective_from"] and
                    iso(store.restricted_models[code]["effective_from"])
                ) if code in store.restricted_models else None,
            }
            for code, row in sorted(store.supported_models.items())
        ])

    @app.post("/v1/supported-models")
    def register_supported_model():
        guard("POST", "/v1/supported-models", ["PlatformAdmin"])
        data = body()
        model_code = as_str(required(data, "model_code"), "model_code")
        floor = range_int(data.get("catalog_floor_cents", 0), "catalog_floor_cents", low=0)
        store.register_model(model_code, floor)
        return ok({"model_code": model_code, "catalog_floor_cents": floor}, 201)

    @app.post("/v1/supported-models/<model_code>/restriction")
    def restrict_model(model_code):
        guard("POST", "/v1/supported-models/{model_code}/restriction", ["PlatformAdmin"])
        if model_code not in store.supported_models:
            raise fail("ERR_RESOURCE_NOT_FOUND")
        data = body()
        effective_raw = opt_str(data, "effective_from")
        effective = parse_iso(effective_raw) if effective_raw else None
        store.restrict_model(model_code, effective)
        return ok({"model_code": model_code, "restricted": True,
                   "effective_from": iso(effective) if effective else None})

    # --------------------------------------------------------- blocklists
    @app.get("/v1/blocklists/<kind>")
    def list_blocklist(kind):
        guard("GET", "/v1/blocklists/{kind}",
              ["PlatformAdmin", "ComplianceReviewer"])
        entries = _blocklist(kind)
        return ok(sorted(entries))

    @app.post("/v1/blocklists/<kind>")
    def add_blocklist_entry(kind):
        guard("POST", "/v1/blocklists/{kind}", ["PlatformAdmin", "ComplianceReviewer"])
        entries = _blocklist(kind)
        data = body()
        imei = as_str(required(data, "imei"), "imei")
        entries.add(imei)
        return ok({"kind": kind, "imei": imei}, 201)


# ------------------------------------------------------------------ helpers
def _audit_or_404(record_id):
    row = store.audit_records.get(record_id)
    if row is None:
        raise fail("ERR_RESOURCE_NOT_FOUND")
    return row


def _blocklist(kind):
    if kind == "stolen":
        return store.stolen_blocklist
    if kind == "counterfeit":
        return store.counterfeit_blocklist
    raise fail("ERR_RESOURCE_NOT_FOUND", "Unknown blocklist '%s'." % kind)