"""Entity assertions and domain invariant checkers.

All field names are PRD-exact. Every business resource carries the common
system-managed property set: id, created_at, updated_at, version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_territory(data: dict):
    _assert_common(data, "Territory")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["royalty_rate_pct"], (int, float))
    assert isinstance(data["development_quota_stores"], int)
    assert data.get("assigned_agent_id") is None or is_valid_uuid(data["assigned_agent_id"])
    assert data["status"] in ("UNASSIGNED", "ASSIGNED", "REASSIGNMENT_PENDING")
    assert isinstance(data["open_store_count"], int) and data["open_store_count"] >= 0


def assert_development_agent(data: dict):
    _assert_common(data, "DevelopmentAgent")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "UNDERPERFORMING", "TERMINATED")
    assert isinstance(data["underperformance_strikes"], int)


def assert_franchisee(data: dict):
    _assert_common(data, "Franchisee")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("PROSPECT", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_store(data: dict):
    _assert_common(data, "Store")
    assert isinstance(data["store_number"], str) and data["store_number"]
    assert is_valid_uuid(data.get("territory_id", ""))
    assert is_valid_uuid(data.get("franchisee_id", ""))
    assert isinstance(data["address"], str)
    assert isinstance(data["geo_lat"], (int, float))
    assert isinstance(data["geo_lng"], (int, float))
    assert isinstance(data["estimated_weekly_sales_cents"], int)
    assert isinstance(data["actual_avg_weekly_sales_cents"], int)
    assert data["status"] in (
        "PIPELINE", "OPEN", "CLOSED_FOR_REMODEL",
        "PROBATION", "TERMINATION_PENDING", "TERMINATED",
    )
    assert isinstance(data["consecutive_failed_inspections"], int)


def assert_site_application(data: dict):
    _assert_common(data, "SiteApplication")
    assert is_valid_uuid(data.get("territory_id", ""))
    assert is_valid_uuid(data.get("applicant_franchisee_id", ""))
    assert isinstance(data["proposed_address"], str)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "IMPACT_REVIEW", "REVISION_REQUESTED", "APPROVED",
        "REJECTED", "WITHDRAWN", "PROTESTED", "SUSPENDED",
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_impact_study(data: dict):
    _assert_common(data, "ImpactStudy")
    assert isinstance(data["radius_miles"], (int, float))
    assert isinstance(data["affected_store_count"], int) and data["affected_store_count"] >= 0
    assert data["status"] in ("PROVISIONAL", "FINAL", "VOID")


def assert_protest(data: dict):
    _assert_common(data, "Protest")
    assert is_valid_uuid(data.get("site_application_id", ""))
    assert is_valid_uuid(data.get("protesting_store_id", ""))
    assert isinstance(data["grounds"], str)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "MEDIATION", "MEDIATION_FAILED",
        "ESCALATED", "RESOLVED_UPHELD", "RESOLVED_REJECTED",
    )


def assert_transfer_request(data: dict):
    _assert_common(data, "TransferRequest")
    assert is_valid_uuid(data.get("store_id", ""))
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["transfer_fee_cents"], int)
    assert data["status"] in (
        "PENDING", "BUYER_TRAINING", "PENDING_APPROVAL", "APPROVED",
        "REJECTED", "COMPLETED", "CANCELLED",
    )


def assert_training_enrollment(data: dict):
    _assert_common(data, "TrainingEnrollment")
    assert is_valid_uuid(data.get("franchisee_id", ""))
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["status"] in ("ENROLLED", "COMPLETED", "FAILED", "EXPIRED")


def assert_remodel_mandate(data: dict):
    _assert_common(data, "RemodelMandate")
    assert is_valid_uuid(data.get("store_id", ""))
    assert data["financing_option"] in ("SELF_FINANCED", "DA_LOAN", "FRANCHISOR_DEFERRAL")
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] in (
        "ISSUED", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "OVERDUE", "WAIVED",
    )


def assert_inspection(data: dict):
    _assert_common(data, "Inspection")
    assert is_valid_uuid(data.get("store_id", ""))
    assert isinstance(data["inspector_ref"], str) and data["inspector_ref"]
    assert data["status"] in ("SCHEDULED", "CONDUCTED", "FINALIZED", "VOID")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("PASS", "FAIL", "FAIL_CRITICAL")


def assert_promotion(data: dict):
    _assert_common(data, "Promotion")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_cost_per_store_cents"], int)
    assert data["status"] in ("PROPOSED", "VOTING", "APPROVED", "REJECTED", "ACTIVE", "CLOSED")
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["votes_abstain"], int)


def assert_promotion_vote(data: dict):
    _assert_common(data, "PromotionVote")
    assert is_valid_uuid(data.get("promotion_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert data["ballot"] in ("FOR", "AGAINST", "ABSTAIN")
    assert isinstance(data["retracted"], bool)


def assert_funding_dispute(data: dict):
    _assert_common(data, "FundingDispute")
    assert is_valid_uuid(data.get("promotion_id", ""))
    assert is_valid_uuid(data.get("store_id", ""))
    assert isinstance(data["disputed_amount_cents"], int)
    assert data["status"] in (
        "OPEN", "RESOLVED_DA_ABSORBS", "RESOLVED_FRANCHISEE_PAYS",
        "RESOLVED_FRANCHISOR_ABSORBS",
    )


def assert_fee_statement(data: dict):
    _assert_common(data, "FeeStatement")
    assert is_valid_uuid(data.get("development_agent_id", ""))
    assert is_valid_uuid(data.get("territory_id", ""))
    assert isinstance(data["gross_fees_cents"], int)
    assert isinstance(data["da_share_cents"], int)
    assert isinstance(data["franchisor_share_cents"], int)
    assert data["variant"] in ("PROVISIONAL_ESTIMATE", "FINAL_RECONCILIATION")
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "SETTLED")


def assert_fee_conservation(data: dict):
    """PRD §2.10: da_share_cents + franchisor_share_cents == gross_fees_cents."""
    assert data["da_share_cents"] + data["franchisor_share_cents"] == data["gross_fees_cents"], (
        f"fee conservation violated: {data['da_share_cents']} + "
        f"{data['franchisor_share_cents']} != {data['gross_fees_cents']}"
    )
