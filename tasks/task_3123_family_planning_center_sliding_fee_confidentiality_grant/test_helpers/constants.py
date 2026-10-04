"""Domain thresholds — numeric constants from the PRD's calculation rules."""

FPL_TABLE = {
    1: 1506000,
    2: 2044200,
    3: 2582400,
    4: 3120600,
    5: 3658800,
    6: 4197000,
    7: 4735200,
    8: 5273400,
}
FPL_INCREMENT = 538200

THRESHOLDS = {
    "SELF_DECLARE_MAX_DISCOUNT_PCT": 80,
    "RAPID_REINSERTION_WINDOW_DAYS": 30,
    "RAPID_LOT_EXPIRY_GRACE_DAYS": 7,
    "CLAIM_MAX_SUBMISSION_ROUND": 3,
}

# Standard logical-clock timestamps used across setups.
CLOCK_START = "2026-09-01T00:00:00Z"
CLOCK_ENCOUNTER_DAY = "2026-09-10T10:00:00Z"
CLOCK_AFTER_SEPTEMBER = "2026-10-02T00:00:00Z"

# Common schedule windows.
ENC_START = "2026-09-10T10:00:00Z"
ENC_END = "2026-09-10T10:30:00Z"
LARC_START = "2026-09-15T10:00:00Z"
LARC_END = "2026-09-15T10:30:00Z"
REPORT_PERIOD_START = "2026-09-01T00:00:00Z"
REPORT_PERIOD_END = "2026-10-01T00:00:00Z"

# Known FPL outcomes under the PRD's FPL table (integer floor, truncated).
FPL_INCOME_FOR_PCT_100 = 1506000   # household 1, exactly the base -> fpl_pct 100
FPL_INCOME_FOR_PCT_99 = 1505999    # household 1, one cent below -> fpl_pct 99
FPL_INCOME_H4_PCT_48 = 1500000     # household 4 -> floor(1500000*100/3120600) = 48
FPL_INCOME_H1_PCT_174 = 2635499    # household 1 -> floor(2635499*100/1506000) = 174
FPL_INCOME_H4_PCT_153 = 4800000    # household 4 -> floor(4800000*100/3120600) = 153
FPL_INCOME_H1_PCT_265 = 4000000    # household 1 -> floor(4000000*100/1506000) = 265
