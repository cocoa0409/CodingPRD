"""Payload factories — one per entity, input (client-supplied) fields only.

The DEFAULTS below are scenario conveniences (canonical fixture values shared
by the test setups), not PRD constants: PRD pins only shapes and ranges (e.g.
early_fee_cents > 0, standard_fee_cents >= early_fee_cents, mps 0..1000,
max_attempts 1..10, scholarship_pct 0..0.5, annual_dues_cents > 0).

API MANIFEST (frozen for Phase B):
  DEFAULTS: dict — canonical scenario values (WINDOW_*, LEVEL fees/MPS, etc.)

  Payload builders (each returns a plain dict ready for the matching
  ApiClient method; **overrides are merged last):
    set_clock_payload(to_iso8601)
    create_candidate_payload(**overrides)
    create_program_enrollment_payload(pathway="EDUCATION", **overrides)
      — fills the pathway-conditional required fields per branch
        (EDUCATION: degree_completed + graduation_date;
         WORK_EXPERIENCE: declared_work_months + declared_work_hours)
    payment_payload(amount_cents, **overrides)
    create_exam_level_payload(**overrides)
    create_curriculum_cycle_payload(**overrides)
    create_exam_window_payload(exam_level_id, **overrides)
      — remaining window fields default to the canonical WINDOW_* values
    create_test_center_payload(**overrides)
    create_appointment_payload(program_enrollment_id, exam_window_id,
                               test_center_id, **overrides)
    reschedule_appointment_payload(expected_appointment_version, **changes)
      — changes subset of {exam_window_id, test_center_id, exam_date,
        calculator_model}
    check_in_payload(identity_document_number, actual_calculator_model)
    score_payload(scaled_score)
    experience_segment(**overrides) -> dict
    create_experience_submission_payload(segments=None, **overrides)
    amend_submission_payload(segments, expected_submission_version)
    review_submission_payload(decision="APPROVED", **overrides)
    create_reference_payload(**overrides)
    respond_reference_payload(decision="VERIFIED", **overrides)
    conduct_statement_payload(disclosure_year, has_disclosures=False, **overrides)
    create_misconduct_case_payload(candidate_id, allegation=..., **overrides)
    adjudicate_case_payload(expected_case_version, outcome="SANCTIONED",
                            sanction_type=None, **overrides)
      — includes sanction_type only when given
    appeal_case_payload(appeal_reason, **overrides)
    create_society_payload(**overrides)
    join_society_payload(candidate_id, dues_payment_cents)
    renew_membership_payload(dues_payment_cents)
    ce_record_payload(**overrides)
"""

# Canonical scenario values shared across the test setups. PRD-consistent but
# not PRD-pinned (they are request inputs, not contract constants).
DEFAULTS = {
    # Logical clock landing point used by the standard setups (chosen so the
    # default window below books at the EARLY tier).
    "CLOCK_SETUP": "2027-01-05T00:00:00Z",
    # Candidate A identity.
    "CANDIDATE_EMAIL": "a.cand@example.com",
    "CANDIDATE_FULL_NAME": "A Candidate",
    "CANDIDATE_DATE_OF_BIRTH": "1995-04-12",
    "CANDIDATE_GOV_ID": "GOV-A-1001",
    # Enrollment defaults (EDUCATION branch).
    "PATHWAY": "EDUCATION",
    "DEGREE_COMPLETED": True,
    "GRADUATION_DATE": "2023-05-15",
    # WORK_EXPERIENCE branch defaults (>= 36 months AND >= 4000 hours).
    "DECLARED_WORK_MONTHS": 48,
    "DECLARED_WORK_HOURS": 6000,
    # Exam level fee card / thresholds.
    "LEVEL_CODE": "LEVEL_I",
    "MPS_SCALED_SCORE": 700,
    "MAX_ATTEMPTS": 6,
    "EARLY_FEE_CENTS": 94000,
    "STANDARD_FEE_CENTS": 125000,
    # Canonical exam window shape: [2027-03-01, 2027-03-15) with the three
    # deadlines inside their PRD ordering constraints.
    "WINDOW_OPENS_AT": "2027-03-01T00:00:00Z",
    "WINDOW_CLOSES_AT": "2027-03-15T00:00:00Z",
    "WINDOW_SCHEDULING_DEADLINE_AT": "2027-02-20T00:00:00Z",
    "WINDOW_RESCHEDULE_DEADLINE_AT": "2027-03-08T00:00:00Z",
    "WINDOW_EARLY_FEE_DEADLINE_AT": "2027-01-31T00:00:00Z",
    # Exam day inside the canonical window; scoring happens the day after close.
    "EXAM_DATE": "2027-03-03",
    # Test center.
    "CENTER_NAME": "Metro Center",
    "CENTER_CITY": "Metropolis",
    "CENTER_CAPACITY": 2,
    # Appointment.
    "CALCULATOR_MODEL": "TI_BA_II_PLUS",
    # Curriculum cycle.
    "CYCLE_YEAR": 2027,
    "CYCLE_EFFECTIVE_FROM": "2027-01-01T00:00:00Z",
    "CYCLE_EFFECTIVE_TO": "2028-01-01T00:00:00Z",
    "CYCLE_CONTENT_VERSION": "L1-2027",
    # Experience submission: single 12-month qualifying segment.
    "SEGMENT": {
        "employer_name": "Alpha Asset Management",
        "role_title": "Analyst",
        "start_date": "2023-01-05",
        "end_date": "2024-01-05",
        "qualifying_activity_pct": 80,
        "hours": 2100,
    },
    # References.
    "REFEREE_NAME_1": "Ref One",
    "REFEREE_EMAIL_1": "ref1@example.com",
    "REFEREE_NAME_2": "Ref Two",
    "REFEREE_EMAIL_2": "ref2@example.com",
    # Misconduct.
    "ALLEGATION": "External report of credential misrepresentation",
    "APPEAL_REASON": "New evidence from employer",
    # Society.
    "SOCIETY_CODE": "NYSSA-EX",
    "SOCIETY_NAME": "Example Society",
    "SOCIETY_REGION": "NY",
    "SOCIETY_ANNUAL_DUES_CENTS": 27500,
    "SOCIETY_CE_CREDITS_REQUIRED": 20,
    # CE record.
    "CE_ACTIVITY_TITLE": "Ethics webinar",
    "CE_CREDIT_HOURS": 5,
    "CE_COMPLETED_ON": "2027-03-10",
}


def set_clock_payload(to_iso8601):
    return {"to_iso8601": to_iso8601}


def create_candidate_payload(**overrides):
    payload = {
        "email": DEFAULTS["CANDIDATE_EMAIL"],
        "full_name": DEFAULTS["CANDIDATE_FULL_NAME"],
        "date_of_birth": DEFAULTS["CANDIDATE_DATE_OF_BIRTH"],
        "gov_id_number": DEFAULTS["CANDIDATE_GOV_ID"],
    }
    payload.update(overrides)
    return payload


def create_program_enrollment_payload(pathway=DEFAULTS["PATHWAY"], **overrides):
    """Enrollment payload; fills exactly the pathway-conditional fields the PRD
    requires for the chosen pathway (education: degree_completed +
    graduation_date; work experience: declared_work_months +
    declared_work_hours)."""
    payload = {"pathway": pathway}
    if pathway == "EDUCATION":
        payload["degree_completed"] = DEFAULTS["DEGREE_COMPLETED"]
        payload["graduation_date"] = DEFAULTS["GRADUATION_DATE"]
    elif pathway == "WORK_EXPERIENCE":
        payload["declared_work_months"] = DEFAULTS["DECLARED_WORK_MONTHS"]
        payload["declared_work_hours"] = DEFAULTS["DECLARED_WORK_HOURS"]
    payload.update(overrides)
    return payload


def payment_payload(amount_cents, **overrides):
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_exam_level_payload(**overrides):
    payload = {
        "level_code": DEFAULTS["LEVEL_CODE"],
        "mps_scaled_score": DEFAULTS["MPS_SCALED_SCORE"],
        "max_attempts": DEFAULTS["MAX_ATTEMPTS"],
        "early_fee_cents": DEFAULTS["EARLY_FEE_CENTS"],
        "standard_fee_cents": DEFAULTS["STANDARD_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_curriculum_cycle_payload(**overrides):
    payload = {
        "cycle_year": DEFAULTS["CYCLE_YEAR"],
        "effective_from": DEFAULTS["CYCLE_EFFECTIVE_FROM"],
        "effective_to": DEFAULTS["CYCLE_EFFECTIVE_TO"],
        "content_version": DEFAULTS["CYCLE_CONTENT_VERSION"],
    }
    payload.update(overrides)
    return payload


def create_exam_window_payload(exam_level_id, **overrides):
    payload = {
        "exam_level_id": exam_level_id,
        "window_opens_at": DEFAULTS["WINDOW_OPENS_AT"],
        "window_closes_at": DEFAULTS["WINDOW_CLOSES_AT"],
        "scheduling_deadline_at": DEFAULTS["WINDOW_SCHEDULING_DEADLINE_AT"],
        "reschedule_deadline_at": DEFAULTS["WINDOW_RESCHEDULE_DEADLINE_AT"],
        "early_fee_deadline_at": DEFAULTS["WINDOW_EARLY_FEE_DEADLINE_AT"],
    }
    payload.update(overrides)
    return payload


def create_test_center_payload(**overrides):
    payload = {
        "name": DEFAULTS["CENTER_NAME"],
        "city": DEFAULTS["CENTER_CITY"],
        "daily_seat_capacity": DEFAULTS["CENTER_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(
    program_enrollment_id, exam_window_id, test_center_id, **overrides
):
    payload = {
        "program_enrollment_id": program_enrollment_id,
        "exam_window_id": exam_window_id,
        "test_center_id": test_center_id,
        "exam_date": DEFAULTS["EXAM_DATE"],
        "calculator_model": DEFAULTS["CALCULATOR_MODEL"],
    }
    payload.update(overrides)
    return payload


def reschedule_appointment_payload(expected_appointment_version, **changes):
    """Reschedule payload; `changes` is the subset of exam_window_id /
    test_center_id / exam_date / calculator_model being superseded (at least
    one required by the PRD)."""
    payload = {"expected_appointment_version": expected_appointment_version}
    payload.update(changes)
    return payload


def check_in_payload(identity_document_number, actual_calculator_model):
    return {
        "identity_document_number": identity_document_number,
        "actual_calculator_model": actual_calculator_model,
    }


def score_payload(scaled_score):
    return {"scaled_score": scaled_score}


def experience_segment(**overrides):
    segment = dict(DEFAULTS["SEGMENT"])
    segment.update(overrides)
    return segment


def create_experience_submission_payload(segments=None, **overrides):
    payload = {"segments": segments if segments is not None else [experience_segment()]}
    payload.update(overrides)
    return payload


def amend_submission_payload(segments, expected_submission_version):
    return {
        "segments": segments,
        "expected_submission_version": expected_submission_version,
    }


def review_submission_payload(decision="APPROVED", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_reference_payload(**overrides):
    payload = {
        "referee_name": DEFAULTS["REFEREE_NAME_1"],
        "referee_email": DEFAULTS["REFEREE_EMAIL_1"],
    }
    payload.update(overrides)
    return payload


def respond_reference_payload(decision="VERIFIED", **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def conduct_statement_payload(disclosure_year, has_disclosures=False, **overrides):
    payload = {"disclosure_year": disclosure_year, "has_disclosures": has_disclosures}
    payload.update(overrides)
    return payload


def create_misconduct_case_payload(candidate_id, allegation=DEFAULTS["ALLEGATION"], **overrides):
    payload = {"candidate_id": candidate_id, "allegation": allegation}
    payload.update(overrides)
    return payload


def adjudicate_case_payload(
    expected_case_version, outcome="SANCTIONED", sanction_type=None, **overrides
):
    """Adjudication payload; sanction_type is included only when given (the PRD
    requires it exactly when outcome is SANCTIONED)."""
    payload = {"outcome": outcome, "expected_case_version": expected_case_version}
    if sanction_type is not None:
        payload["sanction_type"] = sanction_type
    payload.update(overrides)
    return payload


def appeal_case_payload(appeal_reason=DEFAULTS["APPEAL_REASON"], **overrides):
    payload = {"appeal_reason": appeal_reason}
    payload.update(overrides)
    return payload


def create_society_payload(**overrides):
    payload = {
        "society_code": DEFAULTS["SOCIETY_CODE"],
        "name": DEFAULTS["SOCIETY_NAME"],
        "region": DEFAULTS["SOCIETY_REGION"],
        "annual_dues_cents": DEFAULTS["SOCIETY_ANNUAL_DUES_CENTS"],
        "ce_credits_required_per_year": DEFAULTS["SOCIETY_CE_CREDITS_REQUIRED"],
    }
    payload.update(overrides)
    return payload


def join_society_payload(candidate_id, dues_payment_cents):
    return {"candidate_id": candidate_id, "dues_payment_cents": dues_payment_cents}


def renew_membership_payload(dues_payment_cents):
    return {"dues_payment_cents": dues_payment_cents}


def ce_record_payload(**overrides):
    payload = {
        "activity_title": DEFAULTS["CE_ACTIVITY_TITLE"],
        "credit_hours": DEFAULTS["CE_CREDIT_HOURS"],
        "completed_on": DEFAULTS["CE_COMPLETED_ON"],
    }
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULTS",
    "set_clock_payload",
    "create_candidate_payload",
    "create_program_enrollment_payload",
    "payment_payload",
    "create_exam_level_payload",
    "create_curriculum_cycle_payload",
    "create_exam_window_payload",
    "create_test_center_payload",
    "create_appointment_payload",
    "reschedule_appointment_payload",
    "check_in_payload",
    "score_payload",
    "experience_segment",
    "create_experience_submission_payload",
    "amend_submission_payload",
    "review_submission_payload",
    "create_reference_payload",
    "respond_reference_payload",
    "conduct_statement_payload",
    "create_misconduct_case_payload",
    "adjudicate_case_payload",
    "appeal_case_payload",
    "create_society_payload",
    "join_society_payload",
    "renew_membership_payload",
    "ce_record_payload",
]
