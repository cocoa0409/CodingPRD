"""Composite setup helpers built purely from PRD-declared endpoints.

Every helper drives the real API; nothing is seeded behind the scenes. The
helpers raise ``AssertionError`` with a "Setup failed" prefix when any setup
call does not succeed, so a broken precondition surfaces as a clear fixture
error rather than as a puzzling assertion failure in the test body.
"""
from types import SimpleNamespace

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, DEFAULT_PLAN_PAYMENT_CENTS
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_borrower_headers,
    make_cosigner_headers,
    make_school_headers,
    make_servicer_headers,
    make_underwriter_headers,
)

ADMIN = TEST_USERS["admin_headers"]
SERVICER = TEST_USERS["servicer_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------

def _data(response, what):
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup failed: {what} returned HTTP {response.status_code}: "
            f"{response.text[:400]}"
        )
    body = response.json()
    if "data" not in body:
        raise AssertionError(f"Setup failed: {what} returned no data envelope: {body}")
    return body["data"]


def reset_clock():
    """Return the logical clock to its fixed server default."""
    return api_client.set_clock(DEFAULT_CLOCK_ISO, ADMIN)


def set_clock(iso8601):
    return _data(api_client.set_clock(iso8601, SERVICER), f"clock set to {iso8601}")


def add_days(iso8601, days):
    """Shift an ISO 8601 UTC instant by whole days.

    Accepts both the server's three-fractional-digit form and a plain
    second-precision instant, so a server-stamped date can be shifted directly.
    """
    from datetime import datetime, timedelta, timezone

    text = iso8601[:-1] + "+00:00" if iso8601.endswith("Z") else iso8601
    instant = datetime.fromisoformat(text).astimezone(timezone.utc)
    shifted = instant + timedelta(days=days)
    return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")


def period_due_date(loan_id, due_period_index):
    """Read the server-stamped scheduled_due_date for a due period."""
    rows = _data(api_client.list_payments(loan_id, SERVICER), "GET /loans/{id}/payments")
    for row in rows:
        if row.get("due_period_index") == due_period_index:
            return row["scheduled_due_date"]
    raise AssertionError(
        f"Setup failed: no payment row for due period {due_period_index}"
    )


# ---------------------------------------------------------------------------
# Tier 1 — reference data
# ---------------------------------------------------------------------------

def list_borrowers(params=None, headers=None):
    return _data(
        api_client.list_borrowers(headers or ADMIN, params=params),
        "GET /borrowers",
    )


def list_schools(params=None, headers=None):
    return _data(
        api_client.list_schools(headers or ADMIN, params=params),
        "GET /schools",
    )


def create_accrual_entry(loan_id, window_months=6, entry_date="2026-12-31T00:00:00Z"):
    return book_accrual(loan_id, window_months=window_months, entry_date=entry_date)


def list_accrual_entries(loan_id, headers=None):
    return _data(
        api_client.list_accrual_entries(loan_id, headers or SERVICER),
        "GET /loans/{id}/accrual-entries",
    )


def create_borrower(**overrides):
    return _data(
        api_client.create_borrower(f.create_borrower_payload(**overrides), ADMIN),
        "POST /borrowers",
    )


def create_school(**overrides):
    return _data(
        api_client.create_school(f.create_school_payload(**overrides), ADMIN),
        "POST /schools",
    )


def create_policy(**overrides):
    return _data(
        api_client.create_policy(f.create_policy_payload(**overrides), ADMIN),
        "POST /loan-policies",
    )


def invite_cosigner(borrower_id, **overrides):
    return _data(
        api_client.create_cosigner(
            borrower_id, f.create_cosigner_payload(**overrides),
            make_borrower_headers(borrower_id),
        ),
        "POST /borrowers/{id}/cosigners",
    )


def reunderwrite_cosigner(cosigner_id, credit_score, dti_ratio):
    return _data(
        api_client.reunderwrite_cosigner(
            cosigner_id, {"credit_score": credit_score, "dti_ratio": dti_ratio},
            make_cosigner_headers(cosigner_id),
        ),
        "POST /cosigners/{id}/reunderwrite",
    )


# ---------------------------------------------------------------------------
# Tier 2 — origination (borrower -> cosigner -> application)
# ---------------------------------------------------------------------------

def build_origination(
    borrower_score=700,
    borrower_dti=0.24,
    cosigner_score=760,
    cosigner_dti=0.20,
    with_cosigner=True,
    has_cosigner_record=True,
    cosigner_overrides=None,
    reunderwrite=True,
    policy_program_level="UNDERGRADUATE",
    policy_overrides=None,
    school_overrides=None,
    application_overrides=None,
):
    """Create borrower, school, policy, optional cosigner and the application.

    The application advances directly to UNDER_REVIEW and is priced under the
    provisional variant, exactly as the PRD describes for submission.
    """
    reset_clock()
    borrower = create_borrower(
        credit_score=borrower_score, dti_ratio=borrower_dti,
        program_level=policy_program_level,
    )
    school = create_school(**(school_overrides or {}))
    policy = create_policy(
        program_level=policy_program_level, **(policy_overrides or {})
    )
    cosigner = None
    if has_cosigner_record:
        cosigner = invite_cosigner(
            borrower["id"], credit_score=cosigner_score, dti_ratio=cosigner_dti,
            **(cosigner_overrides or {}),
        )
        if reunderwrite:
            cosigner = reunderwrite_cosigner(cosigner["id"], cosigner_score, cosigner_dti)

    application_kwargs = dict(application_overrides or {})
    application = _data(
        api_client.create_application(
            f.create_application_payload(
                borrower["id"], school["id"], policy["id"],
                cosigner_id=cosigner["id"] if (with_cosigner and cosigner) else None,
                **application_kwargs,
            ),
            make_borrower_headers(borrower["id"]),
        ),
        "POST /loan-applications",
    )
    return SimpleNamespace(
        borrower=borrower,
        school=school,
        policy=policy,
        cosigner=cosigner,
        application=application,
        applicant_headers=make_borrower_headers(borrower["id"]),
        cosigner_headers=make_cosigner_headers(cosigner["id"]) if cosigner else None,
        school_headers=make_school_headers(school["id"]),
    )


def add_application(orig, borrower_score=705, borrower_dti=0.22,
                    cosigner_score=None, application_overrides=None):
    """Create another borrower and application against ``orig``'s school and policy.

    Used when a claim needs two applications competing for the same school's
    per-period certification bucket.
    """
    borrower = create_borrower(credit_score=borrower_score, dti_ratio=borrower_dti)
    cosigner = None
    if cosigner_score is not None:
        cosigner = invite_cosigner(borrower["id"], credit_score=cosigner_score,
                                   dti_ratio=0.20)
        cosigner = reunderwrite_cosigner(cosigner["id"], cosigner_score, 0.20)
    application = _data(
        api_client.create_application(
            f.create_application_payload(
                borrower["id"], orig.school["id"], orig.policy["id"],
                cosigner_id=cosigner["id"] if cosigner else None,
                **(application_overrides or {}),
            ),
            make_borrower_headers(borrower["id"]),
        ),
        "POST /loan-applications",
    )
    return SimpleNamespace(
        borrower=borrower,
        school=orig.school,
        policy=orig.policy,
        cosigner=cosigner,
        application=application,
        applicant_headers=make_borrower_headers(borrower["id"]),
        cosigner_headers=make_cosigner_headers(cosigner["id"]) if cosigner else None,
        school_headers=orig.school_headers,
    )


def approve(orig, expected_status=200, fetch_loan=True):
    """Underwrite the application with APPROVE and resolve the created Loan."""
    response = api_client.decide_application(
        orig.application["id"], {"decision": "APPROVE"}, UNDERWRITER
    )
    application = _data(response, "POST /loan-applications/{id}/decision APPROVE")
    orig.application = application
    if fetch_loan:
        loans = _data(
            api_client.list_application_loans(application["id"], UNDERWRITER),
            "GET /loan-applications/{id}/loans",
        )
        if not loans:
            raise AssertionError("Setup failed: approval produced no Loan")
        orig.loan = loans[0]
    return application


def deny(orig):
    response = api_client.decide_application(
        orig.application["id"], {"decision": "DENY"}, UNDERWRITER
    )
    orig.application = _data(response, "POST /loan-applications/{id}/decision DENY")
    return orig.application


# ---------------------------------------------------------------------------
# Tier 3 — certification, disbursement and the in-school lifecycle
# ---------------------------------------------------------------------------

def file_and_certify(
    orig,
    academic_period_label="2026-FALL",
    certified_amount_cents=805000,
    period_end_date="2026-12-20T00:00:00Z",
    certified_enrollment_status="IN_SCHOOL",
):
    """File a certification request then certify it for the full amount."""
    certification = _data(
        api_client.create_certification_request(
            orig.application["id"],
            f.certification_request_payload(
                academic_period_label=academic_period_label,
                certified_amount_cents=certified_amount_cents,
                certified_enrollment_status=certified_enrollment_status,
                period_end_date=period_end_date,
            ),
            orig.school_headers,
        ),
        "POST /loan-applications/{id}/school-certifications",
    )
    _data(
        api_client.certify(
            certification["id"],
            f.certify_payload(
                certified_amount_cents=certified_amount_cents,
                certified_enrollment_status=certified_enrollment_status,
            ),
            orig.school_headers,
        ),
        "POST /school-certifications/{id}/certify",
    )
    # Return the post-certify row: the file response still carried REQUESTED and a
    # zero amount, so callers asserting on the returned object need the certified
    # snapshot (the server is the source of truth for the allocated amount).
    return _data(
        api_client.get_certification(certification["id"], orig.school_headers),
        "GET /school-certifications/{id}",
    )


def file_certification(
    orig,
    academic_period_label="2026-FALL",
    certified_amount_cents=805000,
    period_end_date="2026-12-20T00:00:00Z",
    certified_enrollment_status="IN_SCHOOL",
):
    """File a certification request without certifying it."""
    return _data(
        api_client.create_certification_request(
            orig.application["id"],
            f.certification_request_payload(
                academic_period_label=academic_period_label,
                certified_amount_cents=certified_amount_cents,
                certified_enrollment_status=certified_enrollment_status,
                period_end_date=period_end_date,
            ),
            orig.school_headers,
        ),
        "POST /loan-applications/{id}/school-certifications",
    )


def _loan_version(loan_id, headers=SERVICER):
    return _data(api_client.get_loan(loan_id, headers), "GET /loans/{id}")["version"]


def schedule_disbursement(
    loan_id,
    amount_cents=805000,
    academic_period_label="2026-FALL",
    period_start_date="2026-09-02T00:00:00Z",
    period_end_date="2026-12-20T00:00:00Z",
    scheduled_date="2026-09-15T00:00:00Z",
):
    """Schedule a disbursement against the loan's live version."""
    version = _loan_version(loan_id)
    return _data(
        api_client.schedule_disbursement(
            loan_id,
            f.disbursement_payload(
                academic_period_label=academic_period_label,
                period_start_date=period_start_date,
                period_end_date=period_end_date,
                scheduled_date=scheduled_date,
                amount_cents=amount_cents,
                expected_loan_version=version,
            ),
            SERVICER,
        ),
        "POST /loans/{id}/disbursements",
    )


def release_disbursement(disbursement_id):
    return _data(
        api_client.release_disbursement(disbursement_id, SERVICER),
        "POST /disbursements/{id}/release",
    )


def schedule_and_release(loan_id, **kwargs):
    disbursement = schedule_disbursement(loan_id, **kwargs)
    released = release_disbursement(disbursement["id"])
    return released


def record_enrollment(orig, enrollment_status):
    return _data(
        api_client.record_enrollment_status(
            orig.loan["id"], {"enrollment_status": enrollment_status}, orig.school_headers
        ),
        "POST /loans/{id}/enrollment-status",
    )


def book_accrual(loan_id, window_months=6, entry_date="2026-12-31T00:00:00Z"):
    return _data(
        api_client.create_accrual_entry(
            loan_id, {"entry_date": entry_date, "window_months": window_months}, SERVICER
        ),
        "POST /loans/{id}/accrual-entries",
    )


# Module-level alias so composite helpers whose signature carries a
# ``book_accrual`` boolean flag can still reach the booking helper itself
# without the parameter shadowing the module-level name.
_book_accrual_entry = book_accrual


def submit_standard_plan(loan_id, plan_type="STANDARD", term_months=120):
    version = _loan_version(loan_id)
    return _data(
        api_client.create_repayment_plan(
            loan_id,
            f.repayment_plan_payload(version, plan_type=plan_type, term_months=term_months),
            SERVICER,
        ),
        "POST /loans/{id}/repayment-plans",
    )


def approve_plan(plan_id):
    return _data(
        api_client.approve_plan(plan_id, SERVICER), "POST /repayment-plans/{id}/approve"
    )


def enter_repayment(loan_id):
    return _data(
        api_client.enter_repayment(loan_id, SERVICER), "POST /loans/{id}/enter-repayment"
    )


def generate_payment_schedule(loan_id, periods=30):
    return _data(
        api_client.create_payment_schedule(loan_id, {"periods": periods}, SERVICER),
        "POST /loans/{id}/payment-schedule",
    )


def pay_period(loan_id, due_period_index, clock_iso, paid_date, amount_cents=DEFAULT_PLAN_PAYMENT_CENTS,
               borrower_headers=None):
    """Advance the clock to ``clock_iso`` and record a cleared payment."""
    set_clock(clock_iso)
    return _data(
        api_client.record_payment(
            loan_id,
            f.payment_payload(due_period_index, paid_date, amount_cents=amount_cents),
            borrower_headers or SERVICER,
        ),
        "POST /loans/{id}/payments",
    )


# ---------------------------------------------------------------------------
# Composite fixtures — the shared multi-step preambles
# ---------------------------------------------------------------------------

def setup_certified_loan(
    certified_amount_cents=805000,
    requested_amount_cents=805000,
    cost_of_attendance_cents=900000,
    other_aid_cents=95000,
    academic_period_label="2026-FALL",
    period_end_date="2026-12-20T00:00:00Z",
    disburse=False,
    disbursement_amount_cents=805000,
    interest_accrual_option="DEFERRED",
    borrower_score=700,
    cosigner_score=760,
    policy_program_level="UNDERGRADUATE",
    policy_overrides=None,
    school_overrides=None,
):
    """Approved application with one CERTIFIED period; optionally released too."""
    orig = build_origination(
        borrower_score=borrower_score,
        cosigner_score=cosigner_score,
        policy_program_level=policy_program_level,
        policy_overrides=policy_overrides,
        school_overrides=school_overrides,
        application_overrides={
            "requested_amount_cents": requested_amount_cents,
            "cost_of_attendance_cents": cost_of_attendance_cents,
            "other_aid_cents": other_aid_cents,
            "interest_accrual_option": interest_accrual_option,
        },
    )
    approve(orig)
    orig.certification = file_and_certify(
        orig,
        academic_period_label=academic_period_label,
        certified_amount_cents=certified_amount_cents,
        period_end_date=period_end_date,
    )
    if disburse:
        orig.disbursement = schedule_and_release(
            orig.loan["id"],
            amount_cents=disbursement_amount_cents,
            academic_period_label=academic_period_label,
            period_end_date=period_end_date,
        )
    orig.loan = _data(api_client.get_loan(orig.loan["id"], SERVICER), "GET /loans/{id}")
    return orig


def setup_loan_in_repayment(
    plan_type="STANDARD",
    term_months=120,
    periods=30,
    book_accrual=True,
    interest_accrual_option="DEFERRED",
    requested_amount_cents=805000,
    cost_of_attendance_cents=900000,
    other_aid_cents=95000,
    certified_amount_cents=805000,
    disbursement_amount_cents=805000,
    policy_overrides=None,
    borrower_score=700,
    cosigner_score=760,
):
    """Full in-school lifecycle through GRACE -> REPAYMENT and a payment schedule.

    Sequence mirrors the product exactly: approve -> certify -> disburse ->
    enrollment change to GRADUATED (starts grace) -> accrual -> submit and
    activate a plan -> enter repayment (capitalizes) -> generate the schedule.
    """
    orig = setup_certified_loan(
        certified_amount_cents=certified_amount_cents,
        requested_amount_cents=requested_amount_cents,
        cost_of_attendance_cents=cost_of_attendance_cents,
        other_aid_cents=other_aid_cents,
        disburse=True,
        disbursement_amount_cents=disbursement_amount_cents,
        interest_accrual_option=interest_accrual_option,
        policy_overrides=policy_overrides,
        borrower_score=borrower_score,
        cosigner_score=cosigner_score,
    )
    record_enrollment(orig, "GRADUATED")
    if book_accrual:
        _book_accrual_entry(orig.loan["id"], window_months=6)
    orig.plan = submit_standard_plan(orig.loan["id"], plan_type=plan_type, term_months=term_months)
    approve_plan(orig.plan["id"])
    orig.loan = enter_repayment(orig.loan["id"])
    set_clock(DEFAULT_CLOCK_ISO)
    generate_payment_schedule(orig.loan["id"], periods=periods)
    orig.loan = _data(api_client.get_loan(orig.loan["id"], SERVICER), "GET /loans/{id}")
    return orig


def setup_delinquent_loan(period_1_paid=True, days_past_due=125):
    """Loan in REPAYMENT with period 1 cleared and arrears of ``days_past_due``.

    The clock is placed relative to the server-stamped due date of period 2, so
    the arrears figure is a property of the schedule rather than of an assumed
    calendar.
    """
    orig = setup_loan_in_repayment()
    if period_1_paid:
        pay_period(
            orig.loan["id"], 1, "2026-10-05T00:00:00Z", "2026-10-05T00:00:00Z",
            borrower_headers=orig.applicant_headers,
        )
    due2 = period_due_date(orig.loan["id"], 2)
    set_clock(add_days(due2, days_past_due))
    orig.loan = _data(api_client.get_loan(orig.loan["id"], SERVICER), "GET /loans/{id}")
    return orig


def pay_consecutive_periods(orig, count, start_period=1, start_month=10):
    """Clear ``count`` consecutive periods on time, one calendar month apart."""
    payments = []
    for i in range(count):
        period = start_period + i
        month_index = start_month + i
        year = 2026 + (month_index - 1) // 12
        month = (month_index - 1) % 12 + 1
        iso = f"{year:04d}-{month:02d}-05T00:00:00Z"
        payments.append(
            pay_period(
                orig.loan["id"], period, iso, iso,
                borrower_headers=orig.applicant_headers,
            )
        )
    return payments


def setup_loan_with_qualifying_payments(count, autodebit=False):
    """Loan in REPAYMENT carrying ``count`` consecutive on-time payments."""
    orig = setup_loan_in_repayment(periods=30)
    if autodebit:
        _data(
            api_client.set_autodebit(orig.loan["id"], {"enrolled": True}, orig.applicant_headers),
            "POST /loans/{id}/autodebit",
        )
    orig.payments = pay_consecutive_periods(orig, count)
    orig.loan = _data(api_client.get_loan(orig.loan["id"], SERVICER), "GET /loans/{id}")
    return orig


def setup_loan_with_request_row():
    """The default full preamble: certified, disbursed IN_SCHOOL loan."""
    return setup_certified_loan(disburse=True)