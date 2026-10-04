"""Payload factories — one per creatable resource, input fields only."""

TEST_DEFAULTS = {
    "POLICY_NUMBER": "MP-1001",
    "ANNIVERSARY_UTC": "2026-01-15T00:00:00Z",
    "DELEGATED_CURTAILMENT_RATE": 0.12,
    "NONDELAGATED_CURTAILMENT_RATE": 0.08,
    "LTV_VARIANCE_TOLERANCE": 0.05,
    "SERVICER_STANDARD": "PARTICIPATION_COMPLETE",
    "RESCISSION_RELIEF_CYCLES": 2,
    "MIN_THIRD_PARTY_NET_BPS": 1500,
    "TWO_YEAR_EFFECTIVE_FLAG": True,
    "EXPOSURE_CONTRIBUTION_RATE": 0.35,
    "LENDER_NAME": "Cascade Mortgage",
    "EXPOSURE_CAP_CENTS": 200_000_000,
    "SERVICER_NAME": "Northline Servicing",
    "SERVICER_TIER": "TIER_2",
    "LOAN_AMOUNT_CENTS": 34_000_000,
    "PROPERTY_VALUE_CENTS": 40_000_000,
    "CREDIT_GRADE": "B",
    "COVERAGE_PERCENT": 25,
    "RATE_BPS": 62,
    "COUNTY_CODE": "06037",
    "TERM_MONTHS": 360,
    "EVENT_COMPLETED_UTC": "2026-08-01T00:00:00Z",
    "UNPAID_PRINCIPAL_CENTS": 8_000_000,
    "ACCRUED_INTEREST_CENTS": 1_500_000,
    "ALLOWABLE_ADVANCES_CENTS": 5_000_000,
    "GROSS_PROCEEDS_CENTS": 7_000_000,
    "EXPENSES_OF_SALE_CENTS": 500_000,
    "NOTICE_UTC": "2026-09-01T00:00:00Z",
    "APPLIED_UTC": "2026-10-15T00:00:00Z",
    "EVIDENCE_CENTS": 3_000_000,
}


def create_master_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_number": TEST_DEFAULTS["POLICY_NUMBER"],
        "anniversary_utc": TEST_DEFAULTS["ANNIVERSARY_UTC"],
        "coverage_percent_default": TEST_DEFAULTS["COVERAGE_PERCENT"],
        "delegated_curtailment_rate": TEST_DEFAULTS["DELEGATED_CURTAILMENT_RATE"],
        "nondelagated_curtailment_rate": TEST_DEFAULTS["NONDELAGATED_CURTAILMENT_RATE"],
        "ltv_variance_tolerance": TEST_DEFAULTS["LTV_VARIANCE_TOLERANCE"],
        "servicer_loss_mitigation_standard": TEST_DEFAULTS["SERVICER_STANDARD"],
        "rescission_relief_cycles": TEST_DEFAULTS["RESCISSION_RELIEF_CYCLES"],
        "min_third_party_net_bps": TEST_DEFAULTS["MIN_THIRD_PARTY_NET_BPS"],
        "two_year_effective_flag": TEST_DEFAULTS["TWO_YEAR_EFFECTIVE_FLAG"],
        "exposure_contribution_rate": TEST_DEFAULTS["EXPOSURE_CONTRIBUTION_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "credit_grade": TEST_DEFAULTS["CREDIT_GRADE"],
        "ltv_band": "831_TO_85",
        "coverage_percent": TEST_DEFAULTS["COVERAGE_PERCENT"],
        "premium_plan": "BPM",
        "rate_bps": TEST_DEFAULTS["RATE_BPS"],
        "min_borrower_reserves_months": 0,
    }
    defaults.update(overrides)
    return defaults


def create_treaty_payload(**overrides) -> dict:
    defaults = {
        "treaty_number": "TR-2026-A",
        "inception_utc": "2026-01-01T00:00:00Z",
        "expiration_utc": "2028-01-01T00:00:00Z",
        "retention_per_claim_cents": 1_000_000,
        "exhaustion_per_claim_cents": 6_000_000,
        "aggregate_ceded_cap_cents": 5_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_lender_payload(**overrides) -> dict:
    defaults = {
        "lender_name": TEST_DEFAULTS["LENDER_NAME"],
        "delegated_underwriting": True,
        "policy_exposure_cap_cents": TEST_DEFAULTS["EXPOSURE_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_servicer_payload(**overrides) -> dict:
    defaults = {
        "servicer_name": TEST_DEFAULTS["SERVICER_NAME"],
        "tier": TEST_DEFAULTS["SERVICER_TIER"],
        "loss_mitigation_capability": "PARTICIPATION_COMPLETE",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "borrower_reference": "APP-1",
        "loan_amount_cents": TEST_DEFAULTS["LOAN_AMOUNT_CENTS"],
        "property_value_cents": TEST_DEFAULTS["PROPERTY_VALUE_CENTS"],
        "credit_grade": TEST_DEFAULTS["CREDIT_GRADE"],
        "coverage_percent": TEST_DEFAULTS["COVERAGE_PERCENT"],
        "premium_plan": "BPM",
        "borrower_paid": True,
        "financed_premium": False,
        "borrower_reserves_months": 6,
        "county_code": TEST_DEFAULTS["COUNTY_CODE"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(**overrides) -> dict:
    defaults = {
        "reinsurance_treaty_id": "TREATY-NONE",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "event_kind": "FORECLOSURE",
        "event_completed_utc": TEST_DEFAULTS["EVENT_COMPLETED_UTC"],
        "unpaid_principal_cents": TEST_DEFAULTS["UNPAID_PRINCIPAL_CENTS"],
        "accrued_interest_cents": TEST_DEFAULTS["ACCRUED_INTEREST_CENTS"],
        "allowable_advances_cents": TEST_DEFAULTS["ALLOWABLE_ADVANCES_CENTS"],
        "gross_proceeds_cents": TEST_DEFAULTS["GROSS_PROCEEDS_CENTS"],
        "expenses_of_sale_cents": TEST_DEFAULTS["EXPENSES_OF_SALE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delinquency_report_payload(**overrides) -> dict:
    defaults = {
        "as_of_period": "2026-01",
        "delinquency_class": "A",
        "months_delinquent": 2,
        "loss_mitigation_activities": [
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"},
            {"activity_kind": "INTAKE_COMPLETE", "outcome": "COMPLETED",
             "activity_utc": "2026-01-20T00:00:00Z"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_notice_payload(**overrides) -> dict:
    defaults = {
        "request_kind": "BORROWER_REQUEST",
        "requested_by_role": "BORROWER",
        "notice_utc": TEST_DEFAULTS["NOTICE_UTC"],
        "evidence_cents": TEST_DEFAULTS["EVIDENCE_CENTS"],
        "applied_utc": TEST_DEFAULTS["APPLIED_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_external_report_payload(**overrides) -> dict:
    defaults = {
        "verified_loan_amount_cents": TEST_DEFAULTS["LOAN_AMOUNT_CENTS"],
        "verified_property_value_cents": 39_000_000,
        "post_origination_value_cents": 0,
        "occupancy_reported": "OWNER_OCCUPIED",
        "independent_validation_completed_utc": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "grounds": "ORIGINATION_OMISSION",
        "asserted_coverage_percent": TEST_DEFAULTS["COVERAGE_PERCENT"],
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(**overrides) -> dict:
    defaults = {
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 17_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_cession_payload(**overrides) -> dict:
    defaults = {
        "ceded_amount_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults