"""Carrier endpoints: onboarding, verification staircase, suspension."""

from flask import request

from constants import EQUIPMENT_TYPES, parse_instant
from db import clock_now, db, mint_id, serialize, touch
from middleware import current_actor, require_owner, roles_required
from response import array_response, object_response, paginate
from routers import body, require, require_int
from services import carriers as carrier_service
from services.common import get_carrier, refresh_carrier_score


def register(app):
    @app.route("/v1/carriers", methods=["POST"])
    @roles_required("ComplianceReviewer", "PlatformAdmin")
    def create_carrier():
        payload = body()
        require(payload, "legal_name", "mc_number", "dot_number",
                "insurance_expires_at", "insurance_liability_limit_cents",
                "cargo_coverage_limit_cents", "safety_score", "equipment_types")
        mc_number = payload["mc_number"]
        for existing in db.carriers.values():
            if existing["mc_number"] == mc_number:
                from errors import ApiError
                raise ApiError("ERR_DUPLICATE_MC_NUMBER")
        types = payload["equipment_types"]
        if not isinstance(types, list) or not types:
            from errors import ApiError
            raise ApiError("ERR_INVALID_REQUEST", "equipment_types must be a non-empty list.")
        for item in types:
            if item not in EQUIPMENT_TYPES:
                from errors import ApiError
                raise ApiError("ERR_INVALID_REQUEST", "Unknown equipment_types member.")
        now = clock_now()
        carrier = {
            "id": mint_id(),
            "legal_name": payload["legal_name"],
            "mc_number": mc_number,
            "dot_number": payload["dot_number"],
            "operating_authority_status": "NONE",
            "authority_verified_at": None,
            "insurance_expires_at": parse_instant(payload["insurance_expires_at"],
                                                  "insurance_expires_at"),
            "insurance_liability_limit_cents": int(payload["insurance_liability_limit_cents"]),
            "cargo_coverage_limit_cents": int(payload["cargo_coverage_limit_cents"]),
            "insurance_attested_at": None,
            "certificate_reference": None,
            "safety_score": float(payload["safety_score"]),
            "equipment_types": list(types),
            "claims_clawback_count": 0,
            "operational_risk_score": 100.0,
            "suspension_reason": None,
            "status": "PENDING",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        db.carriers[carrier["id"]] = carrier
        return object_response(serialize("Carrier", carrier), 201)

    @app.route("/v1/carriers", methods=["GET"])
    @roles_required("Carrier", "ComplianceReviewer", "PlatformAdmin", "Shipper")
    def list_carriers():
        rows = list(db.carriers.values())
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        equipment_type = request.args.get("equipment_type")
        if equipment_type:
            rows = [row for row in rows if equipment_type in row["equipment_types"]]
        minimum = request.args.get("min_operational_risk_score")
        if minimum:
            try:
                floor = float(minimum)
            except ValueError:
                from errors import ApiError
                raise ApiError("ERR_INVALID_REQUEST", "min_operational_risk_score must be a number.")
            rows = [row for row in rows if float(row["operational_risk_score"]) >= floor]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Carrier", row) for row in window], pagination)

    @app.route("/v1/carriers/<carrier_id>", methods=["GET"])
    @roles_required("Carrier", "ComplianceReviewer", "ClaimsAdjuster", "PlatformAdmin", "Shipper")
    def get_carrier_route(carrier_id):
        carrier = get_carrier(carrier_id)
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, carrier["id"], "carrier")
        carrier_service.sync_carrier(carrier)
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/verify-authority", methods=["POST"])
    @roles_required("ComplianceReviewer")
    def verify_authority(carrier_id):
        carrier = get_carrier(carrier_id)
        carrier_service.verify_authority(carrier)
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/attest-insurance", methods=["POST"])
    @roles_required("ComplianceReviewer")
    def attest_insurance(carrier_id):
        payload = body()
        require(payload, "insurance_expires_at", "insurance_liability_limit_cents",
                "cargo_coverage_limit_cents")
        carrier = get_carrier(carrier_id)
        carrier_service.attest_insurance(
            carrier,
            parse_instant(payload["insurance_expires_at"], "insurance_expires_at"),
            require_int(payload, "insurance_liability_limit_cents"),
            require_int(payload, "cargo_coverage_limit_cents"),
            payload.get("certificate_reference"))
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/verify-safety", methods=["POST"])
    @roles_required("ComplianceReviewer")
    def verify_safety(carrier_id):
        payload = body()
        carrier = get_carrier(carrier_id)
        carrier_service.verify_safety(carrier, payload.get("safety_score"))
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/suspend", methods=["POST"])
    @roles_required("PlatformAdmin")
    def suspend_carrier(carrier_id):
        payload = body()
        require(payload, "reason_code")
        carrier = get_carrier(carrier_id)
        carrier_service.suspend_carrier(carrier, payload["reason_code"])
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/reinstate", methods=["POST"])
    @roles_required("PlatformAdmin")
    def reinstate_carrier(carrier_id):
        carrier = get_carrier(carrier_id)
        carrier_service.reinstate_carrier(carrier)
        return object_response(serialize("Carrier", carrier))

    @app.route("/v1/carriers/<carrier_id>/equipment", methods=["GET"])
    @roles_required("Carrier", "PlatformAdmin", "ComplianceReviewer")
    def carrier_equipment(carrier_id):
        carrier = get_carrier(carrier_id)
        role, identity = current_actor()
        if role == "Carrier":
            require_owner(role, identity, carrier["id"], "carrier")
        rows = [row for row in db.equipment.values() if row["carrier_id"] == carrier_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        equipment_type = request.args.get("equipment_type")
        if equipment_type:
            rows = [row for row in rows if row["equipment_type"] == equipment_type]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("CarrierEquipment", row) for row in window], pagination)

    @app.route("/v1/carriers/<carrier_id>/bookings", methods=["GET"])
    @roles_required("Carrier", "PlatformAdmin", "Shipper")
    def carrier_bookings(carrier_id):
        get_carrier(carrier_id)
        rows = [row for row in db.bookings.values() if row["carrier_id"] == carrier_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("Booking", row) for row in window], pagination)

    @app.route("/v1/carriers/<carrier_id>/claims", methods=["GET"])
    @roles_required("Carrier", "ClaimsAdjuster", "PlatformAdmin")
    def carrier_claims(carrier_id):
        get_carrier(carrier_id)
        rows = [row for row in db.claims.values() if row["carrier_id"] == carrier_id]
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        rows.sort(key=lambda row: row["created_at"])
        window, pagination = paginate(rows, request.args)
        return array_response([serialize("ClaimsCase", row) for row in window], pagination)