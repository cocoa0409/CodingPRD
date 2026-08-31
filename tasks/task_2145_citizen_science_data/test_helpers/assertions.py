"""Entity assertions and domain invariant checkers."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS

_ISO_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_iso8601_millis(value, field="timestamp"):
    """PRD: ISO 8601 UTC timestamp with three fractional digits."""
    assert isinstance(value, str) and _ISO_MILLIS.match(value), (
        f"{field} must be an ISO 8601 UTC timestamp with exactly three "
        f"fractional digits, got {value!r}"
    )


def assert_bare_uuid(value, field="id"):
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert not re.match(r"^[A-Za-z]+_", value), (
        f"{field} must be a bare UUID with no type prefix, got {value!r}"
    )
    assert is_valid_uuid(value), f"{field} must be a valid UUID, got {value!r}"


def assert_common_fields(data, versioned=True):
    assert_bare_uuid(data.get("id"))
    assert_iso8601_millis(data.get("created_at"), "created_at")
    if versioned:
        assert_iso8601_millis(data.get("updated_at"), "updated_at")
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be an integer >= 1, got {data.get('version')!r}"
        )


def assert_append_only_row(data):
    """VerificationVote / RecognitionAward carry only id and created_at."""
    assert_bare_uuid(data.get("id"))
    assert_iso8601_millis(data.get("created_at"), "created_at")
    assert "updated_at" not in data or data["updated_at"] is None, (
        "append-only ledger rows must not carry updated_at"
    )
    assert "version" not in data or data["version"] is None, (
        "append-only ledger rows must not carry version"
    )


def assert_protocol(data):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert data["required_certification_level"] in ("BASIC", "ADVANCED", "EXPERT")
    assert isinstance(data["min_photo_count"], int) and data["min_photo_count"] >= 0
    assert isinstance(data["max_submission_lag_hours"], int)
    assert data["max_submission_lag_hours"] > 0
    assert data["required_equipment_type"] in (
        "NONE", "ACOUSTIC_RECORDER", "GPS_LOGGER", "SPOTTING_SCOPE")
    assert isinstance(data["certification_valid_days"], int)
    assert data["certification_valid_days"] > 0
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1


def assert_volunteer(data):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACTIVE", "PROBATION", "SUSPENDED")
    assert data["recognition_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert 0.0 <= float(data["quality_score"]) <= 1.0
    assert 0.0 <= float(data["lifetime_quality_score"]) <= 1.0
    for counter in ("lifetime_points", "accepted_observation_count",
                    "rejected_observation_count", "consecutive_accepted",
                    "consecutive_rejections"):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_expert(data):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert 0.50 <= float(data["verification_weight"]) <= 4.00
    assert isinstance(data["vote_count"], int)
    assert isinstance(data["retracted_confirm_count"], int)


def assert_certification(data):
    assert_common_fields(data)
    assert data["status"] in ("ENROLLED", "TRAINED", "CERTIFIED",
                              "SUSPENDED", "EXPIRED", "REVOKED")
    assert data["level"] in ("BASIC", "ADVANCED", "EXPERT")
    assert data["suspended_reason"] in ("NONE", "QUALITY_PROBATION")


def assert_campaign(data):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED", "PUBLISHED", "ARCHIVED")
    assert isinstance(data["target_observations_per_site"], int)
    assert data["target_observations_per_site"] > 0
    assert isinstance(data["site_count"], int) and data["site_count"] >= 0
    assert isinstance(data["gap_count"], int) and data["gap_count"] >= 0
    assert data["gap_count"] <= data["site_count"]
    assert 0.0 <= float(data["coverage_score"]) <= 1.0
    assert isinstance(data["accepted_observation_count"], int)


def assert_survey_site(data):
    assert_common_fields(data)
    assert data["habitat_type"] in ("WETLAND", "FOREST", "GRASSLAND", "URBAN", "COASTAL")
    assert data["coverage_status"] in ("GAP", "UNDER", "MET", "SATURATED")
    assert 0.0 <= float(data["coverage_ratio"]) <= 1.0
    assert 0.50 <= float(data["priority_weight"]) <= 2.00
    assert isinstance(data["accepted_observation_count"], int)


def assert_observation(data):
    assert_common_fields(data)
    assert data["review_status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION",
                                     "ACCEPTED", "REJECTED", "RETRACTED")
    assert data["publication_status"] in ("UNPUBLISHED", "QUEUED", "PUBLISHED", "WITHDRAWN")
    assert isinstance(data["revision_round"], int)
    assert 0 <= data["revision_round"] <= THRESHOLDS["MAX_REVISION_ROUNDS"]
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0
    assert isinstance(data["count_value"], int) and data["count_value"] >= 0
    assert float(data["provisional_quality_points"]) >= 0.0
    assert float(data["final_quality_points"]) >= 0.0
    assert_iso8601_millis(data["submitted_at"], "submitted_at")


def assert_photo_evidence(data):
    assert_common_fields(data)
    assert data["status"] in ("ACCEPTED", "FLAGGED_MISMATCH", "REJECTED")
    assert float(data["geo_delta_meters"]) >= 0.0


def assert_verification_vote(data):
    assert_append_only_row(data)
    assert data["decision"] in ("CONFIRM", "REJECT", "REQUEST_REVISION")
    assert isinstance(data["confidence"], int) and 1 <= data["confidence"] <= 5
    assert isinstance(data["round_number"], int) and data["round_number"] >= 0
    assert float(data["weight_applied"]) > 0.0


def assert_equipment(data):
    assert_common_fields(data)
    assert data["status"] in ("AVAILABLE", "ON_LOAN", "QUARANTINE",
                              "IN_CALIBRATION", "RETIRED")
    assert data["equipment_type"] in ("ACOUSTIC_RECORDER", "GPS_LOGGER", "SPOTTING_SCOPE")
    assert float(data["calibration_drift_ppm"]) >= 0.0
    assert isinstance(data["total_loan_hours"], int) and data["total_loan_hours"] >= 0


def assert_equipment_loan(data):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "ISSUED", "RETURNED",
                              "OVERDUE", "LOST", "CANCELLED")
    assert data["condition_on_return"] in ("NONE", "GOOD", "DAMAGED", "LOST")
    assert isinstance(data["loan_hours"], int) and data["loan_hours"] >= 0
    assert float(data["drift_added_ppm"]) >= 0.0


def assert_data_publication(data):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "EMBARGOED", "RELEASED", "WITHDRAWN")
    assert isinstance(data["record_count"], int) and data["record_count"] >= 0
    assert float(data["quality_floor"]) >= 0.0
    assert float(data["mean_quality"]) >= 0.0


def assert_research_partner(data):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED")
    assert data["trust_tier"] in ("STANDARD", "TRUSTED")
    assert isinstance(data["active_grant_count"], int)
    assert data["active_grant_count"] >= 0


def assert_partner_access_grant(data):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED", "EXPIRED")
    assert data["scope"] in ("AGGREGATE", "FULL", "SENSITIVE")
    assert data["denied_reason"] in ("NONE", "PUBLICATION_WITHDRAWN",
                                     "GRANT_EXPIRED", "ADMIN_REVOKED")


def assert_recognition_award(data):
    assert_append_only_row(data)
    assert data["award_type"] in ("OBSERVATION_ACCEPTED", "STREAK_BONUS",
                                  "MILESTONE", "REVERSAL")
    assert isinstance(data["points_awarded"], int)


# --- Domain invariant checkers ---

def assert_points_ledger_conserved(volunteer, award_rows):
    """PRD: the sum of points_awarded for a volunteer equals lifetime_points."""
    total = sum(int(row["points_awarded"]) for row in award_rows)
    assert total == int(volunteer["lifetime_points"]), (
        f"recognition ledger sum {total} must equal lifetime_points "
        f"{volunteer['lifetime_points']}"
    )


def assert_scale_2dp(value, field="value"):
    quantised = round(float(value) + 1e-9, 2)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{field} must be carried at 2 decimal places, got {value!r}"
    )


def assert_scale_4dp(value, field="value"):
    quantised = round(float(value) + 1e-11, 4)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{field} must be carried at 4 decimal places, got {value!r}"
    )


def assert_coverage_consistent(campaign, sites):
    """PRD: campaign site_count and gap_count mirror the site rows."""
    assert campaign["site_count"] == len(sites), (
        f"site_count {campaign['site_count']} must equal the number of site rows "
        f"{len(sites)}"
    )
    gaps = [s for s in sites if float(s["coverage_ratio"]) < 0.50]
    assert campaign["gap_count"] == len(gaps), (
        f"gap_count {campaign['gap_count']} must equal the number of sites whose "
        f"coverage_ratio is below 0.50 ({len(gaps)})"
    )
