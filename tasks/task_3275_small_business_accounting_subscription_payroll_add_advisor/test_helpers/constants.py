"""Domain thresholds and rate-card constants.

Sourced from the PRD's calculation rules and prose: wholesale discount
ceilings per ProAdvisor tier, payroll rate-card snapshots, tax rates by
region, pagination defaults, and the boot-time logical clock.
"""

# Logical clock bootstrap (PRD 2.7: "At boot, the current time is exactly
# 2026-09-01T00:00:00Z").
CLOCK_PATH = "/api/_clock/set_current_utc"
CLOCK_INITIAL_INSTANT = "2026-09-01T00:00:00Z"

# Wholesale discount ceilings by ProAdvisor tier (PRD 3.5 / 3.10).
SILVER_CEILING = 0.20
GOLD_CEILING = 0.35
PLATINUM_CEILING = 0.50
TIER_CEILINGS = {
    "SILVER": SILVER_CEILING,
    "GOLD": GOLD_CEILING,
    "PLATINUM": PLATINUM_CEILING,
}

# Payroll rate card snapshots (PRD 3.4).
SELF_SERVICE_BASE_FEE_CENTS = 4500
SELF_SERVICE_PER_EMPLOYEE_FEE_CENTS = 600
FULL_SERVICE_BASE_FEE_CENTS = 8500
FULL_SERVICE_PER_EMPLOYEE_FEE_CENTS = 1000

PAYROLL_RATE_CARD = {
    "SELF_SERVICE": {
        "base_fee_cents": SELF_SERVICE_BASE_FEE_CENTS,
        "per_employee_fee_cents": SELF_SERVICE_PER_EMPLOYEE_FEE_CENTS,
    },
    "FULL_SERVICE": {
        "base_fee_cents": FULL_SERVICE_BASE_FEE_CENTS,
        "per_employee_fee_cents": FULL_SERVICE_PER_EMPLOYEE_FEE_CENTS,
    },
}

# Sales tax rates by region (PRD 2.5 / 3.5).
TAX_RATE_US = 0.0
TAX_RATE_UK = 0.20
TAX_RATE_EU = 0.21
TAX_RATES_BY_REGION = {
    "US": TAX_RATE_US,
    "UK": TAX_RATE_UK,
    "EU": TAX_RATE_EU,
}

# Billing / payroll periodicity.
DAYS_IN_BILLING_MONTH = 30
TRIAL_DAYS = 30
READ_ONLY_WINDOW_DAYS = 365
TRANSFER_EXPIRY_DAYS = 14
EXPORT_DOWNLOAD_WINDOW_DAYS = 30
STALE_RECON_AGE_DAYS = 45
INVOICE_PAST_DUE_DAYS = 5
SUBSCRIPTION_SUSPEND_DAYS = 30
CONFLICT_AUTO_PAUSE_THRESHOLD = 3

# Pagination defaults (PRD 2.3).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# Migration list-size ceiling.
MIGRATION_LIST_LIMIT = 750000

# Wholesale discount input range.
WHOLESALE_DISCOUNT_MIN = 0.0
WHOLESALE_DISCOUNT_MAX = 0.50

# Roles (must match the PRD's exact role strings).
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_COMPANY_USER = "CompanyUser"
ROLE_ACCOUNTANT_USER = "AccountantUser"
