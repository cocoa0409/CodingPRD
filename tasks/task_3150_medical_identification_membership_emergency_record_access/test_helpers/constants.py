"""Domain thresholds — numeric constants from the PRD fee / pricing / reminder rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_UTC = "2026-09-01T00:00:00Z"

# Membership fee schedule (PRD §3.1).
FEES = {
    "BASE_STANDARD_CENTS": 4000,
    "BASE_PREMIUM_CENTS": 7500,
    "BASE_LIFETIME_CENTS": 50000,
    "TERM_MONTHS_STANDARD": 12,
    "TERM_MONTHS_PREMIUM": 24,
    "DEPENDENT_FACTOR": 0.5,
    "COGNITIVE_SURCHARGE_CENTS": 1000,
}

# Order pricing discounts (PRD §3.4).
ORDER_PRICING = {
    "PREMIUM_ORDER_DISCOUNT_PCT": 0.15,
    "LIFETIME_ORDER_DISCOUNT_PCT": 0.25,
}

# Reminder schedule (PRD §3.7).
REMINDERS = {
    "RENEWAL_LEAD_DAYS": 30,
    "RECORD_UPDATE_CYCLE_DAYS": 180,
}

# Access rate soft cap (PRD §3.6).
ACCESS = {
    "DAILY_ACCESS_SOFT_CAP": 10,
}

# Disclosure section vocabulary (PRD §3.6).
DISCLOSURE_SECTIONS = {"CONDITIONS", "MEDICATIONS", "ALLERGIES", "CONTACTS", "DIRECTIVES"}
