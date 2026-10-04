"""Composite setup helpers.

Every helper builds its preconditions from an empty database using only
PRD-declared endpoints, because the harness restarts the API server before each
test. Setup calls use the lenient `get_success_data()` validator so a broken
precondition surfaces as a clear "Setup step failed" error.

Identity threading: after a `Teacher` row exists, every teacher-authenticated
call uses `make_teacher_headers(teacher["id"])` — the entity-backed role's
X-User-ID must be the Teacher's own id.
"""
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_APPLICANT_USER_ID,
    DEFAULT_LEARNER_BIRTH_DATE,
    DEFAULT_PARENT_USER_ID,
    DEFAULT_REVIEWER_USER_ID,
    DEFAULT_SAMPLE_MINUTES,
    DEFAULT_SAMPLE_URL,
    DEFAULT_TEACHER_DISPLAY_NAME,
    DEFAULT_TEACHER_EMAIL,
)
from .factories import (
    create_class_listing_payload,
    create_enrollment_payload,
    create_learner_payload,
    create_payout_payload,
    create_report_payload,
    create_section_payload,
    create_teacher_application_payload,
    payout_transition_payload,
    policy_review_payload,
    report_disposition_payload,
    review_application_payload,
    submit_application_payload,
    submit_sample_payload,
    subscription_payload,
)
from .test_users import (
    make_parent_headers,
    make_platform_admin_headers,
    make_teacher_applicant_headers,
    make_teacher_headers,
    make_teacher_reviewer_headers,
)


# ===========================================================================
# Tier 0 — operator capabilities
# ===========================================================================
def set_clock(to_iso8601: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    """Move the logical clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, make_platform_admin_headers(admin_id)))


def run_ops(admin_id: str = "admin-1") -> Dict[str, Any]:
    """Run the batch sweep (PRD §3.9)."""
    return get_success_data(api_client.run_ops(make_platform_admin_headers(admin_id)))


# ===========================================================================
# Tier 1 — state progression: applications and teachers
# ===========================================================================
def create_application(
    applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
    email: str = DEFAULT_TEACHER_EMAIL,
    display_name: str = DEFAULT_TEACHER_DISPLAY_NAME,
    sample_url: str = DEFAULT_SAMPLE_URL,
    sample_minutes: int = DEFAULT_SAMPLE_MINUTES,
) -> Dict[str, Any]:
    """Create a TeacherApplication in DRAFT (PRD §3.1)."""
    payload = create_teacher_application_payload(
        applicant_user_id=applicant_user_id,
        applicant_email=email,
        display_name=display_name,
        teaching_sample_url=sample_url,
        teaching_sample_minutes=sample_minutes,
    )
    return get_success_data(
        api_client.create_teacher_application(payload, make_teacher_applicant_headers(applicant_user_id))
    )


def submit_application(application_id: str, applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
                       sample_url: str = DEFAULT_SAMPLE_URL, sample_minutes: int = DEFAULT_SAMPLE_MINUTES) -> Dict[str, Any]:
    """Submit the application package: records screening and auto-advances (PRD §3.1)."""
    payload = submit_application_payload(
        teaching_sample_url=sample_url, teaching_sample_minutes=sample_minutes
    )
    return get_success_data(
        api_client.submit_application(application_id, payload, make_teacher_applicant_headers(applicant_user_id))
    )


def submit_sample(application_id: str, applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
                  sample_url: str = DEFAULT_SAMPLE_URL, sample_minutes: int = DEFAULT_SAMPLE_MINUTES) -> Dict[str, Any]:
    """Submit or revise the teaching sample, entering the sample review queue (PRD §3.1)."""
    payload = submit_sample_payload(
        teaching_sample_url=sample_url, teaching_sample_minutes=sample_minutes
    )
    return get_success_data(
        api_client.submit_sample(application_id, payload, make_teacher_applicant_headers(applicant_user_id))
    )


def review_sample(application_id: str, verdict: str = "PASS", reviewer_user_id: str = DEFAULT_REVIEWER_USER_ID,
                  reason_code: Optional[str] = None) -> Dict[str, Any]:
    """Reviewer records a SAMPLE-stage verdict (PRD §3.1)."""
    payload = review_application_payload("SAMPLE", verdict, reason_code)
    return get_success_data(
        api_client.review_application(application_id, payload, make_teacher_reviewer_headers(reviewer_user_id))
    )


def approve_application(application_id: str, reviewer_user_id: str = DEFAULT_REVIEWER_USER_ID) -> Dict[str, Any]:
    """Final approval: mints the Teacher account (PRD §3.1)."""
    return get_success_data(
        api_client.approve_application(application_id, make_teacher_reviewer_headers(reviewer_user_id))
    )


def setup_application_at_sample_pending(
    applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
    email: str = DEFAULT_TEACHER_EMAIL,
    display_name: str = DEFAULT_TEACHER_DISPLAY_NAME,
) -> Dict[str, Any]:
    """Create → submit → submit-sample. Returns the application in SAMPLE_PENDING."""
    application = create_application(applicant_user_id, email, display_name)
    submit_application(application["id"], applicant_user_id)
    return submit_sample(application["id"], applicant_user_id)


def onboard_pending_teacher(
    applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
    email: str = DEFAULT_TEACHER_EMAIL,
    display_name: str = DEFAULT_TEACHER_DISPLAY_NAME,
    reviewer_user_id: str = DEFAULT_REVIEWER_USER_ID,
) -> Dict[str, Any]:
    """Full onboarding through final approval; returns the Teacher in PENDING_SETUP."""
    application = create_application(applicant_user_id, email, display_name)
    submit_application(application["id"], applicant_user_id)
    submit_sample(application["id"], applicant_user_id)
    review_sample(application["id"], "PASS", reviewer_user_id)
    return approve_application(application["id"], reviewer_user_id)


def onboard_active_teacher(
    applicant_user_id: str = DEFAULT_APPLICANT_USER_ID,
    email: str = DEFAULT_TEACHER_EMAIL,
    display_name: str = DEFAULT_TEACHER_DISPLAY_NAME,
    reviewer_user_id: str = DEFAULT_REVIEWER_USER_ID,
    activate: bool = True,
) -> Dict[str, Any]:
    """Full onboarding through activation; returns the ACTIVE Teacher."""
    teacher = onboard_pending_teacher(applicant_user_id, email, display_name, reviewer_user_id)
    if activate:
        teacher = get_success_data(
            api_client.activate_teacher(teacher["id"], make_platform_admin_headers())
        )
    return teacher


# ===========================================================================
# Tier 2 — entity hierarchy: listings, sections, learners, enrollments
# ===========================================================================
def create_listing(teacher: Dict[str, Any], **overrides) -> Dict[str, Any]:
    """Create a listing as its owning teacher (PRD §3.3). Enters PENDING_REVIEW/DRAFT."""
    payload = create_class_listing_payload(teacher["id"], **overrides)
    return get_success_data(
        api_client.create_class_listing(payload, make_teacher_headers(teacher["id"]))
    )


def policy_approve_listing(listing_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.policy_review_listing(
            listing_id, policy_review_payload("APPROVE"), make_platform_admin_headers(admin_id)
        )
    )


def publish_listing(listing_id: str, teacher_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.publish_listing(listing_id, make_teacher_headers(teacher_id)))


def setup_listing(teacher: Dict[str, Any], approve: bool = True, publish: bool = True, **overrides) -> Dict[str, Any]:
    """Create a listing and walk it to POLICY_APPROVED / PUBLISHED by default."""
    listing = create_listing(teacher, **overrides)
    if approve:
        listing = policy_approve_listing(listing["id"])
    if publish:
        listing = publish_listing(listing["id"], teacher["id"])
    return listing


def create_section(listing: Dict[str, Any], teacher: Dict[str, Any], open_for_enrollment: bool = True,
                   **overrides) -> Dict[str, Any]:
    """Schedule a section (PRD §3.4) and open it by default."""
    payload = create_section_payload(**overrides)
    section = get_success_data(
        api_client.create_section(listing["id"], payload, make_teacher_headers(teacher["id"]))
    )
    if open_for_enrollment:
        section = get_success_data(
            api_client.open_section(listing["id"], section["id"], make_teacher_headers(teacher["id"]))
        )
    return section


def create_learner(
    parent_user_id: str = DEFAULT_PARENT_USER_ID,
    display_name: str = "Learner One",
    birth_date: str = DEFAULT_LEARNER_BIRTH_DATE,
    tier: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a learner account, optionally subscribing it to a plan tier (PRD §3.5)."""
    payload = create_learner_payload(
        display_name=display_name, birth_date=birth_date, parent_user_id=parent_user_id
    )
    learner = get_success_data(api_client.create_learner(payload, make_parent_headers(parent_user_id)))
    if tier is not None:
        learner = get_success_data(
            api_client.set_subscription(
                learner["id"], subscription_payload(tier), make_parent_headers(parent_user_id)
            )
        )
    return learner


def subscribe_learner(learner_id: str, tier: str, parent_user_id: str = DEFAULT_PARENT_USER_ID) -> Dict[str, Any]:
    """Write a subscription tier and refill the confirmation-credit allowance (PRD §3.5)."""
    return get_success_data(
        api_client.set_subscription(learner_id, subscription_payload(tier), make_parent_headers(parent_user_id))
    )


def _advance_section_minimum(listing: Dict[str, Any], section: Dict[str, Any]) -> None:
    """Declare the minimum met once enough seats are taken.

    Confirmation requires the section to have reached `MIN_ENROLLMENT_MET`, and the
    minimum is reached by seats taken (reserved plus confirmed). A real client
    therefore declares the minimum once its reservations fill the floor, which is
    what this does on the caller's behalf — without it no enrollment could ever be
    confirmed and the section could never run.
    """
    rows = get_success_data(
        api_client.list_sections(listing["id"], make_teacher_headers(listing["teacher_id"]))
    )
    fresh = next((r for r in rows if r["id"] == section["id"]), None)
    if fresh is None or fresh["status"] != "OPEN_FOR_ENROLLMENT":
        return
    if not fresh["enrollment_min_met"]:
        return
    get_success_data(
        api_client.meet_minimum(listing["id"], section["id"], make_teacher_headers(listing["teacher_id"]))
    )


def reserve_seat(listing: Dict[str, Any], section: Dict[str, Any], learner: Dict[str, Any],
                 parent_user_id: str = DEFAULT_PARENT_USER_ID, coupon_code: Optional[str] = None) -> Dict[str, Any]:
    """Reserve a seat: creates the enrollment in RESERVED (PRD §3.5)."""
    payload = create_enrollment_payload(learner["id"], coupon_code)
    enrollment = get_success_data(
        api_client.create_enrollment(listing["id"], section["id"], payload, make_parent_headers(parent_user_id))
    )
    _advance_section_minimum(listing, section)
    return enrollment


def confirm_seat(enrollment_id: str, parent_user_id: str = DEFAULT_PARENT_USER_ID) -> Dict[str, Any]:
    """Confirm a reserved seat, drawing down the learner's confirmation credit (PRD §3.6)."""
    return get_success_data(
        api_client.confirm_enrollment(enrollment_id, make_parent_headers(parent_user_id))
    )


def reserve_and_confirm(listing: Dict[str, Any], section: Dict[str, Any], learner: Dict[str, Any],
                        parent_user_id: str = DEFAULT_PARENT_USER_ID, coupon_code: Optional[str] = None) -> Dict[str, Any]:
    enrollment = reserve_seat(listing, section, learner, parent_user_id, coupon_code)
    return confirm_seat(enrollment["id"], parent_user_id)


def declare_minimum_met(listing_id: str, section_id: str, teacher_id: str) -> Dict[str, Any]:
    """Declare the section's minimum met.

    Idempotent: a section whose reservations have already filled the floor is
    advanced automatically when the seat is reserved, so an explicit declaration
    afterwards is a no-op rather than an invalid-state error. Tests that drive the
    declaration themselves, and tests that rely on the automatic advance, both work.
    """
    rows = get_success_data(api_client.list_sections(listing_id, make_teacher_headers(teacher_id)))
    fresh = next((r for r in rows if r["id"] == section_id), None)
    if fresh is not None and fresh["status"] != "OPEN_FOR_ENROLLMENT":
        return fresh
    return get_success_data(
        api_client.meet_minimum(listing_id, section_id, make_teacher_headers(teacher_id))
    )


def cancel_section(listing_id: str, section_id: str, teacher_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.cancel_section(listing_id, section_id, make_teacher_headers(teacher_id))
    )


# ===========================================================================
# Tier 3 — read-back helpers (assertions need fresh server state)
# ===========================================================================
def get_teacher(teacher_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(api_client.get_teacher(teacher_id, make_platform_admin_headers(admin_id)))


def get_teacher_version(teacher_id: str, admin_id: str = "admin-1") -> int:
    return get_teacher(teacher_id, admin_id)["version"]


def get_listing(listing_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(api_client.get_class_listing(listing_id, make_platform_admin_headers(admin_id)))


def get_section(listing_id: str, section_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    """Sections are read back through their parent listing's section list."""
    data = get_success_data(
        api_client.list_sections(listing_id, make_platform_admin_headers(admin_id), params={"limit": 100})
    )
    for section in data:
        if section["id"] == section_id:
            return section
    raise AssertionError(f"Section {section_id} not found under listing {listing_id}")


def get_learner(learner_id: str, parent_user_id: str = DEFAULT_PARENT_USER_ID) -> Dict[str, Any]:
    return get_success_data(api_client.get_learner(learner_id, make_parent_headers(parent_user_id)))


def get_enrollment(enrollment_id: str, parent_user_id: str = DEFAULT_PARENT_USER_ID) -> Dict[str, Any]:
    return get_success_data(api_client.get_enrollment(enrollment_id, make_parent_headers(parent_user_id)))


def get_payout(payout_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(api_client.get_payout(payout_id, make_platform_admin_headers(admin_id)))


def get_report(report_id: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(api_client.get_report(report_id, make_platform_admin_headers(admin_id)))


def list_payouts_for_teacher(teacher_id: str, admin_id: str = "admin-1") -> Tuple[List[dict], dict]:
    from prd_bench_local_runner.testing import validate_paginated

    response = api_client.list_payouts(
        make_platform_admin_headers(admin_id), params={"teacher_id": teacher_id, "limit": 100}
    )
    return validate_paginated(response)


# ===========================================================================
# Tier 3 — payouts and reports
# ===========================================================================
def request_payout(teacher: Dict[str, Any], period_start: str, period_end: str,
                   expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Request a payout; the caller may pass an observed version to force staleness."""
    if expected_version is None:
        expected_version = get_teacher_version(teacher["id"])
    payload = create_payout_payload(period_start, period_end, expected_version)
    return get_success_data(
        api_client.create_payout(teacher["id"], payload, make_teacher_headers(teacher["id"]))
    )


def transition_payout(payout_id: str, action: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.transition_payout(payout_id, payout_transition_payload(action), make_platform_admin_headers(admin_id))
    )


def file_report(teacher: Dict[str, Any], listing: Dict[str, Any], parent_user_id: str = DEFAULT_PARENT_USER_ID,
                severity: str = "LOW", category: str = "TECHNICAL") -> Dict[str, Any]:
    payload = create_report_payload(
        teacher["id"], listing["id"], reported_by_user_id=parent_user_id,
        severity=severity, category=category,
    )
    return get_success_data(api_client.create_report(payload, make_parent_headers(parent_user_id)))


def dispose_report(report_id: str, action: str, admin_id: str = "admin-1") -> Dict[str, Any]:
    return get_success_data(
        api_client.dispose_report(report_id, report_disposition_payload(action), make_platform_admin_headers(admin_id))
    )


def setup_refund_cascade_scenario() -> Dict[str, Any]:
    """Teacher with lifetime net earnings of 20400 (tax document REQUIRED_UPDATE),
    a REQUESTED payout whose period covers three sections, and a third section
    still open for enrollment that the teacher then cancels.

    Returns the ids and the pre-cascade payout figures.
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Robotics", list_price_cents=10000)
    learner = create_learner(tier="FAMILY")

    starts = ["2026-10-10T14:00:00Z", "2026-10-11T14:00:00Z", "2026-10-20T14:00:00Z"]
    sections = []
    enrollments = []
    for start in starts:
        end = start.replace("T14:00:00Z", "T16:00:00Z")
        subscribe_learner(learner["id"], "FAMILY")
        section = create_section(listing, teacher, start_utc=start, end_utc=end, min_learners=1, capacity=6)
        enrollment = reserve_and_confirm(listing, section, learner)
        sections.append(section)
        enrollments.append(enrollment)

    # The first two sections run and complete; the third is still ahead of the clock.
    for section, start in zip(sections[:2], starts[:2]):
        declare_minimum_met(listing["id"], section["id"], teacher["id"])
    set_clock("2026-10-15T12:00:00Z")
    run_ops()

    payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    return {
        "teacher": teacher,
        "listing": listing,
        "learner": learner,
        "sections": sections,
        "enrollments": enrollments,
        "payout": payout,
    }


def setup_tax_document_gate_scenario() -> Dict[str, Any]:
    """Two OPEN_FOR_ENROLLMENT sections inside one payout period, each with a CONFIRMED
    enrollment at 12000, so the payout accrues 24000 and the teacher's lifetime earnings
    sit at 20400 — above the reporting threshold, which puts the tax document in
    REQUIRED_UPDATE. The clock is parked between the two section starts, so the second
    section can still be cancelled by its teacher.

    The learner's allowance is refilled before each confirmation, because a FAMILY
    allowance of 12000 is consumed whole by one 12000-cent confirmation.
    """
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Robotics", list_price_cents=15000)
    learner = create_learner(tier="FAMILY")
    sections = []
    enrollments = []
    for start in ("2026-10-10T14:00:00Z", "2026-10-20T14:00:00Z"):
        end = start.replace("T14:00:00Z", "T16:00:00Z")
        subscribe_learner(learner["id"], "FAMILY")
        section = create_section(listing, teacher, start_utc=start, end_utc=end, min_learners=1, capacity=6)
        enrollment = reserve_seat(listing, section, learner)
        confirm_seat(enrollment["id"])
        sections.append(section)
        enrollments.append(enrollment)
    set_clock("2026-10-15T12:00:00Z")
    payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    return {
        "teacher": teacher,
        "listing": listing,
        "learner": learner,
        "sections": sections,
        "enrollments": enrollments,
        "payout": payout,
    }


def setup_compensating_refund_scenario() -> Dict[str, Any]:
    """Two OPEN_FOR_ENROLLMENT sections inside one payout period, each with a
    CONFIRMED enrollment at the tier-discounted price; the payout is REQUESTED
    before the second section is cancelled."""
    teacher = onboard_active_teacher()
    listing = setup_listing(teacher, title="Algebra Club", list_price_cents=2000)
    learner = create_learner(tier="FAMILY")
    sections = []
    enrollments = []
    for start in ("2026-10-10T14:00:00Z", "2026-10-20T14:00:00Z"):
        end = start.replace("T14:00:00Z", "T16:00:00Z")
        subscribe_learner(learner["id"], "FAMILY")
        section = create_section(listing, teacher, start_utc=start, end_utc=end, min_learners=1, capacity=6)
        enrollment = reserve_and_confirm(listing, section, learner)
        sections.append(section)
        enrollments.append(enrollment)
    set_clock("2026-10-15T12:00:00Z")
    payout = request_payout(teacher, "2026-10-01T00:00:00Z", "2026-10-31T00:00:00Z")
    return {
        "teacher": teacher,
        "listing": listing,
        "learner": learner,
        "sections": sections,
        "enrollments": enrollments,
        "payout": payout,
    }
