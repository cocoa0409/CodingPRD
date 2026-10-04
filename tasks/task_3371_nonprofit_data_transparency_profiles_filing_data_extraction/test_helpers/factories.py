"""Payload factories — one per entity, input fields only (PRD §3.1–§3.9)."""
from .constants import (
    CLOCK_2027_09_01,
    CLOCK_START,
    DEFAULT_COVERAGE_END,
    DEFAULT_COVERAGE_START,
    DEFAULT_SERVICE_START,
)

DEFAULTS = {
    "ORG_NAME": "Willow Creek Collective",
    "ORG_EIN": "900100200",
    "ORG_TYPE": "501C3",
    "ORG_STATE": "IL",
    "ORG_NTEE": "B82",
    "ORG_MISSION": "Mentoring and scholarships for first-generation students.",
    "PROGRAM_NAME": "Mentoring Core",
    "PROGRAM_YEAR": 2025,
    "OFFICER_TITLE": "Board Chair",
    "FUNDER_NAME": "Kestrel Giving Fund",
    "GRANT_AMOUNT_CENTS": 500000,
}


def create_organization_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["ORG_NAME"],
        "ein": DEFAULTS["ORG_EIN"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "state_code": DEFAULTS["ORG_STATE"],
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "program_name": DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": DEFAULTS["PROGRAM_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_leadership_member_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ada Reyes",
        "office_title": DEFAULTS["OFFICER_TITLE"],
        "service_start": DEFAULT_SERVICE_START,
    }
    payload.update(overrides)
    return payload


def demographic_record_payload(**overrides) -> dict:
    payload = {
        "category": "AGE_BAND",
        "value_code": "AGE_35_44",
        "disclosure_level": "PUBLIC",
        "fiscal_year": 2025,
    }
    payload.update(overrides)
    return payload


def create_filing_payload(organization_id, expected_organization_version, **overrides) -> dict:
    payload = {
        "organization_id": organization_id,
        "form_type": "FORM_990",
        "form_version_year": 2023,
        "tax_year": 2025,
        "coverage_start": DEFAULT_COVERAGE_START,
        "coverage_end": DEFAULT_COVERAGE_END,
        "source": "IRS_BULK_XML",
        "expected_organization_version": expected_organization_version,
    }
    payload.update(overrides)
    return payload


def raw_line(line_code="TOTREV", raw_value="1000.00", raw_format="USD_WHOLE",
             is_revenue_component=True, **overrides) -> dict:
    line = {
        "line_code": line_code,
        "raw_value": raw_value,
        "raw_format": raw_format,
        "is_revenue_component": is_revenue_component,
    }
    line.update(overrides)
    return line


def create_correction_request_payload(**overrides) -> dict:
    payload = {
        "requested_value": "2000.00",
        "evidence_url": "https://evidence.example.org/audited-2025.pdf",
        "justification": "The audited statement reports a different total.",
    }
    payload.update(overrides)
    return payload


def create_license_payload(**overrides) -> dict:
    payload = {
        "tier": "RESEARCHER",
        "permitted_use": "AGGREGATE_RESEARCH",
        "term_start": CLOCK_START,
        "term_end": CLOCK_2027_09_01,
        "projected_annual_records": 12000,
    }
    payload.update(overrides)
    return payload


def usage_event_payload(**overrides) -> dict:
    payload = {
        "dataset_scope": "ORGANIZATION_PROFILES",
        "record_count": 1000,
        "purpose_code": "PILOT_SCAN",
    }
    payload.update(overrides)
    return payload


def create_grant_payload(funder_organization_id, **overrides) -> dict:
    payload = {
        "funder_organization_id": funder_organization_id,
        "funder_name_raw": DEFAULTS["FUNDER_NAME"],
        "recipient_name_raw": DEFAULTS["ORG_NAME"],
        "amount_cents": DEFAULTS["GRANT_AMOUNT_CENTS"],
        "fiscal_year": 2025,
    }
    payload.update(overrides)
    return payload


def create_identity_case_payload(subject_organization_id, case_type="MERGE", **overrides) -> dict:
    payload = {
        "subject_organization_id": subject_organization_id,
        "case_type": case_type,
        "effective_date": CLOCK_START,
    }
    payload.update(overrides)
    return payload


def verify_payload(target_level="DOCUMENT_VERIFIED", evidence_count=1) -> dict:
    return {"target_level": target_level, "evidence_count": evidence_count}


def decide_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
