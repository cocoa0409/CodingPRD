"""Request payload builders.

Every builder starts from a valid default payload and applies the caller's
overrides, so a test states only the field it is exercising. Money is always a
Python ``int`` of whole cents so that it travels as a JSON integer; instants are
always full ISO 8601 UTC instants and plain dates are always ``YYYY-MM-DD``.

Passing ``None`` for an optional field removes it from the payload entirely,
which is how a test asks for the programme default rather than an explicit null.
"""

import itertools

from .constants import (
    DEFAULT_ACCEPTANCE_DEADLINE_DAYS,
    DEFAULT_ADMIN_FEE_PCT,
    DEFAULT_BASE_AWARD_CENTS,
    DEFAULT_MIN_ASSESSMENT_PERCENTILE,
    DEFAULT_MIN_PORTFOLIO_ARTIFACTS,
    DEFAULT_ROLLOVER_CAP_PCT,
)

_ein_counter = itertools.count(1)
_invoice_counter = itertools.count(1)
_household_counter = itertools.count(1)


def unique_ein():
    """A nine-digit employer identification number unique within one test run."""
    return "75%07d" % next(_ein_counter)


def unique_invoice_reference():
    """A vendor invoice identifier unique within one test run."""
    return "INV-%05d" % next(_invoice_counter)


def unique_household_id():
    """An opaque household grouping key unique within one test run."""
    return "HH-%d" % next(_household_counter)


def _merged(defaults, overrides):
    """Apply overrides, dropping any field whose override is ``None``."""
    payload = dict(defaults)
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- Programme year --------------------------------------------------------------

PROGRAM_YEAR_DEFAULTS = {
    "label": "2026-27",
    "residency_state": "TX",
    "total_seats": 2,
    "window_open_at": "2026-08-15T00:00:00Z",
    "window_close_at": "2026-09-30T23:59:59Z",
    "term_start_date": "2026-08-01",
    "term_end_date": "2027-06-30",
    "base_award_cents": DEFAULT_BASE_AWARD_CENTS,
    "rollover_cap_pct": DEFAULT_ROLLOVER_CAP_PCT,
    "admin_fee_pct": DEFAULT_ADMIN_FEE_PCT,
    "acceptance_deadline_days": DEFAULT_ACCEPTANCE_DEADLINE_DAYS,
    "min_assessment_percentile": DEFAULT_MIN_ASSESSMENT_PERCENTILE,
    "min_portfolio_artifacts": DEFAULT_MIN_PORTFOLIO_ARTIFACTS,
}

NEXT_PROGRAM_YEAR_DEFAULTS = {
    "label": "2027-28",
    "residency_state": "TX",
    "total_seats": 2,
    "window_open_at": "2027-08-15T00:00:00Z",
    "window_close_at": "2027-09-30T23:59:59Z",
    "term_start_date": "2027-08-01",
    "term_end_date": "2028-06-30",
    "base_award_cents": DEFAULT_BASE_AWARD_CENTS,
    "rollover_cap_pct": DEFAULT_ROLLOVER_CAP_PCT,
    "admin_fee_pct": DEFAULT_ADMIN_FEE_PCT,
    "acceptance_deadline_days": DEFAULT_ACCEPTANCE_DEADLINE_DAYS,
    "min_assessment_percentile": DEFAULT_MIN_ASSESSMENT_PERCENTILE,
    "min_portfolio_artifacts": DEFAULT_MIN_PORTFOLIO_ARTIFACTS,
}


def create_program_year_payload(**overrides):
    """The canonical 2026-27 Texas award year with two seats."""
    return _merged(PROGRAM_YEAR_DEFAULTS, overrides)


def create_next_program_year_payload(**overrides):
    """A successor 2027-28 year whose instructional term follows the first."""
    return _merged(NEXT_PROGRAM_YEAR_DEFAULTS, overrides)


def create_program_year_payload_defaults_omitted(**overrides):
    """A programme year that supplies only the mandatory inputs.

    The six optional award parameters are left out entirely so that the server
    has to apply the programme defaults.
    """
    payload = {
        "label": "2026-27-defaults",
        "residency_state": "TX",
        "total_seats": 3,
        "window_open_at": "2026-08-15T00:00:00Z",
        "window_close_at": "2026-09-30T23:59:59Z",
        "term_start_date": "2026-08-01",
        "term_end_date": "2027-06-30",
    }
    return _merged(payload, overrides)


# --- Expense catalogue -----------------------------------------------------------

TUTORING_CATEGORY = {
    "code": "TUTORING",
    "name": "Tutoring services",
    "per_year_cap_cents": 200000,
    "allowable": True,
    "requires_preapproval": True,
    "requires_service_period": True,
}

MATERIALS_CATEGORY = {
    "code": "MATERIALS",
    "name": "Curriculum materials",
    "per_year_cap_cents": 300000,
    "allowable": True,
    "requires_preapproval": False,
    "requires_service_period": False,
}

TUITION_CATEGORY = {
    "code": "TUITION",
    "name": "Private school tuition",
    "per_year_cap_cents": 500000,
    "allowable": True,
    "requires_preapproval": True,
    "requires_service_period": False,
}

FIELD_TRIPS_CATEGORY = {
    "code": "FIELD_TRIPS",
    "name": "Field trips",
    "per_year_cap_cents": 100000,
    "allowable": False,
    "requires_preapproval": True,
    "requires_service_period": False,
}


def create_tutoring_category_payload(**overrides):
    """A pre-approval-only category that switches on the service-interval rule."""
    return _merged(TUTORING_CATEGORY, overrides)


def create_materials_category_payload(**overrides):
    """A reimbursement-friendly category exempt from the service-interval rule."""
    return _merged(MATERIALS_CATEGORY, overrides)


def create_tuition_category_payload(**overrides):
    """A pre-approval-only category exempt from the service-interval rule."""
    return _merged(TUITION_CATEGORY, overrides)


def create_field_trips_category_payload(**overrides):
    """A catalogued-but-disallowed category."""
    return _merged(FIELD_TRIPS_CATEGORY, overrides)


# --- Students --------------------------------------------------------------------

STUDENT_DEFAULTS = {
    "household_id": "HH-1",
    "first_name": "Ana",
    "last_name": "Reyes",
    "date_of_birth": "2014-04-02",
    "residency_state": "TX",
    "prior_enrollment": "PUBLIC_SCHOOL_FULL_YEAR",
    "income_band": "BAND_B",
    "category_flags": ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
    "has_enrolled_sibling": False,
}


def create_student_payload(**overrides):
    """The canonical Texas student with a disability and prior public schooling."""
    return _merged(STUDENT_DEFAULTS, overrides)


# --- Applications ----------------------------------------------------------------


def create_application_payload(program_year_id, student_id, **overrides):
    """A guardian's claimed-attribute application for one student and year."""
    payload = {
        "program_year_id": str(program_year_id),
        "student_id": str(student_id),
        "claimed_income_band": "BAND_B",
        "claimed_category_flags": ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
    }
    return _merged(payload, overrides)


def create_determination_payload(**overrides):
    """A clean verified determination: both checks pass, one confirmed flag."""
    payload = {
        "residency_check": "PASS",
        "prior_enrollment_check": "PASS",
        "verified_income_band": "BAND_B",
        "verified_prior_enrollment": "PUBLIC_SCHOOL_FULL_YEAR",
        "verified_category_flags": ["DISABILITY_IEP"],
    }
    return _merged(payload, overrides)


# --- Providers -------------------------------------------------------------------

PROVIDER_TUTOR = {
    "legal_name": "Lone Star Tutors LLC",
    "ein": "751234567",
    "address_state": "TX",
    "provider_type": "TUTOR",
}

PROVIDER_SCHOOL = {
    "legal_name": "Alamo Prep Academy",
    "ein": "741112223",
    "address_state": "TX",
    "provider_type": "SCHOOL",
}

PROVIDER_CURRICULUM = {
    "legal_name": "Hill Country Curriculum Co",
    "ein": "742223331",
    "address_state": "TX",
    "provider_type": "CURRICULUM_VENDOR",
}

PROVIDER_OUT_OF_STATE = {
    "legal_name": "Brazos Learning Supply",
    "ein": "743334441",
    "address_state": "OK",
    "provider_type": "CURRICULUM_VENDOR",
}

PROVIDER_RISKY = {
    "legal_name": "Redline Tutoring Group",
    "ein": "745556661",
    "address_state": "NV",
    "provider_type": "TUTOR",
}


def create_provider_payload(**overrides):
    """The canonical Texas tutoring provider."""
    return _merged(PROVIDER_TUTOR, overrides)


def create_school_provider_payload(**overrides):
    return _merged(PROVIDER_SCHOOL, overrides)


def create_curriculum_provider_payload(**overrides):
    return _merged(PROVIDER_CURRICULUM, overrides)


def create_out_of_state_provider_payload(**overrides):
    return _merged(PROVIDER_OUT_OF_STATE, overrides)


def create_risky_provider_payload(**overrides):
    return _merged(PROVIDER_RISKY, overrides)


def create_screening_payload(flags=None, **overrides):
    """A fraud screening submission; an empty flag list scores 0 and clears cleanly."""
    payload = {"flags": list(flags) if flags else []}
    return _merged(payload, overrides)


def create_approve_provider_payload(codes=None, **overrides):
    """Provider admission pinning the catalogue lines it may bill."""
    payload = {"authorized_category_codes": list(codes) if codes else ["TUTORING"]}
    return _merged(payload, overrides)


def create_sanction_payload(action, reason, **overrides):
    """A compliance sanction: PROBATION, REINSTATE or DELIST."""
    payload = {"action": action, "reason": reason}
    return _merged(payload, overrides)


# --- Purchase requests -----------------------------------------------------------


def create_purchase_request_payload(
    provider_id,
    expense_category_id,
    expected_account_version,
    **overrides,
):
    """A pre-approval purchase request inside the instructional term."""
    payload = {
        "provider_id": str(provider_id),
        "expense_category_id": str(expense_category_id),
        "flow": "PREAPPROVAL",
        "amount_cents": 150000,
        "service_start_at": "2026-10-01T00:00:00Z",
        "service_end_at": "2026-11-01T00:00:00Z",
        "expected_account_version": int(expected_account_version),
    }
    return _merged(payload, overrides)


def create_decision_payload(decision, **overrides):
    """An approval-track decision of APPROVED, DENIED or VOID."""
    payload = {"decision": decision}
    return _merged(payload, overrides)


def create_claim_payload(claimed_amount_cents, invoice_reference, **overrides):
    """A provider's invoice claim against a purchase request."""
    payload = {
        "claimed_amount_cents": int(claimed_amount_cents),
        "invoice_reference": invoice_reference,
    }
    return _merged(payload, overrides)


# --- Misuse cases and clawback ---------------------------------------------------


def create_misuse_case_payload(account_id, **overrides):
    """A compliance officer's misuse case against one account."""
    payload = {
        "account_id": str(account_id),
        "detection_rule": "PROVIDER_COLLUSION",
        "disallowed_principal_cents": 150000,
        "narrative": "Tutor billed sessions that the attendance log does not support.",
    }
    return _merged(payload, overrides)


def create_adjudication_payload(outcome, rationale, **overrides):
    """A misuse-case adjudication of SUBSTANTIATED or DISMISSED."""
    payload = {"outcome": outcome, "rationale": rationale}
    return _merged(payload, overrides)


def create_account_status_action_payload(action, reason, **overrides):
    """A direct account participation action of SUSPEND or REINSTATE."""
    payload = {"action": action, "reason": reason}
    return _merged(payload, overrides)


# --- Renewals and appeals --------------------------------------------------------


def create_renewal_review_payload(
    account_id,
    next_program_year_id,
    expected_application_version,
    **overrides,
):
    """A norm-referenced-test renewal filing that clears the default bar."""
    payload = {
        "account_id": str(account_id),
        "next_program_year_id": str(next_program_year_id),
        "assessment_type": "NORM_REFERENCED_TEST",
        "assessment_score": 55,
        "residency_state_attested": "TX",
        "expected_application_version": int(expected_application_version),
    }
    return _merged(payload, overrides)


def create_renewal_decision_payload(decision, **overrides):
    """A continued-eligibility decision of APPROVED or DENIED."""
    payload = {"decision": decision}
    return _merged(payload, overrides)


def create_application_denial_appeal_payload(application_id, **overrides):
    payload = {
        "subject_type": "APPLICATION_DENIAL",
        "application_id": str(application_id),
        "grounds": "The residency documentation on file names the correct Texas address.",
    }
    return _merged(payload, overrides)


def create_clawback_appeal_payload(misuse_case_id, **overrides):
    payload = {
        "subject_type": "CLAWBACK",
        "misuse_case_id": str(misuse_case_id),
        "grounds": "The enrolment record was mis-keyed by the school, not falsified.",
    }
    return _merged(payload, overrides)


def create_provider_delisting_appeal_payload(provider_id, **overrides):
    payload = {
        "subject_type": "PROVIDER_DELISTING",
        "provider_id": str(provider_id),
        "grounds": "The attendance logs were mis-filed, not falsified.",
    }
    return _merged(payload, overrides)


def create_appeal_decision_payload(decision, rationale, **overrides):
    """An appeal decision of OVERTURNED or UPHELD."""
    payload = {"decision": decision, "rationale": rationale}
    return _merged(payload, overrides)


__all__ = [
    "unique_ein",
    "unique_invoice_reference",
    "unique_household_id",
    "PROGRAM_YEAR_DEFAULTS",
    "NEXT_PROGRAM_YEAR_DEFAULTS",
    "STUDENT_DEFAULTS",
    "TUTORING_CATEGORY",
    "MATERIALS_CATEGORY",
    "TUITION_CATEGORY",
    "FIELD_TRIPS_CATEGORY",
    "PROVIDER_TUTOR",
    "PROVIDER_SCHOOL",
    "PROVIDER_CURRICULUM",
    "PROVIDER_OUT_OF_STATE",
    "PROVIDER_RISKY",
    "create_program_year_payload",
    "create_next_program_year_payload",
    "create_program_year_payload_defaults_omitted",
    "create_tutoring_category_payload",
    "create_materials_category_payload",
    "create_tuition_category_payload",
    "create_field_trips_category_payload",
    "create_student_payload",
    "create_application_payload",
    "create_determination_payload",
    "create_provider_payload",
    "create_school_provider_payload",
    "create_curriculum_provider_payload",
    "create_out_of_state_provider_payload",
    "create_risky_provider_payload",
    "create_screening_payload",
    "create_approve_provider_payload",
    "create_sanction_payload",
    "create_purchase_request_payload",
    "create_decision_payload",
    "create_claim_payload",
    "create_misuse_case_payload",
    "create_adjudication_payload",
    "create_account_status_action_payload",
    "create_renewal_review_payload",
    "create_renewal_decision_payload",
    "create_application_denial_appeal_payload",
    "create_clawback_appeal_payload",
    "create_provider_delisting_appeal_payload",
    "create_appeal_decision_payload",
]
