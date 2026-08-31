"""Entity assertions and domain invariant checkers."""

import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_BARE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_DAY = re.compile(r"^\d{2}-\d{2}$")
_TS_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_bare_uuid(value, label="id"):
    """Identifiers carry no type prefix and are server-minted UUIDs."""
    assert isinstance(value, str) and _BARE_UUID.match(value), (
        f"{label} must be a bare UUID with no type prefix, got {value!r}"
    )
    assert is_valid_uuid(value), f"{label} must be a valid UUID, got {value!r}"


def assert_iso_millis(value, label="timestamp"):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    assert isinstance(value, str) and _TS_MILLIS.match(value), (
        f"{label} must be an ISO 8601 UTC timestamp with three fractional digits, "
        f"got {value!r}"
    )
    assert is_iso8601_timestamp(value), f"{label} must parse as ISO 8601, got {value!r}"


def assert_calendar_date(value, label="date"):
    assert isinstance(value, str) and _DATE.match(value), (
        f"{label} must be a YYYY-MM-DD calendar date, got {value!r}"
    )


def assert_versioned_record(data, label="record"):
    """Most resources carry id, created_at, updated_at and version."""
    assert_bare_uuid(data.get("id"), f"{label}.id")
    assert_iso_millis(data.get("created_at"), f"{label}.created_at")
    assert_iso_millis(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_referral(data):
    assert_versioned_record(data, "referral")
    assert data["source_type"] in ("HOSPICE", "FUNERAL_HOME", "SELF")
    assert data["status"] in ("RECEIVED", "SCREENED", "ACCEPTED", "DECLINED")
    assert_calendar_date(data["date_of_death"], "referral.date_of_death")
    assert data["relationship_to_deceased"] in (
        "SPOUSE", "CHILD", "PARENT", "SIBLING", "OTHER_FAMILY", "FRIEND", "CAREGIVER")
    assert data["loss_type"] in (
        "ANTICIPATED_ILLNESS", "SUDDEN_DEATH", "PERINATAL", "SUICIDE",
        "OVERDOSE", "PEDIATRIC")
    assert isinstance(data["contact_name"], str) and data["contact_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    if data.get("screening_band") is not None:
        assert data["screening_band"] in ("URGENT", "PRIORITY", "ROUTINE")


def assert_participant(data):
    assert_versioned_record(data, "participant")
    assert data["service_status"] in (
        "INTAKE", "ASSESSED", "ACTIVE", "MAINTENANCE", "DISCHARGED", "WITHDRAWN")
    assert data["outreach_status"] in ("SCHEDULED", "ON_HOLD", "LAPSED", "CLOSED")
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")
    assert data["outreach_cadence_days"] in (30, 60, 90)
    assert isinstance(data["composite_need_index"], (int, float))
    assert 0 <= data["composite_need_index"] <= 100
    assert isinstance(data["waitlist_reentry_count"], int)
    assert isinstance(data["sessions_attended_total"], int)
    assert isinstance(data["has_active_companion"], bool)
    assert_calendar_date(data["date_of_death"], "participant.date_of_death")
    assert _MONTH_DAY.match(data["anniversary_month_day"]), (
        "participant.anniversary_month_day must be MM-DD, "
        f"got {data['anniversary_month_day']!r}"
    )


def assert_assessment(data):
    """An assessment is immutable: it carries id and created_at but never
    updated_at or version."""
    assert_bare_uuid(data.get("id"), "assessment.id")
    assert_iso_millis(data.get("created_at"), "assessment.created_at")
    assert "updated_at" not in data, "an assessment must not expose updated_at"
    assert "version" not in data, "an assessment must not expose version"
    assert data["kind"] in ("NEEDS", "BASELINE", "MIDPOINT", "EXIT")
    assert data["instrument"] in ("ICG_SF", "PG13")
    assert 0 <= data["grief_severity"] <= 40
    assert 0 <= data["isolation_index"] <= 20
    assert 0 <= data["functional_impairment"] <= 20
    assert isinstance(data["suicidality_flag"], bool)
    assert data["raw_total"] == (
        data["grief_severity"] + data["isolation_index"] + data["functional_impairment"]
    )
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert_iso_millis(data.get("recorded_at"), "assessment.recorded_at")


def assert_meeting_space(data):
    assert_versioned_record(data, "meeting_space")
    assert data["status"] in ("AVAILABLE", "OUT_OF_SERVICE")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["turnover_buffer_minutes"], int)
    assert data["turnover_buffer_minutes"] >= 0
    assert isinstance(data["accessibility_features"], list)


def assert_cohort(data):
    assert_versioned_record(data, "cohort")
    assert data["status"] in (
        "FORMING", "OPEN_ENROLLMENT", "UNDERSUBSCRIBED", "RUNNING",
        "SUSPENDED", "COMPLETED", "CANCELLED")
    assert data["weekday"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert 0 <= data["start_minute_utc"] <= 1439
    assert data["start_minute_utc"] + data["duration_minutes"] <= 1440
    assert_calendar_date(data["series_start_date"], "cohort.series_start_date")
    assert_calendar_date(data["series_end_date"], "cohort.series_end_date")
    assert_cohort_seat_pool(data)


def assert_cohort_seat_pool(data):
    """seats_total always equals seats_open + seats_held + seats_filled."""
    total = data["seats_total"]
    parts = data["seats_open"] + data["seats_held"] + data["seats_filled"]
    assert total == parts, (
        f"seat pool broken: seats_total {total} != seats_open {data['seats_open']} "
        f"+ seats_held {data['seats_held']} + seats_filled {data['seats_filled']}"
    )
    assert data["seats_open"] >= 0 and data["seats_held"] >= 0 and data["seats_filled"] >= 0


def assert_enrollment(data):
    assert_versioned_record(data, "enrollment")
    assert data["status"] in (
        "HELD", "CONFIRMED", "ATTENDING", "COMPLETED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["sessions_attended"], int) and data["sessions_attended"] >= 0
    assert isinstance(data["attendance_ratio"], (int, float))
    if data.get("withdraw_reason") is not None:
        assert data["withdraw_reason"] in (
            "PARTICIPANT_REQUEST", "NO_SHOW", "TRANSFERRED", "PROGRAM_CANCELLED")


def assert_counselor(data):
    assert_versioned_record(data, "counselor")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert data["license_type"] in ("LCSW", "LPC", "PSYCHOLOGIST", "CHAPLAIN")
    assert isinstance(data["specialties"], list)
    assert data["active_caseload"] >= 0
    assert data["committed_minutes"] >= 0


def assert_counseling_referral(data):
    assert_versioned_record(data, "counseling_referral")
    assert data["status"] in ("WAITLISTED", "ASSIGNED", "CLOSED", "CANCELLED")
    assert data["urgency"] in ("ROUTINE", "PRIORITY", "URGENT")
    assert isinstance(data["queue_priority"], (int, float))
    assert data["requested_minutes_per_week"] >= 1
    assert_iso_millis(data.get("waitlisted_at"), "counseling_referral.waitlisted_at")


def assert_volunteer_companion(data):
    assert_versioned_record(data, "volunteer_companion")
    assert data["status"] in ("APPLIED", "IN_TRAINING", "CERTIFIED", "LAPSED", "SUSPENDED")
    assert isinstance(data["endorsed_loss_types"], list)
    assert isinstance(data["modules_completed"], list)
    assert data["max_concurrent_matches"] >= 1
    assert data["active_match_count"] >= 0
    assert isinstance(data["training_hours"], (int, float))


def assert_companion_match(data):
    assert_versioned_record(data, "companion_match")
    assert data["status"] in ("PROPOSED", "ACTIVE", "DECLINED", "ENDED")
    assert isinstance(data["match_score"], (int, float))
    assert 0 <= data["match_score"] <= 100


def assert_remembrance_event(data):
    assert_versioned_record(data, "remembrance_event")
    assert data["status"] in ("PLANNED", "CONFIRMED", "HELD", "CANCELLED")
    assert_calendar_date(data["event_date"], "remembrance_event.event_date")
    assert 0 <= data["start_minute_utc"] <= 1439
    assert data["start_minute_utc"] + data["duration_minutes"] <= 1440
    assert data["expected_attendance"] >= 1
    assert data["invitations_sent"] >= 0
    assert data["invitations_accepted"] >= 0
    assert data["confirmed_headcount"] >= 0


def assert_invitation(data):
    assert_versioned_record(data, "invitation")
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED", "VOID")
    assert data["guest_count"] >= 0
    assert_calendar_date(data["rsvp_deadline"], "invitation.rsvp_deadline")


def assert_grant_award(data):
    assert_versioned_record(data, "grant_award")
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["allowed_categories"], list)
    assert 0 <= data["indirect_rate_bps"] <= 10000
    assert_grant_money_pool(data)


def assert_grant_money_pool(data):
    """awarded_cents always equals available_cents + committed_cents + spent_cents."""
    awarded = data["awarded_cents"]
    parts = data["available_cents"] + data["committed_cents"] + data["spent_cents"]
    assert awarded == parts, (
        f"money pool broken: awarded_cents {awarded} != available_cents "
        f"{data['available_cents']} + committed_cents {data['committed_cents']} "
        f"+ spent_cents {data['spent_cents']}"
    )
    for field in ("awarded_cents", "available_cents", "committed_cents", "spent_cents"):
        assert isinstance(data[field], int), f"{field} must be whole cents"


def assert_funding_allocation(data):
    assert_versioned_record(data, "funding_allocation")
    assert data["status"] in ("COMMITTED", "SETTLED", "RELEASED")
    assert data["category"] in (
        "GROUP_PROGRAM", "REMEMBRANCE_EVENT", "COUNSELING", "VOLUNTEER_TRAINING")
    assert data["basis"] in (
        "PROJECTED_ENROLLMENT", "EVENT_PLAN", "ACTUAL_ATTENDANCE", "CONFIRMED_HEADCOUNT")
    assert isinstance(data["provisional_cents"], int)


def assert_grant_report(data):
    assert_versioned_record(data, "grant_report")
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETURNED", "ACCEPTED")
    assert isinstance(data["line_count"], int)
    assert isinstance(data["revision_index"], int)
    assert data["reported_total_cents"] == (
        data["direct_total_cents"] + data["indirect_total_cents"]
    ), "reported_total_cents must equal direct_total_cents + indirect_total_cents"


def assert_anniversary_outreach(data):
    assert_versioned_record(data, "anniversary_outreach")
    assert data["occasion"] in (
        "ONE_MONTH", "THREE_MONTH", "SIX_MONTH", "FIRST_ANNIVERSARY")
    assert data["status"] in (
        "SCHEDULED", "DUE", "SENT", "ACKNOWLEDGED", "NO_RESPONSE", "CANCELLED")
    assert data["channel"] in ("EMAIL", "PHONE")
    assert isinstance(data["escalated"], bool)
    assert_calendar_date(data["due_on"], "anniversary_outreach.due_on")


def assert_outcome_summary(data):
    assert isinstance(data["participant_id"], str)
    assert "baseline_score" in data
    assert "latest_score" in data
    assert "raw_delta" in data
    assert "rtm_correction" in data
    assert "attendance_ratio_capped" in data
    assert "attendance_adjusted_delta" in data
    assert isinstance(data["sessions_attended_total"], int)
    assert data["attendance_ratio_capped"] <= 1
