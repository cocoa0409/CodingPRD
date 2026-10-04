"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    CapstoneFacility,
    CapstoneStatus,
    DeliveryStatus,
    DistrictStatus,
    EngagementStatus,
    KitStatus,
    PartnerStatus,
    RecognitionTier,
    ScreeningStatus,
    SessionStatus,
    SurveyStatus,
    TrainingStatus,
)


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_area_office(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["max_districts"], int)


def assert_district(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("area_office_id", "")), "area_office_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["relationship_status"] in [s.value for s in DistrictStatus]


def assert_school(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("district_id", "")), "district_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["grade_band_low"], int)
    assert isinstance(data["grade_band_high"], int)
    assert isinstance(data["instructional_days"], list)
    assert all(d in ("MON", "TUE", "WED", "THU", "FRI") for d in data["instructional_days"])


def assert_corporate_partner(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["industry"], str) and data["industry"]
    assert data["status"] in [s.value for s in PartnerStatus]


def assert_volunteer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("corporate_partner_id", "")), "corporate_partner_id must be a UUID"
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["screening_status"] in [s.value for s in ScreeningStatus]
    assert data["training_status"] in [s.value for s in TrainingStatus]
    assert data["engagement_status"] in [s.value for s in EngagementStatus]
    assert data["screening_expires_on"] is None or is_iso8601_timestamp(data["screening_expires_on"])
    assert data["training_expires_on"] is None or is_iso8601_timestamp(data["training_expires_on"])
    assert isinstance(data["hours_contributed"], (int, float))
    assert isinstance(data["eligible"], bool)


def assert_program_catalog(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["session_count"], int)
    assert isinstance(data["minutes_per_session"], int)
    assert isinstance(data["capstone_required"], bool)
    assert data["capstone_facility"] in [f.value for f in CapstoneFacility]
    assert isinstance(data["min_students"], int)
    assert isinstance(data["max_students"], int)


def assert_partnership_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("school_id", "")), "school_id must be a UUID"
    assert is_valid_uuid(data.get("program_catalog_id", "")), "program_catalog_id must be a UUID"
    assert is_valid_uuid(data.get("sponsor_partner_id", "")), "sponsor_partner_id must be a UUID"
    assert isinstance(data["school_year"], str) and data["school_year"]
    assert isinstance(data["funding_pledged_cents"], int)
    assert isinstance(data["funding_received_cents"], int)
    assert data["pending_program_catalog_id"] is None or isinstance(data["pending_program_catalog_id"], str)
    assert data["pending_funding_pledged_cents"] is None or isinstance(data["pending_funding_pledged_cents"], int)
    assert data["status"] in [s.value for s in AgreementStatus]
    assert isinstance(data["sponsor_volunteer_hours"], (int, float))
    assert data["recognition_tier"] in [t.value for t in RecognitionTier]
    assert isinstance(data["deliveries_completed_count"], int)


def assert_delivery(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert is_valid_uuid(data.get("program_catalog_id", "")), "program_catalog_id must be a UUID"
    assert is_valid_uuid(data.get("lead_volunteer_id", "")), "lead_volunteer_id must be a UUID"
    assert isinstance(data["classroom_label"], str) and data["classroom_label"]
    assert isinstance(data["teacher_email"], str) and data["teacher_email"]
    assert isinstance(data["teacher_confirmed"], bool)
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["required_kits"], int)
    assert data["status"] in [s.value for s in DeliveryStatus]
    assert data["kit_status"] in [s.value for s in KitStatus]
    assert isinstance(data["kits_consumed"], int)
    assert isinstance(data["sessions_delivered_count"], int)
    assert isinstance(data["sessions_blocked_count"], int)


def assert_session(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("delivery_id", "")), "delivery_id must be a UUID"
    assert is_valid_uuid(data.get("volunteer_id", "")), "volunteer_id must be a UUID"
    assert isinstance(data["sequence_no"], int)
    assert isinstance(data["scheduled_date"], str) and len(data["scheduled_date"]) == 10
    assert isinstance(data["start_minutes"], int)
    assert isinstance(data["end_minutes"], int)
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in [s.value for s in SessionStatus]


def assert_kit_inventory(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("area_office_id", "")), "area_office_id must be a UUID"
    assert is_valid_uuid(data.get("program_catalog_id", "")), "program_catalog_id must be a UUID"
    for counter in (
        "assembled_count",
        "available_count",
        "reserved_count",
        "distributed_count",
        "written_off_count",
        "consumed_count",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_kit_ledger_invariant(inv: dict):
    """assembled == available + reserved + distributed + written_off + consumed (PRD §2.9)."""
    total = (
        inv["available_count"]
        + inv["reserved_count"]
        + inv["distributed_count"]
        + inv["written_off_count"]
        + inv["consumed_count"]
    )
    assert inv["assembled_count"] == total, (
        f"kit ledger broken: assembled {inv['assembled_count']} != {total} "
        f"(avail {inv['available_count']} + res {inv['reserved_count']} + "
        f"dist {inv['distributed_count']} + wo {inv['written_off_count']} + "
        f"consumed {inv['consumed_count']})"
    )


def assert_capstone_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("delivery_id", "")), "delivery_id must be a UUID"
    assert data["facility"] in (CapstoneFacility.SIMULATED_TOWN.value, CapstoneFacility.FINANCE_PARK.value)
    assert isinstance(data["event_date"], str) and len(data["event_date"]) == 10
    assert isinstance(data["start_minutes"], int)
    assert isinstance(data["end_minutes"], int)
    assert isinstance(data["rotation_slot_count"], int)
    assert data["status"] in [s.value for s in CapstoneStatus]
    assert isinstance(data["assigned_student_count"], int)


def assert_student(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("delivery_id", "")), "delivery_id must be a UUID"
    assert data["capstone_event_id"] is None or is_valid_uuid(data["capstone_event_id"])
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["external_ref"], str)
    assert data["rotation_group"] is None or isinstance(data["rotation_group"], int)
    assert data["capstone_role"] is None or isinstance(data["capstone_role"], str)
    assert data["pre_score"] is None or isinstance(data["pre_score"], int)
    assert data["post_score"] is None or isinstance(data["post_score"], int)
    assert data["survey_status"] in [s.value for s in SurveyStatus]


def assert_evaluation_report(data: dict):
    """Shape of the computed evaluation report (PRD §3.8)."""
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["sessions_delivered"], int)
    assert isinstance(data["sessions_scheduled"], int)
    assert isinstance(data["total_volunteer_hours"], (int, float))
    assert isinstance(data["sponsor_volunteer_hours"], (int, float))
    assert isinstance(data["students_included"], int)
    assert isinstance(data["students_paired"], int)
    assert data["avg_growth_score"] is None or isinstance(data["avg_growth_score"], (int, float))
    assert isinstance(data["completion_rate_pct"], (int, float))
    assert data["recognition_tier_earned"] in [t.value for t in RecognitionTier]
    assert data["recognition_tier_projected"] in [t.value for t in RecognitionTier]
    assert is_iso8601_timestamp(data.get("generated_at", "")), "generated_at must be ISO 8601"
