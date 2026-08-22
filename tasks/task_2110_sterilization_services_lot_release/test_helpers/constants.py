"""Domain thresholds and shared test defaults quoted from the PRD."""

# Numeric thresholds that the PRD pins by name.
THRESHOLDS = {
    # Emission rate schedule (dollars per abated kilogram).
    "TIER1_MAX_KG": 50.000,
    "TIER2_MAX_KG": 200.000,
    "TIER1_RATE_USD": 12.00,
    "TIER2_RATE_USD": 18.50,
    "TIER3_RATE_USD": 27.00,
    # Aeration density derating.
    "DENSITY_BREAK_LOW": 0.1000,
    "DENSITY_BREAK_HIGH": 0.2000,
    "DENSITY_FACTOR_LOW": 1.00,
    "DENSITY_FACTOR_MID": 1.25,
    "DENSITY_FACTOR_HIGH": 1.60,
    "RETEST_MULTIPLIER_STEP": 0.5,
    "MAX_RESIDUAL_RETESTS": 2,
    # VDmax dose audit.
    "VDMAX_SAMPLE_SIZE": 100,
    "PASS_INTERVAL_DAYS": 90,
    "CONDITIONAL_INTERVAL_DAYS": 30,
    "MAX_CONSECUTIVE_CONDITIONAL": 2,
    # Unit conversions used by the aggregate load density.
    "KG_TO_G": 1000,
    "M3_TO_CM3": 1000000,
}

# Pagination contract.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The logical clock's startup value, before any client moves it.
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# The instant most fixtures park the clock at before building reference data.
DEFAULT_CLOCK = "2026-08-10T00:00:00Z"

# Opaque operator identifiers. All four opaque roles draw from one space, so
# these must stay distinct wherever segregation of duties is under test.
TEST_DEFAULTS = {
    "ADMIN_USER_ID": "admin-1",
    "OPERATOR_USER_ID": "op-1",
    "ANALYST_USER_ID": "ana-1",
    "OFFICER_USER_ID": "qro-1",
    # Product physical constants: 120.0 kg over 1.2 m3 is exactly 0.1000 g/cm3.
    "PALLET_MASS_KG": 120.0,
    "PALLET_VOLUME_M3": 1.2,
    "ALT_PALLET_MASS_KG": 90.0,
    "ALT_PALLET_VOLUME_M3": 0.8,
    "MAX_ALLOWED_DOSE_KGY": 45.0,
    "MAX_CUMULATIVE_DOSE_KGY": 60.0,
    "ETO_RESIDUAL_LIMIT_PPM": 4.0,
    "ECH_RESIDUAL_LIMIT_PPM": 9.0,
    "ANNUAL_ALLOWANCE_KG": 1000.0,
    "MAX_CONCURRENT_ETO_CYCLES": 2,
    "PALLET_CAPACITY": 8,
    "GAMMA_TURNAROUND_MINUTES": 30,
    "ETO_TURNAROUND_MINUTES": 60,
    "ETO_ABATEMENT_EFFICIENCY_PCT": 96.0,
    "TARGET_DOSE_KGY": 30.0,
    "MIN_DOSE_KGY": 27.0,
    "MAX_DOSE_KGY": 45.0,
    "DENSITY_MIN": 0.1000,
    "DENSITY_MAX": 0.1060,
    "ETO_AERATION_BASE_HOURS": 12,
    "VERIFICATION_DOSE_KGY": 12.5,
    "SAL_EXPONENT": 6,
    "AUDIT_PERFORMED_AT": "2026-08-05T00:00:00Z",
}
