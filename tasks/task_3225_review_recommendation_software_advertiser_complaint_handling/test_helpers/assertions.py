"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only records must not carry updated_at"
    assert "version" not in data, "append-only records must not carry version"


def assert_user(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("display_name"), str)
    assert isinstance(data.get("home_region"), str)
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "PURGED"]
    assert isinstance(data.get("trust_score"), int) and 0 <= data["trust_score"] <= 100
    assert isinstance(data.get("strike_count"), int) and data["strike_count"] >= 0


def assert_business_page(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("address_line"), str)
    assert isinstance(data.get("city"), str)
    assert isinstance(data.get("category"), str)
    assert isinstance(data.get("website"), str)
    assert data.get("status") in ["ACTIVE", "CLOSED", "MERGED"]
    assert isinstance(data.get("displayed_review_count"), int)
    assert data["displayed_review_count"] >= 0
    assert isinstance(data.get("displayed_rating_avg_x100"), int)
    assert data["displayed_rating_avg_x100"] >= 0


def assert_review(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert isinstance(data.get("author_user_id"), str)
    assert isinstance(data.get("rating"), int) and 1 <= data["rating"] <= 5
    assert isinstance(data.get("text"), str)
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert data.get("edited_flag") in (True, False)
    assert data.get("evidence_confirmed") in (True, False)
    assert data.get("recommendation_state") in ["PENDING", "DISPLAYED", "FILTERED", "REMOVED"]


def assert_page_claim(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert isinstance(data.get("claimant_user_id"), str)
    assert data.get("kind") in ["CLAIM", "TRANSFER"]
    assert isinstance(data.get("evidence_text"), str)
    assert data.get("status") in ["SUBMITTED", "VERIFIED", "APPROVED", "REJECTED", "EXPIRED"]


def assert_ad_account(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert isinstance(data.get("owner_user_id"), str)
    assert isinstance(data.get("daily_budget_cents"), int)
    assert isinstance(data.get("spent_today_cents"), int)
    assert data.get("status") in ["ACTIVE", "SUSPENDED", "CLOSED"]


def assert_ad_campaign(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("ad_account_id"), str)
    assert data.get("kind") in ["SPONSORED_PLACEMENT", "CALL_TRACKING"]
    assert isinstance(data.get("bid_cents"), int)
    assert data.get("status") in ["DRAFT", "ACTIVE", "PAUSED", "COMPLETED", "CANCELLED"]


def assert_ad_impression_event(data: dict):
    _assert_append_only(data)
    assert isinstance(data.get("ad_account_id"), str)
    assert isinstance(data.get("campaign_id"), str)
    assert isinstance(data.get("idempotency_key"), str)
    assert isinstance(data.get("cost_cents"), int)
    assert isinstance(data.get("served_on"), str)


def assert_call_track_event(data: dict):
    _assert_append_only(data)
    assert isinstance(data.get("ad_account_id"), str)
    assert isinstance(data.get("campaign_id"), str)
    assert isinstance(data.get("caller_number"), str)
    assert isinstance(data.get("duration_seconds"), int)
    assert data.get("qualified") in (True, False)
    assert isinstance(data.get("cost_cents"), int)
    assert data.get("attribution_window_days") == 30


def assert_attribution_report(data: dict):
    _assert_append_only(data)
    assert isinstance(data.get("ad_account_id"), str)
    assert isinstance(data.get("campaign_id"), str)
    assert data.get("variant") in ["STRICT", "EXTENDED"]
    assert isinstance(data.get("impressions"), int)
    assert isinstance(data.get("qualified_calls"), int)
    assert isinstance(data.get("spend_cents"), int)


def assert_complaint(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert isinstance(data.get("review_id"), str)
    assert isinstance(data.get("filer_user_id"), str)
    assert data.get("kind") in ["FILTERED_DISPUTE", "NEGATIVE_DISPUTE", "SOLICITATION_REPORT"]
    assert isinstance(data.get("body"), str)
    assert data.get("escalated") in (True, False)
    assert data.get("status") in [
        "OPEN", "UNDER_REVIEW", "ESCALATED",
        "RESOLVED_UPHELD", "RESOLVED_ACTIONED", "REJECTED",
    ]


def assert_solicitation_case(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert isinstance(data.get("reporter_user_id"), str)
    assert isinstance(data.get("target_review_ids"), list)
    assert isinstance(data.get("confirmed_review_count"), int)
    assert data.get("status") in ["OPEN", "INVESTIGATING", "CONFIRMED", "DISMISSED"]


def assert_consumer_alert(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("page_id"), str)
    assert data.get("kind") in ["SOLICITATION_EVIDENCE", "SUSPICIOUS_ACTIVITY", "MEDIA_ATTENTION"]
    assert isinstance(data.get("evidence_text"), str)
    assert data.get("status") in ["ACTIVE", "LIFTED"]


def assert_identity_request(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("subject_user_id"), str)
    assert isinstance(data.get("requester_label"), str)
    assert data.get("channel") in ["MEDIA", "LEGAL_SUBPOENA", "LAW_ENFORCEMENT"]
    assert data.get("status") in [
        "RECEIVED", "UNDER_REVIEW", "NOTICE_SENT", "RELEASED", "DECLINED", "WITHDRAWN",
    ]


def assert_merge_request(data: dict):
    _assert_versioned(data)
    assert isinstance(data.get("duplicate_page_id"), str)
    assert isinstance(data.get("survivor_page_id"), str)
    assert isinstance(data.get("reason"), str)
    assert data.get("status") in ["PENDING", "EXECUTED", "REJECTED"]


def assert_page_displayed_invariants(page: dict):
    """Displayed aggregate invariants (PRD §2.8): count >= 0, and average is
    exactly 0 whenever the displayed count is 0."""
    assert page["displayed_review_count"] >= 0
    if page["displayed_review_count"] == 0:
        assert page["displayed_rating_avg_x100"] == 0
