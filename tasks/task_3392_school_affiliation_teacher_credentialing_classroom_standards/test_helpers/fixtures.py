"""Composite setup helpers — multi-step API preambles behind one call.

Every builder drives the public API only and uses ``get_success_data`` so a
setup step that the PRD answers with 200 or 201 does not pin either at the
call site; a failed setup raises a clear "Setup step failed" error.

Identity threading (PRD section 2.1): after an entity-backed resource is
created, every ownership-gated call uses ``make_<role>_headers(entity_id)``
— never the shared fallback header sets.

Frozen edition values: the date arithmetic below uses the default test
catalog's numbers (36 validity months, 3 window months, 6 grace months,
12 tenure months, 30 plan-response days) because those are the values the
catalog is created with; tests that build a different edition pass explicit
arguments.
"""

import calendar
import datetime
from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import CLOCK_START_ISO, MIN_DUES_CENTS, RENEWAL_BASE_FEE_CENTS
from .test_users import (
    ACCREDITATION_REVIEWER,
    CONSULTANT_USER_ID,
    REGISTRAR,
    SOCIETY_ADMIN,
    make_adult_learner_headers,
    make_consultant_headers,
    make_program_director_headers,
    make_school_admin_headers,
)

# Frozen values of the default test edition (mirrors
# factories.create_standards_catalog_payload defaults).
CATALOG_VALIDITY_MONTHS = 36
CATALOG_RENEWAL_WINDOW_MONTHS = 3
CATALOG_RENEWAL_GRACE_MONTHS = 6
CATALOG_TENURE_MONTHS = 12
CATALOG_PLAN_RESPONSE_DAYS = 30
CATALOG_PRACTICUM_MIN_HOURS_EC = 540


# ---------------------------------------------------------------------------
# Date arithmetic (calendar-month and day precision, no wall clock)
# ---------------------------------------------------------------------------
def date_of(iso_timestamp: str) -> str:
    """The YYYY-MM-DD date part of an ISO 8601 timestamp."""
    return iso_timestamp[:10]


def add_calendar_months(iso_date: str, months: int) -> str:
    """Shift a YYYY-MM-DD date by whole calendar months, clamping the day
    to the target month's last day (e.g. Jan 31 + 1 month -> Feb 28/29)."""
    d = datetime.date.fromisoformat(iso_date)
    month0 = d.month - 1 + months
    year = d.year + month0 // 12
    month = month0 % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(d.day, last_day)).isoformat()


def add_days(iso_date: str, days: int) -> str:
    return (datetime.date.fromisoformat(iso_date) + datetime.timedelta(days=days)).isoformat()


def instant_day_after(iso_timestamp: str) -> str:
    """Same time-of-day one day later — strictly greater than the input."""
    dt = datetime.datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def expected_plan_due_date(filed_on_date: str, plan_response_days: int = CATALOG_PLAN_RESPONSE_DAYS) -> str:
    """due_date = filing date + plan_response_days (PRD section 3.6)."""
    return add_days(filed_on_date, plan_response_days)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str) -> dict:
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), headers=SOCIETY_ADMIN)
    )


def reset_clock() -> dict:
    """PRD section 2.5: before any call the clock reads 2026-09-01T00:00:00Z;
    fixtures re-assert that baseline explicitly."""
    return set_clock(CLOCK_START_ISO)


# ---------------------------------------------------------------------------
# Standards catalogs
# ---------------------------------------------------------------------------
def create_standards_catalog(**overrides) -> dict:
    return get_success_data(
        api_client.create_standards_catalog(
            f.create_standards_catalog_payload(**overrides), headers=SOCIETY_ADMIN
        )
    )


def create_active_catalog(**overrides) -> dict:
    """Create a DRAFT edition and activate it; returns the ACTIVE catalog."""
    catalog = create_standards_catalog(**overrides)
    return get_success_data(
        api_client.activate_standards_catalog(catalog["id"], headers=SOCIETY_ADMIN)
    )


def read_catalog(catalog_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_standards_catalog(catalog_id, headers=headers or SOCIETY_ADMIN)
    )


# ---------------------------------------------------------------------------
# Schools, brand, dues, standing
# ---------------------------------------------------------------------------
def create_school(**overrides) -> dict:
    return get_success_data(
        api_client.create_school(f.create_school_payload(**overrides), headers=SOCIETY_ADMIN)
    )


def read_school(school_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_school(school_id, headers=headers or SOCIETY_ADMIN))


def school_version(school_id: str) -> int:
    """Fresh read of the school's current OCC version."""
    return read_school(school_id)["version"]


def pay_dues(
    school_id: str,
    period_start: str = "2026-09-01",
    period_end: str = "2027-09-01",
    amount_cents: int = MIN_DUES_CENTS,
) -> dict:
    """Record a dues payment; sets dues_paid_through := period_end."""
    return get_success_data(
        api_client.record_dues_payment(
            school_id,
            f.record_dues_payment_payload(
                period_start=period_start, period_end=period_end, amount_cents=amount_cents
            ),
            headers=SOCIETY_ADMIN,
        )
    )


def update_brand(school_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.update_school_brand(
            school_id,
            f.update_brand_payload(**overrides),
            headers=make_school_admin_headers(school_id),
        )
    )


def set_standing(school_id: str, to_standing: str, reason=None, reviewer_headers=None) -> dict:
    return get_success_data(
        api_client.set_school_standing(
            school_id,
            f.set_standing_payload(to_standing, reason=reason),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


# ---------------------------------------------------------------------------
# Classrooms and audits
# ---------------------------------------------------------------------------
def create_classroom(school_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_classroom(
            f.create_classroom_payload(school_id, **overrides),
            headers=make_school_admin_headers(school_id),
        )
    )


def read_classroom(classroom_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_classroom(classroom_id, headers=headers or SOCIETY_ADMIN))


def transfer_students(from_classroom_id: str, to_classroom_id: str, student_count: int, school_id: str) -> dict:
    return get_success_data(
        api_client.transfer_students(
            from_classroom_id,
            f.transfer_students_payload(to_classroom_id, student_count),
            headers=make_school_admin_headers(school_id),
        )
    )


def file_classroom_audit(classroom_id: str, consultant_id: str = CONSULTANT_USER_ID, **overrides) -> dict:
    """File a standards audit; defaults are compliant under the test edition
    (ratio 12.0 <= 15, work 180 >= 180, materials 0.90 >= 0.9)."""
    return get_success_data(
        api_client.create_classroom_audit(
            f.create_classroom_audit_payload(classroom_id, **overrides),
            headers=make_consultant_headers(consultant_id),
        )
    )


def read_classroom_audit(audit_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_classroom_audit(audit_id, headers=headers or SOCIETY_ADMIN))


# ---------------------------------------------------------------------------
# Teacher education programs and adult learners
# ---------------------------------------------------------------------------
def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_teacher_education_program(
            f.create_program_payload(**overrides), headers=SOCIETY_ADMIN
        )
    )


def read_program(program_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_teacher_education_program(program_id, headers=headers or SOCIETY_ADMIN)
    )


def set_program_status(program_id: str, to_status: str, reason=None, reviewer_headers=None) -> dict:
    return get_success_data(
        api_client.set_program_status(
            program_id,
            f.set_program_status_payload(to_status, reason=reason),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


def create_accredited_program(**overrides) -> dict:
    """PROVISIONAL -> ACCREDITED (default practicum map meets the edition)."""
    program = create_program(**overrides)
    return set_program_status(program["id"], "ACCREDITED")


def enroll_learner(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_adult_learner(
            f.create_adult_learner_payload(program_id, **overrides),
            headers=make_program_director_headers(program_id),
        )
    )


def read_learner(learner_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_adult_learner(learner_id, headers=headers or SOCIETY_ADMIN))


# ---------------------------------------------------------------------------
# Practicum placements
# ---------------------------------------------------------------------------
def create_placement(
    learner_id: str,
    host_school_id: str,
    program_id: str,
    supervisor_credential_id=None,
    start_date: str = f.DEFAULT_PLACEMENT_START_DATE,
    end_date: str = f.DEFAULT_PLACEMENT_END_DATE,
) -> dict:
    return get_success_data(
        api_client.create_practicum_placement(
            f.create_practicum_placement_payload(
                learner_id,
                host_school_id,
                supervisor_credential_id=supervisor_credential_id,
                start_date=start_date,
                end_date=end_date,
            ),
            headers=make_program_director_headers(program_id),
        )
    )


def read_placement(placement_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_practicum_placement(placement_id, headers=headers or SOCIETY_ADMIN)
    )


def log_hours(placement_id: str, learner_id: str, hours: int, work_date: str = f.DEFAULT_WORK_DATE) -> dict:
    return get_success_data(
        api_client.log_placement_hours(
            placement_id,
            f.log_hours_payload(hours, work_date),
            headers=make_adult_learner_headers(learner_id),
        )
    )


def verify_placement(placement_id: str, program_id: str) -> dict:
    return get_success_data(
        api_client.verify_practicum_placement(
            placement_id, headers=make_program_director_headers(program_id)
        )
    )


def cancel_placement(placement_id: str, program_id: str) -> dict:
    return get_success_data(
        api_client.cancel_practicum_placement(
            placement_id, headers=make_program_director_headers(program_id)
        )
    )


def create_verified_placement(
    learner_id: str,
    program_id: str,
    host_school_id: str,
    hours: int = None,
    work_date: str = f.DEFAULT_WORK_DATE,
    **placement_kwargs,
) -> dict:
    """Create a placement, log it to target_hours, and verify it. Returns
    the VERIFIED placement; the learner lands in PRACTICUM_COMPLETE."""
    placement = create_placement(learner_id, host_school_id, program_id, **placement_kwargs)
    target = placement["target_hours"]
    log_hours(placement["id"], learner_id, hours if hours is not None else target, work_date)
    return verify_placement(placement["id"], program_id)


# ---------------------------------------------------------------------------
# School applications
# ---------------------------------------------------------------------------
def create_application(school_id: str, app_type: str) -> dict:
    """Create with a fresh OCC token read inside the fixture."""
    payload = f.create_school_application_payload(school_id, app_type, school_version(school_id))
    return get_success_data(
        api_client.create_school_application(payload, headers=make_school_admin_headers(school_id))
    )


def read_application(application_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_school_application(application_id, headers=headers or SOCIETY_ADMIN)
    )


def submit_application(application_id: str, school_id: str) -> dict:
    return get_success_data(
        api_client.submit_school_application(
            application_id, headers=make_school_admin_headers(school_id)
        )
    )


def review_application(application_id: str, outcome: str, reviewer_headers=None, notes=None) -> dict:
    return get_success_data(
        api_client.review_school_application(
            application_id,
            f.review_application_payload(outcome, notes=notes),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


def advance_school_once(school_id: str, app_type: str, reviewer_headers=None) -> dict:
    """Create -> submit -> APPROVED one level-advancement application."""
    application = create_application(school_id, app_type)
    submit_application(application["id"], school_id)
    return review_application(application["id"], "APPROVED", reviewer_headers=reviewer_headers)


# ---------------------------------------------------------------------------
# Self-studies
# ---------------------------------------------------------------------------
def create_self_study(school_id: str, narrative=None) -> dict:
    """Create with a fresh OCC token; pins the currently ACTIVE catalog."""
    payload = f.create_self_study_payload(school_id, school_version(school_id), narrative=narrative)
    return get_success_data(
        api_client.create_self_study(payload, headers=make_school_admin_headers(school_id))
    )


def read_self_study(self_study_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_self_study(self_study_id, headers=headers or SOCIETY_ADMIN))


def submit_self_study(self_study_id: str, school_id: str) -> dict:
    return get_success_data(
        api_client.submit_self_study(self_study_id, headers=make_school_admin_headers(school_id))
    )


def review_self_study(self_study_id: str, outcome: str, reviewer_headers=None, notes=None) -> dict:
    return get_success_data(
        api_client.review_self_study(
            self_study_id,
            f.review_self_study_payload(outcome, notes=notes),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


def create_accepted_self_study(school_id: str, narrative=None) -> dict:
    """DRAFT -> SUBMITTED -> ACCEPTED; the school adopts the pinned catalog."""
    study = create_self_study(school_id, narrative=narrative)
    submit_self_study(study["id"], school_id)
    return review_self_study(study["id"], "ACCEPTED")


# ---------------------------------------------------------------------------
# Verification visits
# ---------------------------------------------------------------------------
def create_visit(
    school_id: str,
    self_study_id: str,
    consultant_id: str = CONSULTANT_USER_ID,
    window_start: str = f.DEFAULT_VISIT_WINDOW_START,
    window_end: str = f.DEFAULT_VISIT_WINDOW_END,
    reviewer_headers=None,
) -> dict:
    return get_success_data(
        api_client.create_verification_visit(
            f.create_verification_visit_payload(
                school_id,
                self_study_id,
                consultant_id,
                window_start=window_start,
                window_end=window_end,
            ),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


def read_visit(visit_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_verification_visit(visit_id, headers=headers or SOCIETY_ADMIN)
    )


def cancel_visit(visit_id: str, reviewer_headers=None) -> dict:
    return get_success_data(
        api_client.cancel_verification_visit(
            visit_id, headers=reviewer_headers or ACCREDITATION_REVIEWER
        )
    )


def file_visit_report(
    visit_id: str,
    consultant_id: str = CONSULTANT_USER_ID,
    verdict: str = "COMPLIANT",
    findings=None,
) -> dict:
    """The assigned consultant files the report (ownership: X-User-ID ==
    visit.consultant_id)."""
    return get_success_data(
        api_client.file_visit_report(
            visit_id,
            f.file_visit_report_payload(verdict=verdict, findings=findings),
            headers=make_consultant_headers(consultant_id),
        )
    )


# ---------------------------------------------------------------------------
# Improvement plans
# ---------------------------------------------------------------------------
def read_improvement_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_improvement_plan(plan_id, headers=headers or SOCIETY_ADMIN)
    )


def list_plans_for_school(school_id: str) -> list:
    return get_success_data(
        api_client.list_improvement_plans(
            headers=ACCREDITATION_REVIEWER, params={"school_id": school_id}
        )
    )


def get_only_plan_for_school(school_id: str) -> dict:
    plans = list_plans_for_school(school_id)
    assert len(plans) == 1, "expected exactly one plan for school {0}, got {1}".format(
        school_id, len(plans)
    )
    return plans[0]


def respond_to_plan(plan_id: str, school_id: str, response_notes: str = "Response notes") -> dict:
    """Respond with a fresh OCC token read inside the fixture."""
    plan = read_improvement_plan(plan_id)
    return get_success_data(
        api_client.respond_to_improvement_plan(
            plan_id,
            f.respond_to_plan_payload(response_notes, plan["version"]),
            headers=make_school_admin_headers(school_id),
        )
    )


def review_plan(plan_id: str, outcome: str, reviewer_headers=None, notes=None) -> dict:
    return get_success_data(
        api_client.review_improvement_plan(
            plan_id,
            f.review_plan_payload(outcome, notes=notes),
            headers=reviewer_headers or ACCREDITATION_REVIEWER,
        )
    )


def make_plan_overdue(plan: dict) -> dict:
    """Advance the clock strictly past the plan's due_date so the sweep flips
    OPEN -> OVERDUE (firing the school-standing cascade)."""
    set_clock(add_days(plan["due_date"], 1) + "T00:00:00Z")
    return read_improvement_plan(plan["id"])


# ---------------------------------------------------------------------------
# Credentials and the CE ledger
# ---------------------------------------------------------------------------
def issue_credential(learner_id: str, age_level: str = "EARLY_CHILDHOOD") -> dict:
    return get_success_data(
        api_client.create_credential(
            f.create_credential_payload(learner_id, age_level), headers=REGISTRAR
        )
    )


def read_credential(credential_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_credential(credential_id, headers=headers or SOCIETY_ADMIN))


def renew_credential(
    credential_id: str,
    learner_id: str = None,
    fee_cents: int = RENEWAL_BASE_FEE_CENTS,
    as_learner: bool = True,
) -> dict:
    """Renew; as the holder (AdultLearner, X-User-ID == learner_id) by
    default, or as the Registrar when as_learner is False."""
    headers = make_adult_learner_headers(learner_id) if as_learner else REGISTRAR
    return get_success_data(
        api_client.renew_credential(credential_id, f.renew_credential_payload(fee_cents), headers=headers)
    )


def revoke_credential(credential_id: str, reviewer_headers=None, reason=None) -> dict:
    payload = {"reason": reason} if reason is not None else None
    return get_success_data(
        api_client.revoke_credential(
            credential_id, payload=payload, headers=reviewer_headers or ACCREDITATION_REVIEWER
        )
    )


def create_pd_event(**overrides) -> dict:
    return get_success_data(
        api_client.create_pd_event(f.create_pd_event_payload(**overrides), headers=SOCIETY_ADMIN)
    )


def read_pd_event(event_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_pd_event(event_id, headers=headers or SOCIETY_ADMIN))


def record_attendance(event_id: str, credential_id: str, hours_earned=None) -> dict:
    return get_success_data(
        api_client.record_event_attendance(
            event_id,
            f.record_attendance_payload(credential_id, hours_earned=hours_earned),
            headers=SOCIETY_ADMIN,
        )
    )


def read_ce_entry(entry_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_ce_entry(entry_id, headers=headers or SOCIETY_ADMIN))


def void_ce_entry(entry_id: str) -> dict:
    return get_success_data(api_client.void_ce_entry(entry_id, headers=SOCIETY_ADMIN))


def create_completed_pd_event(advance_to: str = None, **overrides) -> dict:
    """Create a PD event and advance the clock strictly past its end_at so
    the sweep marks it COMPLETED."""
    event = create_pd_event(**overrides)
    set_clock(advance_to or instant_day_after(event["end_at"]))
    return read_pd_event(event["id"])


def grant_ce_hours(credential_id: str, advance_to: str = None, **event_overrides):
    """Create a PD event, complete it via the clock, and record attendance.
    Returns (event, ce_entry); earned_at is the event's end_at."""
    event = create_completed_pd_event(advance_to=advance_to, **event_overrides)
    entry = record_attendance(event["id"], credential_id)
    return event, entry


def renewal_window_open_date(credential: dict, window_months: int = CATALOG_RENEWAL_WINDOW_MONTHS) -> str:
    """First date renewal is allowed: date(expires_at) - window months."""
    return add_calendar_months(date_of(credential["expires_at"]), -window_months)


def set_clock_past_expiry(credential: dict) -> dict:
    """Advance strictly past date(expires_at): ACTIVE -> LAPSED."""
    return set_clock(add_days(date_of(credential["expires_at"]), 1) + "T00:00:00Z")


def set_clock_past_grace(credential: dict, grace_months: int = CATALOG_RENEWAL_GRACE_MONTHS) -> dict:
    """Advance strictly past date(expires_at) + grace: LAPSED -> EXPIRED."""
    grace_end = add_calendar_months(date_of(credential["expires_at"]), grace_months)
    return set_clock(add_days(grace_end, 1) + "T00:00:00Z")


# ---------------------------------------------------------------------------
# Composite tiers
# ---------------------------------------------------------------------------
def setup_affiliate_host_school(
    school_overrides=None,
    classroom_overrides=None,
    dues_period_end: str = "2027-09-01",
    dues_amount_cents: int = MIN_DUES_CENTS,
    reviewer_headers=None,
) -> SimpleNamespace:
    """School onboarded, dues paid, one classroom, AFFILIATION approved ->
    AFFILIATE (the practicum-host eligibility floor)."""
    school = create_school(**(school_overrides or {}))
    pay_dues(school["id"], period_end=dues_period_end, amount_cents=dues_amount_cents)
    classroom = create_classroom(school["id"], **(classroom_overrides or {}))
    application = advance_school_once(school["id"], "AFFILIATION", reviewer_headers=reviewer_headers)
    return SimpleNamespace(
        school=read_school(school["id"]), classroom=classroom, application=application
    )


def setup_member_school(
    school_overrides=None,
    classroom_overrides=None,
    dues_period_end: str = "2028-09-01",
    dues_amount_cents: int = MIN_DUES_CENTS,
    consultant_id: str = CONSULTANT_USER_ID,
    reviewer_headers=None,
    ensure_catalog: bool = True,
) -> SimpleNamespace:
    """AFFILIATE school plus one COMPLIANT classroom audit, then MEMBERSHIP
    approved -> MEMBER (member_since = the current logical date).
    ensure_catalog creates and activates the standard edition first (audit
    filing requires an ACTIVE catalog); pass False when the test manages
    catalog editions itself."""
    if ensure_catalog:
        create_active_catalog()
    host = setup_affiliate_host_school(
        school_overrides=school_overrides,
        classroom_overrides=classroom_overrides,
        dues_period_end=dues_period_end,
        dues_amount_cents=dues_amount_cents,
        reviewer_headers=reviewer_headers,
    )
    audit = file_classroom_audit(host.classroom["id"], consultant_id=consultant_id)
    application = advance_school_once(
        host.school["id"], "MEMBERSHIP", reviewer_headers=reviewer_headers
    )
    return SimpleNamespace(
        school=read_school(host.school["id"]),
        classroom=host.classroom,
        audit=audit,
        application=application,
    )


def stage_accreditation_application(
    school_overrides=None,
    classroom_overrides=None,
    dues_period_end: str = "2028-09-01",
    consultant_id: str = CONSULTANT_USER_ID,
    reviewer_headers=None,
    visit_window=("2027-10-10", "2027-10-12"),
    submit_at: str = "2027-10-20T00:00:00Z",
    ensure_catalog: bool = True,
) -> SimpleNamespace:
    """Everything an ACCREDITATION submit needs, then the application left
    UNDER_REVIEW: MEMBER school (member_since = clock start), dues current
    past the submit date, ACCEPTED self-study (catalog pinned), a visit
    reported COMPLIANT, an in-window COMPLIANT audit (NO_FAIL_IN_CYCLE
    clears), no improvement plans, and tenure satisfied (submit_at is after
    member_since + the edition's 12 tenure months). ensure_catalog creates
    and activates the standard edition; pass False when the test manages
    catalog editions itself."""
    member = setup_member_school(
        school_overrides=school_overrides,
        classroom_overrides=classroom_overrides,
        dues_period_end=dues_period_end,
        consultant_id=consultant_id,
        reviewer_headers=reviewer_headers,
        ensure_catalog=ensure_catalog,
    )
    school_id = member.school["id"]
    study = create_accepted_self_study(school_id)
    visit = create_visit(
        school_id,
        study["id"],
        consultant_id=consultant_id,
        window_start=visit_window[0],
        window_end=visit_window[1],
        reviewer_headers=reviewer_headers,
    )
    set_clock(visit_window[0] + "T00:00:00Z")
    in_window_audit = file_classroom_audit(member.classroom["id"], consultant_id=consultant_id)
    visit = file_visit_report(visit["id"], consultant_id=consultant_id, verdict="COMPLIANT")
    set_clock(submit_at)
    application = create_application(school_id, "ACCREDITATION")
    application = submit_application(application["id"], school_id)
    return SimpleNamespace(
        school=read_school(school_id),
        classroom=member.classroom,
        self_study=study,
        visit=visit,
        audit=in_window_audit,
        application=application,
    )


def setup_accredited_school(reviewer_headers=None, **kwargs) -> SimpleNamespace:
    """The full APPLICANT -> AFFILIATE -> MEMBER -> ACCREDITED ladder.
    reviewer_headers must not belong to the visit's consultant (segregation
    of duties, PRD section 3.7)."""
    staged = stage_accreditation_application(reviewer_headers=reviewer_headers, **kwargs)
    application = review_application(
        staged.application["id"], "APPROVED", reviewer_headers=reviewer_headers
    )
    return SimpleNamespace(
        school=read_school(staged.school["id"]),
        classroom=read_classroom(staged.classroom["id"]),
        self_study=staged.self_study,
        visit=staged.visit,
        audit=staged.audit,
        application=application,
    )


def setup_credentialed_teacher(
    age_level: str = "EARLY_CHILDHOOD",
    learner_name: str = None,
    program_overrides=None,
    host_dues_period_end: str = "2027-09-01",
    hours: int = None,
    work_date: str = f.DEFAULT_WORK_DATE,
) -> SimpleNamespace:
    """The whole credentialing bootstrap: ACTIVE catalog, ACCREDITED
    program, enrolled learner, AFFILIATE host school, an unsupervised
    placement logged to its target hours and verified, then the credential
    issued (ACTIVE, cycle_start = the current logical date)."""
    catalog = create_active_catalog()
    program = create_accredited_program(**(program_overrides or {}))
    learner_kwargs = {"age_level": age_level}
    if learner_name is not None:
        learner_kwargs["full_name"] = learner_name
    learner = enroll_learner(program["id"], **learner_kwargs)
    host = setup_affiliate_host_school(dues_period_end=host_dues_period_end)
    placement = create_verified_placement(
        learner["id"], program["id"], host.school["id"], hours=hours, work_date=work_date
    )
    credential = issue_credential(learner["id"], age_level)
    return SimpleNamespace(
        catalog=catalog,
        program=program,
        learner=read_learner(learner["id"]),
        host=host,
        placement=placement,
        credential=credential,
    )


def setup_supervisor_with_mentees(
    mentee_count: int = 3,
    mentee_window=("2027-04-01", "2027-10-01"),
    **kwargs,
) -> SimpleNamespace:
    """A credentialed supervisor (via the unsupervised bootstrap) plus
    ``mentee_count`` learners of the same program, each placed under the
    supervisor's credential. Exactly 3 supervised ACTIVE placements is the
    allowed cap; a 4th is rejected."""
    supervisor = setup_credentialed_teacher(**kwargs)
    mentees = [enroll_learner(supervisor.program["id"]) for _ in range(mentee_count)]
    placements = [
        create_placement(
            mentee["id"],
            supervisor.host.school["id"],
            supervisor.program["id"],
            supervisor_credential_id=supervisor.credential["id"],
            start_date=mentee_window[0],
            end_date=mentee_window[1],
        )
        for mentee in mentees
    ]
    return SimpleNamespace(supervisor=supervisor, mentees=mentees, placements=placements)


def setup_school_with_reported_visit(
    verdict: str = "IMPROVEMENT_REQUIRED",
    findings=None,
    consultant_id: str = CONSULTANT_USER_ID,
    report_date: str = f.DEFAULT_VISIT_WINDOW_START,
    with_pending_application: bool = False,
    dues_period_end: str = "2027-09-01",
    ensure_catalog: bool = True,
) -> SimpleNamespace:
    """School with an ACCEPTED self-study and a visit reported at
    ``report_date`` with ``verdict``. IMPROVEMENT_REQUIRED or NONCOMPLIANT
    auto-create an improvement plan (due report_date + plan_response_days);
    NONCOMPLIANT also drops a GOOD_STANDING school to PROBATION. When
    with_pending_application is set, an AFFILIATION application is left
    UNDER_REVIEW (for the standing-cascade probes). ensure_catalog creates
    and activates the standard edition (self-study creation requires an
    ACTIVE catalog); pass False when the test manages editions itself."""
    if ensure_catalog:
        create_active_catalog()
    school = create_school()
    pay_dues(school["id"], period_end=dues_period_end)
    classroom = create_classroom(school["id"])
    application = None
    if with_pending_application:
        application = create_application(school["id"], "AFFILIATION")
        application = submit_application(application["id"], school["id"])
    study = create_accepted_self_study(school["id"])
    visit = create_visit(school["id"], study["id"], consultant_id=consultant_id)
    set_clock(report_date + "T00:00:00Z")
    visit = file_visit_report(
        visit["id"], consultant_id=consultant_id, verdict=verdict, findings=findings
    )
    plan = None
    if verdict in ("IMPROVEMENT_REQUIRED", "NONCOMPLIANT"):
        plan = get_only_plan_for_school(school["id"])
    return SimpleNamespace(
        school=read_school(school["id"]),
        classroom=classroom,
        application=application,
        self_study=study,
        visit=visit,
        plan=plan,
    )


def setup_expired_credential(**kwargs) -> SimpleNamespace:
    """A credential walked ACTIVE -> LAPSED -> EXPIRED by the clock sweep
    (strictly past date(expires_at), then strictly past the grace end)."""
    ns = setup_credentialed_teacher(**kwargs)
    set_clock_past_expiry(ns.credential)
    lapsed = read_credential(ns.credential["id"])
    set_clock_past_grace(lapsed)
    return SimpleNamespace(**vars(ns), credential=read_credential(ns.credential["id"]))
