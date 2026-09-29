"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted from PRD prose, not inferred.
"""

# ---------------------------------------------------------------- clock
# PRD 2.5: "Before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z".
CLOCK_DEFAULT_INSTANT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"


# ------------------------------------------------------------ pagination
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}


# -------------------------------------------------------------- geometry
GEOMETRY = {
    # PRD 3.3: a further 122 centimetres of run-out for a PLASTIC_SLIDE.
    "SLIDE_RUNOUT_CM": 122,
    # PRD 3.3: "If that maximum ever exceeds 305 centimetres, the operation
    # that would have produced it is refused".
    "MAX_CRITICAL_FALL_HEIGHT_CM": 305,
    # PRD 3.3: absolute minimum required surfacing depth.
    "MIN_REQUIRED_SURFACING_DEPTH_CM": 15,
    # PRD 3.3: base attenuation depth tiers.
    "EWF_BASE_LE_150": 23,
    "EWF_BASE_LE_200": 30,
    "EWF_BASE_ABOVE_200": 38,
    "RUBBER_BASE_LE_150": 5,
    "RUBBER_BASE_LE_200": 8,
    "RUBBER_BASE_ABOVE_200": 13,
    "TODDLER_UPLIFT_CM": 5,
    "CLAY_UPLIFT_CM": 3,
    "TIER_1_FALL_HEIGHT_CM": 150,
    "TIER_2_FALL_HEIGHT_CM": 200,
}


# ------------------------------------------------------- quote pricing
QUOTE_PRICING = {
    # PRD 3.5 step two: non-default colour raises the base line by seven percent.
    "COLOUR_UPLIFT_PCT": 7,
    # PRD 3.5 step four: flat base of 48000 cents plus 1250 cents per priced unit.
    "FREIGHT_BASE_CENTS": 48000,
    "FREIGHT_PER_UNIT_CENTS": 1250,
    # PRD 3.5 step five: volume discount tiers, selected on subtotal_cents alone.
    "DISCOUNT_TIER_6PCT_MIN_SUBTOTAL_CENTS": 5000000,
    "DISCOUNT_TIER_3PCT_MIN_SUBTOTAL_CENTS": 2000000,
    "DISCOUNT_RATE_HIGH_PCT": 6,
    "DISCOUNT_RATE_LOW_PCT": 3,
}


# --------------------------------------------------- fundraising waterfall
ALLOCATION = {
    # PRD 3.6: the surfacing target is subtotal_cents multiplied by twenty percent.
    "SURFACING_TARGET_PCT": 20,
}


# ------------------------------------------------------ community review
COMMUNITY_REVIEW = {
    # PRD 3.4: the sum of yes_votes and no_votes must be at least 25.
    "MIN_TURNOUT": 25,
    # PRD 3.4: exactly 60.0 percent approves.
    "APPROVAL_THRESHOLD_PCT": 60.0,
}


# ------------------------------------------------------------- retrofit
RETROFIT = {
    # PRD 3.9: eighteen percent surcharge on a LEGACY replacement model.
    "LEGACY_SURCHARGE_PCT": 18,
    # PRD 3.9: handling is waived at or above 250000 cents of line amount.
    "HANDLING_WAIVER_LINE_CENTS": 250000,
    "HANDLING_FLAT_CENTS": 3500,
}


# --------------------------------------------------------------- warranty
WARRANTY = {
    # PRD 3.9: elapsed_years divides the day count by 365 and discards the fraction.
    "DAYS_PER_YEAR": 365,
    "PRORATED_CATEGORIES": ["POST", "DECK", "METAL_CLIMBER"],
    "STEP_CATEGORIES": ["PLASTIC_SLIDE", "HARDWARE_KIT"],
}


# -------------------------------------------------------------- installer
INSTALLER = {
    # PRD 3.8: one fully clear calendar day of travel buffer between bookings.
    "TRAVEL_BUFFER_DAYS": 1,
    # PRD 3.8: the suspension threshold is one failed post-installation audit.
    "AUDIT_FAILURE_SUSPENSION_THRESHOLD": 1,
}


# ------------------------------------------------------------ rework loop
JOB = {
    # PRD 3.8: START is admissible only while rework_cycles is strictly less than 2.
    "MAX_REWORK_CYCLES": 2,
}


# Convenience defaults reused by the payload factories.
TEST_DEFAULTS = {
    "STANDARD_CODE": "ASTM_F1487",
    "STANDARD_EDITION_YEAR": 2024,
    "STANDARD_EFFECTIVE_FROM": "2024-01-01",
    "MIN_USE_ZONE_CLEARANCE_CM": 183,
    "MAX_FALL_HEIGHT_CM_TODDLER": 122,
    "MAX_FALL_HEIGHT_CM_PRESCHOOL": 152,
    "MAX_FALL_HEIGHT_CM_SCHOOL_AGE": 244,
    "SITE_LENGTH_CM": 3000,
    "SITE_WIDTH_CM": 1200,
    "BUDGET_CENTS": 500000,
    "FUNDRAISING_DEADLINE": "2026-12-31",
    "QUOTE_VALID_UNTIL": "2026-10-31",
    "CREW_CAPACITY_PER_DAY": 6,
    "CERTIFICATION_EXPIRES_ON": "2030-12-31",
}
