"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` validates the response structure against the
contract: system-managed common fields (``id``, ``created_at``,
``updated_at``, ``version``) plus the entity's own fields and status
membership.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive integer"
    )


def assert_plan(data: dict):
    _assert_common_fields(data, "Plan")
    assert isinstance(data["plan_code"], str) and len(data["plan_code"]) > 0
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["service_area_states"], list) and len(data["service_area_states"]) > 0
    assert data["brand_license_status"] in ["PENDING", "LICENSED", "SUSPENDED", "REVOKED"]
    assert isinstance(data["claims_paid_balance_cents"], int)
    assert isinstance(data["fees_receivable_balance_cents"], int)


def assert_member(data: dict):
    _assert_common_fields(data, "Member")
    assert isinstance(data["home_plan_id"], str)
    assert data.get("national_account_id") is None or isinstance(data["national_account_id"], str)
    assert isinstance(data["member_number"], str) and len(data["member_number"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["eligibility_status"] in ["ACTIVE", "TERMINATED"]


def assert_national_account(data: dict):
    _assert_common_fields(data, "NationalAccount")
    assert isinstance(data["controlling_plan_id"], str)
    assert isinstance(data["account_name"], str) and len(data["account_name"]) > 0
    assert isinstance(data["employer_group_id"], str) and len(data["employer_group_id"]) > 0
    assert isinstance(data["territory_states"], list) and len(data["territory_states"]) > 0
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    assert data["status"] in ["PROPOSED", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_rate_schedule(data: dict):
    _assert_common_fields(data, "RateSchedule")
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["provider_npi"], str) and len(data["provider_npi"]) > 0
    assert isinstance(data["procedure_code"], str) and len(data["procedure_code"]) > 0
    assert isinstance(data["negotiated_rate_cents"], int)
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)


def assert_access_fee_schedule(data: dict):
    _assert_common_fields(data, "AccessFeeSchedule")
    assert isinstance(data["home_plan_id"], str)
    assert isinstance(data["host_plan_id"], str)
    assert isinstance(data["tier1_cap_cents"], int)
    assert isinstance(data["tier1_fee_cents"], int)
    assert isinstance(data["tier2_rate"], (int, float))
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert isinstance(data["member_id"], str)
    assert isinstance(data["host_plan_id"], str)
    assert isinstance(data["home_plan_id"], str)
    assert data.get("national_account_id") is None or isinstance(data["national_account_id"], str)
    assert isinstance(data["provider_npi"], str)
    assert isinstance(data["procedure_code"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["service_state"], str)
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["provisional_allowed_cents"], int)
    assert data["status"] in [
        "RECEIVED",
        "PRICED",
        "ROUTED",
        "BENEFIT_DETERMINED",
        "PAID",
        "ADJUSTMENT_PENDING",
        "SETTLED",
        "DENIED",
    ]


def assert_adjustment(data: dict):
    _assert_common_fields(data, "Adjustment")
    assert isinstance(data["claim_id"], str)
    assert data.get("supersedes_adjustment_id") is None or isinstance(data["supersedes_adjustment_id"], str)
    assert isinstance(data["reason"], str)
    assert isinstance(data["delta_allowed_cents"], int)
    assert isinstance(data["recovery_amount_cents"], int)
    assert data["status"] in ["INITIATED", "VALIDATED", "PROPAGATED", "APPLIED", "REJECTED"]


def assert_settlement_batch(data: dict):
    _assert_common_fields(data, "SettlementBatch")
    assert isinstance(data["debtor_plan_id"], str)
    assert isinstance(data["creditor_plan_id"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["settlement_variant"] in ["NET", "GROSS"]
    assert data["status"] in [
        "OPEN",
        "FINALIZED",
        "ACKNOWLEDGED",
        "DISPUTED",
        "DISBURSED",
        "RECONCILED",
    ]


def assert_eligibility_inquiry(data: dict):
    _assert_common_fields(data, "EligibilityInquiry")
    assert isinstance(data["inquiring_plan_id"], str)
    assert isinstance(data["home_plan_id"], str)
    assert isinstance(data["member_number"], str) and len(data["member_number"]) > 0
    assert data.get("answer_eligibility_status") is None or data["answer_eligibility_status"] in [
        "ACTIVE",
        "TERMINATED",
    ]
    assert data["status"] in ["ROUTED", "ANSWERED", "REJECTED"]
