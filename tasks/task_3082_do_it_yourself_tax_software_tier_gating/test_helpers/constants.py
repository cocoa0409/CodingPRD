"""Domain thresholds — numeric constants fixed by the PRD (§2.5, §3)."""

FREE_FILE_AGI_LIMIT_CENTS = 8400000  # $84,000.00 inclusive upper bound
REFUND_TRANSFER_FEE_CENTS = 4000  # $40.00 bank-partner service fee
STATE_FLAT_RATE = 0.05  # 5% flat rate for every state
GUARANTEE_CAP_CENTS = 100000  # $1,000.00 per-return guarantee cap
AMENDMENT_HOLD_HOURS = 24

BANK_PARTNERS = ("BANK_A", "BANK_B")
ACTIVE_BANK_DISCLOSURE_VERSION = "RTD-2026-1"

DEFAULT_LOGICAL_CLOCK_UTC = "2026-09-01T00:00:00Z"

# Canonical guided-correction texts (PRD §3.7), keyed by rejection code.
CORRECTION_HINTS = {
    "R0000_SSN_MISMATCH": "Verify the SSN exactly as printed on the Social Security card.",
    "R0500_NAME_CONTROL": "Name control mismatch: check last-name spelling against SSA records.",
    "R1000_DUPLICATE_FILED": "A return for this SSN was already accepted; amend instead of refiling.",
    "R2000_DEPENDENT_CLAIMED": "A dependent on this return was claimed elsewhere; review the dependent list.",
    "R3000_MATH_ERROR": "The authority recomputed a line; review the flagged worksheet totals.",
}

TIER_RANKS = {"FREE": 0, "DELUXE": 1, "PREMIER": 2, "SELF_EMPLOYED": 3}

# Standard tier catalog prices used across the tests (cents).
TIER_PRICES = {
    "FREE": {"price_cents": 0, "state_addon_price_cents": 0},
    "DELUXE": {"price_cents": 6999, "state_addon_price_cents": 3999},
    "PREMIER": {"price_cents": 12999, "state_addon_price_cents": 4999},
    "SELF_EMPLOYED": {"price_cents": 19999, "state_addon_price_cents": 5999},
}

# Standard form specifications used across the tests.
FORM_SPECS = {
    "F1040": {"minimum_tier": "FREE", "disqualifies_free_file": False, "counts_toward_refund": False},
    "W2_WH": {"minimum_tier": "FREE", "disqualifies_free_file": False, "counts_toward_refund": True},
    "SCH_E": {"minimum_tier": "DELUXE", "disqualifies_free_file": False, "counts_toward_refund": False},
    "SCH_D": {"minimum_tier": "PREMIER", "disqualifies_free_file": True, "counts_toward_refund": False},
    "F8949": {"minimum_tier": "PREMIER", "disqualifies_free_file": True, "counts_toward_refund": False},
    "F4562": {"minimum_tier": "PREMIER", "disqualifies_free_file": True, "counts_toward_refund": False},
    "SCH_C": {"minimum_tier": "SELF_EMPLOYED", "disqualifies_free_file": True, "counts_toward_refund": False},
}

TEST_DEFAULTS = {
    "TAX_YEAR": 2025,
    "PRIOR_TAX_YEAR": 2024,
    "AGI_CENTS": 1000000,
    "RESIDENT_STATE": "CA",
    "FILING_STATUS": "SINGLE",
}
