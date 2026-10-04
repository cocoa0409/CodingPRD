"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_volunteer_editor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("username"), str) and len(data["username"]) > 0
    assert isinstance(data.get("email"), str) and len(data["email"]) > 0
    assert data.get("account_status") in ["ACTIVE", "SUSPENDED", "BLOCKED"]
    assert isinstance(data.get("coi_disclosed"), bool)
    assert isinstance(data.get("edit_count"), int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_wiki_page(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("title"), str) and len(data["title"]) > 0
    assert data.get("topic_area") in ["GENERAL", "POLITICS", "HEALTH", "BIOGRAPHY", "HISTORY"]
    assert data.get("protection_level") in ["NONE", "SEMI", "FULL"]
    assert data.get("dispute_level") in ["NONE", "TALK", "NOTICE", "ARB"]
    assert isinstance(data.get("content_score"), (int, float))
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_revision(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("page_id", "")), "page_id must be valid UUID"
    assert is_valid_uuid(data.get("editor_id", "")), "editor_id must be valid UUID"
    assert isinstance(data.get("content_text"), str)
    assert isinstance(data.get("summary"), str)
    assert data.get("status") in ["PENDING", "ACCEPTED", "REVERTED", "FLAGGED"]
    assert isinstance(data.get("vandalism_score"), (int, float))
    assert isinstance(data.get("source_quality_score"), (int, float))
    assert isinstance(data.get("neutrality_score"), (int, float))
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_dispute_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("page_id", "")), "page_id must be valid UUID"
    assert is_valid_uuid(data.get("initiator_id", "")), "initiator_id must be valid UUID"
    assert is_valid_uuid(data.get("respondent_id", "")), "respondent_id must be valid UUID"
    assert is_valid_uuid(data.get("subject_revision_id", "")), "subject_revision_id must be valid UUID"
    assert data.get("dispute_type") in ["CONTENT", "CONDUCT", "SOURCING", "NOTABILITY"]
    assert data.get("level") in ["TALK", "NOTICE", "ARBITRATION"]
    assert data.get("status") in ["OPEN", "ESCALATED", "RESOLVED", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_protection_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("page_id", "")), "page_id must be valid UUID"
    assert is_valid_uuid(data.get("requested_by_id", "")), "requested_by_id must be valid UUID"
    assert data.get("requested_level") in ["SEMI", "FULL"]
    assert data.get("status") in ["PENDING", "APPROVED", "DENIED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_vandalism_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("revision_id", "")), "revision_id must be valid UUID"
    assert is_valid_uuid(data.get("reporter_id", "")), "reporter_id must be valid UUID"
    assert data.get("report_type") in ["VANDALISM", "SPAM", "BLP_VIOLATION", "COPYVIO"]
    assert data.get("status") in ["PENDING", "CONFIRMED", "DISMISSED"]
    assert isinstance(data.get("auto_flagged"), bool)
    assert isinstance(data.get("rollback_applied"), bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_donation_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert isinstance(data.get("target_amount_cents"), int)
    assert data.get("status") in ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"]
    assert isinstance(data.get("raised_cents"), int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_campaign_banner(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be valid UUID"
    assert isinstance(data.get("message_variant"), str)
    assert isinstance(data.get("geo_target"), str)
    assert isinstance(data.get("frequency_cap"), int)
    assert isinstance(data.get("priority_weight"), int)
    assert data.get("status") in ["ACTIVE", "PAUSED", "RETIRED"]
    assert isinstance(data.get("impression_count"), int)
    assert isinstance(data.get("click_count"), int)
    assert isinstance(data.get("conversion_count"), int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_donation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("campaign_id", "")), "campaign_id must be valid UUID"
    assert is_valid_uuid(data.get("banner_id", "")), "banner_id must be valid UUID"
    assert isinstance(data.get("donor_email_hash"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("currency"), str)
    assert data.get("status") in ["PLEDGED", "COMPLETED", "FAILED", "REFUNDED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_grant_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("fiscal_year"), int)
    assert isinstance(data.get("budget_cents"), int)
    assert isinstance(data.get("allocated_cents"), int)
    assert data.get("status") in ["OPEN", "CLOSED", "ARCHIVED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_grant_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be valid UUID"
    assert is_valid_uuid(data.get("applicant_id", "")), "applicant_id must be valid UUID"
    assert isinstance(data.get("project_title"), str)
    assert isinstance(data.get("requested_cents"), int)
    assert data.get("status") in ["SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_legal_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data.get("request_type") in ["TAKEDOWN", "USER_INFO", "SUBPOENA", "COURT_ORDER"]
    assert isinstance(data.get("requesting_party"), str)
    assert data.get("status") in ["RECEIVED", "UNDER_REVIEW", "COMPLIED", "REJECTED", "PARTIALLY_COMPLIED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_transparency_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("period_start", "")), "period_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("period_end", "")), "period_end must be ISO 8601"
    assert isinstance(data.get("total_requests"), int)
    assert isinstance(data.get("complied_count"), int)
    assert isinstance(data.get("rejected_count"), int)
    assert data.get("status") in ["DRAFT", "PUBLISHED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int)


def assert_impression_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("banner_id", "")), "banner_id must be valid UUID"
    assert isinstance(data.get("viewer_key"), str)
    assert isinstance(data.get("country_code"), str)
    assert is_iso8601_timestamp(data.get("served_at", "")), "served_at must be ISO 8601"
    assert isinstance(data.get("day_bucket"), str)
    assert isinstance(data.get("clicked"), bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_page_invariants(page: dict):
    """Domain invariants that must hold for a WikiPage."""
    assert page["content_score"] >= 0
    assert page["content_score"] <= 100


def assert_campaign_invariants(campaign: dict):
    """Domain invariants that must hold for a DonationCampaign."""
    assert campaign["raised_cents"] >= 0


def assert_grant_program_invariants(program: dict):
    """Domain invariants that must hold for a GrantProgram."""
    assert program["allocated_cents"] >= 0
    assert program["allocated_cents"] <= program["budget_cents"]
