"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def assert_brand_owner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["home_country"], str) and len(data["home_country"]) > 0
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_territory(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["region_label"], str)
    assert isinstance(data["brand_owner_id"], str)
    assert data["status"] in ["OPEN", "FRANCHISED", "REFRANCHISED"]


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["territory_id"], str)
    assert isinstance(data["bottler_name"], str)
    assert data["marketing_accrual_basis"] in ["CASE_VOLUME", "NET_REVENUE"]
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "REFRANCHISED"]
    assert isinstance(data["marketing_fund_balance_cents"], int)
    assert isinstance(data["service_budget_cents"], int)
    assert isinstance(data["service_spent_cents"], int)
    assert isinstance(data["margin_ledger_cents"], int)


def assert_product_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["brand_owner_id"], str)
    assert isinstance(data["line_code"], str)
    assert data["concentrate_base_price_per_gallon"] > 0
    assert isinstance(data["is_mandatory"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_price_index(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # append-only family: no updated_at / version
    assert "updated_at" not in data, "append-only row must omit updated_at"
    assert "version" not in data, "append-only row must omit version"
    assert isinstance(data["brand_owner_id"], str)
    assert isinstance(data["quarter"], str)
    assert data["index_value"] > 0


def assert_cpo(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["product_line_id"], str)
    assert isinstance(data["quantity_gallons"], int)
    assert data["fulfillment_status"] in ["PLACED", "RECEIVED", "CANCELLED"]
    assert data["pricing_status"] in ["PROVISIONAL", "FINALIZED"]
    assert data["provisional_unit_price"] is not None
    assert isinstance(data["provisional_amount_cents"], int)


def assert_nca(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["brand_owner_id"], str)
    assert isinstance(data["nca_code"], str)
    assert isinstance(data["national_price_cents"], int)
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUSPENDED", "EXPIRED"]


def assert_customer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["name"], str)
    assert data["channel"] in ["RETAIL", "FOUNTAIN"]
    assert isinstance(data["local_price_cents"], int)
    assert isinstance(data["bound_price_cents"], int)
    assert data["status"] in ["ACTIVE", "DISPUTED", "INACTIVE"]


def assert_dsd_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["customer_id"], str)
    assert data["fulfillment_status"] in ["BOOKED", "DELIVERED", "VOIDED"]
    assert data["payment_status"] in ["UNPAID", "PAID"]
    assert isinstance(data["invoice_total_cents"], int)


def assert_equipment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["asset_tag"], str)
    assert data["status"] in ["IN_WAREHOUSE", "PLACED", "UNDER_SERVICE"]


def assert_service_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only row must omit updated_at"
    assert "version" not in data, "append-only row must omit version"
    assert isinstance(data["equipment_id"], str)
    assert isinstance(data["technician_label"], str)
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0


def assert_fountain_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["customer_id"], str)
    assert data["syrup_on_hand_gallons"] >= 0
    assert isinstance(data["maintenance_overdue"], bool)


def assert_syrup_delivery(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert "updated_at" not in data, "append-only row must omit updated_at"
    assert "version" not in data, "append-only row must omit version"
    assert isinstance(data["fountain_account_id"], str)
    assert data["gallons"] > 0


def assert_territory_transfer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["territory_id"], str)
    assert isinstance(data["buyer_name"], str)
    assert isinstance(data["reported_ebitda_cents"], int) and data["reported_ebitda_cents"] > 0
    assert isinstance(data["valuation_round"], int)
    assert data["status"] in ["PROPOSED", "VALUED", "NEGOTIATING", "APPROVED", "EXECUTED", "REJECTED"]


def assert_innovation_launch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["agreement_id"], str)
    assert isinstance(data["product_line_id"], str)
    assert isinstance(data["committed_cases"], int) and data["committed_cases"] > 0
    assert isinstance(data["cases_sold"], int)
    assert isinstance(data["changeover_completed"], bool)
    assert data["status"] in [
        "PLANNED", "CHANGEOVER_SCHEDULED", "IN_PRODUCTION",
        "COMMIT_REVIEW", "MET", "PENALIZED", "EXTENDED",
    ]


def assert_fund_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert "updated_at" not in data, "append-only row must omit updated_at"
    assert "version" not in data, "append-only row must omit version"
    assert isinstance(data["agreement_id"], str)
    assert data["entry_type"] in ["ACCRUAL", "DISBURSEMENT", "CLAWBACK"]
    assert isinstance(data["period"], str)
    assert isinstance(data["amount_cents"], int)


def assert_agreement_ledger_invariants(data: dict):
    """Invariants that hold on a BottlerAgreement at rest."""
    assert isinstance(data["service_spent_cents"], int)
    assert data["service_spent_cents"] >= 0
    assert data["service_spent_cents"] <= data["service_budget_cents"]
