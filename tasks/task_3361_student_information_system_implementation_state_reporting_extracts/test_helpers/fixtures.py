"""Composite setup helpers for multi-step test prerequisites.

Every helper builds state from an empty database using only PRD-declared
endpoints, and uses get_success_data() so setup failures surface as clear
errors rather than assertion failures deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import CLOCK_DEFAULT, DATES
from .factories import (
    create_course_payload,
    create_discipline_incident_payload,
    create_district_payload,
    create_enrollment_payload,
    create_portal_account_payload,
    create_reporting_extract_payload,
    create_rollover_run_payload,
    create_school_year_payload,
    create_section_payload,
    create_spec_payload,
    create_student_payload,
)
from .test_users import TEST_USERS

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
DISTRICT_ADMIN = TEST_USERS["district_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
STATE_REPORTER = TEST_USERS["state_reporter_headers"]


# --- clock ---------------------------------------------------------------

def reset_clock(instant: str = CLOCK_DEFAULT) -> dict:
    """Drive the logical clock to `instant` (PRD §2.4)."""
    return get_success_data(api_client.set_clock({"current_utc": instant}, PLATFORM_ADMIN))


# --- districts -----------------------------------------------------------

def create_district(name: str = "Lone Star ISD", state_code: str = "TX") -> dict:
    return get_success_data(
        api_client.create_district(
            create_district_payload(name=name, state_code=state_code), PLATFORM_ADMIN))


def create_live_district(name: str = "Lone Star ISD", state_code: str = "TX") -> dict:
    """Create a district and activate it IMPLEMENTATION -> LIVE. Returns the LIVE view."""
    district = create_district(name=name, state_code=state_code)
    return get_success_data(api_client.activate_district(district["id"], PLATFORM_ADMIN))


def get_district_version(district_id: str) -> int:
    return get_success_data(api_client.get_district(district_id, DISTRICT_ADMIN))["version"]


# --- state collection specs ----------------------------------------------

def create_spec(**overrides) -> dict:
    """Create a spec in DRAFT (not published)."""
    return get_success_data(
        api_client.create_collection_spec(create_spec_payload(**overrides), PLATFORM_ADMIN))


def create_published_spec(**overrides) -> dict:
    """Create a spec and publish it. Returns the PUBLISHED view."""
    spec = create_spec(**overrides)
    return get_success_data(api_client.publish_collection_spec(spec["id"], PLATFORM_ADMIN))


def get_spec(spec_id: str) -> dict:
    """Read one spec's current state. PRD §4 defines no get-spec-by-id endpoint,
    so observe through the PRD list endpoint instead."""
    data, _meta = validate_paginated(
        api_client.list_collection_specs(PLATFORM_ADMIN, params={"limit": 100}))
    for spec in data:
        if spec["id"] == spec_id:
            return spec
    raise AssertionError(f"spec {spec_id} not present in list response")


# --- school years --------------------------------------------------------

def create_school_year(district_id: str, **overrides) -> dict:
    """Create a school year in PLANNING."""
    return get_success_data(
        api_client.create_school_year(
            create_school_year_payload(district_id, **overrides), DISTRICT_ADMIN))


def open_school_year(year_id: str) -> dict:
    return get_success_data(api_client.open_school_year(year_id, DISTRICT_ADMIN))


def create_open_school_year(district_id: str, **overrides) -> dict:
    year = create_school_year(district_id, **overrides)
    return open_school_year(year["id"])


def create_target_year_opened(district_id: str) -> dict:
    """The standard follow-on year [2027-08-01, 2028-06-01), opened."""
    return create_open_school_year(
        district_id,
        label="2027-2028",
        start_date=DATES["TARGET_YEAR_START"],
        end_date=DATES["TARGET_YEAR_END"],
        instructional_days=180,
        count_date=DATES["TARGET_COUNT_DATE"],
    )


def close_year_for_reporting(year_id: str) -> dict:
    """OPEN -> CLOSED_FOR_REPORTING; the returned data carries the post-close version."""
    return get_success_data(
        api_client.close_school_year_for_reporting(year_id, DISTRICT_ADMIN))


def get_year_version(year_id: str) -> int:
    return get_success_data(api_client.get_school_year(year_id, STATE_REPORTER))["version"]


# --- students and enrollments --------------------------------------------

def create_student(district_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_student(
            create_student_payload(district_id, **overrides), REGISTRAR))


def create_active_enrollment(student_id: str, school_year_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_enrollment(
            create_enrollment_payload(student_id, school_year_id, **overrides), REGISTRAR))


def create_student_with_enrollment(district_id: str, school_year_id: str,
                                   student_overrides: dict = None,
                                   enrollment_overrides: dict = None):
    """Register a student and create an ACTIVE enrollment. Returns (student, enrollment)."""
    student = create_student(district_id, **(student_overrides or {}))
    enrollment = create_active_enrollment(
        student["id"], school_year_id, **(enrollment_overrides or {}))
    return student, enrollment


def withdraw_enrollment(enrollment_id: str, exit_date: str = None) -> dict:
    payload = {} if exit_date is None else {"exit_date": exit_date}
    return get_success_data(api_client.withdraw_enrollment(enrollment_id, payload, REGISTRAR))


def get_enrollment(enrollment_id: str) -> dict:
    return get_success_data(api_client.get_enrollment(enrollment_id, REGISTRAR))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, REGISTRAR))


# --- courses and sections --------------------------------------------------

def create_course(district_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_course(create_course_payload(district_id, **overrides), REGISTRAR))


def create_section(course_id: str, school_year_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_section(
            create_section_payload(course_id, school_year_id, **overrides), REGISTRAR))


def roster_add(section_id: str, enrollment_id: str) -> dict:
    return get_success_data(
        api_client.roster_add(section_id, {"enrollment_id": enrollment_id}, REGISTRAR))


# --- attendance ------------------------------------------------------------

def post_attendance_event(enrollment_id: str, attendance_date: str,
                          raw_code: str = "U") -> dict:
    return get_success_data(
        api_client.post_attendance_event(
            enrollment_id,
            {"attendance_date": attendance_date, "raw_code": raw_code},
            REGISTRAR))


def post_unexcused_full_day_events(enrollment_id: str, dates: list) -> list:
    """Post one unexcused full-day (raw_code U) event per date. Returns the events."""
    return [post_attendance_event(enrollment_id, d, "U") for d in dates]


# --- discipline ------------------------------------------------------------

def create_discipline_incident(student_id: str, enrollment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_discipline_incident(
            create_discipline_incident_payload(student_id, enrollment_id, **overrides),
            REGISTRAR))


# --- composite bases -------------------------------------------------------

def setup_base():
    """Clock reset + LIVE TX district + PUBLISHED TX spec + OPEN standard year.
    Returns (district, spec, year)."""
    reset_clock()
    district = create_live_district()
    spec = create_published_spec()
    year = create_open_school_year(district["id"])
    return district, spec, year


def setup_closed_year_with_enrollment(withdraw_exit: str = None):
    """Base setup + one enrollment (optionally withdrawn at `withdraw_exit`) +
    year CLOSED_FOR_REPORTING.

    Returns a dict: district, spec, year (closed view), student, enrollment,
    year_version (post-close version, valid for the first extract create).
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    if withdraw_exit is not None:
        enrollment = withdraw_enrollment(enrollment["id"], withdraw_exit)
    closed_year = close_year_for_reporting(year["id"])
    return {
        "district": district,
        "spec": spec,
        "year": closed_year,
        "student": student,
        "enrollment": enrollment,
        "year_version": closed_year["version"],
    }


# --- reporting extracts ----------------------------------------------------

def create_extract(school_year_id: str, collection_spec_id: str,
                   expected_school_year_version: int) -> dict:
    return get_success_data(
        api_client.create_reporting_extract(
            create_reporting_extract_payload(
                school_year_id, collection_spec_id, expected_school_year_version),
            STATE_REPORTER))


def get_extract(extract_id: str) -> dict:
    return get_success_data(api_client.get_reporting_extract(extract_id, STATE_REPORTER))


# --- portal accounts ---------------------------------------------------------

def create_portal_account(student_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_portal_account(
            create_portal_account_payload(student_id, **overrides), DISTRICT_ADMIN))


# --- rollover ----------------------------------------------------------------

def setup_rollover_pair():
    """Clock reset + LIVE TX district + PUBLISHED TX spec + source year OPEN +
    target year OPEN. Returns (district, spec, source_year, target_year)."""
    reset_clock()
    district = create_live_district()
    spec = create_published_spec()
    source_year = create_open_school_year(district["id"])
    target_year = create_target_year_opened(district["id"])
    return district, spec, source_year, target_year


def create_rollover_run(district_id: str, source_school_year_id: str,
                        target_school_year_id: str,
                        expected_district_version: int) -> dict:
    return get_success_data(
        api_client.create_rollover_run(
            create_rollover_run_payload(
                district_id, source_school_year_id, target_school_year_id,
                expected_district_version),
            DISTRICT_ADMIN))
