"""Payload factories - one per creation endpoint, input fields only.

Money is always an integer number of cents. Percentages carrying two decimals
are emitted as JSON numbers, never as strings.
"""

DEFAULTS = {
    "LEGAL_NAME": "Test Fintech Inc",
    "BUSINESS_MODEL": "PAYMENT_FACILITATION",
    "FUNDING_STAGE": "SERIES_B_PLUS",
    "MONTHS_RUNWAY": 30,
    "DISCLOSED_COMPLAINTS_PER_10K": 1.00,
    "END_USER_ACCOUNT_COUNT": 1000,
}


def create_partner_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "business_model": DEFAULTS["BUSINESS_MODEL"],
        "funding_stage": DEFAULTS["FUNDING_STAGE"],
        "months_runway": DEFAULTS["MONTHS_RUNWAY"],
        "disclosed_complaints_per_10k": DEFAULTS["DISCLOSED_COMPLAINTS_PER_10K"],
        "end_user_account_count": DEFAULTS["END_USER_ACCOUNT_COUNT"],
    }
    payload.update(overrides)
    return payload


def account_census_payload(**overrides) -> dict:
    payload = {"end_user_account_count": 1000, "as_of_date": "2026-08-01T00:00:00Z"}
    payload.update(overrides)
    return payload


def create_diligence_review_payload(partner_id, expected_partner_version, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "review_type": "INITIAL",
        "business_model_score": 91,
        "funding_score": 87,
        "compliance_capability_score": 89,
        "complaint_history_score": 100,
        "expected_partner_version": expected_partner_version,
    }
    payload.update(overrides)
    return payload


def decide_diligence_review_payload(outcome="PASSED", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_agreement_payload(partner_id, expected_partner_version, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "kyc_owner": "BANK",
        "dispute_owner": "BANK",
        "marketing_owner": "PARTNER",
        "oversight_rights_level": "ENHANCED",
        "audit_access_notice_days": 10,
        "termination_triggers": ["VOLUNTARY"],
        "monthly_growth_cap_pct": 50.00,
        "concentration_cap_pct": 90.00,
        "max_end_user_balance_cents": 500_000_000,
        "reserve_requirement_bps": 500,
        "effective_date": "2026-08-01T00:00:00Z",
        "expected_partner_version": expected_partner_version,
    }
    payload.update(overrides)
    return payload


def create_marketing_review_payload(partner_id, agreement_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "agreement_id": agreement_id,
        "material_type": "DISCLOSURE",
        "placement_channel": "PARTNER_SITE",
        "disclosure_elements": ["BANK_NAME", "FEE_SCHEDULE", "DISPUTE_RIGHTS"],
        "apr_disclosed": False,
        "fdic_signage_correct": True,
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_until": "2026-09-10T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def resubmit_marketing_review_payload(**overrides) -> dict:
    payload = {
        "disclosure_elements": ["BANK_NAME", "FEE_SCHEDULE", "DISPUTE_RIGHTS"],
        "apr_disclosed": False,
        "fdic_signage_correct": True,
        "effective_from": "2026-08-20T00:00:00Z",
        "effective_until": "2026-08-28T23:59:59.999Z",
    }
    payload.update(overrides)
    return payload


def create_settlement_batch_payload(partner_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-07-15T00:00:00Z",
        "gross_settlement_cents": 8_000_000,
        "interchange_cents": 120_000,
        "returns_cents": 45_000,
        "partner_reported_net_cents": 8_000_000,
    }
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(
    partner_id, custody_account_id, expected_custody_account_version, **overrides
) -> dict:
    payload = {
        "partner_id": partner_id,
        "custody_account_id": custody_account_id,
        "entry_type": "VARIANCE_ADJUSTMENT",
        "amount_cents": 1_000_000,
        "effective_at": "2026-08-01T00:00:00Z",
        "expected_custody_account_version": expected_custody_account_version,
    }
    payload.update(overrides)
    return payload


def create_complaint_payload(partner_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "channel": "BANK_CALL_CENTER",
        "category": "FEES",
        "severity": "MEDIUM",
        "received_at": "2026-07-10T00:00:00Z",
        "narrative": "monthly fee charged twice",
        "is_reg_e_dispute": False,
    }
    payload.update(overrides)
    return payload


def create_alert_payload(partner_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "alert_type": "STRUCTURING",
        "triggered_at": "2026-07-20T12:00:00Z",
        "transaction_volume_cents": 4_500_000,
        "detection_note": "repeated deposits just below the reporting threshold",
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(**overrides) -> dict:
    payload = {
        "cycle_label": "2026-08",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_wind_down_plan_payload(partner_id, **overrides) -> dict:
    payload = {
        "partner_id": partner_id,
        "trigger_reason": "VOLUNTARY",
        "end_user_funds_disposition": "RETURN_TO_END_USERS",
        "notice_days": 30,
        "target_completion_date": "2026-10-15T00:00:00Z",
        "milestones": ["STOP_NEW_ACCOUNTS", "NOTIFY_END_USERS", "RETURN_FUNDS", "CLOSE_CUSTODY"],
    }
    payload.update(overrides)
    return payload
