"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_timestamp(value: str, field: str = "timestamp"):
    assert is_iso8601_timestamp(value), f"{field} must be an ISO 8601 timestamp, got {value!r}"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["store_status"] in ["OPEN", "ACTIVE", "SUSPENDED"]
    assert isinstance(data["credit_capacity_cents"], int)
    assert data["open_repair_liability_cents"] >= 0
    assert data["open_inspection_count"] >= 0
    assert data["available_credit_capacity_cents"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["account_status"] in ["NO_FILE", "OPEN", "SUSPENDED", "CLOSED"]
    assert data["credit_tier"] in ["NO_FILE", "TIER_1", "TIER_2", "TIER_3"]
    assert data["standalone_credit_limit_cents"] >= 0
    assert data["revolving_utilization_bps"] >= 0
    assert data["lifetime_purchase_cents"] >= 0
    assert data["outstanding_balance_cents"] >= 0
    assert data["lost_inspection_streak"] >= 0


def assert_credit_application(data: dict):
    _assert_common(data)
    assert data["policy_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["decision_status"] in [
        "PENDING", "APPROVED", "COUNTERED", "DECLINED", "EXPIRED",
    ]
    assert data["decision_tier"] in ["TIER_1", "TIER_2", "TIER_3", None]
    assert data["approved_limit_cents"] >= 0
    assert data["min_down_payment_required_cents"] >= 0
    assert data["down_payment_shortfall_cents"] >= 0
    assert_timestamp(data["expires_at"], "expires_at")


def assert_promotional_plan(data: dict):
    _assert_common(data)
    assert data["plan_code"] in ["PROMO_12_6M", "PROMO_18_6M", "PROMO_24_12M"]
    assert data["plan_status"] in [
        "ACCRUING", "PAID", "CAPITALIZED", "DEFAULTED", "VOIDED",
    ]
    assert data["principal_cents"] >= 0
    assert data["installment_quarter_cents"] >= 0
    assert data["installment_amount_cents"] == data["installment_quarter_cents"]
    assert data["deferred_interest_accrued_cents"] >= 0
    assert data["final_settlement_amount_cents"] >= 0
    assert data["total_paid_cents"] >= 0
    assert_timestamp(data["simplicity_expires_at"], "simplicity_expires_at")


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a ledger entry is an immutable event record"
    assert "version" not in data, "a ledger entry carries no version"
    assert data["entry_kind"] in [
        "INSTALLMENT", "LUMPSUM_PAYOFF", "CAPITALIZATION", "TRADE_UP_CREDIT",
    ]
    assert data["direction"] in ["INCREASE", "DECREASE"]
    assert data["amount_cents"] >= 0
    assert data["entry_sequence"] >= 1
    assert data["reference_bucket"] in ["PROMOTIONAL", "CUSTOM_DESIGN", "RETAIL", None]


def assert_diamond(data: dict):
    _assert_common(data)
    assert isinstance(data["stone_code"], str) and data["stone_code"]
    assert data["stone_kind"] in ["NATURAL", "LAB_GROWN"]
    assert data["custody_status"] in ["IN_CASE", "IN_VAULT", "AT_VENDOR", "WITHDRAWN"]


def assert_bundle(data: dict):
    _assert_common(data)
    assert data["bundle_status"] in ["CURRENT", "RETIRED"]
    assert data["lifetime_plan_fee_cents"] >= 0
    assert data["stone_limit_labor_cents"] >= 0
    assert data["stone_limit_parts_cents"] >= 0
    assert data["inspection_interval_days"] >= 1
    assert data["inspection_cure_days"] >= 0


def assert_vendor_shop(data: dict):
    _assert_common(data)
    assert data["vendor_status"] in ["ACTIVE", "RETIRED"]
    assert data["base_turnaround_days"] >= 1
    assert data["open_repair_count"] >= 0


def assert_regulation(data: dict):
    _assert_common(data)
    assert len(data["state_code"]) == 2
    assert data["max_plan_term_months"] >= 1
    assert data["inspection_required_months"] >= 0
    assert data["lapse_cure_days"] >= 0


def assert_registration(data: dict):
    _assert_common(data)
    assert data["coverage_status"] in [
        "PENDING_INSPECTION", "REMINDER_ISSUED", "ACTIVE", "GRACE_PERIOD",
        "LAPSED", "RENEWED", "TERMINATED", "VOID",
    ]
    assert_timestamp(data["inspection_due_at"], "inspection_due_at")
    assert_timestamp(data["cure_expires_at"], "cure_expires_at")
    assert data["missed_inspection_count"] >= 0
    assert data["renewal_count"] >= 0
    assert data["replacement_claims_used"] >= 0
    assert isinstance(data["is_valid"], bool)
    assert data["is_valid"] == (data["coverage_status"] == "ACTIVE")


def assert_inspection_visit(data: dict):
    _assert_common(data)
    assert data["result"] in ["SCHEDULED", "CLAIMED", "NO_SHOW"]
    assert data["inspection_status"] in ["SCHEDULED", "CLAIMED", "NO_SHOW"]
    assert_timestamp(data["visit_at"], "visit_at")


def assert_repair(data: dict):
    _assert_common(data)
    assert data["repair_status"] in [
        "INTAKE", "ROUTED", "IN_REPAIR", "QC_REVIEW",
        "COMPLETED", "UNREPAIRABLE", "VERIFIED_LOSS", "ABANDONED",
    ]
    assert data["failure_class"] in ["STONE_LOSS", "SETTING", "PRONG", "RESIZE", "OTHER"]
    assert data["loss_liability_cents"] >= 0
    assert data["store_absorbed_cents"] >= 0
    assert data["insurance_parts_cents"] >= 0
    assert data["customer_parts_cents"] >= 0
    assert data["customer_labor_cents"] >= 0
    assert_timestamp(data["accepted_at"], "accepted_at")


def assert_repair_hold(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a repair hold is an immutable event record"
    assert "version" not in data, "a repair hold carries no version"
    assert isinstance(data["deadline_adjusted"], bool)


def assert_appraisal(data: dict):
    _assert_common(data)
    assert data["appraisal_kind"] in ["INSURANCE", "REPLACEMENT"]
    assert data["appraisal_status"] in ["ISSUED", "CIRCULATED", "SUPERSEDED"]
    assert data["appraised_value_cents"] >= 0
    assert_timestamp(data["circulated_at"], "circulated_at")


def assert_purchase(data: dict):
    _assert_common(data)
    assert data["purchase_status"] in [
        "PENDING", "FINANCED", "COMPLETED", "TRADE_UP_APPLIED",
    ]
    assert data["base_price_cents"] >= 0
    assert data["trade_up_credit_cents"] >= 0
    assert data["net_amount_cents"] >= 0
    assert data["protection_fee_cents"] >= 0


def assert_custom_design_order(data: dict):
    _assert_common(data)
    assert data["design_status"] in [
        "DEPOSIT_PAID", "CAD_REVISION", "CAD_APPROVED",
        "IN_PRODUCTION", "COMPLETED", "CANCELLED",
    ]
    assert data["deposit_cents"] >= 0
    assert data["revision_count"] >= 0
    assert data["revision_fee_cents"] >= 0
    assert data["non_refundable_deposit_cents"] >= 0
    assert data["refundable_deposit_cents"] >= 0


def assert_billing_statement(data: dict):
    _assert_common(data)
    assert data["statement_status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["bucket_totals_cents"], dict)
    assert data["min_payment_due_cents"] >= 0
    assert data["statement_balance_cents"] >= 0


# --- Domain invariant checkers ---


def assert_registration_invariants(data: dict):
    """Cross-field invariants that must hold after any registration operation."""
    assert data["missed_inspection_count"] >= 0
    assert data["renewal_count"] >= 0
    assert data["is_valid"] == (data["coverage_status"] == "ACTIVE"), (
        "is_valid is true only while coverage_status is ACTIVE"
    )


def assert_repair_invariants(data: dict):
    """The liability split must stay a partition of the declared cost."""
    assert data["loss_liability_cents"] >= 0
    assert data["store_absorbed_cents"] == data["loss_liability_cents"], (
        "store_absorbed_cents equals the store-absorbed liability"
    )
    assert data["insurance_parts_cents"] >= 0
    assert data["customer_parts_cents"] >= 0
    assert_cost_precision(data["loss_liability_cents"])


def assert_purchase_invariants(data: dict):
    assert data["net_amount_cents"] == max(
        0, data["base_price_cents"] - data["trade_up_credit_cents"]
    ), "net_amount_cents is base_price_cents minus the credited trade-up, floored at 0"
    if data.get("origin_purchase_id") is None:
        assert data["trade_up_credit_cents"] == 0, (
            "with no origin named the stored trade_up_credit_cents is recomputed to 0"
        )


def assert_plan_invariants(data: dict):
    assert data["total_paid_cents"] >= 0
    assert_cost_precision(data["principal_cents"])
    if data["plan_status"] == "PAID":
        assert data["final_settlement_amount_cents"] == 0
        assert data["deferred_interest_accrued_cents"] == 0
        assert data["merchant_deferral_fee_cents"] == 0


def assert_customer_invariants(data: dict):
    assert data["outstanding_balance_cents"] >= 0
    assert data["lifetime_purchase_cents"] >= 0
    assert data["lost_inspection_streak"] >= 0
    if data["standalone_credit_limit_cents"] == 0:
        assert data["revolving_utilization_bps"] == 0, (
            "revolving_utilization_bps is 0 when the limit is 0"
        )


__all__ = [
    "assert_timestamp",
    "assert_store",
    "assert_customer",
    "assert_credit_application",
    "assert_promotional_plan",
    "assert_ledger_entry",
    "assert_diamond",
    "assert_bundle",
    "assert_vendor_shop",
    "assert_regulation",
    "assert_registration",
    "assert_inspection_visit",
    "assert_repair",
    "assert_repair_hold",
    "assert_appraisal",
    "assert_purchase",
    "assert_custom_design_order",
    "assert_billing_statement",
    "assert_registration_invariants",
    "assert_repair_invariants",
    "assert_purchase_invariants",
    "assert_plan_invariants",
    "assert_customer_invariants",
]