"""Payload factories - one per creatable entity, input fields only.

Defaults mirror the canonical Texas rating fixture used across the suite:
class code 3632 rated 250 cents per 100 dollars of payroll, ELR 150, d-ratio
4000 bp, under a bureau with the standard parameter set.
"""

BUREAU_DEFAULTS = {
    "code": "NCCI",
    "name": "National Bureau",
    "eligibility_threshold_cents": 500000,
    "split_point_cents": 1000000,
    "credibility_ballast_bp": 4000,
    "credibility_excess_divisor_bp": 6000,
    "underwriting_threshold_cents": 2500000,
}

CARRIER_DEFAULTS = {
    "naic_number": "10001",
    "legal_name": "Alamo Mutual",
    "assigned_risk_quota_cents": 100000000,
}

CLASS_CODE_3632 = {
    "code": "3632",
    "description": "Machine Shop NOC",
    "state_code": "TX",
}

RATING_VALUE_3632 = {
    "class_code": "3632",
    "rate_per_100_payroll_cents": 250,
    "elr_per_100_payroll_cents": 150,
    "d_ratio_bp": 4000,
}


def create_bureau_payload(**overrides) -> dict:
    payload = dict(BUREAU_DEFAULTS)
    payload.update(overrides)
    return payload


def create_carrier_payload(**overrides) -> dict:
    payload = dict(CARRIER_DEFAULTS)
    payload.update(overrides)
    return payload


def create_employer_payload(**overrides) -> dict:
    payload = {
        "fein": "75-1000001",
        "legal_name": "Pecos Machine Works",
        "state_code": "TX",
    }
    payload.update(overrides)
    return payload


def create_class_code_payload(**overrides) -> dict:
    payload = dict(CLASS_CODE_3632)
    payload.update(overrides)
    return payload


def create_rating_table_payload(**overrides) -> dict:
    payload = {
        "state_code": "TX",
        "effective_date": "2024-01-01",
        "values": [dict(RATING_VALUE_3632)],
    }
    payload.update(overrides)
    return payload


def create_policy_payload(**overrides) -> dict:
    payload = {
        "policy_number": "WC-1001",
        "effective_date": "2024-01-01",
        "expiration_date": "2025-01-01",
        "class_codes": [{"class_code": "3632", "payroll_dollars": 100000}],
    }
    payload.update(overrides)
    return payload


def create_unit_stat_report_payload(**overrides) -> dict:
    payload = {
        "payroll_lines": [{"class_code": "3632", "payroll_dollars": 100000}],
        "claim_lines": [
            {
                "claim_number": "Q1",
                "claim_type": "MEDICAL",
                "incurred_cents": 50000,
                "paid_cents": 50000,
                "claim_status": "CLOSED",
                "state_code": "TX",
            }
        ],
    }
    payload.update(overrides)
    return payload


def create_class_assignment_payload(**overrides) -> dict:
    payload = {"effective_date": "2026-03-01"}
    payload.update(overrides)
    return payload


def create_class_assignment_dispute_payload(**overrides) -> dict:
    payload = {"reason": "WRONG_CLASS"}
    payload.update(overrides)
    return payload


def create_experience_mod_sheet_payload(**overrides) -> dict:
    payload = {"rating_effective_date": "2026-01-01"}
    payload.update(overrides)
    return payload


def create_mod_appeal_payload(**overrides) -> dict:
    payload = {"reason": "dispute"}
    payload.update(overrides)
    return payload


def create_ownership_change_payload(**overrides) -> dict:
    payload = {"change_type": "MERGER", "effective_date": "2026-06-01"}
    payload.update(overrides)
    return payload


def create_assigned_risk_enrollment_payload(**overrides) -> dict:
    payload = {
        "state_code": "TX",
        "effective_date": "2026-01-01",
        "expiration_date": "2026-12-31",
        "estimated_annual_premium_cents": 500000,
    }
    payload.update(overrides)
    return payload


def create_assigned_risk_take_out_payload(**overrides) -> dict:
    payload = {"exit_date": "2026-07-01"}
    payload.update(overrides)
    return payload
