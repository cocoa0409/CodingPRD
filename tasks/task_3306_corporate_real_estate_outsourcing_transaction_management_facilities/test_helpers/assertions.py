"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def assert_common_fields(data: dict):
    """Every entity carries id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_account(data: dict):
    assert_common_fields(data)
    assert data["lifecycle_state"] in [
        "DRAFT", "ACTIVE", "OFFBOARDING", "CLOSED_CONVERTED", "CLOSED_TERMINATED",
    ]
    assert data["governance_posture"] in ["NORMAL", "ON_WATCH", "RESTRICTED"]
    assert data["client_data_rights"] in [
        "BROKER_OWNED", "CLIENT_OWNED_EXCLUSIVE", "CLIENT_OWNED_SHARED",
    ]
    assert data["platform_tier"] in ["BASIC", "COMPLETE", "ENTERPRISE"]
    assert isinstance(data["portfolio_sqft"], int) and data["portfolio_sqft"] >= 1
    assert isinstance(data["open_escalation_count"], int)
    assert isinstance(data["completion_pct_bps"], int)
    assert_cost_precision(data["annual_net_fee_cents"])
    assert_cost_precision(data["fee_ledger_credit_cents"])


def assert_lease(data: dict):
    assert_common_fields(data)
    assert data["pipeline_state"] in [
        "PIPELINE", "APPROVAL_PENDING", "BROKER_ASSIGNED",
        "IN_MARKET", "NEGOTIATING", "EXECUTED", "REJECTED",
    ]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["expiration_bucket"] in [
        "UNASSIGNED", "NEAR_TERM", "MID_TERM", "LONG_TERM",
    ]


def assert_transaction_request(data: dict):
    assert_common_fields(data)
    assert data["request_state"] in [
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED",
        "WITHDRAWN", "EXECUTED", "CANCELLED",
    ]


def assert_commission_record(data: dict):
    assert_common_fields(data)
    assert data["commission_source"] in ["THIRD_PARTY", "SELF_PERFORM"]
    assert_cost_precision(data["credit_amount_cents"])
    assert isinstance(data["credited"], bool)


def assert_broker_engagement(data: dict):
    assert_common_fields(data)
    assert data["engagement_state"] in ["PENDING", "ASSIGNED", "EXECUTED", "TERMINATED"]
    assert data["broker_class"] in ["SENIOR", "STANDARD"]


def assert_kpi(data: dict):
    assert_common_fields(data)
    assert data["kpi_family"] in ["SERVICE_LEVEL", "SAVINGS"]
    assert data["measurement_unit"] in ["BPS", "CENTS"]
    assert data["evaluation_state"] in [
        "AWAITING_BASELINE", "EVALUATED", "ESCALATED",
    ]
    assert data["escalation_status"] in ["NONE", "OPEN", "RESOLVED"]


def assert_vendor(data: dict):
    assert_common_fields(data)
    assert data["vendor_state"] in ["SOURCING", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["kpi_track"] in ["LEVEL_A", "LEVEL_B", "LEVEL_C"]
    assert data["delivery_model"] in ["SELF_PERFORM", "SUBCONTRACTED"]
    assert data["sourcing_program"] in ["DIVERSITY", "LOCAL", "NATIONAL"]


def assert_site(data: dict):
    assert_common_fields(data)
    assert data["vacancy_state"] in ["OCCUPIED", "VACATED", "CONSOLIDATING", "DISPOSED"]
    assert isinstance(data["sqft"], int) and data["sqft"] >= 1


def assert_consolidation_project(data: dict):
    assert_common_fields(data)
    assert data["project_state"] in [
        "PLANNED", "IN_REVIEW", "APPROVED", "IN_EXECUTION", "COMPLETED", "CANCELLED",
    ]


def assert_scorecard(data: dict):
    assert_common_fields(data)
    assert data["scorecard_state"] in ["DRAFT", "PUBLISHED", "OVERRIDDEN"]


def assert_audit(data: dict):
    assert_common_fields(data)
    assert data["audit_state"] in ["SCHEDULED", "IN_REVIEW", "PASSED", "FAILED"]
    assert data["discipline"] in ["TRANSACTION", "FACILITIES", "PROJECT"]


def assert_data_license(data: dict):
    assert_common_fields(data)
    assert data["license_state"] in ["REQUESTED", "GRANTED", "REJECTED", "REVOKED"]
    assert data["data_scope"] in ["AGGREGATE", "LINE_ITEM"]
    assert isinstance(data["requires_written_client_consent"], bool)


def assert_transition_task(data: dict):
    assert_common_fields(data)
    assert data["task_state"] in ["PENDING", "IN_PROGRESS", "DONE", "FAILED"]


def assert_fee_accrual(data: dict):
    assert_common_fields(data)
    assert data["credit_application_state"] in ["OPEN", "CREDITED", "SETTLED"]
    assert_cost_precision(data["applied_credit_cents"])


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert data["assignment_role"] in [
        "ACCOUNT_EXECUTIVE", "TRANSACTION_MANAGER", "FACILITIES_MANAGER",
        "OCCUPANCY_PLANNER", "GOVERNANCE_MANAGER", "DATA_STEWARD",
        "TRANSITION_MANAGER", "APPROVAL_AUTHORITY",
    ]
    assert data["approval_level"] in ["MANAGER", "DIRECTOR", "ACCOUNT_EXECUTIVE"]


def assert_audit_review(data: dict):
    assert_common_fields(data)
    assert isinstance(data["review_round_no"], int) and data["review_round_no"] >= 1


# ─── Domain invariants ────────────────────────────────

def assert_account_invariants(data: dict):
    """Conserved quantities that must hold after any operation (PRD §2.9, §2.10)."""
    assert data["fee_ledger_credit_cents"] >= 0
    assert data["broker_pool_allocated_cents"] >= 0
    assert data["portfolio_leased_sqft"] >= 0
    assert_cost_precision(data["fee_ledger_credit_cents"])
    assert_cost_precision(data["annual_net_fee_cents"])


def assert_broker_split_conserved(data: dict):
    """broker_share_cents + account_share_cents == deal_commission_cents."""
    total = data["broker_share_cents"] + data["account_share_cents"]
    assert total == data["deal_commission_cents"], (
        f"Commission split not conserved: {data['broker_share_cents']} + "
        f"{data['account_share_cents']} != {data['deal_commission_cents']}"
    )