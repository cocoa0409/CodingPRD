"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(str(data.get("created_at", ""))), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(str(data.get("updated_at", ""))), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, f"{entity}.version must be an int >= 1"


def assert_site(data: dict):
    _assert_common(data, "Site")
    assert isinstance(data.get("site_code"), str) and data["site_code"]
    assert isinstance(data.get("address"), str) and data["address"]
    assert data.get("acquisition_type") in ("FEE_SIMPLE", "GROUND_LEASE")
    assert data.get("holding_status") in ("HELD", "COMMITTED", "DIVESTED")


def assert_operator(data: dict):
    _assert_common(data, "Operator")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("status") in ("CANDIDATE", "APPROVED", "SUSPENDED", "TERMINATED")
    assert isinstance(data.get("fy_net_worth_cents"), int)
    assert isinstance(data.get("fy_operating_income_cents"), int)
    assert isinstance(data.get("stores_operated_count"), int) and data["stores_operated_count"] >= 0
    assert isinstance(data.get("delinquency_balance_cents"), int) and data["delinquency_balance_cents"] >= 0
    assert isinstance(data.get("escrow_balance_cents"), int)


def assert_store(data: dict):
    _assert_common(data, "Store")
    assert isinstance(data.get("store_code"), str) and data["store_code"]
    assert data.get("status") in ("SETUP", "OPEN", "SUSPENDED", "REPOSSESSED")
    assert isinstance(data.get("site_id"), str)
    assert isinstance(data.get("operator_id"), str)


def assert_agreement(data: dict):
    _assert_common(data, "FranchiseAgreement")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("operator_id"), str)
    assert isinstance(data.get("initial_fee_cents"), int) and data["initial_fee_cents"] > 0
    assert 0 < data.get("royalty_rate") < 1
    assert 0 < data.get("ad_fund_rate") < 1
    assert 0 < data.get("occupancy_allocation_pct") < 1
    assert isinstance(data.get("term_years"), int) and data["term_years"] >= 1
    assert isinstance(data.get("term_start_date"), str)
    assert isinstance(data.get("term_end_date"), str)
    assert data.get("status") in ("DRAFT", "FEE_PENDING", "ACTIVE", "EXPIRED", "SUPERSEDED", "TERMINATED")


def assert_sublease(data: dict):
    _assert_common(data, "Sublease")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("operator_id"), str)
    assert isinstance(data.get("base_rent_cents"), int) and data["base_rent_cents"] > 0
    assert 0 < data.get("pct_rent_rate") < 1
    assert data.get("escalation_rate") >= 0
    assert 1 <= data.get("escalation_month") <= 12
    assert 1 <= data.get("escalation_day") <= 28
    assert data.get("status") in ("PENDING", "ACTIVE", "DEFAULTED", "CURED", "REPOSSESSED", "EXPIRED")


def assert_sales_report(data: dict):
    _assert_common(data, "SalesReport")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("period_month"), str)
    assert isinstance(data.get("gross_sales_cents"), int) and data["gross_sales_cents"] >= 0
    assert data.get("status") in ("DRAFT", "SUBMITTED", "LOCKED")


def assert_rent_charge(data: dict):
    _assert_common(data, "RentCharge")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("billing_period"), str)
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    for field in ("escalation_count", "effective_base_rent_cents", "percentage_rent_cents",
                  "annual_sales_cents", "selected_rent_cents", "amount_paid_cents"):
        assert isinstance(data.get(field), int), f"RentCharge.{field} must be an integer"
    # greater-of rule invariant
    assert data["selected_rent_cents"] == max(
        data["effective_base_rent_cents"], data["percentage_rent_cents"]
    ), "selected_rent_cents must be the greater of effective base and percentage rent"
    assert data.get("status") in ("OPEN", "PAID", "WAIVED")


def assert_fund_assessment(data: dict):
    _assert_common(data, "FundAssessment")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("agreement_id"), str)
    assert isinstance(data.get("period_month"), str)
    for field in ("occupancy_share_cents", "royalty_sales_cents", "royalty_cents",
                  "ad_fund_cents", "provisional_royalty_cents"):
        assert isinstance(data.get(field), int), f"FundAssessment.{field} must be an integer"
    assert data.get("status") in ("OPEN", "PAID", "WAIVED")


def assert_reinvestment_obligation(data: dict):
    _assert_common(data, "ReinvestmentObligation")
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("agreement_id"), str)
    assert isinstance(data.get("required_budget_cents"), int) and data["required_budget_cents"] > 0
    assert isinstance(data.get("min_spend_cents"), int)
    assert isinstance(data.get("verified_spend_cents"), int)
    assert data.get("status") in ("PENDING", "SUBMITTED", "SATISFIED", "BREACHED")


def assert_default_event(data: dict):
    _assert_common(data, "DefaultEvent")
    assert isinstance(data.get("sublease_id"), str)
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("cure_fee_cents"), int)
    assert isinstance(data.get("shortfall_cents"), int)
    assert data.get("status") in ("DECLARED", "CURED", "REPOSSESSED")


def assert_advertising_fund(data: dict):
    _assert_common(data, "AdvertisingFund")
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("fund_type") in ("NATIONAL", "LOCAL_COOP")
    assert data.get("admin_fee_rate") >= 0
    assert isinstance(data.get("balance_cents"), int)
    assert data.get("governance_status") in ("ACTIVE", "FROZEN")


def assert_coop_assessment(data: dict):
    _assert_common(data, "CoopAssessment")
    assert isinstance(data.get("fund_id"), str)
    assert isinstance(data.get("store_id"), str)
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0
    assert data.get("status") in ("ASSESSED", "PAID", "WAIVED")


def assert_capacity_review(data: dict):
    _assert_common(data, "CapacityReview")
    assert isinstance(data.get("operator_id"), str)
    assert isinstance(data.get("review_period"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED")
