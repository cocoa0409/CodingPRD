"""Domain thresholds and shared fixture defaults for the wellness booking API.

Every numeric value below is the platform constant named in the product
requirements document; the names mirror the PRD's own vocabulary.
"""

# --- Temporal windows -------------------------------------------------------
LATE_CANCEL_WINDOW_MINUTES = 720          # twelve hours before start_at
CHECKIN_OPEN_MINUTES = 60                 # check-in gate opens 60 minutes early
OFFER_WINDOW_MINUTES = 120                # a waitlist offer lapses after 2 hours
OFFER_HOLD_HOLD_MINUTES = 30              # released seat held when no taker
STANDBY_CONFIRM_WINDOW_MINUTES = 90
STRIKE_RESTORE_WINDOW_HOURS = 72
PORTABILITY_RESPONSE_WINDOW_HOURS = 168
PORTABILITY_ADJUDICATION_WINDOW_HOURS = 336
PORTABILITY_COOLDOWN_DAYS = 30
EXPORT_WINDOW_HOURS = 72
EXPORT_MAX_DOWNLOADS = 3
CLAIM_RESUBMIT_MAX = 1

# --- Strike counters and lifetime caps --------------------------------------
MEMBER_FEE_STRIKE_THRESHOLD = 3
FIRST_OFFENCE_FREE_STRIKES = 1            # prior strikes below 2 are free
STRIKE_MULTIPLIER_CAP = 2                 # never more than 2.0x list price
STRIKE_OFFER_BLOCK_THRESHOLD = 3          # >= blocks a new offer
STRIKE_REVOCATION_THRESHOLD = 5           # reversal of a claimed seat
PACK_MAX_EXTENSION_DAYS = 90
PACK_EXPIRY_GRACE_DAYS = 14
FREEZE_ANNUAL_CAP_DAYS = 60
DAYS_PER_CYCLE = 30
OVER_FREEZE_PENALTY_DAYS = 5
MIN_PAYROLL_PERIOD_DAYS = 7

# --- Money rules ------------------------------------------------------------
DUNNING_LATE_FEE_PCT = 0.10
UNUSED_CREDIT_RETURN_DENOMINATOR = 4

OFF_PEAK_BPS = 8000
STANDARD_BPS = 10000

TIER_PRICE_BPS = {"STARTER": 10000, "GROWTH": 10500, "ENTERPRISE": 11000}
TIER_PRICE_FLOOR_CENTS = {"STARTER": 1500, "GROWTH": 1800, "ENTERPRISE": 2000}

INSTRUCTOR_TEACH_COMMISSION_BPS = {"STARTER": 2000, "GROWTH": 2500, "ENTERPRISE": 3000}
INSTRUCTOR_DEPUTY_COMMISSION_BPS = {"STARTER": 500, "GROWTH": 700, "ENTERPRISE": 900}
PAYROLL_ACCRUAL_CEILING_CENTS = 1200
PAYROLL_TIER_MULTIPLIER = {"STARTER": 1.0, "GROWTH": 1.0, "ENTERPRISE": 1.25}
MARKETPLACE_CHANNEL_BONUS_BPS = 1000
CHANNEL_BONUS_THRESHOLD_CENTS = 150

# --- Canonical tier rows used by fixtures -----------------------------------
TIER_PAYLOADS = {
    "STARTER": {
        "tier": "STARTER", "monthly_fee_cents": 4900, "tier_rank": 1,
        "included_staff_seats": 2, "seat_overage_fee_cents": 1900,
        "marketplace_listing_enabled": False, "staff_payroll_enabled": False,
        "instructor_substitution_enabled": False,
        "waitlist_auto_promotion_enabled": False,
        "crm_client_export_enabled": False, "marketplace_commission_bps": 2000,
    },
    "GROWTH": {
        "tier": "GROWTH", "monthly_fee_cents": 9900, "tier_rank": 2,
        "included_staff_seats": 4, "seat_overage_fee_cents": 1900,
        "marketplace_listing_enabled": True, "staff_payroll_enabled": True,
        "instructor_substitution_enabled": True,
        "waitlist_auto_promotion_enabled": True,
        "crm_client_export_enabled": True, "marketplace_commission_bps": 1500,
    },
    "ENTERPRISE": {
        "tier": "ENTERPRISE", "monthly_fee_cents": 24900, "tier_rank": 3,
        "included_staff_seats": 12, "seat_overage_fee_cents": 1900,
        "marketplace_listing_enabled": True, "staff_payroll_enabled": True,
        "instructor_substitution_enabled": True,
        "waitlist_auto_promotion_enabled": True,
        "crm_client_export_enabled": True, "marketplace_commission_bps": 1200,
    },
}

# --- Canonical fixture dates -------------------------------------------------
CLOCK_JUNE_1 = "2026-06-01T00:00:00Z"
CLOCK_JUNE_19_0400 = "2026-06-19T04:00:00Z"
CLOCK_JUNE_20_0600 = "2026-06-20T06:00:00Z"
CLOCK_JUNE_20_1200 = "2026-06-20T12:00:00Z"
CLOCK_JUNE_20_1700 = "2026-06-20T17:00:00Z"
CLOCK_JULY_15 = "2026-07-15T00:00:00Z"

JUNE_PERIOD = ("2026-06-01T00:00:00Z", "2026-06-30T23:59:59Z")
JULY_PERIOD = ("2026-07-01T00:00:00Z", "2026-07-31T23:59:59Z")

# --- Fixture defaults --------------------------------------------------------
TEST_DEFAULTS = {
    "LEGAL_NAME": "Prana Loft",
    "OWNER_NAME": "Nadia Okafor",
    "HOME_STATE": "CA",
    "TEMPLATE_NAME": "Reformer Flow 50",
    "DURATION_MINUTES": 50,
    "BASE_PRICE_CENTS": 4000,
    "DEFAULT_CAPACITY": 2,
    "CREDIT_COST": 1,
    "BUFFER_MINUTES": 15,
    "INSTRUCTOR_NAME": "Ivy Chen",
    "CLIENT_NAME": "Maya Alvarez",
    "CLIENT_EMAIL": "maya@example.com",
    "SECOND_CLIENT_NAME": "Bea Tan",
    "SECOND_CLIENT_EMAIL": "bea@example.com",
}

# Derived prices for the canonical template at each tier (off-peak, 4000 base).
# list_price_cents = floor(base * off_peak_bps * tier_bps / 100_000_000)
LIST_PRICE_GROWTH_OFF_PEAK = 3360