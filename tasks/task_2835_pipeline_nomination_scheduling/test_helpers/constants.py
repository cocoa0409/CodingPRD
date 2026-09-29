"""Domain thresholds and shared test literals drawn from the PRD's stated rules."""

# Numeric rules the PRD states outright.
THRESHOLDS = {
    # PRD 3.5: "a shipper with at least two qualifying records on the segment is
    # HISTORICAL, and a shipper with fewer than two is NEW_SHIPPER".
    "MIN_HISTORY_RECORDS": 2,
    # PRD 3.5: the lookback is "the instant exactly 365 days -- one full year --
    # before the cycle's window_open_at".
    "HISTORY_LOOKBACK_DAYS": 365,
    # PRD 3.5: "A new-shipper reserve equal to one tenth -- ten percent -- of
    # effective_capacity_bbl".
    "NEW_SHIPPER_RESERVE_PCT": 0.10,
    # PRD 3.6: each ticket's window is "advanced by one 24-hour slot for every
    # position ahead of it".
    "SLOT_HOURS": 24,
    # PRD 3.6: an upgrade interface "costs twice as much".
    "UPGRADE_MULTIPLIER": 2,
    # PRD 3.6: requires_flush is true "when and only when the rank gap is two or
    # more steps".
    "FLUSH_RANK_GAP": 2,
    # PRD 3.7: the batch dies when "retest_count reaches 2".
    "MAX_RETESTS": 2,
    # PRD 3.8: notice needs "two full days -- 48 hours"; the conflict buffer is
    # "one full day -- 24 hours -- on each side".
    "NOTICE_HOURS": 48,
    "MAINTENANCE_BUFFER_HOURS": 24,
    # PRD 3.9 imbalance tier boundaries and multipliers.
    "TOLERANCE_PCT": 0.005,
    "STANDARD_PCT": 0.02,
    "TOLERANCE_MULTIPLIER": 0,
    "STANDARD_MULTIPLIER": 1.0,
    "PENALTY_MULTIPLIER": 2.5,
}

# Rounding scales, PRD 2.9.
PRECISION = {
    "MONEY_DP": 2,
    "RATE_DP": 3,
    "RATIO_DP": 6,
    "DERATE_DP": 2,
    "VOLUME_DP": 2,
}

# Pagination bounds, PRD 2.3.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The instant the logical clock reads before any call in a session, PRD 2.4.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Test literals shared by the composite fixtures.
TEST_DEFAULTS = {
    "ORIGIN_SHELL_BBL": 500000,
    "ORIGIN_MIN_OPERATING_BBL": 10000,
    "ORIGIN_INJECTION_BAYS": 2,
    "DEST_SHELL_BBL": 400000,
    "DEST_MIN_OPERATING_BBL": 5000,
    "SEGMENT_CAPACITY_BBL": 101000,
    "TRANSMIX_RESERVE_BBL": 1000,
    "TRANSMIX_CUT_BBL": 250,
    "MIN_TENDER_BBL": 6000,
    "LINEFILL_REQUIREMENT_BBL": 20000,
    "LINEFILL_FUNDING_BBL": 20000,
    "ORIGIN_STOCK_BBL": 100000,
    "CREDIT_LIMIT_USD": 250000,
    "BASE_RATE": 1.855,
    "TIER1_MIN_BBL": 25000,
    "TIER1_RATE": 1.705,
    "TIER2_MIN_BBL": 45000,
    "TIER2_RATE": 1.555,
    "TENDER_MINIMUM_BBL": 6000,
    "IMBALANCE_PENALTY_RATE": 0.45,
    "TARIFF_EFFECTIVE_FROM": "2026-07-01T00:00:00Z",
    "CYCLE_CODE": "2026-09",
    "WINDOW_OPEN_AT": "2026-08-01T00:00:00Z",
    "WINDOW_CLOSE_AT": "2026-08-20T00:00:00Z",
    "SHIP_START_AT": "2026-09-01T00:00:00Z",
    "SHIP_END_AT": "2026-09-30T00:00:00Z",
}

# Opaque operator identifiers used where duty separation matters (PRD 2.10).
PUBLISHER_USER_ID = "sched-publisher-1"
CERTIFIER_USER_ID = "sched-certifier-1"
SECOND_CERTIFIER_USER_ID = "sched-certifier-2"
TARIFF_ADMIN_USER_ID = "tariff-admin-1"

# UUIDs that exist in no table, for path-existence and body-reference tests.
UNKNOWN_CYCLE_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_NOMINATION_ID = "00000000-0000-4000-8000-000000000901"
UNKNOWN_BATCH_TICKET_ID = "00000000-0000-4000-8000-000000000902"
UNKNOWN_MAINTENANCE_EVENT_ID = "00000000-0000-4000-8000-000000000903"
UNKNOWN_SETTLEMENT_ID = "00000000-0000-4000-8000-000000000904"
