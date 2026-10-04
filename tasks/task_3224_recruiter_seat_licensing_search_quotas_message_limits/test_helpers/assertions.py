"""Entity assertions and domain invariant checkers.

Each assert_* helper checks the common fields (id, created_at, updated_at,
version) that PRD section "Common Resource Properties" guarantees on every
primary resource, plus the entity-specific fields named in PRD prose.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert isinstance(data, dict), f"expected object, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_number"], str)
    assert data["product_tier"] in ("RECRUITER_LITE", "RECRUITER_PRO", "RECRUITER_CORP")
    assert isinstance(data["seat_cap"], int) and 1 <= data["seat_cap"] <= 5000
    assert isinstance(data["seats_purchased"], int) and data["seats_purchased"] >= 0
    assert isinstance(data["seats_assigned"], int) and data["seats_assigned"] >= 0
    assert data["contract_status"] in (
        "PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "RENEWAL_PENDING", "EXPIRED",
    )
    assert isinstance(data["monthly_credit_per_seat"], int)
    assert isinstance(data["monthly_search_quota_per_seat"], int)
    assert isinstance(data["search_result_page_cap"], int)
    assert isinstance(data["true_up_allowed"], bool)


def assert_seat(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["seat_label"], str)
    assert data["seat_status"] in ("UNASSIGNED", "ASSIGNED", "SUSPENDED", "REVOKED")
    assert "assigned_recruiter_id" in data
    assert "assignment_started_at" in data
    assert isinstance(data["assignment_audit_count"], int)
    assert isinstance(data["last_period_credit_refresh"], int)


def assert_recruiter(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert "manager_recruiter_id" in data
    assert data["recruiter_status"] in ("ACTIVE", "DEACTIVATED")
    assert isinstance(data["home_contract_id"], str)
    assert "active_seat_id" in data


def assert_quota_ledger(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["search_quota_total"], int)
    assert isinstance(data["searches_used"], int)
    assert isinstance(data["searches_remaining"], int)
    assert data["searches_remaining"] == data["search_quota_total"] - data["searches_used"]
    assert data["searches_remaining"] >= 0
    assert data["ledger_status"] in ("OPEN", "EXHAUSTED", "CLOSED")


def assert_credit_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["credits_granted"], int)
    assert isinstance(data["credits_used"], int)
    assert isinstance(data["credits_returned"], int)
    assert isinstance(data["credits_available"], int)
    assert data["credits_available"] >= 0
    assert isinstance(data["spam_strike_count"], int)
    assert data["pool_status"] in ("OPEN", "THROTTLED", "CLOSED")


def assert_credit_pool_invariants(data: dict):
    """credits_available == credits_granted - credits_used + credits_returned, floored at 0."""
    expected = data["credits_granted"] - data["credits_used"] + data["credits_returned"]
    assert data["credits_available"] == max(0, expected), (
        f"credit accounting identity violated: available={data['credits_available']} "
        f"expected max(0, {expected})"
    )


def assert_message(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["project_id"], str)
    assert "job_posting_id" in data
    assert data["delivery_status"] in ("PENDING", "SENT", "FAILED")
    assert data["response_status"] in (
        "AWAITING", "RESPONDED", "NEGATIVE_RESPONSE", "REPORTED_AS_SPAM", "EXPIRED",
    )
    assert data["credit_consumed"] in (0, 1)
    assert isinstance(data["credit_returned_flag"], bool)


def assert_candidate_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["headline"], str)
    assert data["privacy_setting"] in ("PUBLIC", "CONNECTIONS_ONLY", "PRIVATE")
    assert isinstance(data["open_to_work"], bool)
    assert data["open_to_work_visibility"] in ("ALL_MEMBERS", "RECRUITERS_ONLY", "NONE")
    assert isinstance(data["years_experience"], int)
    assert isinstance(data["current_title"], str)


def assert_search_project(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["owner_seat_id"], str)
    assert isinstance(data["name"], str)
    assert data["project_status"] in ("DRAFT", "OPEN", "ON_HOLD", "CLOSED")
    assert isinstance(data["pinned_candidate_ids"], list)
    assert isinstance(data["message_count"], int)


def assert_job_posting(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["created_by_seat_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 1000
    assert isinstance(data["daily_cap_cents"], int) and data["daily_cap_cents"] >= 100
    assert data["daily_cap_cents"] <= data["budget_cents"]
    assert data["pacing_mode"] in ("EVEN", "FRONT_LOADED")
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0
    assert data["posting_status"] in ("DRAFT", "ACTIVE", "PAUSED", "EXHAUSTED", "CLOSED")


def assert_promoted_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["job_posting_id"], str)
    assert isinstance(data["slot_date"], str)
    assert isinstance(data["reserved_cents"], int) and data["reserved_cents"] >= 1
    assert data["slot_status"] in ("RESERVED", "CONFIRMED", "RELEASED")


def assert_ats_integration(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["vendor"] in ("GREENHOUSE", "LEVER", "WORKDAY", "ICIMS")
    assert isinstance(data["external_tenant_id"], str)
    assert isinstance(data["write_back_enabled"], bool)
    assert data["integration_status"] in ("PROVISIONING", "CONNECTED", "SYNC_ERROR", "DISABLED")


def assert_ats_sync_record(data: dict):
    _assert_common(data)
    assert isinstance(data["ats_integration_id"], str)
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["external_candidate_ref"], str)
    assert data["event_type"] in ("APPLICATION_FORWARDED", "STAGE_CHANGED", "HIRED", "DISQUALIFIED")
    assert isinstance(data["payload_fingerprint"], str)
    assert data["sync_status"] in ("QUEUED", "WRITTEN", "DUPLICATE_SKIPPED", "FAILED")


def assert_talent_insight_report(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["report_name"], str)
    assert isinstance(data["aggregation_floor"], int) and data["aggregation_floor"] == 25
    assert data["report_status"] in ("DRAFT", "GENERATED", "PUBLISHED", "SUPPRESSED")


def assert_renewal_event(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str)
    assert data["event_kind"] in ("TRUE_UP", "RENEWAL", "SUSPENSION")
    assert data["event_status"] in ("PROPOSED", "APPROVED", "APPLIED", "REJECTED")
