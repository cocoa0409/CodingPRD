"""Per-entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """A resource carrying the full common field set (§2.8)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_service_provider(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["provider_type"] in ("AGREED", "SUCCESSOR")
    assert data["status"] in ("UNDER_REVIEW", "APPROVED", "SUSPENDED")
    assert isinstance(data["brand_compliance_pct"], (int, float))
    assert isinstance(data["qualification_pct"], (int, float))
    assert isinstance(data["lifetime_paid_cents"], int)
    assert isinstance(data["chargeback_outstanding_cents"], int)


def assert_service_area(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("UNASSIGNED", "ASSIGNED", "ARCHIVED")
    assert isinstance(data["stop_capacity_weekly"], int)
    assert data["stop_capacity_weekly"] >= 1
    assert data.get("assigned_provider_id") is None or is_valid_uuid(data["assigned_provider_id"])


def assert_route_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "PENDING_TRANSFER", "TRANSFERRED", "TERMINATED")
    assert isinstance(data["transfer_price_cents"], int)
    assert isinstance(data["compliance_failures_count"], int)
    assert data.get("occupancy_ends_at") is None or is_iso8601_timestamp(data["occupancy_ends_at"])


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "RE_NEGOTIATION", "ACTIVE", "EXPIRED", "TERMINATED"
    )
    assert isinstance(data["base_rate_cents_per_stop"], int)
    assert isinstance(data["package_rate_cents"], int)
    assert isinstance(data["insurance_coverage_cents"], int)


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert data["vehicle_class"] in ("STEP_VAN", "BOX_TRUCK", "TRACTOR_TRAILER")
    assert data["branding_compliance"] in ("PASSED", "FAILED")
    assert data["status"] in ("PENDING", "ACTIVE", "DECOMMISSIONED")
    assert isinstance(data["is_temporary"], bool)


def assert_driver(data: dict):
    assert_common_fields(data)
    assert data["license_class"] in ("CLASS_C", "CLASS_B", "CLASS_A")
    assert data["qualification_status"] in ("QUALIFIED", "UNQUALIFIED")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_insurance_policy(data: dict):
    assert_common_fields(data)
    assert data["policy_type"] in ("AUTO_LIABILITY", "CARGO", "GENERAL_LIABILITY")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "EXPIRED", "REJECTED")
    assert isinstance(data["coverage_cents"], int)


def assert_settlement_period(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "ACCRUAL_CLOSED", "RECONCILED", "DISPUTED", "RELEASED")
    assert isinstance(data["is_peak_week"], bool)
    assert isinstance(data["net_amount_cents"], int)
    assert isinstance(data["base_gross_cents"], int)


def assert_performance_metric(data: dict):
    assert_common_fields(data)
    for field in ("service_score", "safety_score", "customer_experience_score"):
        assert 0.00 <= data[field] <= 100.00, f"{field} must lie in [0.00, 100.00]"
    assert 0.00 <= data["composite_score"] <= 100.00


def assert_chargeback_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_type"] in ("DAMAGE", "MISSED_PICKUP", "EQUIPMENT")
    assert data["status"] in ("FILED", "APPROVED", "REJECTED", "SETTLED")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_peak_declaration(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DECLARED", "ACTIVE", "ENDED", "CANCELED")
    assert isinstance(data["authorized_vehicles"], int)
    assert isinstance(data["authorized_drivers"], int)


# ── Append-only entities: id + created_at only, no updated_at / version (§2.8) ──

def assert_stop_observation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "StopObservation carries no updated_at"
    assert "version" not in data, "StopObservation carries no version"
    assert isinstance(data["stops_count"], int) and data["stops_count"] >= 0


def assert_settlement_deduction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "SettlementDeduction carries no updated_at"
    assert "version" not in data, "SettlementDeduction carries no version"
    assert data["deduction_type"] in ("FUEL", "MAINTENANCE", "ACCESSORIAL", "CHARGEBACK")


def assert_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Dispute carries no updated_at"
    assert "version" not in data, "Dispute carries no version"
    assert data["status"] in (
        "OPEN", "EVIDENCE_SUBMITTED", "COUNTERED", "ESCALATED", "RESOLVED", "WITHDRAWN"
    )


# ── Domain invariants (§2.4) ──────────────────────────────────────

def assert_provider_money_invariants(data: dict):
    """Conserved monetary totals are non-negative integer cents."""
    assert isinstance(data["lifetime_paid_cents"], int)
    assert data["lifetime_paid_cents"] >= 0
    assert isinstance(data["chargeback_outstanding_cents"], int)
    assert data["chargeback_outstanding_cents"] >= 0


def assert_percent_in_range(pct: float, lower=0.00, upper=100.00):
    assert lower <= pct <= upper, f"percentage {pct} outside [{lower}, {upper}]"


def assert_settlement_identity(base_gross_cents: int, net_amount_cents: int,
                               non_chargeback_deduction_sum_cents: int):
    """§3.8 — base_gross − net equals the sum of non-CHARGEBACK deduction amounts."""
    assert base_gross_cents - net_amount_cents == non_chargeback_deduction_sum_cents, (
        f"base_gross {base_gross_cents} − net {net_amount_cents} != "
        f"non-CHARGEBACK deductions {non_chargeback_deduction_sum_cents}"
    )