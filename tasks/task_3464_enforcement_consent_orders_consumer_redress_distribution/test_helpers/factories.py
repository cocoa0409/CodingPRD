"""Payload factories — one per endpoint input shape, input fields only.

Defaults come from constants.TEST_DEFAULTS. Every factory accepts **overrides
so tests control exactly the fields under test.
"""
from .constants import TEST_DEFAULTS


# --- Platform -----------------------------------------------------------------
def clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# --- Entities -------------------------------------------------------------------
def create_subject_company_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["COMPANY_LEGAL_NAME"],
        "complaint_count_90d": TEST_DEFAULTS["COMPANY_COMPLAINT_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_investigation_payload(subject_company_id: str, **overrides) -> dict:
    payload = {
        "subject_company_id": subject_company_id,
        "origin": "REFERRAL",
        "summary": TEST_DEFAULTS["INVESTIGATION_SUMMARY"],
    }
    payload.update(overrides)
    return payload


def create_cid_payload(**overrides) -> dict:
    payload = {
        "subject_matter": TEST_DEFAULTS["CID_SUBJECT_MATTER"],
        "response_due_date": TEST_DEFAULTS["CID_RESPONSE_DUE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_consent_order_payload(**overrides) -> dict:
    payload = {
        "monetary_relief_cents": TEST_DEFAULTS["ORDER_MONETARY_RELIEF_CENTS"],
        "max_penalty_cents": TEST_DEFAULTS["ORDER_MAX_PENALTY_CENTS"],
        "reporting_frequency_months": TEST_DEFAULTS["ORDER_REPORTING_FREQUENCY_MONTHS"],
        "monitoring_term_years": TEST_DEFAULTS["ORDER_MONITORING_TERM_YEARS"],
        "conduct_prohibitions": list(TEST_DEFAULTS["ORDER_CONDUCT_PROHIBITIONS"]),
    }
    payload.update(overrides)
    return payload


def create_comment_payload(**overrides) -> dict:
    payload = {
        "author_email": "watcher@public.org",
        "body": "Support the order as drafted.",
    }
    payload.update(overrides)
    return payload


def create_compliance_report_payload(**overrides) -> dict:
    payload = {
        "period_start": "2026-10-01T00:00:00Z",
        "period_end": "2027-03-31T00:00:00Z",
        "report_document_ref": TEST_DEFAULTS["REPORT_DOCUMENT_REF"],
    }
    payload.update(overrides)
    return payload


def create_violation_penalty_payload(**overrides) -> dict:
    payload = {
        "severity": "AGGRAVATED",
        "detected_on": "2026-10-01T00:00:00Z",
        "description": "Billing disclosures still deceptive",
    }
    payload.update(overrides)
    return payload


def create_judgment_payload(**overrides) -> dict:
    payload = {
        "amount_cents": TEST_DEFAULTS["ORDER_MONETARY_RELIEF_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(**overrides) -> dict:
    payload = {
        "amount_cents": TEST_DEFAULTS["ORDER_MONETARY_RELIEF_CENTS"],
        "kind": "COLLECTION",
    }
    payload.update(overrides)
    return payload


def create_asset_trace_payload(**overrides) -> dict:
    payload = {
        "found_assets_cents": 300_000,
        "trace_ref": "trace-1",
    }
    payload.update(overrides)
    return payload


def create_claimant_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["CLAIMANT_FULL_NAME"],
        "email": TEST_DEFAULTS["CLAIMANT_EMAIL"],
        "identified_from": "COMPANY_RECORDS",
    }
    payload.update(overrides)
    return payload


def create_claim_payload(claimant_id: str, redress_fund_id: str, **overrides) -> dict:
    payload = {
        "claimant_id": claimant_id,
        "redress_fund_id": redress_fund_id,
        "documented_loss_cents": 500_000,
    }
    payload.update(overrides)
    return payload


# --- Transition payloads ----------------------------------------------------------
def investigation_transition_payload(target_state: str, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def cid_transition_payload(target_state: str, **overrides) -> dict:
    """Extra inputs (e.g. response_document_ref) ride in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def consent_order_transition_payload(target_state: str, expected_consent_order_version, **overrides) -> dict:
    payload = {
        "target_state": target_state,
        "expected_consent_order_version": expected_consent_order_version,
    }
    payload.update(overrides)
    return payload


def compliance_report_transition_payload(target_state: str, **overrides) -> dict:
    """deficiency_notes / report_document_ref ride in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def violation_penalty_transition_payload(target_state: str, **overrides) -> dict:
    """cured_on rides in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def judgment_transition_payload(target_state: str, **overrides) -> dict:
    """sworn_total_assets_cents rides in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def redress_fund_transition_payload(target_state: str, expected_redress_fund_version, **overrides) -> dict:
    """residual_recipient_name rides in overrides."""
    payload = {
        "target_state": target_state,
        "expected_redress_fund_version": expected_redress_fund_version,
    }
    payload.update(overrides)
    return payload


def claim_transition_payload(target_state: str, **overrides) -> dict:
    """denial_reason rides in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def refund_check_transition_payload(target_state: str, **overrides) -> dict:
    """voided_reason rides in overrides."""
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload
