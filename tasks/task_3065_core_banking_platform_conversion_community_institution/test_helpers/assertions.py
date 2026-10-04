"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, *, full: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    if full:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["incumbent_core_name"], str) and data["incumbent_core_name"]
    assert isinstance(data["target_core_name"], str) and data["target_core_name"]
    assert data["status"] in [
        "DISCOVERY", "CONFIGURATION", "MOCK_CONVERSION",
        "CUTOVER_PLANNED", "LIVE", "CLOSED",
    ]
    assert isinstance(data["mock_runs_used"], int) and data["mock_runs_used"] >= 0


def assert_product_type(data: dict):
    _assert_common(data)
    assert data["kind"] in ["DEPOSIT", "LOAN"]
    assert data["accrual_method"] in ["ACT_365", "ACT_360", "THIRTY_360"]
    assert data["statement_frequency"] in ["MONTHLY", "QUARTERLY"]
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["minimum_balance_cents"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert data["account_type"] in ["DEPOSIT", "LOAN"]
    assert data["status"] in [
        "STAGED", "MAPPED", "EXCEPTION", "CLEARED", "CONVERTED", "BLOCKED",
    ]
    assert isinstance(data["opening_principal_cents"], int)
    assert isinstance(data["statement_cycle_day"], int)
    assert 1 <= data["statement_cycle_day"] <= 28


def assert_gl_account(data: dict):
    _assert_common(data)
    assert isinstance(data["expected_balance_cents"], int)
    assert isinstance(data["converted_balance_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["variance_cents"] == (
        data["converted_balance_cents"] - data["expected_balance_cents"]
    ), "variance must equal converted minus expected"


def assert_mock_run(data: dict):
    _assert_common(data)
    assert data["state"] in ["RUNNING", "FAILED", "PASSED_WITH_EXCEPTIONS", "PASSED"]
    assert is_iso8601_timestamp(data.get("started_at", ""))
    assert isinstance(data["is_cutover_baseline"], bool)


def assert_ancillary_system(data: dict):
    _assert_common(data)
    assert data["category"] in [
        "CARDS", "ONLINE_BANKING", "ITEM_PROCESSING", "REPORTING",
    ]
    assert data["status"] in [
        "PENDING", "INTEGRATING", "VERIFIED", "FAILED", "RETEST_PASSED",
    ]


def assert_training_session(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["attended_count"], int) and data["attended_count"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_enrollment(data: dict):
    # Lighter-weight record: id + created_at only, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert data["state"] in ["RESERVED", "ATTENDED", "NO_SHOW", "CANCELLED"]


def assert_staff_member(data: dict):
    _assert_common(data)
    assert data["role_scope"] in ["TELLER", "LENDER", "OPS", "BRANCH_MANAGER"]
    assert isinstance(data["parallel_ops_certified"], bool)


def assert_customer_comm(data: dict):
    _assert_common(data)
    assert data["comm_type"] in [
        "ACCOUNT_NUMBER_CHANGE", "CARD_REISSUE", "PAYMENT_REDIRECTION",
    ]
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "SENT", "DELIVERED", "FAILED", "CANCELLED",
    ]
    assert isinstance(data["wave"], int) and data["wave"] >= 1
    assert isinstance(data["resend_count"], int) and data["resend_count"] >= 0


def assert_defect(data: dict):
    _assert_common(data)
    assert data["severity"] in ["SEV1", "SEV2", "SEV3"]
    assert data["status"] in [
        "OPEN", "TRIAGED", "IN_FIX", "RESOLVED", "REOPENED", "CLOSED",
    ]
    assert isinstance(data["reopened_count"], int) and data["reopened_count"] >= 0


def assert_service_credit(data: dict):
    _assert_common(data)
    assert data["claim_status"] in [
        "OPEN", "APPROVED", "DISPUTED", "PAID", "REJECTED",
    ]
    assert isinstance(data["defect_ids"], list) and len(data["defect_ids"]) > 0
    assert isinstance(data["breach_hours"], list)
    assert len(data["breach_hours"]) == len(data["defect_ids"])
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0


def assert_cutover_plan(data: dict):
    # Lighter-weight record: id + created_at only, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert data["status"] in ["DRAFT", "SCHEDULED", "GO", "LIVE", "ROLLED_BACK"]


def assert_cutover_task(data: dict):
    # Lighter-weight record: id + created_at only, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert data["status"] in ["PENDING", "RUNNING", "COMPLETE", "SKIPPED", "FAILED"]
    assert data["owner_role"] in ["CONVERSION_ENGINEER", "OPERATIONS_LEAD"]
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
