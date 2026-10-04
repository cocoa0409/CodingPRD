"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BlurObligation,
    ContributorLevel,
    ContributorStatus,
    EditStatus,
    EditType,
    FlagReason,
    FlagStatus,
    GrantSourceType,
    GrantStatus,
    HoursSource,
    ImageryStatus,
    ListingCategory,
    ListingStatus,
    ListingVisibility,
    RegionPosture,
    ReviewStatus,
    RoutingKind,
    RoutingStatus,
    SuspensionCaseStatus,
    TicketPriority,
    TicketQueue,
    TicketResolution,
    TicketStatus,
    UserReview,
    VerificationFailureReason,
    VerificationMethod,
    VerificationStatus,
    ViolationType,
)


def _assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), (
            f"version must be an integer, got {data.get('version')!r}"
        )


def assert_region(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["country_code"], str) and len(data["country_code"]) == 2
    assert isinstance(data["timezone"], str) and len(data["timezone"]) > 0
    assert isinstance(data["geo_min_lat"], (int, float))
    assert isinstance(data["geo_max_lat"], (int, float))
    assert isinstance(data["geo_min_lng"], (int, float))
    assert isinstance(data["geo_max_lng"], (int, float))
    assert data["posture"] in [p.value for p in RegionPosture]
    assert isinstance(data["privacy_pending_count"], int)
    assert isinstance(data["routing_version"], int)
    assert isinstance(data["max_active_imagery_tasks"], int)


def assert_contributor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert is_valid_uuid(data.get("home_region_id", ""))
    assert data["status"] in [s.value for s in ContributorStatus]
    assert isinstance(data["total_points"], int)
    assert isinstance(data["lifetime_points"], int)
    assert data["level"] in [lv.value for lv in ContributorLevel]
    assert isinstance(data["provisional_trust_score"], (int, float))
    assert isinstance(data["finalized_trust_score"], (int, float))
    assert isinstance(data["failed_verification_count"], int)


def assert_contributor_grant(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "ContributorGrant must not carry updated_at"
    assert "version" not in data, "ContributorGrant must not carry version"
    assert is_valid_uuid(data.get("contributor_id", ""))
    assert data["source_type"] in [s.value for s in GrantSourceType]
    assert isinstance(data["source_id"], str)
    assert isinstance(data["base_points"], int)
    assert isinstance(data["quality_multiplier"], (int, float))
    assert isinstance(data["points"], int)
    assert data["status"] in [s.value for s in GrantStatus]


def assert_business_listing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("region_id", ""))
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in [c.value for c in ListingCategory]
    assert isinstance(data["address_text"], str)
    assert isinstance(data["geo_lat"], (int, float))
    assert isinstance(data["geo_lng"], (int, float))
    assert data["status"] in [s.value for s in ListingStatus]
    assert data["visibility"] in [v.value for v in ListingVisibility]
    assert isinstance(data["health_score"], (int, float))
    assert isinstance(data["moderation_health_score"], (int, float))
    assert isinstance(data["review_count"], int)
    assert isinstance(data["rating_avg"], (int, float))
    assert isinstance(data["accepted_edit_count"], int)
    assert isinstance(data["keyword_stuffing_strikes"], int)


def assert_verification_attempt(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["method"] in [m.value for m in VerificationMethod]
    assert data["status"] in [s.value for s in VerificationStatus]
    assert isinstance(data["attempts_used"], int)
    assert isinstance(data["max_attempts"], int)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    if data.get("failure_reason") is not None:
        assert data["failure_reason"] in [r.value for r in VerificationFailureReason]


def assert_map_edit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert is_valid_uuid(data.get("contributor_id", ""))
    assert data["edit_type"] in [t.value for t in EditType]
    assert isinstance(data["payload"], dict)
    assert data["status"] in [s.value for s in EditStatus]
    assert isinstance(data["auto_score"], (int, float))
    assert isinstance(data["quality_weight"], (int, float))


def assert_review_ticket(data: dict):
    _assert_common_fields(data)
    assert data["queue"] in [q.value for q in TicketQueue]
    assert data["status"] in [s.value for s in TicketStatus]
    assert data["priority"] in [p.value for p in TicketPriority]
    if data.get("resolution") is not None:
        assert data["resolution"] in [r.value for r in TicketResolution]


def assert_user_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert is_valid_uuid(data.get("contributor_id", ""))
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5
    assert isinstance(data["text"], str) and len(data["text"]) > 0
    assert data["status"] in [s.value for s in ReviewStatus]
    assert isinstance(data["fake_probability"], (int, float))
    assert isinstance(data["flag_count"], int)


def assert_review_flag(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "ReviewFlag must not carry updated_at"
    assert "version" not in data, "ReviewFlag must not carry version"
    assert is_valid_uuid(data.get("review_id", ""))
    assert data["reason"] in [r.value for r in FlagReason]
    assert data["status"] in [s.value for s in FlagStatus]
    assert isinstance(data["reporter_is_owner"], bool)


def assert_suspension_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["violation_type"] in [v.value for v in ViolationType]
    assert data["status"] in [s.value for s in SuspensionCaseStatus]
    assert isinstance(data["evidence_notes"], str)
    assert is_iso8601_timestamp(data.get("appeal_deadline", ""))


def assert_hours_observation(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "HoursObservation must not carry updated_at"
    assert "version" not in data, "HoursObservation must not carry version"
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["source"] in [s.value for s in HoursSource]
    assert isinstance(data["day_mask"], str) and len(data["day_mask"]) == 7
    assert isinstance(data["open_time"], str)
    assert isinstance(data["close_time"], str)
    assert isinstance(data["corroboration_count"], int)
    assert isinstance(data["accepted"], bool)


def assert_imagery_task(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("region_id", ""))
    assert isinstance(data["collection_zone"], str)
    assert isinstance(data["operator_id"], str)
    assert data["status"] in [s.value for s in ImageryStatus]
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["blur_obligation"] in [b.value for b in BlurObligation]
    assert isinstance(data["capture_media_count"], int)
    assert isinstance(data["blurred_media_count"], int)


def assert_routing_update(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("region_id", ""))
    assert isinstance(data["segment_ref"], str)
    assert data["kind"] in [k.value for k in RoutingKind]
    assert data["status"] in [s.value for s in RoutingStatus]
    assert is_iso8601_timestamp(data.get("effective_start", ""))
    assert is_iso8601_timestamp(data.get("effective_end", ""))
