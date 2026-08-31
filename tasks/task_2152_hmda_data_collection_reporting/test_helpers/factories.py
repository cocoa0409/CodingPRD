"""Payload factories — one per entity, input fields only."""

import itertools

from .constants import (
    DEFAULT_ACTIVITY_YEAR,
    PROPERTY_CA,
    TEST_DEFAULTS,
    TRACT_A,
)

# ULI values must be at least 23 characters of uppercase letters and digits for
# the register's syntactical edits to stay silent; every generated ULI is 25.
_ULI_PREFIX = "10BX939C5543TQA1B"
_uli_counter = itertools.count(1)


def next_uli() -> str:
    """Return a fresh 25-character ULI unique within a single test."""
    return f"{_ULI_PREFIX}{next(_uli_counter):08d}"


def create_institution_payload(**overrides) -> dict:
    defaults = {
        "lei": TEST_DEFAULTS["PRIMARY_LEI"],
        "name": TEST_DEFAULTS["PRIMARY_NAME"],
        "activity_year": DEFAULT_ACTIVITY_YEAR,
        "asset_size_usd_cents": TEST_DEFAULTS["ASSET_SIZE_CENTS"],
        "prior_year_closed_end_originations": TEST_DEFAULTS["CLOSED_END_ORIGINATIONS"],
        "prior_year_open_end_originations": TEST_DEFAULTS["OPEN_END_ORIGINATIONS"],
    }
    defaults.update(overrides)
    return defaults


def create_census_tract_payload(**overrides) -> dict:
    defaults = dict(TRACT_A)
    defaults.update(overrides)
    return defaults


def create_application_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "uli": next_uli(),
        "application_date": "2026-02-10T00:00:00Z",
        "application_channel": "MAIL",
        "loan_type": "CONVENTIONAL",
        "loan_purpose": "HOME_PURCHASE",
        "occupancy_type": "PRINCIPAL",
        "lien_status": "FIRST_LIEN",
        "loan_amount_cents": TEST_DEFAULTS["LOAN_AMOUNT_CENTS"],
        "income_thousands": TEST_DEFAULTS["INCOME_THOUSANDS"],
    }
    defaults.update(overrides)
    return defaults


def create_demographic_entry_payload(application_id: str, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "applicant_role": "APPLICANT",
        "collection_method": "PROVIDED_BY_APPLICANT",
        "ethnicity_codes": ["NOT_HISPANIC_OR_LATINO"],
        "race_codes": ["WHITE"],
        "sex_code": "MALE",
    }
    defaults.update(overrides)
    return defaults


def create_geocode_assignment_payload(
    application_id: str, expected_application_version: int, **overrides
) -> dict:
    defaults = {
        "application_id": application_id,
        "expected_application_version": expected_application_version,
    }
    defaults.update(PROPERTY_CA)
    defaults.update(overrides)
    return defaults


def manual_override_payload(census_tract_id: str, **overrides) -> dict:
    defaults = {
        "census_tract_id": census_tract_id,
        "override_reason": "Parcel map places the property in this tract.",
    }
    defaults.update(overrides)
    return defaults


def create_edit_run_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "scope": "FULL",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def verify_exception_payload(**overrides) -> dict:
    defaults = {
        "verification_note": "Reviewed against the underwriting file and confirmed correct.",
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(institution_id: str, expected_institution_version: int,
                              **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "expected_institution_version": expected_institution_version,
    }
    defaults.update(overrides)
    return defaults


def certify_payload(**overrides) -> dict:
    defaults = {
        "attestation_text": "Register certified complete and accurate for activity year 2026.",
    }
    defaults.update(overrides)
    return defaults


def review_payload(decision: str = "ACCEPT", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def resubmit_payload(**overrides) -> dict:
    defaults = {"reason": "Register corrected; refiling."}
    defaults.update(overrides)
    return defaults


def action_taken_payload(**overrides) -> dict:
    """Companion fields only become applicable once the action is known, so an
    override of None drops the field from the request body entirely rather than
    sending an explicit null."""
    defaults = {
        "action_taken": "ORIGINATED",
        "action_taken_date": "2026-03-15T00:00:00Z",
        "rate_spread": TEST_DEFAULTS["RATE_SPREAD"],
        "purchaser_type": "NOT_APPLICABLE",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_audit_sample_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "method": "SYSTEMATIC_INTERVAL",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T23:59:59Z",
        "fields_reviewed_per_record": 4,
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(audit_sample_id: str, application_id: str,
                                 **overrides) -> dict:
    defaults = {
        "audit_sample_id": audit_sample_id,
        "application_id": application_id,
        "field_name": "income_thousands",
        "recorded_value": "120",
        "source_document_value": "112",
        "severity": "MATERIAL",
        "remediation_start": "2026-09-01T00:00:00Z",
        "remediation_end": "2026-09-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def close_sample_payload(defect_rate_basis: str = "FIELD_WEIGHTED", **overrides) -> dict:
    defaults = {"defect_rate_basis": defect_rate_basis}
    defaults.update(overrides)
    return defaults


def create_fair_lending_payload(institution_id: str, **overrides) -> dict:
    defaults = {
        "institution_id": institution_id,
        "basis": "RACE",
        "control_group_code": "WHITE",
        "protected_group_code": "BLACK",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-06-30T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def reopen_payload(**overrides) -> dict:
    defaults = {"reason": "Source document disagrees with the register."}
    defaults.update(overrides)
    return defaults
