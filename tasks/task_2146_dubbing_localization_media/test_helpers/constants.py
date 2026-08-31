"""Domain thresholds and shared test defaults taken from the PRD."""

# Numeric constants the PRD pins by name or by prose.
THRESHOLDS = {
    "BLOCK_MINUTES": 30,             # rooms are billed in whole thirty-minute blocks
    "UNION_UPLIFT_PCT": 0.125,       # one hundred and twenty-five thousandths
    "RETAKE_CREDIT_PCT": 0.40,       # four tenths
    "BUYOUT_MULTIPLIER": 1.75,       # one and seventy-five hundredths
    "RESIDUAL_BANDS": [0.45, 0.30, 0.18],
    "RESIDUAL_TAIL_PCT": 0.07,
    "RESIDUAL_CAP_PCT": 1.20,
    "LOUDNESS_TOLERANCE_LU": 2.0,
    "MIN_CONFORMANCE_INDEX": 0.80,
    "MAX_RETAKE_CYCLES": 2,
    "MAX_LINEAGE_DEPTH": 3,
    "DISCOUNT_TIER_1_CENTS": 200000,
    "DISCOUNT_TIER_2_CENTS": 500000,
}

RUSH_PCT = {"STANDARD": 0.00, "EXPEDITED": 0.10, "RUSH": 0.22}
TIER_WEIGHT = {"STANDARD": 1.00, "EXPEDITED": 0.97, "RUSH": 0.94}
DISCOUNT_BANDS = {"TIER_1_PCT": 0.05, "TIER_2_PCT": 0.08}

TERRITORY_ORDER = ["US", "CA", "UK", "DE", "FR", "JP", "BR", "AU", "ROW"]

# The logical clock's declared starting instant (PRD 2.8).
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Shared scenario values used by the composite fixtures.
TEST_DEFAULTS = {
    "CLOCK_SETUP": "2026-09-01T00:00:00Z",
    "TITLE_CODE": "TTL-2146",
    "SOURCE_LANGUAGE": "en-US",
    "TARGET_LANGUAGE": "de-DE",
    "TERRITORY": "DE",
    "RUNTIME_SECONDS": 7200,
    "CUT_LOOP_COUNT": 400,
    "STUDIO_HOURLY_RATE_CENTS": 24000,
    "STUDIO_BUFFER_MINUTES": 30,
    "STUDIO_DAILY_CAPACITY_MINUTES": 600,
    "TALENT_BASE_RATE_CENTS_PER_HOUR": 30000,
    "TALENT_MAX_DAILY_MINUTES": 300,
    "BUDGET_CAP_CENTS": 500000,
    "PRIORITY_TIER": "EXPEDITED",
    "DECLARED_LOOP_COUNT": 380,
    "MEASURED_SYNC_DEVIATION_MS_TOTAL": 22800,
    "LINES_OVER_DEVIATION": 38,
    "CA1_RATE_CENTS_PER_HOUR": 36000,
    "CA2_RATE_CENTS_PER_HOUR": 30000,
    "SAMPLED_LOOP_COUNT": 200,
    "LOUDNESS_LUFS": -24.8,
    "SESSION_1_START": "2026-09-10T09:00:00Z",
    "SESSION_1_END": "2026-09-10T11:00:00Z",
    "SESSION_2_START": "2026-09-10T12:00:00Z",
    "SESSION_2_END": "2026-09-10T13:08:00Z",
}

# Operator identities. The PRD makes X-User-ID an opaque operator identifier for
# every role except VoiceTalentUser, so segregation-of-duties scenarios need
# distinct, stable strings.
ADAPTOR_1 = "adaptor-1"
ADAPTOR_2 = "adaptor-2"
ADAPTOR_3 = "adaptor-3"
REVIEWER_1 = "reviewer-1"
REVIEWER_2 = "reviewer-2"
REVIEWER_9 = "reviewer-9"

# Syntactically valid UUIDs that name no stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
UNKNOWN_UUIDS = {
    "title": "00000000-0000-4000-8000-000000000001",
    "cut": "00000000-0000-4000-8000-000000000002",
    "character": "00000000-0000-4000-8000-000000000003",
    "platform_spec": "00000000-0000-4000-8000-000000000004",
    "talent": "00000000-0000-4000-8000-000000000005",
    "adaptation": "00000000-0000-4000-8000-000000000006",
    "assignment": "00000000-0000-4000-8000-000000000007",
    "session": "00000000-0000-4000-8000-000000000008",
    "mix_job": "00000000-0000-4000-8000-000000000009",
    "review": "00000000-0000-4000-8000-00000000000a",
    "retake_item": "00000000-0000-4000-8000-00000000000b",
    "payment": "00000000-0000-4000-8000-00000000000c",
    "studio": "00000000-0000-4000-8000-0000000000ff",
}
