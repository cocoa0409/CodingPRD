"""Domain thresholds and pinned numeric constants taken from the PRD."""

# Precision and rounding, PRD Section 2.6.
MONEY_PRECISION = 2
FACTOR_RATIO_PRECISION = 6

# Default logical-clock reading before the clock has ever been set, PRD Section 2.5.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Nexus tripwires, PRD Section 3.1 / 3.2.
    "DEFAULT_SALES_THRESHOLD": 500000,
    "DEFAULT_EMPLOYEE_DAYS_THRESHOLD": 15,
    # Apportionment, PRD Section 3.4.
    "RENT_CAPITALIZATION_MULTIPLE": 8,
    # Extensions, PRD Section 3.6.
    "EXTENSION_PREPAY_PCT": 0.90,
    # Estimated payments, PRD Section 3.6.
    "UNDERPAYMENT_PENALTY_RATE": 0.05,
    "SAFE_HARBOR_PRIOR_YEAR_100_FACTOR": 1.00,
    "SAFE_HARBOR_PRIOR_YEAR_110_FACTOR": 1.10,
    "SAFE_HARBOR_CURRENT_YEAR_90_FACTOR": 0.90,
    "INSTALLMENT_DUE_MONTHS": [4, 6, 9, 12],
    "INSTALLMENT_DUE_DAY": 15,
    # Notices, PRD Section 3.8.
    "NOTICE_PENALTY_RATE": 0.10,
    "NOTICE_PENALTY_CAP": 2500.00,
    "NOTICE_INTEREST_RATE": 0.06,
    "DAYS_PER_YEAR": 365,
    "APPEAL_WINDOW_DAYS": 90,
    "DEFAULT_RESPONSE_DUE_DAYS": 45,
    # Voluntary disclosure, PRD Section 3.9.
    "FULL_EXPOSURE_YEARS": 7,
    "VDA_MAX_LOOKBACK_YEARS": 4,
    "VDA_PENALTY_WAIVER_RATE": 0.25,
    "VDA_COOLING_MONTHS": 24,
    "VDA_SHIELD_MONTHS": 24,
}

# Pagination bounds, PRD Section 2.3.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The reference multistate scenario used across the suite: one combined group,
# two member entities (one unprotected, one solicitation-protected) and a CA
# state profile on a double-weighted-sales formula.
BASELINE = {
    "GROUP_NAME": "Meridian Industries",
    "GROUP_BASE_STATE": "DE",
    "EVERYWHERE_SALES": 10_000_000,
    "EVERYWHERE_PROPERTY": 4_000_000,
    "EVERYWHERE_PAYROLL": 2_000_000,
    "MEMBER_A_NAME": "Meridian Manufacturing",
    "MEMBER_B_NAME": "Meridian Services",
    "STATE_CODE": "CA",
    "TAX_RATE": 0.0884,
    "TAX_YEAR": 2026,
    "FEDERAL_TAXABLE_INCOME": 5_000_000,
    # Derived figures pinned by the PRD arithmetic on the reference scenario.
    "MODIFICATION_TOTAL": 676.57,
    "JOYCE_APPORTIONMENT_PERCENTAGE": 0.200000,
    "JOYCE_STATE_TAXABLE_INCOME": 1_000_135.31,
    "JOYCE_TAX_BEFORE_CREDITS": 88_411.96,
    "FINNIGAN_APPORTIONMENT_PERCENTAGE": 0.245000,
    "FINNIGAN_STATE_TAXABLE_INCOME": 1_225_165.76,
    "FINNIGAN_TAX_BEFORE_CREDITS": 108_304.65,
    "ORIGINAL_DUE_DATE": "2027-04-15T00:00:00Z",
    "EXTENDED_DUE_DATE": "2027-10-15T00:00:00Z",
    "REQUIRED_PREPAYMENT": 79_570.76,
}

# Well-formed but unused identifiers, for typed not-found probes.
UNKNOWN_UUIDS = {
    "group": "00000000-0000-4000-8000-0000000000ff",
    "registration": "00000000-0000-4000-8000-000000000001",
    "election": "00000000-0000-4000-8000-000000000002",
    "notice": "00000000-0000-4000-8000-000000000003",
    "vda": "00000000-0000-4000-8000-000000000004",
    "payment": "00000000-0000-4000-8000-000000000005",
    "credit_claim": "00000000-0000-4000-8000-000000000006",
    "activity_record": "00000000-0000-4000-8000-000000000007",
    "filing": "00000000-0000-4000-8000-000000000000",
}
