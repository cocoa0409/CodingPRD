"""Domain thresholds — numeric constants from the PRD calculations."""

THRESHOLDS = {
    # recommended_firmness
    "BASE_SIDE": 35,
    "BASE_BACK": 55,
    "BASE_STOMACH": 65,
    "BASE_COMBINATION": 50,
    "WEIGHT_UNDER_130": -10,
    "WEIGHT_OVER_230": 10,
    "FEEL_PLUSH": -10,
    "FEEL_FIRM": 10,
    "PARTNER_ADJ": -5,
    "FIRMNESS_MIN": 5,
    "FIRMNESS_MAX": 100,
    # order_totals
    "DISCOUNT_TIER1_SUBTOTAL": 500000,
    "DISCOUNT_TIER2_SUBTOTAL": 1000000,
    "DELIVERY_FEE_CENTS": 9900,
    "FREE_DELIVERY_SUBTOTAL": 200000,
    # financing_schedule
    "ALLOWED_TERMS": (12, 24, 36),
    "DEFERRED_PROMO_MONTHS": 12,
    "MAX_PRINCIPAL_CENTS": 500000,
    # sleep_score
    "TARGET_SLEEP_MINUTES": 480,
    "RESTLESSNESS_PENALTY_PER_EVENT": 2,
    "TARGET_HEART_RATE": 60,
    # prorated_warranty_credit
    "WARRANTY_MONTHS_STRUCTURAL": 120,
    "WARRANTY_MONTHS_CHAMBER": 60,
    "WARRANTY_MONTHS_PUMP": 36,
    "WARRANTY_MONTHS_ELECTRONICS": 24,
    "NIGHTS_PER_MONTH": 30,
    # restocking_refund
    "RESTOCKING_FEE_MIN_CENTS": 9900,
    # trial
    "TRIAL_NIGHTS": 100,
    # window slots
    "VISIT_BASE_SLOTS": 2,
    "REMOVAL_EXTRA_SLOTS": 1,
}

# Logical clock startup default pinned by the PRD.
CLOCK_START = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "WINDOW_START": "2026-09-02T08:00:00Z",
    "WINDOW_END": "2026-09-02T12:00:00Z",
    "TEAM_ID": "T1",
    "CHECKLIST_ALL_TRUE": {
        "base_assembled": True,
        "chambers_connected": True,
        "remote_configured": True,
        "connectivity_verified": True,
    },
    "CHECKLIST_ALL_FALSE": {
        "base_assembled": False,
        "chambers_connected": False,
        "remote_configured": False,
        "connectivity_verified": False,
    },
}
