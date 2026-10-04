"""Entity assertions and score-snapshot helpers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_publication(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("outlet_name"), str) and data["outlet_name"]
    assert data.get("reach_tier") in ("NATIONAL", "REGIONAL", "NICHE")
    assert data.get("status") in ("PENDING", "ACCREDITED", "PROBATION", "REVOKED")
    assert isinstance(data.get("accredited_critic_count"), int)
    assert data["accredited_critic_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_critic(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert is_valid_uuid(data.get("publication_id", ""))
    assert isinstance(data.get("is_top_critic"), bool)
    assert data.get("accreditation_status") in (
        "APPLIED", "ACCREDITED", "UNDER_REVIEW", "PROBATION", "REVOKED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_title(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("canonical_name"), str) and data["canonical_name"]
    assert isinstance(data.get("release_year"), int)
    assert data.get("posture") in ("SETUP", "OPEN", "RETIRED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_release(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data.get("cut_label"), str) and data["cut_label"]
    assert data.get("status") in ("UPCOMING", "OPEN", "CLOSED")
    assert isinstance(data.get("audience_display_suspended"), bool)
    tomatometer = data.get("tomatometer_pct")
    assert tomatometer is None or (isinstance(tomatometer, int)
                                   and 0 <= tomatometer <= 100)
    audience = data.get("audience_score_pct")
    assert audience is None or (isinstance(audience, int)
                                and 0 <= audience <= 100)
    assert data.get("certification") in (
        "NONE", "CERTIFIED_FRESH", "CERTIFIED_ROTTEN")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("critic_id", ""))
    assert data.get("self_designation") in ("FRESH", "ROTTEN")
    assert data.get("status") in ("INGESTED", "PUBLISHED", "FLAGGED", "WITHDRAWN")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_ticket_verification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("audience_member_id", ""))
    assert data.get("status") in ("SUBMITTED", "VERIFIED", "REJECTED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_audience_rating(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("audience_member_id", ""))
    assert isinstance(data.get("stars"), int) and 1 <= data["stars"] <= 5
    assert data.get("status") in ("UNVERIFIED", "VERIFIED", "INVALIDATED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def find_live_snapshot(snapshots, scope, variant):
    """Return the non-superseded snapshot for (scope, variant), or None."""
    for snap in snapshots:
        if (snap.get("scope") == scope
                and snap.get("variant") == variant
                and snap.get("superseded") is False):
            return snap
    return None
