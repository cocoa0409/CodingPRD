"""Entity assertions and domain invariant checkers.

Each assert_* validates the PRD-visible shape of a resource: system-managed
common fields plus the entity's own fields with their types.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["auto_renew_enabled"], bool)
    assert data["status"] in ("ACTIVE", "LAPSED")
    assert isinstance(data["primary_member_id"], str) and data["primary_member_id"]
    assert "secondary_member_id" in data
    assert isinstance(data["lifetime_collected_cents"], int)
    assert isinstance(data["lifetime_refunded_cents"], int)


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["role_in_household"] in ("PRIMARY", "SECONDARY")
    assert isinstance(data["benefit_marketing_opt_out"], bool)
    assert isinstance(data["age_years"], int)
    assert isinstance(data["in_good_standing"], bool)


def assert_membership_term(data: dict):
    _assert_common(data)
    assert isinstance(data["household_id"], str) and data["household_id"]
    assert data["term_years"] in (1, 3, 5)
    assert isinstance(data["is_renewal"], bool)
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert is_iso8601_timestamp(data.get("purchased_at", ""))
    assert isinstance(data["paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)
    assert data["status"] in ("ACTIVE", "RENEWED", "LAPSED", "CANCELLED")


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in ("APPLICANT", "LICENSED", "SUSPENDED")
    assert isinstance(data["royalty_balance_cents"], int)
    assert isinstance(data["escalations_trailing_12mo"], int)


def assert_license_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert data["product_category"] in (
        "INSURANCE_HEALTH", "INSURANCE_AUTO", "INSURANCE_LIFE",
        "FINANCIAL_SERVICES", "TRAVEL_SERVICES", "HOME_SERVICES",
    )
    assert isinstance(data["effective_from"], str) and data["effective_from"]
    assert isinstance(data["effective_to"], str) and data["effective_to"]
    assert data["status"] in ("DRAFT", "ACTIVE", "PROBATION", "TERMINATED")
    assert isinstance(data["probation_count"], int)
    assert isinstance(data["escalations_trailing_12mo"], int)
    assert isinstance(data["recognized_royalty_cents"], int)
    assert isinstance(data["provisional_outstanding_cents"], int)


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["license_agreement_id"], str) and data["license_agreement_id"]
    assert isinstance(data["period_year"], int)
    assert data["period_quarter"] in (1, 2, 3, 4)
    assert isinstance(data["reported_sales_cents"], int)
    assert isinstance(data["provisional_royalty_cents"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "SUPERSEDED")


def assert_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert isinstance(data["license_agreement_id"], str) and data["license_agreement_id"]
    assert data["category"] in ("PRODUCT_QUALITY", "BILLING", "SERVICE", "CLAIMS")
    assert data["severity"] in ("LOW", "HIGH")
    assert data["status"] in ("FILED", "UNDER_REVIEW", "ESCALATED", "RESOLVED")
    assert is_iso8601_timestamp(data.get("filed_at", ""))


def assert_legal_entity(data: dict):
    _assert_common(data)
    assert data["kind"] in ("MEMBERSHIP_ORG", "FOUNDATION", "LOBBY_ARM")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["balance_cents"], int)


def assert_fund_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["from_entity_id"], str) and data["from_entity_id"]
    assert isinstance(data["to_entity_id"], str) and data["to_entity_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["requested_by_user_id"], str)
    assert data["status"] in ("PENDING_APPROVAL", "EXECUTED", "REJECTED")


def assert_publication(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["publication_date"], str) and data["publication_date"]
    assert isinstance(data["min_cpm_cents"], int)
    assert isinstance(data["max_cpm_cents"], int)
    assert data["max_cpm_cents"] >= data["min_cpm_cents"]
    assert isinstance(data["circulation_count"], int) and data["circulation_count"] >= 0


def assert_ad_booking(data: dict):
    _assert_common(data)
    assert isinstance(data["publication_id"], str) and data["publication_id"]
    assert isinstance(data["advertiser_name"], str) and data["advertiser_name"]
    assert data["category"] in (
        "TRAVEL", "INSURANCE", "HEALTH", "FINANCE", "RETAIL",
        "TOBACCO", "FIREARMS", "POLITICAL",
    )
    assert isinstance(data["agreed_cpm_cents"], int)
    assert isinstance(data["estimated_cost_cents"], int)
    assert data["status"] == "BOOKED"


def assert_chapter(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["city"], str) and data["city"]


def assert_course_session(data: dict):
    _assert_common(data)
    assert isinstance(data["chapter_id"], str) and data["chapter_id"]
    assert data["course_kind"] in ("TAX_PREP", "DRIVER_SAFETY")
    assert isinstance(data["instructor_name"], str) and data["instructor_name"]
    assert is_iso8601_timestamp(data.get("start_time", ""))
    assert is_iso8601_timestamp(data.get("end_time", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_member_ids"], list)
    assert data["enrolled_count"] == len(data["enrolled_member_ids"])
    assert data["status"] in ("SCHEDULED", "HELD")


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["level"] in ("FEDERAL", "STATE")
    assert isinstance(data["issue_area"], str) and data["issue_area"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["end_date"] >= data["start_date"]
    assert isinstance(data["sponsor_entity_id"], str) and data["sponsor_entity_id"]
    assert data["computed_status"] in ("UPCOMING", "ACTIVE", "CLOSED")


def assert_mobilization_event(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str) and data["campaign_id"]
    assert data["channel"] in ("EMAIL", "PHONE", "MAIL")
    assert isinstance(data["audience_spec"], dict)
    assert isinstance(data["audience_count"], int) and data["audience_count"] >= 0


def assert_royalty_exposure_invariant(agreement: dict, provider: dict):
    """The royalty ledger conservation invariant from the PRD: an agreement's
    recognized plus provisional-outstanding buckets equal this agreement's
    contribution to the provider's royalty balance (the whole balance when the
    provider has exactly one agreement)."""
    exposure = agreement["recognized_royalty_cents"] + agreement["provisional_outstanding_cents"]
    assert exposure == provider["royalty_balance_cents"], (
        f"royalty exposure {exposure} != provider balance "
        f"{provider['royalty_balance_cents']}"
    )


def assert_balance_conservation(from_before, to_before, from_after, to_after):
    """Fund transfers move cents; they never create or destroy them."""
    assert from_after + to_after == from_before + to_before, (
        f"pair balance not conserved: {from_before}+{to_before} before vs "
        f"{from_after}+{to_after} after"
    )
