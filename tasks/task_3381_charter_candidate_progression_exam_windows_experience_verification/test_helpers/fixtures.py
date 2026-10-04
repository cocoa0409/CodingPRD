"""Composite setup helpers (fixtures) — multi-step PRD workflows made callable.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch via the public API. Setup calls are validated with
the lenient framework reader; any failure raises AssertionError naming the
step ("Setup failed during ...").

Identity threading: candidate-scoped writes always use
make_candidate_headers(candidate["id"]); reference responses always use
make_reference_provider_headers(reference["id"]) (PRD §2.1 ownership rules).

API MANIFEST (frozen for Phase B) — all functions are plain helpers, not
pytest fixtures:

  Money / calendar helpers:
    expected_charge_cents(list_price_cents, scholarship_pct=0) -> int
      — per-line half-up discounted charge (PRD §2.8 rounding order).

  Clock:
    set_logical_clock(to_iso8601) -> dict

  Single-entity creators (return the created entity dict):
    create_candidate(**overrides)
    create_enrollment_pending(candidate_id, **overrides)       # PENDING_PAYMENT
    pay_enrollment(enrollment_id, amount_cents, as_candidate_id=None) -> dict
    create_enrolled_enrollment(candidate_id, **overrides)      # ENROLLED (fee paid)
    create_exam_level(**overrides)
    create_three_levels(mps_by_level=None, max_attempts=..., early_fee_cents=...,
                        standard_fee_cents=...) -> {"LEVEL_I": ..., "LEVEL_II": ..., "LEVEL_III": ...}
    create_curriculum_cycle(level_id, **overrides)
    create_exam_window(exam_level_id, **overrides)
    create_three_windows(levels) -> {"LEVEL_I": ..., "LEVEL_II": ..., "LEVEL_III": ...}
    create_test_center(**overrides)
    create_society(**overrides)

  Readers (return fresh entity dicts / lists; admin headers by default):
    get_candidate(candidate_id, headers=None)
    get_program_enrollment(enrollment_id, headers=None)
    get_appointment(appointment_id, headers=None)
    get_exam_window(window_id, headers=None)
    get_experience_submission(submission_id, headers=None)
    get_misconduct_case(case_id, headers=None)
    get_membership(membership_id, headers=None)
    list_program_enrollments(params=None, headers=None) -> list
    list_appointments(params=None, headers=None) -> list
    list_exam_attempts(params=None, headers=None) -> list
    list_exam_windows(params=None, headers=None) -> list
    list_curriculum_cycles(params=None, headers=None) -> list
    list_experience_submissions(params=None, headers=None) -> list
    list_references(params=None, headers=None) -> list
    list_misconduct_cases(params=None, headers=None) -> list
    list_memberships(params=None, headers=None) -> list
    get_enrollment_of_candidate(candidate_id) -> dict          # exactly one row
    get_attempt_for_appointment(appointment_id) -> dict        # exactly one row

  Booking/lifecycle composites:
    setup_bookable_context(clock=..., candidate_overrides=None,
                           enrollment_overrides=None, level_overrides=None,
                           window_overrides=None, center_overrides=None,
                           auto_pay=True) -> dict
      — keys: candidate, enrollment, level, window, center,
              candidate_headers, admin_headers, proctor_headers
    book_appointment(context, exam_date=..., calculator_model=...,
                     pay_fee=True, as_admin=False, **payload_overrides) -> dict
    check_in_appointment(appointment, candidate, clock_iso=None,
                         proctor_headers=None) -> (appointment, attempt)
    score_attempt(attempt_id, scaled_score, clock_iso=None, window=None) -> dict
    book_checkin_score(candidate, enrollment, window, center, exam_date,
                       scaled_score, calculator_model=..., pay_fee=True,
                       score_clock=None) -> {"appointment", "attempt"}
    setup_scored_appointment(scaled_score=None, context=None, **context_kwargs)
      -> {**context, "appointment", "attempt"}

  Work experience composites:
    OVERLAPPING_QUALIFYING_SEGMENTS — the canonical 47/41-month segment pair
    create_experience_submission(candidate, segments=None, **overrides) -> dict
    add_reference(submission, candidate, **overrides) -> dict
    verify_reference(reference, **overrides) -> dict
    decline_reference(reference, **overrides) -> dict
    create_submission_with_references(candidate, segments=None,
                                      num_references=2, verify=False)
      -> {"submission", "references"}
    submit_submission(submission, candidate) -> dict
    review_submission(submission, decision="APPROVED", reviewer_user_id="rev-1",
                      **overrides) -> dict
    setup_approved_submission(candidate, segments=None) -> {"submission", "references"}

  Conduct / charter composites:
    file_conduct_statement(candidate, disclosure_year=2027,
                           has_disclosures=False, **overrides) -> dict (Candidate)
    setup_charterholder(conduct_year=2027, award_clock="2027-08-17T00:00:00Z",
                        segments=None, mps_by_level=None) -> dict
      — full chain: candidate ENROLLED, three levels passed, APPROVED
        experience (>= 36 committee months with defaults), PCS filed, charter
        awarded. Keys: candidate, enrollment, levels, windows, center,
        appointments, attempts, submission, references, candidate_headers,
        admin_headers, proctor_headers
    join_society(society, candidate, dues_payment_cents=None) -> dict
    setup_active_membership(society_overrides=None, charterholder_kwargs=None)
      -> {**charterholder, "society", "membership"}

  Misconduct composites:
    open_external_case(candidate_id, allegation=..., investigator_user_id="inv-1") -> dict
    open_incident_case(candidate_id, appointment_id, allegation=...,
                       proctor_user_id="prt-7", origin=None) -> dict
    adjudicate_case(case, outcome="SANCTIONED", sanction_type=None,
                    expected_case_version=None, adjudicator_user_id="adj-1") -> dict
    appeal_case(case, candidate, appeal_reason=...) -> dict
"""
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .constants import PROGRAM_FEE_CENTS
from .factories import DEFAULTS
from .test_users import (
    TEST_USERS,
    make_candidate_headers,
    make_conduct_adjudicator_headers,
    make_conduct_investigator_headers,
    make_experience_reviewer_headers,
    make_proctor_headers,
    make_reference_provider_headers,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_PROCTOR = TEST_USERS["proctor_headers"]

# Canonical three-window calendar used by the full-progression setups. Dates
# satisfy every PRD window constraint (early <= scheduling <= opens;
# reschedule <= closes; half-open, non-overlapping, one per level).
THREE_WINDOWS_SPEC = {
    "LEVEL_I": {
        "window_opens_at": "2027-03-01T00:00:00Z",
        "window_closes_at": "2027-03-15T00:00:00Z",
        "scheduling_deadline_at": "2027-02-20T00:00:00Z",
        "reschedule_deadline_at": "2027-03-08T00:00:00Z",
        "early_fee_deadline_at": "2027-01-31T00:00:00Z",
        "exam_date": "2027-03-03",
        "score_clock": "2027-03-16T00:00:00Z",
    },
    "LEVEL_II": {
        "window_opens_at": "2027-05-03T00:00:00Z",
        "window_closes_at": "2027-05-17T00:00:00Z",
        "scheduling_deadline_at": "2027-04-19T00:00:00Z",
        "reschedule_deadline_at": "2027-04-26T00:00:00Z",
        "early_fee_deadline_at": "2027-03-31T00:00:00Z",
        "exam_date": "2027-05-05",
        "score_clock": "2027-05-18T00:00:00Z",
    },
    "LEVEL_III": {
        "window_opens_at": "2027-08-02T00:00:00Z",
        "window_closes_at": "2027-08-16T00:00:00Z",
        "scheduling_deadline_at": "2027-07-19T00:00:00Z",
        "reschedule_deadline_at": "2027-07-26T00:00:00Z",
        "early_fee_deadline_at": "2027-06-30T00:00:00Z",
        "exam_date": "2027-08-04",
        "score_clock": "2027-08-17T00:00:00Z",
    },
}

DEFAULT_MPS_BY_LEVEL = {"LEVEL_I": 700, "LEVEL_II": 720, "LEVEL_III": 740}

# Canonical overlapping qualifying segment pair: provisional (cumulative)
# months 24 + 23 = 47; committee (interval-merged) months 41 (PRD §3.6 worked
# example), comfortably above the 36-month charter gate.
OVERLAPPING_QUALIFYING_SEGMENTS = [
    {
        "employer_name": "Alpha Asset Management",
        "role_title": "Analyst",
        "start_date": "2022-01-10",
        "end_date": "2024-01-10",
        "qualifying_activity_pct": 80,
        "hours": 4200,
    },
    {
        "employer_name": "Beta Capital",
        "role_title": "Senior Analyst",
        "start_date": "2023-07-10",
        "end_date": "2025-06-10",
        "qualifying_activity_pct": 60,
        "hours": 4000,
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _must(response, what):
    """Lenient-read a setup call; failure aborts the fixture with context."""
    try:
        return get_success_data(response)
    except Exception as exc:
        body = getattr(response, "text", "")
        raise AssertionError(
            f"Setup failed during {what}: HTTP {response.status_code} — {body[:400]}"
        ) from exc


def expected_charge_cents(list_price_cents, scholarship_pct=0) -> int:
    """Per-line charge after scholarship: round_half_up(list * (1 - pct))."""
    raw = Decimal(str(list_price_cents)) * (Decimal("1") - Decimal(str(scholarship_pct)))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_logical_clock(to_iso8601) -> dict:
    return _must(api_client.set_clock(to_iso8601, _ADMIN), f"set clock to {to_iso8601}")


# ---------------------------------------------------------------------------
# Single-entity creators
# ---------------------------------------------------------------------------
def create_candidate(**overrides) -> dict:
    payload = factories.create_candidate_payload(**overrides)
    return _must(api_client.create_candidate(payload, _ADMIN), "create candidate")


def create_enrollment_pending(candidate_id, **overrides) -> dict:
    payload = factories.create_program_enrollment_payload(**overrides)
    return _must(
        api_client.create_program_enrollment(candidate_id, payload, _ADMIN),
        f"create enrollment for candidate {candidate_id}",
    )


def pay_enrollment(enrollment_id, amount_cents, as_candidate_id=None) -> dict:
    """Post a payment; admin by default, or the owning candidate when
    as_candidate_id is given. Returns the updated enrollment."""
    headers = (
        make_candidate_headers(as_candidate_id) if as_candidate_id else _ADMIN
    )
    return _must(
        api_client.post_enrollment_payment(
            enrollment_id, factories.payment_payload(amount_cents), headers
        ),
        f"pay {amount_cents} on enrollment {enrollment_id}",
    )


def create_enrolled_enrollment(candidate_id, **overrides) -> dict:
    """Create an enrollment and pay the (scholarship-adjusted) program fee in
    full, driving PENDING_PAYMENT -> ENROLLED at zero balance."""
    enrollment = create_enrollment_pending(candidate_id, **overrides)
    fee = expected_charge_cents(
        PROGRAM_FEE_CENTS, enrollment.get("scholarship_pct", 0) or 0
    )
    return pay_enrollment(enrollment["id"], fee)


def create_exam_level(**overrides) -> dict:
    payload = factories.create_exam_level_payload(**overrides)
    return _must(api_client.create_exam_level(payload, _ADMIN), "create exam level")


def create_three_levels(
    mps_by_level=None,
    max_attempts=DEFAULTS["MAX_ATTEMPTS"],
    early_fee_cents=DEFAULTS["EARLY_FEE_CENTS"],
    standard_fee_cents=DEFAULTS["STANDARD_FEE_CENTS"],
) -> dict:
    mps = dict(DEFAULT_MPS_BY_LEVEL)
    if mps_by_level:
        mps.update(mps_by_level)
    return {
        code: create_exam_level(
            level_code=code,
            mps_scaled_score=mps[code],
            max_attempts=max_attempts,
            early_fee_cents=early_fee_cents,
            standard_fee_cents=standard_fee_cents,
        )
        for code in ("LEVEL_I", "LEVEL_II", "LEVEL_III")
    }


def create_curriculum_cycle(level_id, **overrides) -> dict:
    payload = factories.create_curriculum_cycle_payload(**overrides)
    return _must(
        api_client.create_curriculum_cycle(level_id, payload, _ADMIN),
        f"create curriculum cycle for level {level_id}",
    )


def create_exam_window(exam_level_id, **overrides) -> dict:
    payload = factories.create_exam_window_payload(exam_level_id, **overrides)
    return _must(api_client.create_exam_window(payload, _ADMIN), "create exam window")


def create_three_windows(levels) -> dict:
    """One canonical window per level (see THREE_WINDOWS_SPEC)."""
    return {
        code: create_exam_window(
            levels[code]["id"],
            **{k: v for k, v in spec.items() if k.endswith("_at")},
        )
        for code, spec in THREE_WINDOWS_SPEC.items()
    }


def create_test_center(**overrides) -> dict:
    payload = factories.create_test_center_payload(**overrides)
    return _must(api_client.create_test_center(payload, _ADMIN), "create test center")


def create_society(**overrides) -> dict:
    payload = factories.create_society_payload(**overrides)
    return _must(api_client.create_society(payload, _ADMIN), "create society")


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def get_candidate(candidate_id, headers=None) -> dict:
    return _must(
        api_client.get_candidate(candidate_id, headers or _ADMIN), "read candidate"
    )


def get_program_enrollment(enrollment_id, headers=None) -> dict:
    return _must(
        api_client.get_program_enrollment(enrollment_id, headers or _ADMIN),
        "read enrollment",
    )


def get_appointment(appointment_id, headers=None) -> dict:
    return _must(
        api_client.get_appointment(appointment_id, headers or _ADMIN), "read appointment"
    )


def get_exam_window(window_id, headers=None) -> dict:
    return _must(
        api_client.get_exam_window(window_id, headers or _ADMIN), "read window"
    )


def get_experience_submission(submission_id, headers=None) -> dict:
    return _must(
        api_client.get_experience_submission(submission_id, headers or _ADMIN),
        "read submission",
    )


def get_misconduct_case(case_id, headers=None) -> dict:
    return _must(
        api_client.get_misconduct_case(case_id, headers or _ADMIN), "read case"
    )


def get_membership(membership_id, headers=None) -> dict:
    return _must(
        api_client.get_membership(membership_id, headers or _ADMIN), "read membership"
    )


def _list(list_fn, params, headers, what):
    return _must(list_fn(headers or _ADMIN, params=params), what)


def list_program_enrollments(params=None, headers=None) -> list:
    return _list(api_client.list_program_enrollments, params, headers, "list enrollments")


def list_appointments(params=None, headers=None) -> list:
    return _list(api_client.list_appointments, params, headers, "list appointments")


def list_exam_attempts(params=None, headers=None) -> list:
    return _list(api_client.list_exam_attempts, params, headers, "list attempts")


def list_exam_windows(params=None, headers=None) -> list:
    return _list(api_client.list_exam_windows, params, headers, "list windows")


def list_curriculum_cycles(params=None, headers=None) -> list:
    return _list(api_client.list_curriculum_cycles, params, headers, "list cycles")


def list_experience_submissions(params=None, headers=None) -> list:
    return _list(api_client.list_experience_submissions, params, headers, "list submissions")


def list_references(params=None, headers=None) -> list:
    return _list(api_client.list_references, params, headers, "list references")


def list_misconduct_cases(params=None, headers=None) -> list:
    return _list(api_client.list_misconduct_cases, params, headers, "list cases")


def list_memberships(params=None, headers=None) -> list:
    return _list(api_client.list_memberships, params, headers, "list memberships")


def get_enrollment_of_candidate(candidate_id) -> dict:
    """Reverse-reach a candidate's single enrollment via the list filter."""
    rows = list_program_enrollments(params={"candidate_id": candidate_id})
    assert len(rows) == 1, (
        f"expected exactly 1 enrollment for candidate {candidate_id}, got {len(rows)}"
    )
    return rows[0]


def get_attempt_for_appointment(appointment_id) -> dict:
    """Fetch the single attempt created by an appointment's check-in."""
    rows = list_exam_attempts(params={"exam_appointment_id": appointment_id})
    assert len(rows) == 1, (
        f"expected exactly 1 attempt for appointment {appointment_id}, got {len(rows)}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# Booking / lifecycle composites
# ---------------------------------------------------------------------------
def setup_bookable_context(
    clock=DEFAULTS["CLOCK_SETUP"],
    candidate_overrides=None,
    enrollment_overrides=None,
    level_overrides=None,
    window_overrides=None,
    center_overrides=None,
    auto_pay=True,
) -> dict:
    """Candidate + enrollment + one LEVEL_I exam level + one OPEN window + one
    test center, with the logical clock at `clock` (inside the EARLY fee tier
    of the default window).

    auto_pay=True pays the program fee so the enrollment is ENROLLED and the
    outstanding balance is zero (booking-ready). Returns a context dict.
    """
    set_logical_clock(clock)
    candidate = create_candidate(**(candidate_overrides or {}))
    if auto_pay:
        enrollment = create_enrolled_enrollment(
            candidate["id"], **(enrollment_overrides or {})
        )
    else:
        enrollment = create_enrollment_pending(
            candidate["id"], **(enrollment_overrides or {})
        )
    level = create_exam_level(**(level_overrides or {}))
    window = create_exam_window(level["id"], **(window_overrides or {}))
    center = create_test_center(**(center_overrides or {}))
    return {
        "candidate": candidate,
        "enrollment": enrollment,
        "level": level,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(candidate["id"]),
        "admin_headers": _ADMIN,
        "proctor_headers": _PROCTOR,
    }


def book_appointment(
    context,
    exam_date=DEFAULTS["EXAM_DATE"],
    calculator_model=DEFAULTS["CALCULATOR_MODEL"],
    pay_fee=True,
    as_admin=False,
    **payload_overrides,
) -> dict:
    """Book an appointment into the context's window/center as the owning
    candidate (or a ProgramAdmin when as_admin=True). pay_fee=True then pays
    the posted exam fee in full so the enrollment returns to zero balance."""
    payload = factories.create_appointment_payload(
        context["enrollment"]["id"],
        context["window"]["id"],
        context["center"]["id"],
        exam_date=exam_date,
        calculator_model=calculator_model,
        **payload_overrides,
    )
    headers = context["admin_headers"] if as_admin else context["candidate_headers"]
    appointment = _must(
        api_client.create_appointment(payload, headers),
        f"book appointment (date {exam_date})",
    )
    if pay_fee:
        pay_enrollment(context["enrollment"]["id"], appointment["exam_fee_cents"])
    return appointment


def check_in_appointment(appointment, candidate, clock_iso=None, proctor_headers=None):
    """Move the clock onto the exam date and check in as Proctor with the
    candidate's registered gov id and declared calculator. Returns the
    (updated appointment, created attempt) pair."""
    exam_date = appointment["exam_date"]
    set_logical_clock(clock_iso or f"{exam_date}T08:00:00Z")
    updated = _must(
        api_client.check_in_appointment(
            appointment["id"],
            factories.check_in_payload(
                candidate["gov_id_number"], appointment["calculator_model"]
            ),
            proctor_headers or _PROCTOR,
        ),
        f"check in appointment {appointment['id']}",
    )
    attempt = get_attempt_for_appointment(appointment["id"])
    return updated, attempt


def score_attempt(attempt_id, scaled_score, clock_iso=None, window=None) -> dict:
    """Score an attempt. The clock must be at or past the window's close; pass
    clock_iso explicitly, or pass window= and the close instant is used."""
    if clock_iso is None:
        assert window is not None, "score_attempt needs clock_iso or window="
        clock_iso = window["window_closes_at"]
    set_logical_clock(clock_iso)
    return _must(
        api_client.score_exam_attempt(
            attempt_id, factories.score_payload(scaled_score), _ADMIN
        ),
        f"score attempt {attempt_id}",
    )


def book_checkin_score(
    candidate,
    enrollment,
    window,
    center,
    exam_date,
    scaled_score,
    calculator_model=DEFAULTS["CALCULATOR_MODEL"],
    pay_fee=True,
    score_clock=None,
) -> dict:
    """Full single-level pass/fail chain: book (as the candidate) -> optional
    fee payment -> clock to exam day -> check-in -> clock to window close ->
    score. Returns {"appointment": ..., "attempt": ...} (attempt post-score)."""
    context = {
        "candidate": candidate,
        "enrollment": enrollment,
        "window": window,
        "center": center,
        "candidate_headers": make_candidate_headers(candidate["id"]),
        "admin_headers": _ADMIN,
        "proctor_headers": _PROCTOR,
    }
    appointment = book_appointment(
        context,
        exam_date=exam_date,
        calculator_model=calculator_model,
        pay_fee=pay_fee,
    )
    _, attempt = check_in_appointment(appointment, candidate)
    scored = score_attempt(
        attempt["id"],
        scaled_score,
        clock_iso=score_clock or window["window_closes_at"],
    )
    return {"appointment": get_appointment(appointment["id"]), "attempt": scored}


def setup_scored_appointment(scaled_score=None, context=None, **context_kwargs) -> dict:
    """Bookable context plus one checked-in, scored appointment. Defaults to a
    boundary PASS at the level's MPS. Returns {**context, appointment, attempt}."""
    context = context or setup_bookable_context(**context_kwargs)
    score = (
        scaled_score if scaled_score is not None else context["level"]["mps_scaled_score"]
    )
    result = book_checkin_score(
        context["candidate"],
        context["enrollment"],
        context["window"],
        context["center"],
        exam_date=DEFAULTS["EXAM_DATE"],
        scaled_score=score,
    )
    return {**context, **result}


# ---------------------------------------------------------------------------
# Work experience composites
# ---------------------------------------------------------------------------
def create_experience_submission(candidate, segments=None, **overrides) -> dict:
    payload = factories.create_experience_submission_payload(
        segments=segments, **overrides
    )
    return _must(
        api_client.create_experience_submission(
            candidate["id"], payload, make_candidate_headers(candidate["id"])
        ),
        "create experience submission",
    )


def add_reference(submission, candidate, **overrides) -> dict:
    payload = factories.create_reference_payload(**overrides)
    return _must(
        api_client.create_reference(
            submission["id"], payload, make_candidate_headers(candidate["id"])
        ),
        f"attach reference to submission {submission['id']}",
    )


def verify_reference(reference, **overrides) -> dict:
    """The reference answers for itself: X-User-ID == the reference's own id."""
    payload = factories.respond_reference_payload(decision="VERIFIED", **overrides)
    return _must(
        api_client.respond_reference(
            reference["id"], payload, make_reference_provider_headers(reference["id"])
        ),
        f"verify reference {reference['id']}",
    )


def decline_reference(reference, **overrides) -> dict:
    payload = factories.respond_reference_payload(decision="DECLINED", **overrides)
    return _must(
        api_client.respond_reference(
            reference["id"], payload, make_reference_provider_headers(reference["id"])
        ),
        f"decline reference {reference['id']}",
    )


def create_submission_with_references(
    candidate, segments=None, num_references=2, verify=False
) -> dict:
    """DRAFT submission with `num_references` attached PENDING references
    (VERIFIED instead when verify=True)."""
    submission = create_experience_submission(candidate, segments=segments)
    references = []
    for index in range(num_references):
        reference = add_reference(
            submission,
            candidate,
            referee_name=f"Ref {index + 1}",
            referee_email=f"ref{index + 1}@example.com",
        )
        if verify:
            reference = verify_reference(reference)
        references.append(reference)
    return {"submission": submission, "references": references}


def submit_submission(submission, candidate) -> dict:
    return _must(
        api_client.submit_experience_submission(
            submission["id"], make_candidate_headers(candidate["id"])
        ),
        f"submit submission {submission['id']}",
    )


def review_submission(submission, decision="APPROVED", reviewer_user_id="rev-1", **overrides) -> dict:
    payload = factories.review_submission_payload(decision=decision, **overrides)
    return _must(
        api_client.review_experience_submission(
            submission["id"],
            payload,
            make_experience_reviewer_headers(reviewer_user_id),
        ),
        f"review submission {submission['id']} ({decision})",
    )


def setup_approved_submission(candidate, segments=None) -> dict:
    """Submission with two VERIFIED references, submitted and APPROVED. With
    the default OVERLAPPING_QUALIFYING_SEGMENTS the committee figure is 41
    months (>= the 36-month charter gate)."""
    bundle = create_submission_with_references(
        candidate, segments=segments or OVERLAPPING_QUALIFYING_SEGMENTS, verify=True
    )
    submitted = submit_submission(bundle["submission"], candidate)
    approved = review_submission(submitted, decision="APPROVED")
    return {"submission": approved, "references": bundle["references"]}


# ---------------------------------------------------------------------------
# Conduct statements, charter award, societies
# ---------------------------------------------------------------------------
def file_conduct_statement(candidate, disclosure_year=2027, has_disclosures=False, **overrides) -> dict:
    """File a PCS; returns the updated Candidate. For the award gate the
    disclosure_year must equal the logical clock's current calendar year."""
    payload = factories.conduct_statement_payload(
        disclosure_year, has_disclosures=has_disclosures, **overrides
    )
    return _must(
        api_client.file_conduct_statement(
            candidate["id"], payload, make_candidate_headers(candidate["id"])
        ),
        f"file conduct statement {disclosure_year}",
    )


def award_charter(enrollment_id) -> dict:
    return _must(
        api_client.award_charter(enrollment_id, _ADMIN),
        f"award charter on enrollment {enrollment_id}",
    )


def setup_charterholder(
    conduct_year=2027,
    award_clock="2027-08-17T00:00:00Z",
    segments=None,
    mps_by_level=None,
) -> dict:
    """Full progression chain to a chartered candidate:

    clock 2027-01-05 -> candidate -> ENROLLED enrollment -> three levels with
    canonical windows -> each level booked EARLY, fee paid, checked in on exam
    day, scored exactly at its MPS (PASS) once the window closed -> APPROVED
    experience submission (>= 36 committee months) -> PCS for `conduct_year`
    -> award-charter at `award_clock` (which must lie within `conduct_year`).

    Returns a dict with candidate, enrollment (post-award), levels, windows,
    center, appointments, attempts (keyed by level code), submission,
    references, and the three standard header sets.
    """
    set_logical_clock(DEFAULTS["CLOCK_SETUP"])
    candidate = create_candidate()
    enrollment = create_enrolled_enrollment(candidate["id"])
    levels = create_three_levels(mps_by_level=mps_by_level)
    windows = create_three_windows(levels)
    center = create_test_center()

    appointments = {}
    attempts = {}
    for code in ("LEVEL_I", "LEVEL_II", "LEVEL_III"):
        spec = THREE_WINDOWS_SPEC[code]
        result = book_checkin_score(
            candidate,
            enrollment,
            windows[code],
            center,
            exam_date=spec["exam_date"],
            scaled_score=levels[code]["mps_scaled_score"],
            score_clock=spec["score_clock"],
        )
        appointments[code] = result["appointment"]
        attempts[code] = result["attempt"]

    set_logical_clock(award_clock)
    experience = setup_approved_submission(candidate, segments=segments)
    file_conduct_statement(candidate, disclosure_year=conduct_year)
    awarded = award_charter(enrollment["id"])

    return {
        "candidate": get_candidate(candidate["id"]),
        "enrollment": awarded,
        "levels": levels,
        "windows": windows,
        "center": center,
        "appointments": appointments,
        "attempts": attempts,
        "submission": experience["submission"],
        "references": experience["references"],
        "candidate_headers": make_candidate_headers(candidate["id"]),
        "admin_headers": _ADMIN,
        "proctor_headers": _PROCTOR,
    }


def join_society(society, candidate, dues_payment_cents=None) -> dict:
    dues = (
        dues_payment_cents
        if dues_payment_cents is not None
        else society["annual_dues_cents"]
    )
    return _must(
        api_client.create_membership(
            society["id"],
            factories.join_society_payload(candidate["id"], dues),
            make_candidate_headers(candidate["id"]),
        ),
        f"join society {society['id']}",
    )


def setup_active_membership(society_overrides=None, charterholder_kwargs=None) -> dict:
    """Charterholder + society + ACTIVE membership joined at exact dues.
    Returns {**charterholder_context, "society", "membership"}."""
    context = setup_charterholder(**(charterholder_kwargs or {}))
    society = create_society(**(society_overrides or {}))
    membership = join_society(society, context["candidate"])
    return {**context, "society": society, "membership": membership}


# ---------------------------------------------------------------------------
# Misconduct composites
# ---------------------------------------------------------------------------
def open_external_case(candidate_id, allegation=DEFAULTS["ALLEGATION"], investigator_user_id="inv-1") -> dict:
    """Manual case with no appointment (origin EXTERNAL_REPORT)."""
    payload = factories.create_misconduct_case_payload(candidate_id, allegation=allegation)
    return _must(
        api_client.create_misconduct_case(
            payload, make_conduct_investigator_headers(investigator_user_id)
        ),
        "open external misconduct case",
    )


def open_incident_case(
    candidate_id,
    appointment_id,
    allegation="Suspected unauthorized notes",
    proctor_user_id="prt-7",
    origin=None,
) -> dict:
    """Appointment-linked case filed by a Proctor (origin EXAM_INCIDENT; also
    flags the appointment's compliance dimension)."""
    overrides = {"appointment_id": appointment_id}
    if origin is not None:
        overrides["origin"] = origin
    payload = factories.create_misconduct_case_payload(
        candidate_id, allegation=allegation, **overrides
    )
    return _must(
        api_client.create_misconduct_case(
            payload, make_proctor_headers(proctor_user_id)
        ),
        "open exam-incident misconduct case",
    )


def adjudicate_case(
    case,
    outcome="SANCTIONED",
    sanction_type=None,
    expected_case_version=None,
    adjudicator_user_id="adj-1",
) -> dict:
    """Adjudicate a case as a ConductAdjudicator whose id differs from the
    case's investigator (pass a distinct adjudicator_user_id as needed)."""
    version = (
        expected_case_version if expected_case_version is not None else case["version"]
    )
    payload = factories.adjudicate_case_payload(
        expected_case_version=version, outcome=outcome, sanction_type=sanction_type
    )
    return _must(
        api_client.adjudicate_misconduct_case(
            case["id"], payload, make_conduct_adjudicator_headers(adjudicator_user_id)
        ),
        f"adjudicate case {case['id']} ({outcome})",
    )


def appeal_case(case, candidate, appeal_reason=DEFAULTS["APPEAL_REASON"]) -> dict:
    return _must(
        api_client.appeal_misconduct_case(
            case["id"],
            factories.appeal_case_payload(appeal_reason),
            make_candidate_headers(candidate["id"]),
        ),
        f"appeal case {case['id']}",
    )


__all__ = [
    "THREE_WINDOWS_SPEC",
    "DEFAULT_MPS_BY_LEVEL",
    "OVERLAPPING_QUALIFYING_SEGMENTS",
    "expected_charge_cents",
    "set_logical_clock",
    "create_candidate",
    "create_enrollment_pending",
    "pay_enrollment",
    "create_enrolled_enrollment",
    "create_exam_level",
    "create_three_levels",
    "create_curriculum_cycle",
    "create_exam_window",
    "create_three_windows",
    "create_test_center",
    "create_society",
    "get_candidate",
    "get_program_enrollment",
    "get_appointment",
    "get_exam_window",
    "get_experience_submission",
    "get_misconduct_case",
    "get_membership",
    "list_program_enrollments",
    "list_appointments",
    "list_exam_attempts",
    "list_exam_windows",
    "list_curriculum_cycles",
    "list_experience_submissions",
    "list_references",
    "list_misconduct_cases",
    "list_memberships",
    "get_enrollment_of_candidate",
    "get_attempt_for_appointment",
    "setup_bookable_context",
    "book_appointment",
    "check_in_appointment",
    "score_attempt",
    "book_checkin_score",
    "setup_scored_appointment",
    "create_experience_submission",
    "add_reference",
    "verify_reference",
    "decline_reference",
    "create_submission_with_references",
    "submit_submission",
    "review_submission",
    "setup_approved_submission",
    "file_conduct_statement",
    "award_charter",
    "setup_charterholder",
    "join_society",
    "setup_active_membership",
    "open_external_case",
    "open_incident_case",
    "adjudicate_case",
    "appeal_case",
]
