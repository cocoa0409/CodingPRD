"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Fee waterfall (PRD §3.9): first 20000 cents of savings at 0.25, excess at 0.20.
    "TIER1_CAP_CENTS": 20000,
    "TIER1_RATE": 0.25,
    "TIER2_RATE": 0.20,
    # Negotiation round cap (PRD §3.5): case auto-expires at round_count 5.
    "NEGOTIATION_ROUND_CAP": 5,
    # NSA open negotiation window (PRD §3.7): 30 business days.
    "OPEN_NEGOTIATION_BUSINESS_DAYS": 30,
    # Appeal window (PRD §3.8): determination creation + 45 calendar days.
    "APPEAL_WINDOW_DAYS": 45,
    # Feed turnaround hours (PRD §3.10).
    "TURNAROUND_CLAIM_INTAKE_HOURS": 4,
    "TURNAROUND_DEFAULT_HOURS": 24,
    "BUSINESS_DAY_START": "09:00:00Z",
    "BUSINESS_DAY_END": "17:00:00Z",
    # UCR benchmark percentile pinned for reference-based pricing.
    "UCR_BENCHMARK_PERCENTILE": 80,
}

TEST_DEFAULTS = {
    "FEE_PERCENT": 0.25,
    "FEE_CAP_CENTS_PER_CLAIM": 5000,
    "SERVICE_DATE": "2026-09-10T00:00:00Z",
    "AGREEMENT_START": "2026-01-01T00:00:00Z",
    "AGREEMENT_END": "2027-01-01T00:00:00Z",
    # Canonical priced-claim fixture: Medicare 10000 @ gaf 1.10, x1.50, qty 2.
    "MEDICARE_BASE_RATE_CENTS": 10000,
    "MEDICARE_GAF": 1.10,
    "PERCENT_OF_MEDICARE": 1.50,
    "LINE_UNIT_CHARGE_CENTS": 30000,
    "LINE_QUANTITY": 2,
    "EXPECTED_ALLOWED_33000": 33000,
}
