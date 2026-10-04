"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _common(data: dict):
    """Every top-level resource carries the four system-managed properties."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_driver(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["platform_driver_id"].startswith("PLT-")
    assert 0 <= data["platform_activity_score"] <= 100
    assert 0 <= data["driving_record_points"] <= 12
    assert data["license_class"] in ("STANDARD", "FOR_HIRE", "COMMERCIAL")
    assert data["program_driver_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert data["eligibility_status"] in (
        "PENDING", "ELIGIBLE", "INELIGIBLE", "SUSPENDED"
    )


def assert_enrollment(data: dict):
    _common(data)
    assert is_valid_uuid(data["driver_id"])
    assert data["program_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert 0 <= data["eligibility_score"] <= 100
    assert data["eligibility_decision"] in ("APPROVED", "DENIED", "DEFERRED")
    assert data["enrollment_status"] in (
        "PENDING_VERIFICATION", "ACTIVE", "REJECTED", "SUSPENDED", "WITHDRAWN"
    )


def assert_vehicle(data: dict):
    _common(data)
    assert len(data["vin"]) == 17, "vin is exactly 17 characters"
    assert isinstance(data["model_name"], str) and data["model_name"]
    assert 2018 <= data["model_year"] <= 2027
    assert data["vehicle_class"] in ("STANDARD", "XL", "LUXURY", "DELIVERY_VAN")
    assert isinstance(data["qualifies_ride"], bool)
    assert isinstance(data["qualifies_delivery"], bool)
    assert data["odometer_miles"] >= 0
    assert data["vehicle_status"] in (
        "AVAILABLE", "ASSIGNED", "MAINTENANCE", "RECOVERY", "RETIRED"
    )
    assert len(data["region_code"]) == 2 and data["region_code"].isupper()


def assert_agreement(data: dict):
    _common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["driver_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["weekly_rate_cents"] >= 0
    assert data["insurance_premium_cents"] >= 0
    assert isinstance(data["unlimited_mileage"], bool)
    assert data["maintenance_allowance_miles"] >= 0
    assert data["compliance_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["agreement_status"] in (
        "DRAFT", "ACTIVE", "RENEWAL_DUE", "DELINQUENT", "RECOVERY_PENDING",
        "RECOVERED", "COMPLETED", "PURCHASE_PENDING", "PURCHASED",
    )
    assert data["current_week_number"] >= 0
    assert data["total_billed_cents"] >= 0
    assert data["total_waived_cents"] >= 0
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])


def assert_week(data: dict):
    _common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["week_number"] >= 1
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert data["miles_driven"] >= 0
    assert data["week_status"] in (
        "SCHEDULED", "OPEN", "DUE", "PAID", "GRACE", "DELINQUENT",
        "DEFERRED", "RECOVERED", "WAIVED",
    )
    assert data["payment_status"] in ("UNPAID", "PARTIAL", "SETTLED", "FAILED")
    for field in ("base_charge_cents", "insurance_charge_cents",
                  "mileage_overage_cents", "damage_charge_cents",
                  "platform_credit_cents", "amount_due_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer number of cents"


def assert_maintenance_event(data: dict):
    _common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["event_type"] in (
        "SCHEDULED_SERVICE", "UNSCHEDULED_REPAIR", "DAMAGE_REPAIR"
    )
    assert data["odometer_at_service"] >= 0
    assert data["downtime_hours"] >= 0
    assert data["event_status"] in (
        "REPORTED", "IN_PROGRESS", "LOANER_ISSUED", "COMPLETED"
    )
    assert data["damage_liability_cents"] >= 0
    assert data["maintenance_allowance_applied_miles"] >= 0
    assert data["earnings_interruption_hours"] >= 0


def assert_payment(data: dict):
    _common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["amount_cents"] >= 0
    assert data["payment_outcome"] in ("SUCCEEDED", "FAILED")


def assert_purchase_option(data: dict):
    _common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["driver_id"])
    assert data["option_status"] in (
        "OFFERED", "ELECTED", "ESCROW_FUNDED", "COMPLETED", "WITHDRAWN"
    )
    assert data["purchase_price_cents"] >= 0
    assert data["equity_credit_cents"] >= 0
    assert data["escrow_balance_cents"] >= 0
    assert data["escrow_weeks_required"] >= 1
    assert 0 <= data["escrow_weeks_funded"] <= data["escrow_weeks_required"]


def assert_platform_integration(data: dict):
    _common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["integration_result"] in (
        "QUALIFIED", "REJECTED_RIDE", "REJECTED_DELIVERY", "REJECTED_MODEL"
    )
    assert isinstance(data["ride_qualified"], bool)
    assert isinstance(data["delivery_qualified"], bool)
    assert isinstance(data["model_restriction_hit"], bool)
    assert is_iso8601_timestamp(data["checked_at"])


def assert_fleet_fact(data: dict):
    _common(data)
    assert len(data["region_code"]) == 2 and data["region_code"].isupper()
    assert data["demand_units"] >= 0
    assert data["active_agreements_count"] >= 0
    assert data["available_fleet_count"] >= 0
    assert 0 <= data["utilization_bps"] <= 20_000
    assert isinstance(data["sizing_deficit_units"], int)
    assert data["fleet_fact_status"] in (
        "BALANCED", "UNDER_SUPPLIED", "OVER_SUPPLIED"
    )


# ─── Domain invariant checkers ────────────────────────

def assert_week_money_invariants(data: dict):
    """The week's net amount is the pinned component sum."""
    expected = (
        data["base_charge_cents"]
        + data["insurance_charge_cents"]
        + data["mileage_overage_cents"]
        + data["damage_charge_cents"]
        - data["platform_credit_cents"]
    )
    assert data["amount_due_cents"] == expected, (
        f"amount_due_cents {data['amount_due_cents']} != component sum {expected}"
    )
    assert data["amount_due_cents"] >= 0
    for field in ("base_charge_cents", "insurance_charge_cents",
                  "mileage_overage_cents", "damage_charge_cents",
                  "platform_credit_cents", "amount_due_cents"):
        assert_cost_precision(float(data[field]), 0)


def assert_agreement_posture_matches_delinquency(data: dict, delinquent_weeks: int):
    """The posture is a derived reading of the delinquent-week count."""
    expected = "OPEN" if delinquent_weeks == 0 else (
        "RESTRICTED" if delinquent_weeks == 1 else "FROZEN"
    )
    assert data["compliance_posture"] == expected, (
        f"{delinquent_weeks} delinquent weeks implies {expected}, "
        f"got {data['compliance_posture']}"
    )


def assert_assigned_units_conserved(before: int, after: int):
    """The compensating loaner pair leaves the assigned-unit count unchanged."""
    assert before == after, (
        f"assigned-fleet-unit count moved from {before} to {after}"
    )


def assert_platform_credit(credit_cents: int, expected_cents: int):
    assert credit_cents == expected_cents, (
        f"platform credit expected {expected_cents}, got {credit_cents}"
    )
    assert credit_cents <= 600, "the platform credit is capped at 600 cents"


def assert_cents_equal(actual, expected, label="amount"):
    """Exact integer-cents comparison — no floating-point dollars anywhere."""
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_amount_due_exact(actual: int, expected: int, action: str = "settlement"):
    assert actual == expected, (
        f"amount_due_cents expected {expected} after {action}, got {actual}"
    )


def assert_approx_cents(actual: int, expected: int, abs_tol: int = 1):
    assert actual == pytest.approx(expected, abs=abs_tol), (
        f"expected {expected} cents, got {actual}"
    )