"""Composite state builders.

Each helper drives the public API only -- there is no back door into storage --
and every one starts from an empty database, because the service is relaunched
against a fresh database before each test. Helpers use the lenient
``get_success_data`` so that a broken setup step fails loudly as a setup error
rather than masquerading as an assertion failure.

Because the logical clock is explicit, several helpers move it. Each one
documents the instant it leaves the clock at so a caller can reason about
session windows, checkout leads, air times and retention deadlines.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ADVANCED_COMPETENCY_CODES,
    BASIC_COMPETENCY_CODES,
    CLOCK_AFTER_ADVANCED_SESSION,
    CLOCK_AFTER_BASIC_SESSION,
    CLOCK_AFTER_LIVE_SESSION,
    CURRENT_STATEMENT_VERSION,
    DEFAULT_CLOCK_UTC,
    LIVE_COMPETENCY_CODES,
    REQUIRED_ATTESTATION_KINDS,
)
from .test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    FINANCE_HEADERS,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    make_producer_headers,
)


# ------------------------------------------------------------------- clock
def set_clock(client, instant: str) -> str:
    """Move the logical clock and return the instant it now reads."""
    get_success_data(client.set_clock(instant))
    return instant


def reset_clock(client) -> str:
    return set_clock(client, DEFAULT_CLOCK_UTC)


# --------------------------------------------------------------- membership
def register_producer(client, **overrides: Any) -> Dict[str, Any]:
    """Register an applicant. Leaves the producer in APPLICANT status."""
    payload = f.producer_payload(**overrides)
    return get_success_data(client.create_producer(payload, ADMIN_HEADERS))


def activate_producer(client, producer_id: str, **overrides: Any) -> Dict[str, Any]:
    """Record the residency document, moving APPLICANT to ACTIVE."""
    payload = f.residency_payload(**overrides)
    return get_success_data(client.verify_residency(producer_id, payload, ADMIN_HEADERS))


def setup_active_producer(client, **overrides: Any) -> Dict[str, Any]:
    """An ACTIVE producer holding no competencies and certification NONE."""
    producer = register_producer(client, **overrides)
    return activate_producer(client, producer["id"])


def read_producer(client, producer_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_producer(producer_id, ADMIN_HEADERS))


# ---------------------------------------------------------------- curriculum
def publish_course(client, **overrides: Any) -> Dict[str, Any]:
    payload = f.training_course_payload(**overrides)
    return get_success_data(client.create_training_course(payload, TRAINER_HEADERS))


def enroll(client, producer_id: str, course_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.enrollment_payload(producer_id, course_id, **overrides)
    return get_success_data(
        client.create_course_enrollment(payload, make_producer_headers(producer_id))
    )


def mark_attended(client, enrollment_id: str, attended: bool = True) -> Dict[str, Any]:
    return get_success_data(
        client.record_attendance(enrollment_id, f.attendance_payload(attended), TRAINER_HEADERS)
    )


def grade(client, enrollment_id: str, score: int) -> Dict[str, Any]:
    return get_success_data(
        client.grade_enrollment(enrollment_id, f.grade_payload(score), TRAINER_HEADERS)
    )


def complete_course(
    client, producer_id: str, course: Dict[str, Any], score: int, clock_after: str
) -> Dict[str, Any]:
    """Enroll, attend and grade one course, moving the clock past its session.

    Leaves the clock at ``clock_after``.
    """
    enrollment = enroll(client, producer_id, course["id"])
    set_clock(client, clock_after)
    mark_attended(client, enrollment["id"])
    return grade(client, enrollment["id"], score)


def setup_basic_certified_producer(
    client, score: int = 88, course: Optional[Dict[str, Any]] = None, **producer_overrides: Any
) -> Dict[str, Any]:
    """An ACTIVE producer who has passed a BASIC course.

    Certification settles at BASIC and the competency set is the granting
    course's ``grants_competency_codes``. Leaves the clock at 2026-08-06T00:00:00Z.
    """
    producer = setup_active_producer(client, **producer_overrides)
    if course is None:
        course = publish_course(
            client,
            tier="BASIC",
            grants_competency_codes=list(BASIC_COMPETENCY_CODES),
            session_start_at="2026-08-05T17:00:00Z",
            session_end_at="2026-08-05T21:00:00Z",
        )
    complete_course(client, producer["id"], course, score, CLOCK_AFTER_BASIC_SESSION)
    return read_producer(client, producer["id"])


def setup_live_certified_producer(client, **producer_overrides: Any) -> Dict[str, Any]:
    """An ACTIVE producer who has passed the BASIC, ADVANCED and LIVE tiers.

    The tier prerequisites force the ladder to be walked in order. Leaves the
    clock at 2026-08-10T00:00:00Z.
    """
    producer = setup_active_producer(client, **producer_overrides)
    basic = publish_course(
        client,
        tier="BASIC",
        grants_competency_codes=list(BASIC_COMPETENCY_CODES),
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    complete_course(client, producer["id"], basic, 93, CLOCK_AFTER_BASIC_SESSION)
    advanced = publish_course(
        client,
        title="Control Room Operations",
        tier="ADVANCED",
        grants_competency_codes=list(ADVANCED_COMPETENCY_CODES),
        session_start_at="2026-08-07T17:00:00Z",
        session_end_at="2026-08-07T21:00:00Z",
    )
    complete_course(client, producer["id"], advanced, 90, CLOCK_AFTER_ADVANCED_SESSION)
    live = publish_course(
        client,
        title="Live Switching",
        tier="LIVE",
        grants_competency_codes=list(LIVE_COMPETENCY_CODES),
        session_start_at="2026-08-09T17:00:00Z",
        session_end_at="2026-08-09T21:00:00Z",
    )
    complete_course(client, producer["id"], live, 95, CLOCK_AFTER_LIVE_SESSION)
    return read_producer(client, producer["id"])


# ------------------------------------------------------------------- series
def propose_series(client, producer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.series_payload(producer_id, **overrides)
    return get_success_data(client.create_series(payload, make_producer_headers(producer_id)))


def activate_series(client, series_id: str) -> Dict[str, Any]:
    return get_success_data(client.activate_series(series_id, {}, SCHEDULER_HEADERS))


def read_series(client, series_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_series(series_id, SCHEDULER_HEADERS))


def grant_hold_plan(client, series_id: str, slots: int) -> Dict[str, Any]:
    """Replace the hold plan, reading the current version for the guard."""
    current = read_series(client, series_id)
    payload = f.hold_plan_payload(current["version"], slots)
    return get_success_data(client.replace_hold_plan(series_id, payload, SCHEDULER_HEADERS))


def setup_active_series_with_hold_plan(
    client, producer_id: str, slots: int = 4, **overrides: Any
) -> Dict[str, Any]:
    """A series in ACTIVE status carrying a hold plan of ``slots`` slots."""
    series = propose_series(client, producer_id, **overrides)
    activate_series(client, series["id"])
    return grant_hold_plan(client, series["id"], slots)


# ----------------------------------------------------------------- programs
def create_program(client, producer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.program_payload(producer_id, **overrides)
    return get_success_data(client.create_program(payload, make_producer_headers(producer_id)))


def append_attestation(
    client, program_id: str, producer_id: str, kind: str, **overrides: Any
) -> Dict[str, Any]:
    payload = f.attestation_payload(producer_id, kind, **overrides)
    return get_success_data(
        client.append_attestation(program_id, payload, make_producer_headers(producer_id))
    )


def clear_program(
    client, program_id: str, producer_id: str, statement_version: str = CURRENT_STATEMENT_VERSION
) -> List[Dict[str, Any]]:
    """Append the three required attestation kinds so clearance is earned."""
    signed = []
    for kind in REQUIRED_ATTESTATION_KINDS:
        signed.append(
            append_attestation(client, program_id, producer_id, kind,
                               statement_version=statement_version)
        )
    return signed


def read_program(client, program_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_program(program_id, ADMIN_HEADERS))


def submit_program(client, program_id: str, producer_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.submit_program(program_id, {}, make_producer_headers(producer_id))
    )


def claim_review(client, program_id: str, reviewer_headers=REVIEWER_HEADERS) -> Dict[str, Any]:
    return get_success_data(client.claim_program_review(program_id, {}, reviewer_headers))


def approve_program(client, program_id: str, reviewer_headers=REVIEWER_HEADERS) -> Dict[str, Any]:
    payload = f.review_decision_payload("APPROVE")
    return get_success_data(client.decide_program_review(program_id, payload, reviewer_headers))


def request_changes(
    client, program_id: str, reviewer_headers=REVIEWER_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    payload = f.request_changes_payload(**overrides)
    return get_success_data(client.decide_program_review(program_id, payload, reviewer_headers))


def setup_cleared_program(client, producer_id: str, **overrides: Any) -> Dict[str, Any]:
    """A DRAFT program whose clearance_status has reached CLEARED."""
    program = create_program(client, producer_id, **overrides)
    clear_program(client, program["id"], producer_id)
    return read_program(client, program["id"])


def setup_approved_program(
    client, producer_id: str, reviewer_headers=REVIEWER_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    """A program that is APPROVED and CLEARED, and therefore bookable."""
    program = setup_cleared_program(client, producer_id, **overrides)
    submit_program(client, program["id"], producer_id)
    claim_review(client, program["id"], reviewer_headers)
    approve_program(client, program["id"], reviewer_headers)
    return read_program(client, program["id"])


# ----------------------------------------------------------------- channels
def create_channel(client, **overrides: Any) -> Dict[str, Any]:
    payload = f.channel_payload(**overrides)
    return get_success_data(client.create_channel(payload, ADMIN_HEADERS))


def read_channel(client, channel_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_channel(channel_id, ADMIN_HEADERS))


# ----------------------------------------------------------- playback slots
def book_slot(
    client, channel_id: str, program_id: str, start_at: str = "2026-08-20T18:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    payload = f.playback_slot_payload(channel_id, program_id, start_at, **overrides)
    return get_success_data(client.create_playback_slot(payload, SCHEDULER_HEADERS))


def read_slot(client, slot_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_playback_slot(slot_id, SCHEDULER_HEADERS))


def air_slot(client, slot_id: str, measured_households: int = 640) -> Dict[str, Any]:
    payload = f.air_payload(measured_households)
    return get_success_data(client.air_playback_slot(slot_id, payload, SCHEDULER_HEADERS))


def cancel_slot(client, slot_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.slot_cancel_payload(**overrides)
    return get_success_data(client.cancel_playback_slot(slot_id, payload, SCHEDULER_HEADERS))


def setup_scheduled_slot(
    client,
    producer_id: str,
    start_at: str = "2026-08-20T18:00:00Z",
    channel: Optional[Dict[str, Any]] = None,
    program: Optional[Dict[str, Any]] = None,
    **program_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A SCHEDULED slot for an approved program.

    Returns ``(channel, program, slot)``.
    """
    if channel is None:
        channel = create_channel(client)
    if program is None:
        program = setup_approved_program(client, producer_id, **program_overrides)
    slot = book_slot(client, channel["id"], program["id"], start_at)
    return channel, program, slot


# --------------------------------------------------------- crew assignments
def offer_crew(
    client, slot_id: str, volunteer_producer_id: str, crew_role: str = "CAMERA"
) -> Dict[str, Any]:
    payload = f.crew_assignment_payload(slot_id, volunteer_producer_id, crew_role)
    return get_success_data(client.create_crew_assignment(payload, SCHEDULER_HEADERS))


def confirm_crew(client, assignment_id: str, volunteer_producer_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.confirm_crew_assignment(
            assignment_id, {}, make_producer_headers(volunteer_producer_id)
        )
    )


def release_crew(client, assignment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.crew_release_payload(**overrides)
    return get_success_data(client.release_crew_assignment(assignment_id, payload, SCHEDULER_HEADERS))


def read_crew(client, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_crew_assignment(assignment_id, SCHEDULER_HEADERS))


def staff_slot(
    client, slot_id: str, volunteer_producer_id: str, crew_role: str = "CAMERA"
) -> Dict[str, Any]:
    """Offer and confirm one crew role, so the slot gains that coverage."""
    assignment = offer_crew(client, slot_id, volunteer_producer_id, crew_role)
    return confirm_crew(client, assignment["id"], volunteer_producer_id)


# --------------------------------------------------------- studio resources
def create_resource(client, **overrides: Any) -> Dict[str, Any]:
    payload = f.studio_resource_payload(**overrides)
    return get_success_data(client.create_studio_resource(payload, FACILITIES_HEADERS))


def read_resource(client, resource_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_studio_resource(resource_id, FACILITIES_HEADERS))


def set_resource_status(client, resource_id: str, status: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.resource_status_payload(status, **overrides)
    return get_success_data(
        client.set_studio_resource_status(resource_id, payload, FACILITIES_HEADERS)
    )


# ------------------------------------------------------------- reservations
def request_reservation(
    client,
    producer_id: str,
    resource_id: str,
    start_at: str = "2026-08-08T10:00:00Z",
    end_at: str = "2026-08-08T12:00:00Z",
    **overrides: Any
) -> Dict[str, Any]:
    payload = f.reservation_payload(producer_id, resource_id, start_at, end_at, **overrides)
    return get_success_data(
        client.create_reservation(payload, make_producer_headers(producer_id))
    )


def confirm_reservation(client, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(client.confirm_reservation(reservation_id, {}, FACILITIES_HEADERS))


def read_reservation(client, reservation_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_reservation(reservation_id, FACILITIES_HEADERS))


def checkout_reservation(client, reservation_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.checkout_payload(**overrides)
    return get_success_data(client.checkout_reservation(reservation_id, payload, FACILITIES_HEADERS))


def return_clean(client, reservation_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.clean_return_payload(**overrides)
    return get_success_data(client.return_reservation(reservation_id, payload, FACILITIES_HEADERS))


def return_damaged(
    client, reservation_id: str, severity: str = "MINOR", repair_estimate_cents: int = 40000,
    **overrides: Any
) -> Dict[str, Any]:
    payload = f.damaged_return_payload(severity, repair_estimate_cents, **overrides)
    return get_success_data(client.return_reservation(reservation_id, payload, FACILITIES_HEADERS))


def setup_confirmed_reservation(
    client,
    producer_id: str,
    resource: Optional[Dict[str, Any]] = None,
    start_at: str = "2026-08-08T10:00:00Z",
    end_at: str = "2026-08-08T12:00:00Z",
    **reservation_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A CONFIRMED reservation whose deposit hold is frozen.

    Returns ``(resource, reservation)``.
    """
    if resource is None:
        resource = create_resource(client)
    reservation = request_reservation(
        client, producer_id, resource["id"], start_at, end_at, **reservation_overrides
    )
    reservation = confirm_reservation(client, reservation["id"])
    return resource, reservation


def list_assessments_for(client, reservation_id: str) -> List[Dict[str, Any]]:
    response = client.list_damage_assessments(FACILITIES_HEADERS, {"reservation_id": reservation_id})
    data = get_success_data(response)
    return data if isinstance(data, list) else [data]


def read_assessment(client, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_damage_assessment(assessment_id, FACILITIES_HEADERS))


def finalize_assessment(client, assessment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.finalize_damage_assessment(assessment_id, {}, FACILITIES_HEADERS)
    )


def waive_assessment(client, assessment_id: str, headers=FINANCE_HEADERS, **overrides: Any):
    payload = f.waiver_payload(**overrides)
    return get_success_data(client.waive_damage_assessment(assessment_id, payload, headers))


def setup_reservation_in_damage_review(
    client,
    producer_id: str,
    resource: Optional[Dict[str, Any]] = None,
    start_at: str = "2026-08-08T10:00:00Z",
    end_at: str = "2026-08-08T12:00:00Z",
    checkout_at: str = "2026-08-08T10:00:00Z",
    return_at: str = "2026-08-08T11:00:00Z",
    severity: str = "MINOR",
    repair_estimate_cents: int = 40000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A reservation in DAMAGE_REVIEW with its FILED assessment.

    Returns ``(resource, reservation, assessment)`` and leaves the clock at
    ``return_at``.
    """
    resource, reservation = setup_confirmed_reservation(
        client, producer_id, resource, start_at, end_at
    )
    set_clock(client, checkout_at)
    checkout_reservation(client, reservation["id"])
    set_clock(client, return_at)
    reservation = return_damaged(client, reservation["id"], severity, repair_estimate_cents)
    assessment = list_assessments_for(client, reservation["id"])[0]
    return resource, reservation, assessment


def accrue_suspension_points(
    client,
    producer_id: str,
    severity: str = "MINOR",
    repair_estimate_cents: int = 40000,
    resource: Optional[Dict[str, Any]] = None,
    start_at: str = "2026-08-06T10:00:00Z",
    end_at: str = "2026-08-06T12:00:00Z",
    checkout_at: str = "2026-08-06T10:00:00Z",
    return_at: str = "2026-08-06T11:00:00Z",
) -> Dict[str, Any]:
    """Run one damage cycle to finalization so the producer carries points.

    Returns the finalized assessment and leaves the clock at ``return_at``.
    """
    _resource, _reservation, assessment = setup_reservation_in_damage_review(
        client,
        producer_id,
        resource,
        start_at,
        end_at,
        checkout_at,
        return_at,
        severity,
        repair_estimate_cents,
    )
    return finalize_assessment(client, assessment["id"])


# ---------------------------------------------------------- funding periods
def open_funding_period(client, **overrides: Any) -> Dict[str, Any]:
    payload = f.funding_period_payload(**overrides)
    return get_success_data(client.create_funding_period(payload, FINANCE_HEADERS))


def read_funding_period(client, period_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_funding_period(period_id, FINANCE_HEADERS))


def submit_funding_report(client, period_id: str, headers=FINANCE_HEADERS) -> Dict[str, Any]:
    return get_success_data(client.submit_funding_report(period_id, {}, headers))


def decide_funding_report(
    client, period_id: str, decision: str = "ACCEPT", headers=ADMIN_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    payload = f.report_decision_payload(decision, **overrides)
    return get_success_data(client.decide_funding_report(period_id, payload, headers))


def revise_funding_period(client, period_id: str, **changes: Any) -> Dict[str, Any]:
    """Restate a period, reading the stored version for the concurrency guard."""
    current = read_funding_period(client, period_id)
    payload = f.revise_funding_payload(current["version"], **changes)
    return get_success_data(client.revise_funding_period(period_id, payload, FINANCE_HEADERS))


def setup_submitted_funding_period(client, **overrides: Any) -> Dict[str, Any]:
    """A funding period whose municipal report has been submitted."""
    period = open_funding_period(client, **overrides)
    return submit_funding_report(client, period["id"])


# ----------------------------------------------------------- archive assets
def list_assets_for_slot(client, slot_id: str) -> List[Dict[str, Any]]:
    response = client.list_archive_assets(ADMIN_HEADERS, {"source_slot_id": slot_id})
    data = get_success_data(response)
    return data if isinstance(data, list) else [data]


def read_asset(client, asset_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_archive_asset(asset_id, ADMIN_HEADERS))


def publish_asset(client, asset_id: str, retention_class: str = "STANDARD_24M") -> Dict[str, Any]:
    payload = f.publish_payload(retention_class)
    return get_success_data(client.publish_archive_asset(asset_id, payload, ADMIN_HEADERS))


def record_views(client, asset_id: str, on_demand_views: int = 250) -> Dict[str, Any]:
    payload = f.record_views_payload(on_demand_views)
    return get_success_data(client.record_archive_views(asset_id, payload, ADMIN_HEADERS))


def purge_asset(client, asset_id: str) -> Dict[str, Any]:
    return get_success_data(client.purge_archive_asset(asset_id, {}, ADMIN_HEADERS))


def setup_aired_slot_with_asset(
    client,
    producer_id: str,
    start_at: str = "2026-08-20T18:00:00Z",
    measured_households: int = 640,
    channel: Optional[Dict[str, Any]] = None,
    program: Optional[Dict[str, Any]] = None,
    **program_overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Book a slot, move the clock to its start and air it.

    Returns ``(channel, program, slot, asset)`` and leaves the clock at
    ``start_at``.
    """
    channel, program, slot = setup_scheduled_slot(
        client, producer_id, start_at, channel, program, **program_overrides
    )
    set_clock(client, start_at)
    slot = air_slot(client, slot["id"], measured_households)
    asset = list_assets_for_slot(client, slot["id"])[0]
    return channel, program, slot, asset


def setup_published_asset(
    client,
    producer_id: str,
    retention_class: str = "STANDARD_24M",
    start_at: str = "2026-08-20T18:00:00Z",
    measured_households: int = 640,
    **kwargs: Any
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """An asset published on demand under a retention class.

    Returns ``(channel, program, slot, asset)`` and leaves the clock at
    ``start_at``, which is also the publication instant.
    """
    channel, program, slot, asset = setup_aired_slot_with_asset(
        client, producer_id, start_at, measured_households, **kwargs
    )
    asset = publish_asset(client, asset["id"], retention_class)
    return channel, program, slot, asset
