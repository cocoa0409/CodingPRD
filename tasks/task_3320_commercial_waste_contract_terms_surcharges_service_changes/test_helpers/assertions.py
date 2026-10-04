"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert isinstance(data.get("billing_email"), str) and len(data["billing_email"]) > 0
    assert isinstance(data.get("credit_balance_cents"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_contract(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a valid UUID"
    assert data.get("status") in (
        "DRAFT", "ACTIVE", "TERMINATION_PENDING", "TERMINATED"
    ), f"unexpected contract status {data.get('status')}"
    assert isinstance(data.get("term_months"), int) and data["term_months"] >= 1
    assert isinstance(data.get("current_term_index"), int)
    assert isinstance(data.get("base_monthly_total_cents"), int)
    assert isinstance(data.get("rofr_enabled"), bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_service_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("container_size") in ("CY_2", "CY_4", "CY_6", "CY_8")
    assert isinstance(data.get("frequency_per_week"), int)
    assert 1 <= data["frequency_per_week"] <= 6
    assert isinstance(data.get("base_rate_cents"), int) and data["base_rate_cents"] >= 0


def assert_pickup_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("outcome") in (
        "COMPLETED", "MISSED", "CONTAMINATED", "OVERWEIGHT", "CONTAMINATED_OVERWEIGHT"
    )
    assert isinstance(data.get("occurred_date"), str)
    assert isinstance(data.get("contamination_fee_cents"), int)
    assert isinstance(data.get("overweight_fee_cents"), int)
    assert data.get("dispute_status") in (
        "NONE", "DISPUTED", "RESOLVED_UPHELD", "RESOLVED_CREDITED"
    )
    assert isinstance(data.get("appeal_count"), int)


def assert_surcharge_config(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("fuel_mode") in ("FIXED", "INDEXED")
    assert isinstance(data.get("environmental_pct"), (int, float))
    assert isinstance(data.get("admin_pct"), (int, float))
    assert isinstance(data.get("contamination_fee_cents"), int)
    assert isinstance(data.get("overweight_fee_cents"), int)
    assert is_iso8601_timestamp(data.get("effective_from", ""))


def assert_rate_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("reason") in ("CPI", "FUEL_INDEX", "COST_RECOVERY")
    assert isinstance(data.get("pct_increase"), (int, float))
    assert data.get("status") in ("SCHEDULED", "APPLIED", "CANCELLED")


def assert_service_change_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("new_container_size") in ("CY_2", "CY_4", "CY_6", "CY_8")
    assert isinstance(data.get("new_frequency_per_week"), int)
    assert isinstance(data.get("old_rate_cents"), int)
    assert isinstance(data.get("quoted_new_rate_cents"), int)
    assert data.get("status") in ("PENDING", "APPROVED", "APPLIED", "REJECTED", "CANCELLED")


def assert_competing_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("competitor_monthly_cents"), int)
    assert data.get("status") in ("SUBMITTED", "MATCHED", "NOT_MATCHED", "VOID")


def assert_cancellation_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("timely"), bool)
    assert isinstance(data.get("months_remaining"), int)
    assert isinstance(data.get("ld_total_cents"), int)
    assert data.get("ld_status") in ("NONE", "ASSESSED", "WAIVED")
    assert data.get("status") in ("PENDING", "APPROVED", "DENIED", "WITHDRAWN")


def assert_service_credit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data.get("credit_cents"), int)
    assert data.get("status") in ("ACTIVE", "CANCELLED")


def assert_rolloff_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data.get("container_size") in ("YD_10", "YD_20", "YD_30", "YD_40")
    assert isinstance(data.get("rental_days"), int) and 1 <= data["rental_days"] <= 30
    assert isinstance(data.get("total_cents"), int)
    assert data.get("status") in ("RESERVED", "DELIVERED", "COMPLETED", "CANCELLED")


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a valid UUID"
    assert data.get("source") in ("RATE_NOTICE", "SERVICE_CHANGE", "ROFR_MATCH")
    assert isinstance(data.get("old_base_monthly_cents"), int)
    assert isinstance(data.get("new_base_monthly_cents"), int)
    # Ledger entries are immutable: no version, no updated_at.
    assert "version" not in data, "ledger entries must not carry a version field"
    assert "updated_at" not in data, "ledger entries must not carry an updated_at field"
