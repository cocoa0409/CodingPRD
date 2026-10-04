"""Carrier resource and its derived collections (PRD 3.1)."""

import calculations as calc
import core
import db
import middleware
import response
import serializers
from decorators import requires
from errors import ApiError

READ_ROLES = ("PlatformAdmin", "DirectorOfSales", "CarrierIntegration",
              "ComplianceOfficer", "LicensingCoordinator", "Any")


def register(app):
    @app.post("/carriers")
    @requires("PlatformAdmin")
    def create_carrier():
        payload = middleware.body()
        contract_type = middleware.require_field(payload, "contract_type", str)
        if contract_type not in ("CONTRACTED", "MARKETING_ONLY"):
            raise ApiError("ERR_INVALID_REQUEST", "contract_type must be CONTRACTED or MARKETING_ONLY.")
        row = {
            "id": db.new_id(),
            "_seq": db.next_seq(),
            "created_at": db.now(),
            "updated_at": db.now(),
            "version": 1,
            "legal_name": middleware.require_field(payload, "legal_name", str),
            "naic_number": middleware.require_field(payload, "naic_number", str),
            "contract_type": contract_type,
            "initial_commission_rate_pct": calc.dec(
                middleware.require_field(payload, "initial_commission_rate_pct")),
            "renewal_commission_rate_pct": calc.dec(
                middleware.require_field(payload, "renewal_commission_rate_pct")),
            "chargeback_clawback_pct": calc.dec(
                middleware.require_field(payload, "chargeback_clawback_pct")),
            "ack_expected_within_days": middleware.as_int(
                middleware.optional(payload, "ack_expected_within_days", 5), "ack_expected_within_days"),
            "effectuation_expected_within_days": middleware.as_int(
                middleware.optional(payload, "effectuation_expected_within_days", 30),
                "effectuation_expected_within_days"),
            "status": "ACTIVE",
        }
        db.carriers[row["id"]] = row
        return response.ok(serializers.serialize("Carrier", row), status=201)

    @app.get("/carriers")
    @requires(*READ_ROLES)
    def list_carriers():
        rows = list(db.carriers.values())
        contract_type = middleware.text_arg("contract_type")
        if contract_type is not None:
            rows = [row for row in rows if row["contract_type"] == contract_type]
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Carrier", page), limit, offset, total)

    @app.get("/carriers/<carrier_id>")
    @requires(*READ_ROLES)
    def get_carrier(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        return response.ok(serializers.serialize("Carrier", carrier))

    @app.put("/carriers/<carrier_id>")
    @requires("PlatformAdmin")
    def update_carrier(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        payload = middleware.body()
        expected = middleware.as_int(
            middleware.require_field(payload, "expected_carrier_version"), "expected_carrier_version")
        if expected != carrier["version"]:
            raise ApiError("ERR_STALE_VERSION",
                           "expected_carrier_version does not match the carrier's version.")

        if payload.get("legal_name") is not None:
            carrier["legal_name"] = payload["legal_name"]
        for field in ("initial_commission_rate_pct", "renewal_commission_rate_pct",
                      "chargeback_clawback_pct"):
            if payload.get(field) is not None:
                carrier[field] = calc.dec(payload[field])
        for field in ("ack_expected_within_days", "effectuation_expected_within_days"):
            if payload.get(field) is not None:
                carrier[field] = middleware.as_int(payload[field], field)
        if payload.get("status") is not None:
            if payload["status"] not in ("ACTIVE", "SUSPENDED"):
                raise ApiError("ERR_INVALID_REQUEST", "status must be ACTIVE or SUSPENDED.")
            carrier["status"] = payload["status"]
        core.touch(carrier)
        return response.ok(serializers.serialize("Carrier", carrier))

    @app.get("/carriers/<carrier_id>/plans")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "LicensedAgent", "Any")
    def list_carrier_plans(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        rows = [row for row in db.plans.values() if row["carrier_id"] == carrier["id"]]
        status = middleware.text_arg("status")
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
        return response.ok_list(serializers.listing("Plan", page), limit, offset, total)

    @app.get("/carriers/<carrier_id>/appointments")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "LicensingCoordinator", "Any")
    def list_carrier_appointments(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        rows = [row for row in db.appointments.values() if row["carrier_id"] == carrier["id"]]
        return _filtered_list("CarrierAppointment", rows,
                              {"agent_id": "agent_id", "state_code": "state_code", "status": "status"})

    @app.get("/carriers/<carrier_id>/certifications")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer", "LicensingCoordinator", "Any")
    def list_carrier_certifications(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        rows = [row for row in db.certifications.values() if row["carrier_id"] == carrier["id"]]
        return _filtered_list("CarrierCertification", rows,
                              {"agent_id": "agent_id", "product_type": "product_type", "status": "status"})

    @app.get("/carriers/<carrier_id>/carrier-reconciliations")
    @requires("PlatformAdmin", "DirectorOfSales", "ComplianceOfficer")
    def list_carrier_reconciliations(carrier_id):
        carrier = middleware.resolve("Carrier", carrier_id)
        rows = [row for row in db.reconciliations.values() if row["carrier_id"] == carrier["id"]]
        return _filtered_list("CarrierReconciliation", rows,
                              {"period_month": "period_month", "status": "status"})


def _filtered_list(entity_name, rows, mapping):
    for arg, field in mapping.items():
        value = middleware.text_arg(arg)
        if value is not None:
            rows = [row for row in rows if str(row[field]) == value]
    page, limit, offset, total = middleware.paginate(rows, middleware.by_creation)
    return response.ok_list(serializers.listing(entity_name, page), limit, offset, total)