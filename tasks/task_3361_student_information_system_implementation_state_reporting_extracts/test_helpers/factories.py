"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import DATES, TEST_DEFAULTS, THRESHOLDS


def create_district_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["DISTRICT_NAME"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_school_year_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "label": "2026-2027",
        "start_date": DATES["YEAR_START"],
        "end_date": DATES["YEAR_END"],
        "instructional_days": THRESHOLDS["INSTRUCTIONAL_DAYS"],
        "count_date": DATES["COUNT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_spec_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "funding_method": "ADM",
        "attendance_code_map": {
            "U": {"state_code": "S_ABS_U", "absence_weight": 1.0, "is_excused": False},
            "E": {"state_code": "S_ABS_E", "absence_weight": 1.0, "is_excused": True},
            "H": {"state_code": "S_ABS_H", "absence_weight": 0.5, "is_excused": False},
            "P": {"state_code": "S_ABS_P", "absence_weight": 0.0, "is_excused": False},
        },
        "discipline_code_map": {
            "FIGHT": {"state_offense_code": "S_OFF_29", "severity_base": 25},
            "TARDY": {"state_offense_code": "S_OFF_51", "severity_base": 5},
        },
        "program_code_map": {
            "EL": {"state_program_code": "S_PRG_EL", "weight_factor": 1.2},
            "HDK": {"state_program_code": "S_PRG_HDK", "weight_factor": 0.5},
            "GT": {"state_program_code": "S_PRG_GT", "weight_factor": 1.25},
        },
        "submission_window_opens_at": DATES["WINDOW_OPENS"],
        "submission_window_closes_at": DATES["WINDOW_CLOSES"],
        "chronic_absence_threshold": THRESHOLDS["CHRONIC_ABSENCE_THRESHOLD"],
        "auto_withdraw_streak": THRESHOLDS["AUTO_WITHDRAW_STREAK"],
        "min_membership_days": THRESHOLDS["MIN_MEMBERSHIP_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "student_number": "S001",
        "first_name": "Ada",
        "last_name": "Lopez",
        "birth_date": "2011-03-04T00:00:00Z",
        "entry_grade_level": "09",
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "course_code": "ALG1",
        "title": "Algebra I",
        "credit_hours": 1.0,
        "grade_band": "HIGH",
        "state_course_code": "TX-02001",
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(course_id: str, school_year_id: str, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "school_year_id": school_year_id,
        "teacher_ref": "T1",
        "term_label": "SEM_1",
        "room": "R1",
        "period_start_min": 480,
        "period_end_min": 540,
        "capacity": 30,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id: str, school_year_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "school_year_id": school_year_id,
        "grade_level": "09",
        "entry_date": DATES["YEAR_START"],
    }
    defaults.update(overrides)
    return defaults


def create_attendance_event_payload(**overrides) -> dict:
    defaults = {
        "attendance_date": "2026-09-02T00:00:00Z",
        "raw_code": "U",
    }
    defaults.update(overrides)
    return defaults


def create_discipline_incident_payload(student_id: str, enrollment_id: str,
                                       **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "incident_date": "2026-10-05T00:00:00Z",
        "raw_offense_code": "FIGHT",
        "action_type": "OSS",
        "action_days": 1,
    }
    defaults.update(overrides)
    return defaults


def create_reporting_extract_payload(school_year_id: str, collection_spec_id: str,
                                     expected_school_year_version: int,
                                     **overrides) -> dict:
    defaults = {
        "school_year_id": school_year_id,
        "collection_spec_id": collection_spec_id,
        "expected_school_year_version": expected_school_year_version,
    }
    defaults.update(overrides)
    return defaults


def create_portal_account_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "account_type": "PARENT",
        "access_level": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_integration_feed_payload(district_id: str, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "platform": "ASSESSMENT",
    }
    defaults.update(overrides)
    return defaults


def create_rollover_run_payload(district_id: str, source_school_year_id: str,
                                target_school_year_id: str,
                                expected_district_version: int,
                                **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "source_school_year_id": source_school_year_id,
        "target_school_year_id": target_school_year_id,
        "expected_district_version": expected_district_version,
    }
    defaults.update(overrides)
    return defaults
