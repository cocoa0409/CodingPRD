"""Domain thresholds and pinned literals from the PRD calculations.

PRD §2.6 fixes the citator weight matrix and signal thresholds; §3.4 fixes the
bulk-rate platform defaults; §2.4 fixes the logical-clock startup instant.
PRD §3.6 names the net-terms period symbolically as NET_TERMS_DAYS without a
numeric value; the design instances pin the concrete offset used by the
overdue tests (an invoice issued 2026-09-10 falls due 2026-10-10), so that
pinned literal is defined here as a named constant for the hand-off audit.
Tests that walk the overdue boundary read `due_at` back from the issued
invoice and step the clock relative to it, so they hold for any positive
net-terms period; NET_TERMS_DAYS documents the design-pinned value.
"""

# --- Citator scoring (PRD §2.6) ---
SIGNAL_RED_MIN = 80
SIGNAL_YELLOW_MIN = 40

CITATOR_WEIGHTS = {
    "OVERRULED": {"EXAMINED": 100, "DISCUSSED": 80, "CITED": 50, "MENTIONED": 20},
    "CRITICIZED": {"EXAMINED": 60, "DISCUSSED": 45, "CITED": 25, "MENTIONED": 10},
    "QUESTIONED": {"EXAMINED": 50, "DISCUSSED": 35, "CITED": 20, "MENTIONED": 8},
    "DISTINGUISHED": {"EXAMINED": 20, "DISCUSSED": 15, "CITED": 8, "MENTIONED": 3},
    "FOLLOWED": {"EXAMINED": -30, "DISCUSSED": -20, "CITED": -10, "MENTIONED": -4},
    "CITED_NEUTRALLY": {"EXAMINED": 0, "DISCUSSED": 0, "CITED": 0, "MENTIONED": 0},
}

# --- Bulk-rate platform defaults (PRD §3.4) ---
DEFAULT_BULK_HOURLY_LIMIT = 100
DEFAULT_BULK_DAILY_LIMIT = 500

# --- Logical clock (PRD §2.4) ---
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# --- Net terms (PRD §3.6 names NET_TERMS_DAYS symbolically) ---
# Design-pinned literal: issued 2026-09-10 -> due 2026-10-10 (30 days).
NET_TERMS_DAYS = 30

# --- Clock instants used across fixtures ---
CLOCK_SEP_05 = "2026-09-05T00:00:00Z"
CLOCK_SEP_10 = "2026-09-10T00:00:00Z"
CLOCK_SEP_15 = "2026-09-15T00:00:00Z"
CLOCK_SEP_20 = "2026-09-20T00:00:00Z"
CLOCK_OCT_05 = "2026-10-05T00:00:00Z"

# --- Billing window shared by most invoice recipes ---
SEPT_PERIOD_START = "2026-09-01"
SEPT_PERIOD_END = "2026-10-01"

# --- Canonical worked-example invoice figures (PRD §3.6) ---
# Flat plan: base 5000, included 2 searches / 1 view, overage 250/105,
# 15% volume discount at >= 4 combined overage units; usage 5 SEARCH + 4 DOC_VIEW.
WORKED_FLAT_TOTAL_CENTS = 5906
WORKED_FLAT_OVERAGE_CENTS = 906
WORKED_TXN_TOTAL_CENTS = 1980

# --- Non-existent UUID reused for 404 tests (well-formed, never created) ---
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
