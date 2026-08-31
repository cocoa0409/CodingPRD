"""Payload factories — one per entity, carrying only client-supplied input fields."""

import itertools

_email_counter = itertools.count(1)
_reference_counter = itertools.count(1)


def unique_contact_email(prefix: str = "family") -> str:
    return f"{prefix}.{next(_email_counter)}@example.org"


def unique_award_reference(prefix: str = "HF-2026") -> str:
    return f"{prefix}-{next(_reference_counter):04d}"


DEFAULTS = {
    "SPACE_NAME": "Chapel Room",
    "SPACE_CAPACITY": 20,
    "TURNOVER_BUFFER_MINUTES": 30,
    "COHORT_SEATS_TOTAL": 4,
    "COHORT_MIN_VIABLE": 1,
    "COHORT_START_MINUTE": 600,
    "COHORT_DURATION": 90,
    "COHORT_SERIES_START": "2026-09-08",
    "COHORT_SESSIONS_TOTAL": 8,
    "COHORT_DIRECT_COST_CENTS": 100_000,
    "EVENT_DATE": "2026-10-05",
    "EVENT_START_MINUTE": 600,
    "EVENT_DURATION": 60,
    "EVENT_EXPECTED_ATTENDANCE": 20,
    "EVENT_DIRECT_COST_CENTS": 10_220,
    "AWARDED_CENTS": 5_000_000,
    "PERIOD_START": "2026-01-01",
    "PERIOD_END": "2026-12-31",
    "INDIRECT_RATE_BPS": 1200,
    "COUNSELOR_CASELOAD_CAP": 5,
    "COUNSELOR_WEEKLY_MINUTES": 600,
    "REQUESTED_MINUTES_PER_WEEK": 60,
}


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "source_type": "HOSPICE",
        "source_org_name": "Riverside Hospice",
        "decedent_name": "Ann Vance",
        "date_of_death": "2026-06-01",
        "relationship_to_deceased": "SPOUSE",
        "loss_type": "ANTICIPATED_ILLNESS",
        "contact_name": "Ben Vance",
        "contact_email": "ben.vance@example.org",
    }
    defaults.update(overrides)
    if defaults.get("source_type") == "SELF":
        defaults.pop("source_org_name", None)
    return defaults


def screen_referral_payload(**overrides) -> dict:
    defaults = {"eligibility_note": "in service area"}
    defaults.update(overrides)
    return defaults


def decline_referral_payload(**overrides) -> dict:
    defaults = {"decline_reason": "OUT_OF_AREA"}
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "kind": "NEEDS",
        "instrument": "ICG_SF",
        "grief_severity": 20,
        "isolation_index": 8,
        "functional_impairment": 8,
        "suicidality_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_space_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SPACE_NAME"],
        "capacity": DEFAULTS["SPACE_CAPACITY"],
        "turnover_buffer_minutes": DEFAULTS["TURNOVER_BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(meeting_space_id: str, **overrides) -> dict:
    defaults = {
        "name": "Tuesday Illness Group",
        "loss_type": "ANTICIPATED_ILLNESS",
        "meeting_space_id": meeting_space_id,
        "seats_total": DEFAULTS["COHORT_SEATS_TOTAL"],
        "min_viable_enrollment": DEFAULTS["COHORT_MIN_VIABLE"],
        "weekday": "TUE",
        "start_minute_utc": DEFAULTS["COHORT_START_MINUTE"],
        "duration_minutes": DEFAULTS["COHORT_DURATION"],
        "series_start_date": DEFAULTS["COHORT_SERIES_START"],
        "sessions_total": DEFAULTS["COHORT_SESSIONS_TOTAL"],
        "direct_cost_cents": DEFAULTS["COHORT_DIRECT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(participant_id: str, cohort_id: str,
                              expected_cohort_version: int, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "cohort_id": cohort_id,
        "expected_cohort_version": expected_cohort_version,
    }
    defaults.update(overrides)
    return defaults


def withdraw_enrollment_payload(**overrides) -> dict:
    defaults = {"withdraw_reason": "PARTICIPANT_REQUEST"}
    defaults.update(overrides)
    return defaults


def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Wren Adisa",
        "license_type": "LCSW",
        "specialties": ["SUDDEN_DEATH"],
        "caseload_cap": DEFAULTS["COUNSELOR_CASELOAD_CAP"],
        "weekly_capacity_minutes": DEFAULTS["COUNSELOR_WEEKLY_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_counseling_referral_payload(participant_id: str, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "requested_minutes_per_week": DEFAULTS["REQUESTED_MINUTES_PER_WEEK"],
        "urgency": "ROUTINE",
        "required_specialty": "SUDDEN_DEATH",
    }
    defaults.update(overrides)
    return defaults


def assign_counseling_referral_payload(counselor_id: str,
                                       expected_counselor_version: int,
                                       **overrides) -> dict:
    defaults = {
        "counselor_id": counselor_id,
        "expected_counselor_version": expected_counselor_version,
    }
    defaults.update(overrides)
    return defaults


def close_counseling_referral_payload(**overrides) -> dict:
    defaults = {"close_reason": "COMPLETED"}
    defaults.update(overrides)
    return defaults


def create_volunteer_companion_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Noor Ellery",
        "endorsed_loss_types": ["ANTICIPATED_ILLNESS"],
        "max_concurrent_matches": 3,
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(**overrides) -> dict:
    defaults = {"module_code": "CORE_LISTENING", "hours": 8}
    defaults.update(overrides)
    return defaults


def create_companion_match_payload(companion_id: str, participant_id: str,
                                   **overrides) -> dict:
    defaults = {"companion_id": companion_id, "participant_id": participant_id}
    defaults.update(overrides)
    return defaults


def create_remembrance_event_payload(meeting_space_id: str, **overrides) -> dict:
    defaults = {
        "title": "Autumn Remembrance",
        "meeting_space_id": meeting_space_id,
        "event_date": DEFAULTS["EVENT_DATE"],
        "start_minute_utc": DEFAULTS["EVENT_START_MINUTE"],
        "duration_minutes": DEFAULTS["EVENT_DURATION"],
        "expected_attendance": DEFAULTS["EVENT_EXPECTED_ATTENDANCE"],
        "direct_cost_cents": DEFAULTS["EVENT_DIRECT_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(event_id: str, participant_id: str, **overrides) -> dict:
    defaults = {"event_id": event_id, "participant_id": participant_id, "guest_count": 0}
    defaults.update(overrides)
    return defaults


def create_grant_award_payload(**overrides) -> dict:
    defaults = {
        "funder_name": "Hollis Foundation",
        "award_reference": unique_award_reference(),
        "awarded_cents": DEFAULTS["AWARDED_CENTS"],
        "allowed_categories": ["GROUP_PROGRAM"],
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "indirect_rate_bps": DEFAULTS["INDIRECT_RATE_BPS"],
    }
    defaults.update(overrides)
    return defaults


def create_funding_allocation_payload(grant_award_id: str, category: str,
                                      expected_grant_award_version: int,
                                      cohort_id=None, event_id=None,
                                      **overrides) -> dict:
    defaults = {
        "grant_award_id": grant_award_id,
        "category": category,
        "expected_grant_award_version": expected_grant_award_version,
    }
    if cohort_id is not None:
        defaults["cohort_id"] = cohort_id
    if event_id is not None:
        defaults["event_id"] = event_id
    defaults.update(overrides)
    return defaults


def create_grant_report_payload(grant_award_id: str, **overrides) -> dict:
    defaults = {
        "grant_award_id": grant_award_id,
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    defaults.update(overrides)
    return defaults
