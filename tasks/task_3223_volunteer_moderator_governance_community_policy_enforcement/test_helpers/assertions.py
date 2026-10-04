"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _require(data: dict, *fields):
    for field in fields:
        assert field in data, f"response is missing the field {field!r}"


def assert_envelope_identity(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a plain UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be an ISO 8601 timestamp"


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version, for a mutable resource."""
    assert_envelope_identity(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_identity(data: dict):
    """id + created_at only; updated_at and version are absent by design."""
    assert_envelope_identity(data)
    assert "updated_at" not in data, "an append-only record carries no updated_at"
    assert "version" not in data, "an append-only record carries no version"


def assert_community(data: dict):
    assert_common_fields(data)
    _require(data, "name", "description", "is_over_18", "state", "enforcement_tier",
             "health_index", "open_report_weight", "inactive_moderator_count",
             "active_top_moderator_count", "active_moderator_count", "active_rule_count",
             "applying_sanction_count")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["description"], str)
    assert isinstance(data["is_over_18"], bool)
    assert data["state"] in ["ACTIVE", "PROTEST_RESTRICTED", "RESTRICTED",
                             "INSTITUTION_NEGOTIATION", "QUARANTINED", "ARCHIVED"]
    assert data["enforcement_tier"] in [1, 2, 3]
    assert 0.00 <= data["health_index"] <= 100.00
    assert data["open_report_weight"] >= 0.00
    assert isinstance(data["inactive_moderator_count"], int)


def assert_community_rule(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "rule_code", "rule_text", "rule_band", "is_sitewide_floor", "status")
    assert isinstance(data["rule_band"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["is_sitewide_floor"], bool)


def assert_moderator(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "moderator_account_id", "display_name", "moderator_role",
             "is_top_moderator", "top_rank", "status", "moderator_version")
    assert data["status"] in ["ACTIVE", "REMOVED_FOR_INACTIVITY", "RESIGNED", "DEMOTED"]
    assert data["moderator_role"] in ["TOP_MODERATOR", "REGULAR_MODERATOR"]
    assert isinstance(data["is_top_moderator"], bool)
    assert isinstance(data["top_rank"], int)
    assert isinstance(data["moderator_version"], int)


def assert_team_succession(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "state", "previous_state", "discussion_round_count",
             "initiated_at_utc", "handover_deadline_utc")
    assert data["state"] in ["PENDING_HANDOVER", "DISCUSSION", "HANDOVER_BLOCKED", "COMPLETED"]
    assert isinstance(data["discussion_round_count"], int)


def assert_post(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "author_account_id", "title", "body", "post_type", "status", "removal_count")
    assert data["post_type"] in ["TEXT", "LINK", "IMAGE", "CROSSPOST"]
    assert data["status"] in ["PUBLISHED", "REMOVED", "LOCKED"]
    assert isinstance(data["removal_count"], int)


def assert_account(data: dict):
    assert_common_fields(data)
    _require(data, "handle", "account_state", "karma_points", "account_sanction_index")
    assert data["account_state"] in ["HONORED", "WARNED", "MUTED", "BANNED"]
    assert 50 <= data["karma_points"] <= 100
    assert 0.0 <= data["account_sanction_index"] <= 1.0


def assert_content_report(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "content_source_type", "content_source_id",
             "reporter_account_id", "report_reason_code", "resolution_tier", "status")
    assert data["content_source_type"] in ["POST", "COMMENT", "ACCOUNT"]
    assert data["resolution_tier"] in [1, 2, 3]
    assert data["status"] in ["OPEN", "RESOLVED", "RESOLVED_LOCKED", "DISMISSED"]


def assert_detection_item(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "source_type", "source_id", "subject_account_id",
             "signal_severity_band", "detection_confidence", "overlap_ratio",
             "published_at_utc", "status")
    assert 1 <= data["signal_severity_band"] <= 5
    assert 0.0 <= data["detection_confidence"] <= 1.0
    assert 0.0 <= data["overlap_ratio"] <= 1.0
    assert data["status"] in ["OPEN", "CONSUMED", "DISMISSED"]
    assert isinstance(data["legitimacy_score"], int)
    assert data["legitimacy_band"] in ["LOW", "MID", "HIGH"]


def assert_content_decision(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "decision_outcome", "dissection_band",
             "effective_enforcement_tier", "requires_cross_power_approval",
             "community_safety_override", "status", "audit_log_ref")
    assert data["decision_outcome"] in ["KEEP", "REMOVE", "LOCK", "REPORT_REJECTED",
                                        "WARNING_ISSUED", "MUTE_ISSUED", "BAN_ISSUED"]
    assert 1 <= data["effective_enforcement_tier"] <= 5
    assert isinstance(data["requires_cross_power_approval"], bool)
    assert isinstance(data["community_safety_override"], bool)
    assert data["audit_log_ref"] != data["id"], "audit_log_ref is distinct from the decision id"
    assert data["status"] in ["RECORDED", "AUDITED", "REVISED", "SETTLED"]


def assert_account_sanction(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "account_id", "decision_id", "decision_outcome",
             "status", "account_wide_enforcement_counted", "award_points", "sanction_date_utc")
    assert data["status"] in ["ACTIVE", "LIFTED"]
    assert isinstance(data["account_wide_enforcement_counted"], bool)
    assert isinstance(data["award_points"], int)


def assert_brigading_cluster(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "internal_link_count", "external_link_count",
             "participant_count", "legitimate_participant_count", "overlap_ratio",
             "signal_severity_band", "evidence_complete", "status", "detected_at_utc")
    assert 0.0 <= data["overlap_ratio"] <= 1.0
    assert 1 <= data["signal_severity_band"] <= 5
    assert data["evidence_complete"] == (data["overlap_ratio"] >= 0.30)
    assert data["status"] in ["DETECTED", "ESCALATED", "DISMISSED"]


def assert_appeal(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "account_id", "sanction_id", "ground_code",
             "state", "filed_at_utc", "referral_count")
    assert data["ground_code"] in ["ANALYSIS_ERROR", "MODERATOR_MISCONDUCT"]
    assert data["state"] in ["FILED", "SUBMITTED", "UNDER_WATCH", "GRANTED", "DENIED"]
    assert isinstance(data["referral_count"], int)


def assert_protest_event(data: dict):
    assert_common_fields(data)
    _require(data, "community_id", "requested_access_mode", "status",
             "quorum_approval_count", "required_quorum_count", "distinct_power_count")
    assert data["requested_access_mode"] in ["READ_ONLY", "RESTRICTED", "PRIVATE"]
    assert data["status"] in ["REQUESTED", "COORDINATED", "ENDED"]
    assert isinstance(data["quorum_approval_count"], int)
    assert isinstance(data["required_quorum_count"], int)


def assert_protest_approval(data: dict):
    assert_append_only_identity(data)
    _require(data, "protest_id", "moderator_id", "approving_account_id", "approved_on_utc")


# --- domain invariant checkers ----------------------------------------------

def assert_health_index_invariants(data: dict):
    """health_index is a 2 dp value inside the closed interval [0.00, 100.00]."""
    assert 0.00 <= data["health_index"] <= 100.00
    assert_cost_precision(data["health_index"], places=2)
    assert_cost_precision(data["open_report_weight"], places=2)


def assert_enforcement_tier_ladder(data: dict):
    """The ladder tracks applying_sanction_count: 1 when <=1, 2 at exactly 2, 3 at >=3."""
    count = data["applying_sanction_count"]
    expected = 1 if count <= 1 else (2 if count == 2 else 3)
    assert data["enforcement_tier"] == expected, (
        f"enforcement_tier {data['enforcement_tier']} does not match "
        f"applying_sanction_count {count}"
    )


def assert_karma_bounds(data: dict):
    assert 50 <= data["karma_points"] <= 100
    assert isinstance(data["karma_points"], int)


def assert_decision_flags_consistent(data: dict):
    tier = data["effective_enforcement_tier"]
    precedent = data["precedent_approval_count"]
    if tier == 5 and precedent < 3:
        assert data["requires_cross_power_approval"] is True
    else:
        assert data["requires_cross_power_approval"] is False
    if tier == 5 and data["community_health_index_override_present"] is False:
        assert data["community_safety_override"] is True
    else:
        assert data["community_safety_override"] is False


def assert_cluster_band_capped(data: dict):
    assert 1 <= data["signal_severity_band"] <= 5


def assert_cross_power_quorum_met(data: dict):
    assert data["distinct_power_count"] >= 2


def assert_quorum_met(data: dict):
    assert data["quorum_approval_count"] >= data["required_quorum_count"]


def assert_pagination_meta(meta: dict):
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"pagination meta is missing {field!r}"
    assert isinstance(meta["has_more"], bool)
    assert isinstance(meta["total_count"], int)