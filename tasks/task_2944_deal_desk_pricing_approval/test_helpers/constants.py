"""Domain constants: the configured commercial rulebook used by the test suite.

Every number here is a value the tests configure through the public API
(desk policy, approval matrix, catalogue, quantity bands, bundle rules,
accounts), or a fixed figure the PRD itself states.
"""

# The logical clock reads exactly this instant before any client sets it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Instant literal helpers used by tests that assert stamped timestamps.
EPOCH_STAMP = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Desk policy revision under test — the seventeen configured numbers.
# ---------------------------------------------------------------------------
POLICY_NAME = "FY26 Deal Desk Policy"

POLICY_CONFIG = {
    "name": POLICY_NAME,
    "margin_floor_pct": 0.35,
    "absolute_margin_floor_pct": 0.22,
    "quote_validity_days": 30,
    "standard_payment_terms_days": 30,
    "uplift_rate_per_30_days": 0.015,
    "max_stack_discount_pct": 0.45,
    "volume_rebate_tier1_min_cents": 5000000,
    "volume_rebate_tier1_pct": 0.02,
    "volume_rebate_tier2_min_cents": 25000000,
    "volume_rebate_tier2_pct": 0.04,
    "surge_window_days": 10,
    "surge_sla_multiplier": 0.5,
    "price_hold_cooldown_days": 30,
    "exception_allowance_cents": 4000000,
    "terms_review_risk_threshold": 30.0,
    "terms_cfo_risk_threshold": 35.0,
}

# ---------------------------------------------------------------------------
# Approval matrix: four contiguous bands covering [0.0, 1.0].
# ---------------------------------------------------------------------------
APPROVAL_TIERS = [
    {
        "tier_level": 1,
        "min_discount_pct": 0.00,
        "max_discount_pct": 0.15,
        "required_role": "DealDeskAnalyst",
        "sla_hours": 8,
        "max_delegation_levels": 0,
    },
    {
        "tier_level": 2,
        "min_discount_pct": 0.15,
        "max_discount_pct": 0.25,
        "required_role": "SalesDirector",
        "sla_hours": 12,
        "max_delegation_levels": 1,
    },
    {
        "tier_level": 3,
        "min_discount_pct": 0.25,
        "max_discount_pct": 0.40,
        "required_role": "VPSales",
        "sla_hours": 24,
        "max_delegation_levels": 1,
    },
    {
        "tier_level": 4,
        "min_discount_pct": 0.40,
        "max_discount_pct": 1.00,
        "required_role": "CFO",
        "sla_hours": 48,
        "max_delegation_levels": 0,
    },
]

# ---------------------------------------------------------------------------
# Catalogue: four products spanning the three revenue recognition categories.
# ---------------------------------------------------------------------------
PRODUCT_CORE = {
    "sku": "CORE-PLAT",
    "name": "Core Platform",
    "product_type": "SUBSCRIPTION_LICENSE",
    "list_unit_price_cents": 120000,
    "unit_cost_cents": 30000,
    "rev_rec_category": "RATABLE",
    "min_term_months": 12,
}

PRODUCT_SUPPORT = {
    "sku": "SUP-PREM",
    "name": "Premium Support",
    "product_type": "SUPPORT_PLAN",
    "list_unit_price_cents": 30000,
    "unit_cost_cents": 6000,
    "rev_rec_category": "RATABLE",
    "min_term_months": 12,
}

PRODUCT_SERVICE = {
    "sku": "SVC-IMPL",
    "name": "Implementation Services",
    "product_type": "PROFESSIONAL_SERVICES",
    "list_unit_price_cents": 200000,
    "unit_cost_cents": 150000,
    "rev_rec_category": "POINT_IN_TIME",
    "min_term_months": 1,
}

PRODUCT_USAGE = {
    "sku": "USG-API",
    "name": "Metered API Calls",
    "product_type": "USAGE_METERED",
    "list_unit_price_cents": 500,
    "unit_cost_cents": 200,
    "rev_rec_category": "USAGE_AS_INCURRED",
    "min_term_months": 12,
}

# Quantity bands on the Core Platform product only.
CORE_VOLUME_TIERS = [
    {"tier_level": 1, "min_quantity": 1, "max_quantity": 49, "tier_discount_pct": 0.00},
    {"tier_level": 2, "min_quantity": 50, "max_quantity": 199, "tier_discount_pct": 0.10},
    {"tier_level": 3, "min_quantity": 200, "tier_discount_pct": 0.18},
]

# Core Platform anchors a 5% bundle discount onto Premium Support.
CORE_SUPPORT_BUNDLE = {"bundle_discount_pct": 0.05, "min_attach_quantity_ratio": 1.0}

# ---------------------------------------------------------------------------
# Customer account under test.
# ---------------------------------------------------------------------------
ACCOUNT_CONFIG = {
    "name": "Northwind Industries",
    "segment": "ENTERPRISE",
    "region": "NA",
    "existing_arr_cents": 0,
}

# ---------------------------------------------------------------------------
# Figures the PRD states outright rather than configuring.
# ---------------------------------------------------------------------------
TERM_MULTIPLIERS = {
    "under_12": 1.10,
    "12_to_23": 1.00,
    "24_to_35": 0.95,
    "36_plus": 0.90,
}

TERM_CATEGORY_WEIGHTS = {
    "PAYMENT_TERMS": 20,
    "SLA_COMMITMENT": 30,
    "INDEMNITY_CAP": 30,
    "TERMINATION_FOR_CONVENIENCE": 30,
    "PRICE_HOLD_RENEWAL": 30,
}

AUTO_APPROVED_REVIEWER_NOTE = "AUTO_APPROVED_BELOW_RISK_THRESHOLD"

VOID_REASON_QUOTE_EXPIRED = "QUOTE_EXPIRED"
VOID_REASON_SUPERSEDED = "SUPERSEDED_BY_NEW_ORDER_FORM"
VOID_REASON_BOOKING_REVERSED = "BOOKING_REVERSED"

# Pagination contract.
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# A syntactically valid identifier that never names a stored record.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
