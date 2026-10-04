"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

# ─── Common shape ─────────────────────────────────────

def assert_common_fields(data: dict):
    """Every persistable resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


# ─── Per-entity assertions ────────────────────────────

def assert_region(data: dict):
    assert_common_fields(data)
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN"), data.get("posture")
    assert isinstance(data["state_codes"], list) and len(data["state_codes"]) > 0
    for cents_field in (
        "premium_revenue_cents",
        "employed_delivery_cost_cents",
        "outside_services_spend_cents",
        "operating_margin_cents",
        "computed_margin_cents",
        "referential_integration_credit_cents",
        "open_alert_count",
        "staffing_and_facility_cents",
        "capacity_budget_appointments",
        "capacity_committed_appointments",
        "member_count",
    ):
        if cents_field in data:
            assert isinstance(data[cents_field], int), f"{cents_field} must be integer cents"


def assert_region_invariants(data: dict):
    """Domain invariants that hold after any operation on a region."""
    assert data["open_alert_count"] >= 0
    assert data["member_count"] >= 0
    assert data["capacity_budget_appointments"] >= 0
    assert data["capacity_committed_appointments"] >= 0


def assert_member(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "TRANSFER_PENDING", "SUSPENDED", "TERMINATED")
    assert isinstance(data["capitation_rate_cents"], int)
    assert isinstance(data["risk_score"], (int, float))


def assert_care_site(data: dict):
    assert_common_fields(data)
    assert data["site_type"] in ("MEDICAL_CENTER", "HOSPITAL", "MEDICAL_OFFICE")
    assert isinstance(data["staffing_fte_filled"], (int, float))
    assert isinstance(data["facility_investment_spent_cents"], int)


def assert_department(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "CONSTRAINED", "CLOSED")
    assert isinstance(data["appointment_slots_committed"], int)
    assert isinstance(data["accepting_internal_referrals"], bool)


def assert_provider(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PANEL_CLOSED")
    assert data["volume_component_cents"] == 0, "volume component is pinned to zero"
    assert isinstance(data["comp_total_cents"], int)


def assert_network_service(data: dict):
    assert_common_fields(data)
    assert data["availability_status"] in ("AVAILABLE", "CONSTRAINED", "UNAVAILABLE")
    assert isinstance(data["available_provider_count"], int)


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert data["fulfillment_status"] in (
        "REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"
    )
    assert data["appointment_type"] in ("ROUTINE", "SPECIALTY", "URGENT", "FOLLOW_UP")
    if data.get("access_status") is not None:
        assert data["access_status"] in (
            "WITHIN_ACCESS_TARGET", "BREACHED_ACCESS_TARGET"
        )


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PENDING_TRIAGE", "AUTHORIZED", "SCHEDULED", "COMPLETED",
        "DENIED", "APPEALED", "EXPIRED", "HELD",
    )
    assert isinstance(data["appeal_rounds"], int)


def assert_outside_service_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "PENDED", "ADJUDICATED", "PAID", "DENIED", "APPEALED"
    )
    assert data["claim_type"] in ("EMERGENCY", "CONTRACTED", "OUT_OF_AREA", "DIRECT")


def assert_regional_budget(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "CLOSED", "REOPENED")
    assert isinstance(data["staffing_budget_cents"], int)


def assert_capacity_plan(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PLANNING", "UNDER_REVIEW", "ACTIVE", "ADJUSTED", "FROZEN"
    )
    assert data["supply_shortfall_slots"] >= 0, "supply shortfall is floored at zero"


def assert_member_transfer(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "PENDING_EFFECTIVE", "COMPLETED", "REJECTED", "CANCELLED"
    )
    assert isinstance(data["network_difference_flag"], bool)


def assert_quality_metric(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("MEASURING", "FINALIZED", "REMEDIATION", "REOPENED")
    assert data["metric_code"] in (
        "ACCESS_WAIT_DAYS", "QUALITY_COMPOSITE", "MEMBER_SATISFACTION", "PANEL_AVAILABILITY"
    )


def assert_referential_integration(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PROPOSED", "BOUND", "ENROLLED", "CONTRACTED", "TERMINATED"
    )
    assert data["integration_type"] in (
        "PAYER_ENTITY", "MEDICAL_GROUP", "HOSPITAL_ENTITY", "TPA_PLATFORM"
    )
    assert isinstance(data["settlement_account_cents"], int)


def assert_alert(data: dict):
    assert_common_fields(data)
    assert data["alert_type"] in (
        "POSTURE_CHANGE", "BUDGET_BREACH", "QUALITY_GAP", "CAPACITY_SHORTFALL"
    )
    assert data["severity"] in ("INFO", "WARNING", "CRITICAL")
    assert data["status"] in ("RAISED", "ACKNOWLEDGED")