"""Per-entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    ALL_DEVICE_STATUSES,
    ALL_MEMBERSHIP_STATUSES,
    ALL_POSTURES,
)


def assert_common_fields(data: dict):
    """Every entity exposes id, created_at, updated_at and version (PRD §2.11)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare server UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_membership(data: dict):
    """Validate a Membership response against the PRD contract."""
    assert_common_fields(data)
    assert data["status"] in ALL_MEMBERSHIP_STATUSES, f"unknown status {data['status']!r}"
    assert data["posture"] in ALL_POSTURES, f"unknown posture {data['posture']!r}"
    assert data["plan_tier"] in ("PLUS", "BUSINESS")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["active_user_count"], int) and data["active_user_count"] >= 0
    assert isinstance(data["concurrent_limit_effective"], int)
    assert isinstance(data["safety_gate_open"], bool)
    assert isinstance(data["unpaid_financing_count"], int)
    assert isinstance(data["accrued_pause_credit_cents"], int)
    assert is_iso8601_timestamp(data["billing_cycle_start_at"])
    assert is_iso8601_timestamp(data["paid_through_at"])


def assert_household_user(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED", "REMOVED")
    assert data["role"] in ("OWNER", "MEMBER")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["verified"], bool)
    assert isinstance(data["eviction_count"], int)


def assert_device(data: dict):
    assert_common_fields(data)
    assert data["activation_status"] in ALL_DEVICE_STATUSES
    assert data["hardware_sku"] in ("BIKE", "TREAD", "ROWER", "REFURB_BIKE", "REFURB_TREAD")
    assert data["condition"] in ("NEW", "REFURBISHED")
    assert isinstance(data["serial"], str) and data["serial"]
    assert isinstance(data["entitlement_lock"], bool)
    assert isinstance(data["content_access_allowed"], bool)
    assert isinstance(data["total_workouts"], int)
    assert isinstance(data["resale_cycle_count"], int)


def assert_hardware_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLACED", "DELIVERY_SCHEDULED", "DELIVERED", "ACTIVATED", "CANCELLED")
    assert data["financing_method"] in ("FULL_PAYMENT", "FINANCE_SCHEDULED")
    assert data["refund_dispute_status"] in ("NONE", "FILED", "DENIED", "APPROVED")
    for field in (
        "subtotal_cents",
        "quote_total_cents",
        "delivery_fee_cents",
        "stair_carry_fee_cents",
        "assembly_fee_cents",
        "finance_charge_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count of cents"


def assert_delivery_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED",
    )
    assert data["zone"] in ("METRO", "SUBURBAN", "RURAL")
    assert isinstance(data["delivery_legs"], int)
    assert isinstance(data["reschedule_count"], int)


def assert_financing_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ORIGINATED", "CURRENT", "DELINQUENT", "DEFAULTED", "PAID_OFF")
    assert data["safety_disable_latched"] is False, (
        "safety_disable_latched must be false in every financing state"
    )
    assert isinstance(data["installments_paid"], int)
    assert isinstance(data["retry_count"], int)
    assert isinstance(data["delinquency_count"], int)
    assert isinstance(data["monthly_installment_cents"], int)


def assert_service_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DISPATCHED", "DISPATCH_PENDING_PART", "PART_RESERVED",
        "SCHEDULED", "REPAIR_IN_PROGRESS", "RESOLVED", "CANCELLED",
    )
    assert data["fault_class"] in ("SAFETY_CRITICAL", "COSMETIC")
    assert data["priority"] in ("PRIORITY_SAFETY", "PRIORITY_WARRANTY", "PRIORITY_STANDARD")
    assert data["safety_functions_maintained"] is True, (
        "safety_functions_maintained must always be true"
    )


def assert_part(data: dict):
    assert_common_fields(data)
    for field in ("on_hand_qty", "stock_received_qty", "reserved_qty", "consumed_qty",
                  "safety_stock_qty"):
        assert isinstance(data[field], int), f"{field} must be an integer quantity"
    assert data["compatible_sku"] in ("BIKE", "TREAD", "ROWER", "REFURB_BIKE", "REFURB_TREAD")


def assert_class_session(data: dict):
    assert_common_fields(data)
    assert data["scheduled_status"] in (
        "DRAFT", "PUBLISHED", "STREAMING", "ARCHIVED", "CANCELLED",
    )
    assert data["discipline"] in ("CYCLING", "RUNNING", "STRENGTH", "YOGA")
    assert data["delivery_mode"] in ("LIVE", "ON_DEMAND")
    assert isinstance(data["live_enrollment_count"], int)


def assert_class_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ENROLLED", "WAITLISTED", "COMPLETED", "DROPPED", "EXPIRED")
    assert isinstance(data["integrity_points"], int)
    assert isinstance(data["integrity_flagged"], bool)
    if data["status"] == "COMPLETED":
        assert data["completion_grade"] in ("FULL_CREDIT", "PARTIAL_CREDIT")


def assert_refurb_batch(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("INSPECTING", "CERTIFIED", "LISTED", "SOLD")
    assert data["certification_grade"] in ("A", "B", "C")
    assert isinstance(data["certification_chain_depth"], int)
    assert data["library_availability"] in ("AVAILABLE", "UNAVAILABLE")


# ─── Domain invariants ─────────────────────────────────

def assert_membership_invariants(data: dict):
    """Invariants that must hold after any operation touching a membership."""
    assert data["safety_gate_open"] is True, (
        "no financing or entitlement path may clear safety_gate_open"
    )
    if data["status"] == "CANCELLED":
        assert data["posture"] == "FROZEN"
    if data["status"] == "TERMINATED":
        assert data["posture"] == "FROZEN"
    if data["unpaid_financing_count"] >= 1 and data["status"] not in ("CANCELLED", "TERMINATED"):
        assert data["posture"] == "RESTRICTED"
    if data["status"] == "PAUSED":
        assert data["posture"] == "RESTRICTED"


def assert_parts_books_balance(data: dict):
    """on_hand_qty is always stock_received_qty - reserved_qty - consumed_qty."""
    assert data["on_hand_qty"] == (
        data["stock_received_qty"] - data["reserved_qty"] - data["consumed_qty"]
    ), "the stock identity must balance at every observation point"


def assert_safety_floor(data: dict):
    """No financing plan may ever latch safety off."""
    assert data["safety_disable_latched"] is False


def assert_financing_amortization(total_due_cents: int, term_months: int,
                                  monthly_installment_cents: int):
    """ceil-first / floor-rest construction: the first installment absorbs the
    whole remainder and every later installment is the base."""
    base = total_due_cents // term_months
    remainder = total_due_cents - base * term_months
    assert monthly_installment_cents == base + remainder, (
        f"first installment must be base {base} + remainder {remainder}"
    )


def amortized_sum(installments_paid: int, total_due_cents: int, term_months: int) -> int:
    """Sum actually collected after `installments_paid` settled installments."""
    base = total_due_cents // term_months
    remainder = total_due_cents - base * term_months
    if installments_paid < term_months:
        return installments_paid * base + remainder
    return total_due_cents


def delivery_fee_cents(hardware_sku: str, zone: str) -> int:
    """Delivery charge: lesser of legs × zone base and zone base + weight × tier rate."""
    from .constants import (
        DELIVERY_LEGS_BY_ZONE, TIER_RATE_CENTS_BY_LEGS, WEIGHT_UNITS, ZONE_BASE_CENTS,
    )
    legs = DELIVERY_LEGS_BY_ZONE[zone]
    base = ZONE_BASE_CENTS[zone]
    weight = WEIGHT_UNITS[hardware_sku]
    tier_rate = TIER_RATE_CENTS_BY_LEGS[min(legs, 3)]
    return min(legs * base, base + weight * tier_rate)


def advisory_stair_surcharge_cents(stair_flights: int, has_elevator: bool) -> int:
    """Per-term rounding then cap; the order of arithmetic is pinned."""
    from .constants import (
        CARRY_FEE_CAP_CENTS, FINE_RATE_CENTS, FIRST_FLIGHT_FLAT_CENTS, TAX_BASIS,
    )
    eligible = max(0, stair_flights - (1 if has_elevator else 0))
    billable = max(0, eligible - 1)
    flat = round(FIRST_FLIGHT_FLAT_CENTS * TAX_BASIS)
    per_flight = round(billable * FINE_RATE_CENTS * TAX_BASIS)
    return min(flat + per_flight, CARRY_FEE_CAP_CENTS)