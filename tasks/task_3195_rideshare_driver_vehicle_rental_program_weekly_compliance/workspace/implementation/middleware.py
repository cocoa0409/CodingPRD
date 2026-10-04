"""Auth header handling, RBAC matrix and request-body schema checks."""

import re

from flask import request

import db
from errors import (E_INVALID_REQUEST, E_UNAUTHENTICATED, E_UNAUTHORIZED, raise_error)

ROLES = ("Driver", "FleetOpsAgent", "ComplianceOfficer", "PlatformAdmin", "SupportAgent")

# Roles whose X-User-ID is the id of a persisted entity rather than an opaque
# operator identifier (PRD 2.1).
ENTITY_BACKED_ROLES = ("Driver",)


def _rule(method, path):
    return method + " " + path


# --- RBAC matrix (PRD 4 / SCAFFOLD roles) -------------------------------------
PERMISSIONS = {}


def _allow(role, method, path):
    PERMISSIONS.setdefault(_rule(method, path), set()).add(role)


_PUBLIC_RULE_SOURCES = """
PlatformAdmin|GET /program/drivers
PlatformAdmin|POST /program/drivers
PlatformAdmin|GET /program/drivers/{id}
PlatformAdmin|POST /program/drivers/{id}/activity
PlatformAdmin|POST /program/drivers/{id}/driving-record
PlatformAdmin|GET /program/drivers/{id}/enrollments
PlatformAdmin|GET /program/drivers/{id}/summary
PlatformAdmin|GET /program/enrollments
PlatformAdmin|GET /program/enrollments/{id}
PlatformAdmin|GET /program/vehicles
PlatformAdmin|GET /program/vehicles/{id}
PlatformAdmin|GET /program/agreements
PlatformAdmin|GET /program/agreements/{id}
PlatformAdmin|GET /program/agreements/{id}/summary
PlatformAdmin|GET /program/weeks
PlatformAdmin|GET /program/weeks/{id}
PlatformAdmin|POST /program/weeks/{id}/payments
PlatformAdmin|POST /program/weeks/{id}/retry-payment
PlatformAdmin|POST /program/weeks/{id}/waive
PlatformAdmin|GET /program/maintenance-events
PlatformAdmin|GET /program/maintenance-events/{id}
PlatformAdmin|GET /program/payments
PlatformAdmin|GET /program/payments/{id}
PlatformAdmin|POST /program/purchase-options
PlatformAdmin|GET /program/purchase-options
PlatformAdmin|GET /program/purchase-options/{id}
PlatformAdmin|POST /program/purchase-options/{id}/complete
PlatformAdmin|GET /program/platform-checks
PlatformAdmin|GET /program/platform-checks/{id}
PlatformAdmin|POST /program/fleet-facts
PlatformAdmin|GET /program/fleet-facts/{id}
PlatformAdmin|POST /program/fleet-facts/{id}/recompute
PlatformAdmin|POST /program/_clock/set_current_utc
ComplianceOfficer|GET /program/drivers
ComplianceOfficer|POST /program/drivers/{id}/activity
ComplianceOfficer|POST /program/drivers/{id}/driving-record
ComplianceOfficer|GET /program/drivers/{id}
ComplianceOfficer|GET /program/drivers/{id}/enrollments
ComplianceOfficer|GET /program/drivers/{id}/summary
ComplianceOfficer|POST /program/enrollments
ComplianceOfficer|GET /program/enrollments
ComplianceOfficer|GET /program/enrollments/{id}
ComplianceOfficer|POST /program/enrollments/{id}/verify
ComplianceOfficer|POST /program/enrollments/{id}/re-evaluate
ComplianceOfficer|POST /program/enrollments/{id}/reinstate
ComplianceOfficer|POST /program/enrollments/{id}/withdraw
ComplianceOfficer|GET /program/vehicles
ComplianceOfficer|GET /program/vehicles/{id}
ComplianceOfficer|GET /program/agreements
ComplianceOfficer|GET /program/agreements/{id}
ComplianceOfficer|GET /program/agreements/{id}/summary
ComplianceOfficer|GET /program/weeks
ComplianceOfficer|GET /program/weeks/{id}
ComplianceOfficer|POST /program/weeks/{id}/mileage
ComplianceOfficer|POST /program/weeks/{id}/settle
ComplianceOfficer|POST /program/weeks/{id}/grace-lapse
ComplianceOfficer|POST /program/weeks/{id}/reopen
ComplianceOfficer|GET /program/maintenance-events
ComplianceOfficer|GET /program/maintenance-events/{id}
ComplianceOfficer|GET /program/payments
ComplianceOfficer|GET /program/payments/{id}
ComplianceOfficer|GET /program/purchase-options
ComplianceOfficer|GET /program/purchase-options/{id}
ComplianceOfficer|POST /program/platform-checks
ComplianceOfficer|GET /program/platform-checks
ComplianceOfficer|GET /program/platform-checks/{id}
ComplianceOfficer|POST /program/platform-checks/{id}
FleetOpsAgent|POST /program/vehicles
FleetOpsAgent|GET /program/vehicles
FleetOpsAgent|GET /program/vehicles/{id}
FleetOpsAgent|GET /program/drivers
FleetOpsAgent|GET /program/drivers/{id}
FleetOpsAgent|GET /program/drivers/{id}/enrollments
FleetOpsAgent|GET /program/enrollments
FleetOpsAgent|GET /program/enrollments/{id}
FleetOpsAgent|POST /program/agreements
FleetOpsAgent|GET /program/agreements
FleetOpsAgent|GET /program/agreements/{id}
FleetOpsAgent|GET /program/agreements/{id}/summary
FleetOpsAgent|POST /program/agreements/{id}/activate
FleetOpsAgent|POST /program/agreements/{id}/swap
FleetOpsAgent|POST /program/agreements/{id}/complete
FleetOpsAgent|POST /program/agreements/{id}/escalate-recovery
FleetOpsAgent|POST /program/agreements/{id}/recover
FleetOpsAgent|POST /program/weeks
FleetOpsAgent|GET /program/weeks
FleetOpsAgent|GET /program/weeks/{id}
FleetOpsAgent|POST /program/weeks/{id}/mileage
FleetOpsAgent|POST /program/maintenance-events
FleetOpsAgent|GET /program/maintenance-events
FleetOpsAgent|GET /program/maintenance-events/{id}
FleetOpsAgent|POST /program/maintenance-events/{id}/start
FleetOpsAgent|POST /program/maintenance-events/{id}/issue-loaner
FleetOpsAgent|POST /program/maintenance-events/{id}/complete
FleetOpsAgent|GET /program/platform-checks
FleetOpsAgent|GET /program/platform-checks/{id}
FleetOpsAgent|GET /program/fleet-facts/{id}
FleetOpsAgent|POST /program/fleet-facts/{id}/recompute
SupportAgent|GET /program/drivers
SupportAgent|GET /program/drivers/{id}
SupportAgent|GET /program/drivers/{id}/enrollments
SupportAgent|GET /program/drivers/{id}/summary
SupportAgent|GET /program/enrollments
SupportAgent|GET /program/enrollments/{id}
SupportAgent|GET /program/vehicles
SupportAgent|GET /program/vehicles/{id}
SupportAgent|GET /program/agreements
SupportAgent|GET /program/agreements/{id}
SupportAgent|GET /program/agreements/{id}/summary
SupportAgent|GET /program/weeks
SupportAgent|GET /program/weeks/{id}
SupportAgent|POST /program/weeks/{id}/payments
SupportAgent|POST /program/weeks/{id}/retry-payment
SupportAgent|GET /program/maintenance-events
SupportAgent|GET /program/maintenance-events/{id}
SupportAgent|GET /program/payments
SupportAgent|GET /program/payments/{id}
SupportAgent|GET /program/purchase-options
SupportAgent|GET /program/purchase-options/{id}
SupportAgent|GET /program/platform-checks
SupportAgent|GET /program/platform-checks/{id}
SupportAgent|GET /program/fleet-facts/{id}
Driver|GET /program/drivers/{id}
Driver|GET /program/drivers/{id}/summary
Driver|GET /program/enrollments/{id}
Driver|POST /program/enrollments/{id}/withdraw
Driver|GET /program/agreements/{id}
Driver|GET /program/agreements/{id}/summary
Driver|GET /program/weeks/{id}
Driver|GET /program/maintenance-events/{id}
Driver|GET /program/purchase-options/{id}
Driver|POST /program/purchase-options/{id}/elect
Driver|POST /program/purchase-options/{id}/fund-escrow
Driver|POST /program/purchase-options/{id}/withdraw
"""

for _line in _PUBLIC_RULE_SOURCES.strip().splitlines():
    _role, _rest = _line.split("|", 1)
    _method, _path = _rest.split(" ", 1)
    _allow(_role, _method, _path)

# --- Request-body schemas -----------------------------------------------------

SCHEMAS = {
    ("POST", "/program/drivers"): {
        "required": {"full_name", "email", "platform_driver_id", "platform_activity_score",
                     "driving_record_points", "license_class", "program_driver_tier"},
        "optional": set(),
    },
    ("POST", "/program/drivers/{id}/activity"): {
        "required": {"platform_activity_score"}, "optional": set()},
    ("POST", "/program/drivers/{id}/driving-record"): {
        "required": {"driving_record_points"}, "optional": set()},
    ("POST", "/program/enrollments"): {
        "required": {"driver_id", "program_tier"}, "optional": set()},
    ("POST", "/program/vehicles"): {
        "required": {"vin", "model_name", "model_year", "vehicle_class",
                     "odometer_miles", "region_code"},
        "optional": set()},
    ("POST", "/program/agreements"): {
        "required": {"enrollment_id", "driver_id", "vehicle_id", "weekly_rate_cents",
                     "insurance_premium_cents", "maintenance_allowance_miles",
                     "period_start", "period_end"},
        "optional": {"unlimited_mileage", "mileage_cap_miles"}},
    ("POST", "/program/agreements/{id}/swap"): {
        "required": {"new_vehicle_id"}, "optional": set()},
    ("POST", "/program/weeks"): {
        "required": {"agreement_id", "expected_agreement_version"}, "optional": set()},
    ("POST", "/program/weeks/{id}/mileage"): {
        "required": {"miles_driven"}, "optional": set()},
    ("POST", "/program/weeks/{id}/payments"): {
        "required": {"amount_cents", "payment_outcome"},
        "optional": {"expected_amount_due_cents"}},
    ("POST", "/program/weeks/{id}/retry-payment"): {
        "required": {"amount_cents", "payment_outcome"}, "optional": set()},
    ("POST", "/program/maintenance-events"): {
        "required": {"agreement_id", "vehicle_id", "event_type", "odometer_at_service",
                     "expected_vehicle_version"},
        "optional": {"downtime_hours", "damage_liability_cents"}},
    ("POST", "/program/purchase-options"): {
        "required": {"agreement_id", "driver_id", "purchase_price_cents",
                     "escrow_weeks_required"},
        "optional": set()},
    ("POST", "/program/purchase-options/{id}/elect"): {
        "required": {"expected_agreement_version"}, "optional": set()},
    ("POST", "/program/platform-checks"): {
        "required": {"agreement_id", "vehicle_id"}, "optional": set()},
    ("POST", "/program/fleet-facts"): {
        "required": {"region_code", "demand_units"}, "optional": set()},
    ("POST", "/program/_clock/set_current_utc"): {
        "required": {"to_iso8601"}, "optional": set()},
}


def authenticate():
    """Guards 1 and 2: role header then identity header."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise_error(E_UNAUTHENTICATED, "X-User-Role is missing or unknown.")
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise_error(E_UNAUTHENTICATED, "X-User-ID is missing.")
    if role in ENTITY_BACKED_ROLES and user_id not in db.DRIVERS:
        raise_error(E_UNAUTHENTICATED, "X-User-ID does not resolve to an existing Driver.")
    return role, user_id


def authorize(role, method, path):
    if role not in PERMISSIONS.get(_rule(method, path), set()):
        raise_error(E_UNAUTHORIZED, "The acting role may not perform this operation.")


def require_owner(user_id, owner_id, role):
    """The four ownership-checked operations (PRD 2.1)."""
    if str(user_id) != str(owner_id):
        raise_error(E_UNAUTHORIZED, "The acting principal does not own the target resource.")


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise_error(E_INVALID_REQUEST, "The request body must be a JSON object.")
    return payload


def check_schema(payload, method, path):
    """Guard 3: required fields present, no undeclared field supplied."""
    schema = SCHEMAS.get((method, path))
    if schema is None:
        if payload:
            raise_error(E_INVALID_REQUEST, "This operation accepts no request body fields.")
        return
    allowed = schema["required"] | schema["optional"]
    for key in payload:
        if key not in allowed:
            raise_error(E_INVALID_REQUEST, "Undeclared field supplied: %s." % key)
    for key in schema["required"]:
        if key not in payload or payload[key] is None:
            raise_error(E_INVALID_REQUEST, "Required field missing: %s." % key)


# --- Scalar validators --------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PLATFORM_ID_RE = re.compile(r"^PLT-[A-Za-z0-9]{8}$")
REGION_RE = re.compile(r"^[A-Z]{2}$")
VIN_RE = re.compile(r"^[A-Za-z0-9]{17}$")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_bool(value):
    return isinstance(value, bool)


def is_str(value):
    return isinstance(value, str)


def is_number(value):
    return is_int(value) or isinstance(value, float)


def invalid(message="The request body failed schema validation."):
    raise_error(E_INVALID_REQUEST, message)