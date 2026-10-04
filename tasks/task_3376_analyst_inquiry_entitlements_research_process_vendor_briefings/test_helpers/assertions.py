"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ENTITLEMENT_MATRIX,
    MAX_INCLUSION_CRITERIA_MET,
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
    SPONSOR_SHARE_CEILING,
    TIER_BASE_FEE_CENTS,
)


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at and an integer version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_client_account(data: dict):
    assert_common_fields(data)
    assert data["contract_status"] in ["ACTIVE", "RENEWAL_REVIEW", "RENEWED", "CHURNED"]
    assert data["region"] in ["NA", "EMEA", "APAC"]
    assert data["reprint_tier"] in ["NONE", "STANDARD", "PREMIUM"]
    for field in ("active_seat_count", "provisioned_seat_count", "revoked_seat_count",
                  "consumed_inquiry_units", "reserved_inquiry_units",
                  "remaining_reserved_units", "remaining_consumed_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["renewal_posture"] in ["HEALTHY", "WATCH", "AT_RISK"]


def assert_ledger_identity(data: dict):
    """inquiry_allowance_total == remaining_reserved + reserved + consumed."""
    total = data["inquiry_allowance_total"]
    lhs = data["remaining_reserved_units"] + data["reserved_inquiry_units"] + \
        data["consumed_inquiry_units"]
    assert lhs == total, (
        f"Allowance identity broken: {data['remaining_reserved_units']} + "
        f"{data['reserved_inquiry_units']} + {data['consumed_inquiry_units']} != {total}"
    )


def assert_seat(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PROVISIONED", "ACTIVE", "REVOKED"]
    assert data["seat_kind"] in ["NAMED", "SHARED"]
    assert data["research_role"] in ENTITLEMENT_MATRIX
    assert isinstance(data["entitlement_document_types"], list)
    assert isinstance(data["entitlement_override_types"], list)
    if data["status"] == "PROVISIONED":
        assert data["activated_at"] is None and data["revoked_at"] is None
    if data["status"] == "REVOKED":
        assert data["entitlement_document_types"] == []


def assert_analyst(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "ON_LEAVE", "EMERITUS"]
    assert data["seniority"] in ["ASSOCIATE", "SENIOR", "VP", "DISTINGUISHED"]
    assert data["integrity_flag"] in ["CLEAR", "CONFLICT_REVIEW", "CONFLICT_BLOCKED"]
    assert isinstance(data["conflicted_vendor_ids"], list)
    assert isinstance(data["topic_routes"], list)


def assert_inquiry(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "ROUTED", "SCHEDULED", "IN_PREP", "COMPLETED", "NO_SHOW", "CANCELLED",
    ]
    assert data["duration_minutes"] in (30, 45, 60)
    assert isinstance(data["declined_analyst_ids"], list)
    if data["status"] in ("COMPLETED", "NO_SHOW"):
        assert data["units_consumed"] == 1
        assert data["settled_at"] is not None


def assert_document(data: dict):
    assert_common_fields(data)
    assert data["editorial_status"] in [
        "DRAFT", "PEER_REVIEW", "FACT_CHECK", "CLEARED", "PUBLISHED", "REVISED",
    ]
    assert data["embargo_status"] in ["EMBARGOED", "RELEASED"]
    assert data["peer_verdict"] in ["NOT_ASSIGNED", "PENDING", "APPROVE", "REVISE"]
    assert data["doc_type"] in [
        "MARKET_GUIDE", "COMPARATIVE_MATRIX", "HYPE_PROFILE", "CRITICAL_CAPABILITIES",
    ]


def assert_vendor(data: dict):
    assert_common_fields(data)
    assert data["status"] == "ACTIVE"
    assert isinstance(data["briefing_eligible"], bool)
    assert isinstance(data["active_sales_relationship_count"], int)


def assert_inclusion(data: dict):
    assert_common_fields(data)
    assert data["inclusion_status"] in [
        "PROPOSED", "UNDER_EVALUATION", "INCLUDED", "EXCLUDED", "UNDER_APPEAL",
        "APPEAL_UPHELD", "APPEAL_DENIED", "SUPERSEDED",
    ]
    assert data["fact_check_status"] in [
        "NOT_STARTED", "REQUESTED", "VENDOR_RESPONDED", "ADJUDICATED", "DISPUTED", "LAPSED",
    ]
    assert data["reprint_tier"] in ["NONE", "STANDARD", "PREMIUM"]
    assert data["permitted_marketing_use"] in [
        "NO_USE", "INTERNAL_ONLY", "SOCIAL_SNIPPET", "FULL_REPRINT",
    ]
    assert isinstance(data["placement_locked"], bool)
    assert isinstance(data["lead_analyst_conflicted"], bool)
    assert data["reprint_fee_cents"] >= 0
    if data["reprint_tier"] == "NONE":
        assert data["reprint_fee_cents"] == 0


def assert_briefing(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "REQUESTED", "SCREENED", "SCHEDULED", "HELD", "DECLINED", "REVOKED_BY_SEPARATION",
    ]
    assert data["separation_check_result"] in ["PENDING", "PASS", "FAIL_SALES_RELATIONSHIP"]
    assert data["duration_minutes"] in (30, 45, 60)
    if data["status"] == "HELD":
        assert data["held_at"] is not None


def assert_sales_relationship(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert data["relationship_type"] in ["SPONSORSHIP", "PAID_ADVISORY", "SPEAKING_FEE"]
    if data["status"] == "TERMINATED":
        assert data["terminated_at"] is not None


def assert_conference_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "PROGRAMMING", "AGENDA_LOCKED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["sessions"], list)
    assert isinstance(data["sponsorship_revenue_cents"], int)
    assert data["sponsor_minute_share"] <= SPONSOR_SHARE_CEILING or data["status"] == "COMPLETED"


def assert_sponsorship(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "ACTIVE", "CANCELLED"]
    assert data["tier"] in ["PLATINUM", "GOLD", "SILVER"]
    assert isinstance(data["sponsor_slot_counted"], bool)
    if data["status"] == "ACTIVE":
        assert data["sponsor_slot_counted"] is True
        assert data["activated_at"] is not None
    if data["status"] == "CANCELLED":
        assert data["cancelled_at"] is not None


def assert_pagination_meta(meta: dict, expected_total=None):
    assert meta["limit"] >= PAGINATION_LIMIT_MIN
    assert meta["limit"] <= PAGINATION_LIMIT_MAX
    assert meta["offset"] >= 0
    assert isinstance(meta["total_count"], int)
    assert isinstance(meta["has_more"], bool)
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )


def assert_default_pagination(meta: dict):
    assert meta["limit"] == PAGINATION_LIMIT_DEFAULT
    assert meta["offset"] == PAGINATION_OFFSET_DEFAULT


def assert_entitlement_matrix(research_role: str, overrides, actual):
    """Base role types in matrix order, then overrides appended and de-duplicated."""
    expected = list(ENTITLEMENT_MATRIX[research_role])
    for doc_type in overrides or []:
        if doc_type not in expected:
            expected.append(doc_type)
    assert actual == expected, (
        f"Expected entitlement_document_types {expected}, got {actual}"
    )


def assert_reprint_fee(data: dict):
    """The licence fee is a whole number of cents and is 0 for the NONE tier."""
    fee = data["reprint_fee_cents"]
    assert isinstance(fee, int), f"reprint_fee_cents must be an integer, got {fee!r}"
    assert fee >= 0
    if data["reprint_tier"] == "NONE":
        assert fee == 0, f"NONE tier must not be charged, got {fee}"
    assert TIER_BASE_FEE_CENTS[data["reprint_tier"]] >= 0


def assert_inclusion_criteria_range(data: dict):
    assert 0 <= data["inclusion_criteria_met_count"] <= MAX_INCLUSION_CRITERIA_MET
