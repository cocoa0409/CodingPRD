"""Domain thresholds and defaults from the PRD calculations (§2.6, §3)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"

# Fixed month length for departure proration (PRD §3.10).
FIXED_MONTH_DAYS = 30
# Termination notice window in days (PRD §3.10).
DEPARTURE_NOTICE_DAYS = 14
# Offer TTL in hours (PRD §3.5).
OFFER_TTL_HOURS = 72
# Write-off floor in days past due (PRD §3.4).
WRITE_OFF_FLOOR_DAYS = 90
# Overdue -> collections escalation in days past due (PRD §3.4).
COLLECTIONS_ESCALATION_DAYS = 30
# Auto invoice due-date offset in days (PRD §3.4).
AUTO_INVOICE_DUE_OFFSET_DAYS = 7
# Basis-point denominator (PRD §2.6).
BPS_DENOMINATOR = 10000
# Maximum referral fee in basis points (PRD §3.2, §3.11).
MAX_REFERRAL_FEE_BPS = 5000
# Open-ended schedule sentinel effective_to (PRD §3.2).
OPEN_ENDED_SENTINEL = "9999-12-31T00:00:00Z"
# Maximum negotiation rounds (PRD §3.5).
MAX_OFFER_ROUNDS = 4
# Supervision cadence values (PRD §2.9, §3.10).
SUPERVISION_CADENCE_ACTIVE_DAYS = 30
SUPERVISION_CADENCE_WIND_DOWN_DAYS = 7
# Fixed CDA review ladder (PRD §3.6).
REVIEW_LADDER = ["COMPLIANCE_REVIEW", "TRUST_REVIEW", "BROKER_SIGNOFF"]

# Shared fixture literals used across the test suite.
FIXTURE = {
    "OFFICE_NAME": "Denver Central",
    "OFFICE_MARKET": "DEN",
    "OFFICE_TARGET": 25,
    "OFFICE2_NAME": "Phoenix North",
    "OFFICE2_MARKET": "PHX",
    "OFFICE2_TARGET": 10,
    "SCHEDULE_NAME": "95/5 Desk Plan",
    "DESK_FEE_CENTS": 300000,
    "OVERHEAD_SHARE_BPS": 500,
    "RETENTION_BPS": 9500,
    "REFERRAL_FEE_BPS": 2500,
    "TECH_MONTHLY_CENTS": 25000,
    "MARKETING_MONTHLY_CENTS": 40000,
    "SCHED_FROM": "2026-01-01T00:00:00Z",
    "SCHED_TO": "9999-12-31T00:00:00Z",
    "ALICE_NAME": "Alice Agent",
    "ALICE_EMAIL": "alice@x.com",
    "ALICE_LICENSE": "LIC-A-001",
    "BOB_NAME": "Bob Agent",
    "BOB_EMAIL": "bob@x.com",
    "BOB_LICENSE": "LIC-B-002",
    "CAROL_NAME": "Carol Agent",
    "CAROL_EMAIL": "carol@x.com",
    "CAROL_LICENSE": "LIC-C-003",
    "OFFER_LISTING": "L-100",
    "OFFER_BUYER": "Buyer One",
    "OFFER_PRICE_CENTS": 50000000,
    "TXN_SALE_PRICE_CENTS": 50000000,
    "TXN_GCI_CENTS": 1000000,
    "MONTHLY_INVOICE_CENTS": 365000,
    "BILLING_MONTH": "2026-09",
}
