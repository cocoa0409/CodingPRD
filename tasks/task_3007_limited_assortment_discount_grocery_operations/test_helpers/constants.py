"""Domain thresholds and rate constants from the PRD's calculation rules.

These are the numeric constants the contract pins: award-score weights, the
panel disqualification threshold, tier shares for the allocation waterfall,
the scan-rate standard and void penalty, the refund multipliers, the cart
coin value, and the per-role hourly labor rates.
"""

# tender award scoring
W_PANEL = 0.5
W_PRICE = 0.3
W_QUALITY = 0.2
PANEL_MIN_SCORE = 60
SUPPLIER_INITIAL_QUALITY_SCORE = 80.0
DISQUALIFIED_SCORE_MARKER = -1.0

# finds allocation waterfall
TIER_SHARE_HIGH_VOLUME = 0.6
TIER_SHARE_STANDARD = 0.4

# register shift scan rate
SCAN_TARGET = 1000
VOID_PENALTY = 2

# double-refund guarantee
GUARANTEE_MULTIPLIER = 2.0
STANDARD_MULTIPLIER = 1.0

# cart coin ledger
COIN_VALUE_CENTS = 25

# labor windows
ROLE_RATE_CENTS_PER_HOUR = {
    "CASHIER": 1700,
    "STOCKER": 1800,
    "SHIFT_LEAD": 2400,
}
MAX_WINDOWS_PER_ISO_WEEK = 6

# claims
CLAIM_WINDOW_DAYS = 45

# sku cap band
SKU_CAP_MIN = 1
SKU_CAP_MAX = 5
SKU_CAP_DEFAULT = 2
MIN_SOURCES_DEFAULT = 2

# The contract's logical clock default before any set call.
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"
