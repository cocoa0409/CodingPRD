"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical-clock anchors (all temporal rules read from the logical clock)
CLOCK_EPOCH = "2026-09-01T00:00:00Z"
CLOCK_EPOCH_DATE = "2026-09-01"

# Deficiency streak detection (PRD §3.4)
BID_TRIGGER_DAYS = 30          # BID_PRICE trigger
OTHER_TRIGGER_DAYS = 10        # all other monitored standards
REGAIN_DAYS = 10               # consecutive compliant days to regain
CURE_DAYS = 180                # compliance_due_at = detected_at + 180 days
APPEAL_WINDOW_DAYS = 7         # appeal window after staff determination
BID_THRESHOLD_CENTS = 100      # bid-price threshold at every tier

# Continued (deficiency-monitoring) thresholds per tier (PRD §3.4)
CONT_MVPHS = {"GLOBAL": 5_000_000_000, "CAPITAL": 1_000_000_000}
CONT_MVLS = {
    "GLOBAL_SELECT": 30_000_000_000_000,
    "GLOBAL": 7_500_000_000_000,
    "CAPITAL": 5_000_000_000_000,
}
CONT_HOLDERS = {"GLOBAL_SELECT": 400, "GLOBAL": 400, "CAPITAL": 300}

# Entry standards thresholds (PRD §3.2)
GS_S1_INCOME = 1_100_000_000
GS_S2_MVLS = 45_000_000_000_000
GS_S2_UPHS = 1_250_000
GS_S3_REV = 9_000_000_000_000
GS_S3_MVLS = 20_000_000_000_000
G_S1_SE = 1_500_000_000
G_S1_MVUPH = 800_000_000
G_S2_MVLS = 7_500_000_000_000
G_S2_MVUPH = 2_000_000_000
G_S3_REV = 7_500_000_000_000
G_S3_MVUPH = 2_000_000_000
G_HOLDERS = 400
G_MM = 3
C_BID = 400
C_PHS = 1_000_000
C_HOLDERS = 300
C_MM = 3
C_A1_SE = 500_000_000
C_A2_MVLS = 5_000_000_000_000
C_A3_INCOME = 75_000_000

# Continued standards for tier-transfer gating (PRD §3.5)
CONT_TIER_TRANSFER_GS_MVLS = 30_000_000_000_000
CONT_TIER_TRANSFER_G_MVPH = 5_000_000_000
CONT_TIER_TRANSFER_G_HOLDERS = 400
CONT_TIER_TRANSFER_C_MVPH = 1_000_000_000
CONT_TIER_TRANSFER_C_HOLDERS = 300

# Fee brackets (PRD §3.10) — (lower_shares_incl, upper_shares_incl, amount_min, amount_max)
ENTRY_BRACKETS = {
    "GLOBAL_SELECT": [
        (1, 50_000_000, 150_000_00, 250_000_00),
        (50_000_001, 75_000_000, 200_000_00, 300_000_00),
        (75_000_001, 100_000_000, 250_000_00, 350_000_00),
        (100_000_001, None, 295_000_00, 500_000_00),
    ],
    "GLOBAL": [
        (1, 50_000_000, 150_000_00, 250_000_00),
        (50_000_001, 75_000_000, 200_000_00, 300_000_00),
        (75_000_001, 100_000_000, 250_000_00, 350_000_00),
        (100_000_001, None, 295_000_00, 500_000_00),
    ],
    "CAPITAL": [
        (1, 5_000_000, 50_000_00, 75_000_00),
        (5_000_001, 15_000_000, 75_000_00, 100_000_00),
        (15_000_001, None, 100_000_00, 150_000_00),
    ],
}
ANNUAL_BRACKETS = {
    "GLOBAL_SELECT": [
        (1, 50_000_000, 45_000_00, 105_000_00),
        (50_000_001, 75_000_000, 55_000_00, 125_000_00),
        (75_000_001, 100_000_000, 65_000_00, 145_000_00),
        (100_000_001, None, 75_000_00, 175_000_00),
    ],
    "GLOBAL": [
        (1, 50_000_000, 45_000_00, 105_000_00),
        (50_000_001, 75_000_000, 55_000_00, 125_000_00),
        (75_000_001, 100_000_000, 65_000_00, 145_000_00),
        (100_000_001, None, 75_000_00, 175_000_00),
    ],
    "CAPITAL": [
        (1, 5_000_000, 30_000_00, 50_000_00),
        (5_000_001, 15_000_000, 40_000_00, 65_000_00),
        (15_000_001, None, 50_000_00, 80_000_00),
    ],
}
MID_YEAR_SURCHARGE_CENTS = 1_000_000  # flat $10,000.00 on delisted_mid_year rows


def compute_fee_amount_cents(tier: str, shares_outstanding: int, fee_kind: str,
                             delisted_mid_year: bool = False) -> int:
    """Bracket lookup then clamp into [min, max]; mid-year surcharge added after."""
    table = ENTRY_BRACKETS if fee_kind == "ENTRY" else ANNUAL_BRACKETS
    for lo, hi, amt_min, amt_max in table[tier]:
        if shares_outstanding >= lo and (hi is None or shares_outstanding <= hi):
            amount = min(max(shares_outstanding, amt_min), amt_max)
            if delisted_mid_year:
                amount += MID_YEAR_SURCHARGE_CENTS
            return amount
    raise ValueError(f"no bracket for tier={tier} shares={shares_outstanding}")


# Reusable governance-good committees (pass PRD §3.2 composition checks)
GOOD_BOARD = [
    {"director_name": "D1", "is_independent": True},
    {"director_name": "D2", "is_independent": True},
    {"director_name": "D3", "is_independent": True},
]
GOOD_AUDIT_COMMITTEE = [
    {"director_name": "D1", "is_independent": True, "is_financial_expert": True},
    {"director_name": "D2", "is_independent": True, "is_financial_expert": False},
    {"director_name": "D3", "is_independent": True, "is_financial_expert": False},
]
GOOD_COMPENSATION_COMMITTEE = [
    {"director_name": "D1", "is_independent": True},
    {"director_name": "D2", "is_independent": True},
]
