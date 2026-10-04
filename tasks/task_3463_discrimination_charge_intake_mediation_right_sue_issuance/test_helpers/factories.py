"""Payload factories — input fields only (system-stamped fields excluded).

Every factory takes **overrides so tests can steer exactly the inputs the
PRD makes meaningful (deadline days, headcounts, dates, amounts).
"""

DEFAULTS = {
    "STATE_CODE": "FL",
    "EMPLOYER_COUNT": 40,
    "INCIDENT_DATE": "2026-06-01",
    "HARM_DESCRIPTION": "Unlawful employment practice",
    "AGENCY_NAME": "State Fair Employment Agency",
    "DEADLINE_DAYS": 300,
    "WORK_SHARING_POLICY": "DUAL_FILE_DEFAULT",
    "COVERS_AGE": True,
    "REQUEST_TYPE": "POSITION_STATEMENT",
    "RESPONSE_TEXT": "Respondent position statement",
    "WITNESS_NAME": "Witness One",
    "INTERVIEW_SUMMARY": "Witness corroborated the account",
    "RATIONALE": "The record supports this outcome",
    "OFFER_AMOUNT_CENTS": 100_000,
    "SETTLEMENT_AMOUNT_CENTS": 500_000,
    "FAIL_REASON": "Respondent refused to engage",
    "VACATE_REASON": "Settlement repudiated",
    "SYSTEMIC_TITLE": "Pattern-or-practice probe",
    "TARGET_DESCRIPTION": "Authorized recipient",
    "LEGAL_BASIS": "PARTY_CONSENT",
    "HARM_START_DATE": "2026-06-01",
    "INVESTIGATOR_USER_ID": "inv-default",
}


def set_clock_payload(**overrides) -> dict:
    """Payload for POST /eeoc/_clock/set_current_utc (to_iso8601 required)."""
    defaults = {"to_iso8601": "2026-09-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_deferral_agency_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "agency_name": DEFAULTS["AGENCY_NAME"],
        "filing_deadline_days": DEFAULTS["DEADLINE_DAYS"],
        "work_sharing_policy": DEFAULTS["WORK_SHARING_POLICY"],
        "covers_age": DEFAULTS["COVERS_AGE"],
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer LLC",
        "state_code": DEFAULTS["STATE_CODE"],
        "employee_count_current": DEFAULTS["EMPLOYER_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def update_employer_payload(**overrides) -> dict:
    """PATCH body: employee_count_current and/or legal_name."""
    return dict(overrides)


def create_complainant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Complainant",
        "email": "complainant@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(**overrides) -> dict:
    """Required: complainant_id, employer_id. The rest have timely defaults
    (incident 2026-06-01 is 92 days before the boot clock 2026-09-01, so the
    charge is timely under both the 180- and 300-day deadlines)."""
    defaults = {
        "complainant_id": None,
        "employer_id": None,
        "basis_codes": ["RACE"],
        "incident_date": DEFAULTS["INCIDENT_DATE"],
        "harm_description": DEFAULTS["HARM_DESCRIPTION"],
        "employee_count_at_incident": DEFAULTS["EMPLOYER_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def amend_charge_payload(**overrides) -> dict:
    """expected_charge_version is mandatory (OCC); the rest are optional edits."""
    defaults = {"expected_charge_version": None}
    defaults.update(overrides)
    return defaults


def respond_mediation_payload(**overrides) -> dict:
    defaults = {"response": "ACCEPTED"}
    defaults.update(overrides)
    return defaults


def create_mediation_session_payload(**overrides) -> dict:
    """scheduled_end must be strictly after scheduled_start; the start must not
    be before the current logical clock."""
    defaults = {
        "scheduled_start": "2026-10-01T10:00:00Z",
        "scheduled_end": "2026-10-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def conclude_mediation_payload(**overrides) -> dict:
    """outcome SETTLED additionally requires settlement_amount_cents > 0."""
    defaults = {"outcome": "IMPASSE"}
    defaults.update(overrides)
    return defaults


def assign_investigator_payload(**overrides) -> dict:
    defaults = {"investigator_user_id": DEFAULTS["INVESTIGATOR_USER_ID"]}
    defaults.update(overrides)
    return defaults


def create_evidence_request_payload(**overrides) -> dict:
    defaults = {"request_type": DEFAULTS["REQUEST_TYPE"]}
    defaults.update(overrides)
    return defaults


def respond_evidence_payload(**overrides) -> dict:
    defaults = {"response_text": DEFAULTS["RESPONSE_TEXT"]}
    defaults.update(overrides)
    return defaults


def create_interview_payload(**overrides) -> dict:
    """Interviews are logged after the fact — past windows are legitimate."""
    defaults = {
        "witness_name": DEFAULTS["WITNESS_NAME"],
        "interview_start": "2026-08-10T10:00:00Z",
        "interview_end": "2026-08-10T11:00:00Z",
        "summary": DEFAULTS["INTERVIEW_SUMMARY"],
    }
    defaults.update(overrides)
    return defaults


def create_determination_payload(**overrides) -> dict:
    """Default outcome is NO_CAUSE (no remedy components). For CAUSE pass the
    four remedy components plus harm_start_date — all required together."""
    defaults = {
        "outcome": "NO_CAUSE",
        "rationale": DEFAULTS["RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def cause_determination_payload(**overrides) -> dict:
    """CAUSE variant with all five required fields populated."""
    defaults = {
        "outcome": "CAUSE",
        "rationale": DEFAULTS["RATIONALE"],
        "back_pay_cents": 100_000,
        "front_pay_cents": 0,
        "compensatory_damages_cents": 0,
        "punitive_damages_cents": 0,
        "harm_start_date": DEFAULTS["HARM_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def review_determination_payload(**overrides) -> dict:
    """decision RETURN additionally requires return_reason (null on APPROVE)."""
    defaults = {"decision": "APPROVE"}
    defaults.update(overrides)
    return defaults


def table_offer_payload(**overrides) -> dict:
    """expected_conciliation_version is mandatory (OCC)."""
    defaults = {
        "amount_cents": DEFAULTS["OFFER_AMOUNT_CENTS"],
        "expected_conciliation_version": None,
    }
    defaults.update(overrides)
    return defaults


def fail_conciliation_payload(**overrides) -> dict:
    defaults = {"reason": DEFAULTS["FAIL_REASON"]}
    defaults.update(overrides)
    return defaults


def create_systemic_case_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["SYSTEMIC_TITLE"],
        "basis_focus": ["RACE"],
    }
    defaults.update(overrides)
    return defaults


def link_charge_payload(**overrides) -> dict:
    defaults = {"charge_id": None}
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(**overrides) -> dict:
    defaults = {
        "legal_basis": DEFAULTS["LEGAL_BASIS"],
        "target_description": DEFAULTS["TARGET_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def vacate_settlement_payload(**overrides) -> dict:
    defaults = {"reason": DEFAULTS["VACATE_REASON"]}
    defaults.update(overrides)
    return defaults
