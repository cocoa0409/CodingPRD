"""Domain thresholds — numeric constants from the PRD's calculations."""

THRESHOLDS = {
    # Net-worth requirement (application tiering)
    "MIN_NET_WORTH_CENTS": 250000000,          # $2.5M base
    "PER_BRANCH_NET_WORTH_CENTS": 25000000,    # +$250k per additional branch
    "VOLUME_NET_WORTH_BPS": 10,                # 0.10% of origination volume
    "MIN_ORIGINATION_EXPERIENCE_MONTHS": 24,
    # Liquidity monitoring
    "LIQUIDITY_MONITOR_THRESHOLD_BPS": 500,    # 5% soft threshold
    "LIQUIDITY_HARD_FLOOR_BPS": 300,           # 3% hard floor -> SUSPENDED
    # Pool delinquency
    "POOL_DELINQUENCY_THRESHOLD_BPS": 500,     # 5% of aggregate principal
    # Pool composition
    "MIN_POOL_PRINCIPAL_CENTS": 100000000,     # $1M minimum pool balance
    "MAX_LOANS_PER_POOL": {
        "SINGLE_FAMILY": 3,
        "MANUFACTURED_HOME": 3,
        "MULTIFAMILY": 2,
    },
    # Loan note-rate band above the pool note rate (inclusive)
    "LOAN_NOTE_RATE_MIN_ABOVE_POOL_BPS": 50,
    "LOAN_NOTE_RATE_MAX_ABOVE_POOL_BPS": 150,
    # Escrow split
    "ESCROW_TAX_SHARE_BPS": 6000,              # 60% tax, remainder to insurance
    # Pass-through payment
    "PASS_THROUGH_MONTHS": 12,
    "FULL_COLLECTION_RATE_BPS": 10000,
    # Pool terms by type
    "POOL_TERMS": {
        "SINGLE_FAMILY": (360, 180),
        "MANUFACTURED_HOME": (240,),
        "MULTIFAMILY": (360,),
    },
}

TEST_DEFAULTS = {
    "NET_WORTH_CENTS": 900000000,
    "LIQUID_ASSETS_CENTS": 3000000,
    "ORIGINATION_EXPERIENCE_MONTHS": 40,
    "BRANCH_COUNT": 1,
    "ANNUAL_ORIGINATION_VOLUME_CENTS": 3000000000,
    "ENGAGEMENT_WINDOW_START": "2026-01-01",
    "ENGAGEMENT_WINDOW_END": "2027-01-01",
    "POOL_NOTE_RATE_BPS": 700,
    "LOAN_NOTE_RATE_BPS": 800,
    "ESCROW_MONTHLY_CENTS": 20000,
    "CLOCK_DATE": "2026-09-03T00:00:00Z",
    "CLOCK_MONTH": "2026-09",
}

# Default startup clock per PRD §2.6.
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
