"""Payload validation, role resolution and shared field projections."""

import clock
import db
from errors import api_error

# PRD section 2.1: the system recognises exactly five roles.
ROLES = ("MembershipOwner", "ServiceTechnician", "Instructor", "PlatformAdmin", "Anonymous")

# Roles whose X-User-ID names a persisted Membership (PRD section 2.1).
ENTITY_BACKED_ROLE = "MembershipOwner"

_OPAQUE_ROLES = ("ServiceTechnician", "Instructor", "PlatformAdmin", "Anonymous")


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_owner(self):
        return self.role == ENTITY_BACKED_ROLE


def header_value(headers, canonical):
    """Read a header case-insensitively (HTTP header names are not case sensitive)."""
    value = headers.get(canonical)
    if value is not None:
        return value
    lowered = canonical.lower()
    for name, candidate in headers.items():
        if name.lower() == lowered:
            return candidate
    return None


def authenticate(headers):
    """Priority 1 (validations row 1): both headers present, role declared."""
    role = header_value(headers, "X-User-Role")
    user_id = header_value(headers, "X-User-ID")
    if role is None or user_id is None or role == "" or user_id == "":
        raise api_error("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise api_error("ERR_UNAUTHENTICATED")
    return Caller(role, user_id)


def require_role(caller, allowed):
    """Priority 2 (validations row 2): the role must be permitted."""
    if caller.role not in allowed:
        raise api_error("ERR_UNAUTHORIZED")


def scope_membership(caller, membership):
    """Entity-backed ownership: a MembershipOwner only touches its own rows.

    PRD section 2.1: ownership checks compare the resource's foreign-key field
    to X-User-ID.  The four opaque roles never participate in ownership
    comparison.
    """
    if caller.is_owner and membership is not None and membership["id"] != caller.user_id:
        raise api_error("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------
def require_object(payload):
    if not isinstance(payload, dict):
        raise api_error("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def reject_unknown(payload, known):
    """Priority 3: no unknown field may be supplied."""
    known_set = set(known)
    for key in payload:
        if key not in known_set:
            raise api_error(
                "ERR_INVALID_REQUEST",
                "Field '%s' is not accepted by this operation." % key,
            )


def field_str(payload, name, required=True, default=None, allow_blank=False):
    if name not in payload or payload[name] is None:
        if required:
            raise api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
    return value


def field_enum(payload, name, allowed, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if value not in allowed:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (name, ", ".join(allowed)),
        )
    return value


def field_int(payload, name, required=True, default=None, minimum=None):
    if name not in payload or payload[name] is None:
        if required:
            raise api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be at least %d." % (name, minimum),
        )
    return value


def field_bool(payload, name, required=False, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def field_datetime(payload, name, required=True, default=None):
    if name not in payload or payload[name] is None:
        if required:
            raise api_error("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    parsed = clock.parse(payload[name])
    if parsed is None:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be an ISO 8601 timestamp." % name,
        )
    return parsed


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------
def limit_of(args):
    raw = args.get("limit")
    if raw is None or raw == "":
        return 10
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
    if value < 1 or value > 100:
        raise api_error(
            "ERR_INVALID_REQUEST",
            "Query parameter 'limit' must be between 1 and 100.",
        )
    return value


def offset_of(args):
    raw = args.get("offset")
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
    if value < 0:
        raise api_error("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return value


def query_matches(args, name, value):
    """Filter helper: absent parameter matches every row."""
    wanted = args.get(name)
    if wanted is None or wanted == "":
        return True
    if value is None:
        return False
    if isinstance(value, bool):
        return str(value).lower() == str(wanted).lower()
    return str(value) == str(wanted)


def paginate(rows, args):
    limit = limit_of(args)
    offset = offset_of(args)
    ordered = db.ordered(rows)
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total


# ---------------------------------------------------------------------------
# Field projections
# ---------------------------------------------------------------------------
def membership_view(row):
    return {
        "id": row["id"],
        "household_name": row["household_name"],
        "billing_email": row["billing_email"],
        "plan_tier": row["plan_tier"],
        "monthly_fee_cents": row["monthly_fee_cents"],
        "concurrent_limit_override": row["concurrent_limit_override"],
        "concurrent_limit_effective": row["concurrent_limit_effective"],
        "active_user_count": row["active_user_count"],
        "billing_cycle_start_at": clock.fmt(row["billing_cycle_start_at"]),
        "paid_through_at": clock.fmt(row["paid_through_at"]),
        "status": row["status"],
        "posture": row["posture"],
        "pause_started_at": clock.fmt(row["pause_started_at"]),
        "accrued_pause_credit_cents": row["accrued_pause_credit_cents"],
        "total_streams_observed": row["total_streams_observed"],
        "unpaid_financing_count": row["unpaid_financing_count"],
        "safety_gate_open": row["safety_gate_open"],
        "attr_frozen_reason": row["attr_frozen_reason"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def household_user_view(row):
    return {
        "id": row["id"],
        "membership_id": row["membership_id"],
        "display_name": row["display_name"],
        "email": row["email"],
        "role": row["role"],
        "status": row["status"],
        "streaming_device_serial": row["streaming_device_serial"],
        "suspended_reason": row["suspended_reason"],
        "verification_token": row["verification_token"],
        "verified": row["verified"],
        "eviction_count": row["eviction_count"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def device_view(row):
    return {
        "id": row["id"],
        "membership_id": row["membership_id"],
        "hardware_sku": row["hardware_sku"],
        "serial": row["serial"],
        "condition": row["condition"],
        "certifying_device_id": row["certifying_device_id"],
        "provenance_source": row["provenance_source"],
        "activation_status": row["activation_status"],
        "entitlement_lock": row["entitlement_lock"],
        "activated_at": clock.fmt(row["activated_at"]),
        "warranty_expires_at": clock.fmt(row["warranty_expires_at"]),
        "resale_cycle_count": row["resale_cycle_count"],
        "total_workouts": row["total_workouts"],
        "content_access_allowed": row["content_access_allowed"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def hardware_order_view(row):
    return {
        "id": row["id"],
        "membership_id": row["membership_id"],
        "hardware_sku": row["hardware_sku"],
        "subtotal_cents": row["subtotal_cents"],
        "quote_total_cents": row["quote_total_cents"],
        "captured_total_cents": row["captured_total_cents"],
        "delivery_fee_cents": row["delivery_fee_cents"],
        "stair_carry_fee_cents": row["stair_carry_fee_cents"],
        "assembly_fee_cents": row["assembly_fee_cents"],
        "finance_charge_cents": row["finance_charge_cents"],
        "financing_method": row["financing_method"],
        "status": row["status"],
        "refund_dispute_status": row["refund_dispute_status"],
        "device_id": row["device_id"],
        "return_device_id": row["return_device_id"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def delivery_appointment_view(row):
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "hardware_order_id": row["hardware_order_id"],
        "start_at": clock.fmt(row["start_at"]),
        "end_at": clock.fmt(row["end_at"]),
        "zone": row["zone"],
        "stair_flights": row["stair_flights"],
        "has_elevator": row["has_elevator"],
        "delivery_legs": row["delivery_legs"],
        "technician_crew_code": row["technician_crew_code"],
        "status": row["status"],
        "reschedule_count": row["reschedule_count"],
        "completion_grade": row["completion_grade"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def financing_plan_view(row):
    return {
        "id": row["id"],
        "membership_id": row["membership_id"],
        "order_id": row["order_id"],
        "principal_cents": row["principal_cents"],
        "term_months": row["term_months"],
        "apr_bps": row["apr_bps"],
        "monthly_installment_cents": row["monthly_installment_cents"],
        "installments_paid": row["installments_paid"],
        "installments_late": row["installments_late"],
        "retry_count": row["retry_count"],
        "status": row["status"],
        "delinquency_count": row["delinquency_count"],
        "safety_disable_latched": row["safety_disable_latched"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def service_order_view(row):
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "order_id": row["order_id"],
        "reported_fault_code": row["reported_fault_code"],
        "fault_class": row["fault_class"],
        "priority": row["priority"],
        "status": row["status"],
        "part_id": row["part_id"],
        "reserved_part_qty": row["reserved_part_qty"],
        "diagnosis_note": row["diagnosis_note"],
        "resolved_at": clock.fmt(row["resolved_at"]),
        "failure_before_part": row["failure_before_part"],
        "safety_functions_maintained": row["safety_functions_maintained"],
        "technician_crew_code": row.get("technician_crew_code"),
        "scheduled_start_at": clock.fmt(row.get("scheduled_start_at")),
        "scheduled_end_at": clock.fmt(row.get("scheduled_end_at")),
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def parts_inventory_view(row):
    return {
        "id": row["id"],
        "part_code": row["part_code"],
        "compatible_sku": row["compatible_sku"],
        "on_hand_qty": row["on_hand_qty"],
        "stock_received_qty": row["stock_received_qty"],
        "reserved_qty": row["reserved_qty"],
        "consumed_qty": row["consumed_qty"],
        "safety_stock_qty": row["safety_stock_qty"],
        "part_lot_key": row["part_lot_key"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def class_session_view(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "instructor_name": row["instructor_name"],
        "discipline": row["discipline"],
        "delivery_mode": row["delivery_mode"],
        "starts_at": clock.fmt(row["starts_at"]),
        "ends_at": clock.fmt(row["ends_at"]),
        "capacity": row["capacity"],
        "license_starts_at": clock.fmt(row["license_starts_at"]),
        "license_ends_at": clock.fmt(row["license_ends_at"]),
        "scheduled_status": row["scheduled_status"],
        "live_enrollment_count": row["live_enrollment_count"],
        "on_demand_window_ends_at": clock.fmt(row["on_demand_window_ends_at"]),
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def class_enrollment_view(row):
    return {
        "id": row["id"],
        "class_session_id": row["class_session_id"],
        "device_id": row["device_id"],
        "enroller_user_id": row["enroller_user_id"],
        "enrolled_at": clock.fmt(row["enrolled_at"]),
        "status": row["status"],
        "output_points": row["output_points"],
        "integrity_points": row["integrity_points"],
        "integrity_flagged": row["integrity_flagged"],
        "completion_pct": row["completion_pct"],
        "completion_grade": row["completion_grade"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }


def refurb_batch_view(row):
    return {
        "id": row["id"],
        "source_device_id": row["source_device_id"],
        "performance_resale_enabled": row["performance_resale_enabled"],
        "certification_grade": row["certification_grade"],
        "inspected_at": clock.fmt(row["inspected_at"]),
        "status": row["status"],
        "sold_device_id": row["sold_device_id"],
        "certification_chain_depth": row["certification_chain_depth"],
        "resale_price_cents": row["resale_price_cents"],
        "library_availability": row["library_availability"],
        "created_at": clock.fmt(row["created_at"]),
        "updated_at": clock.fmt(row["updated_at"]),
        "version": row["version"],
    }