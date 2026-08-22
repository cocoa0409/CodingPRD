"""Numeric constants pinned by the PRD's formulas, thresholds and defaults."""

# ---- logical clock -------------------------------------------------------
SERVER_EPOCH_UTC = "2026-08-01T00:00:00Z"
CLOCK_START = "2026-08-03T06:00:00Z"
CLOCK_START_STAMP = "2026-08-03T06:00:00.000Z"

# ---- run / cycle windows used by the canonical plant scenario ------------
RUN_START = "2026-08-03T06:00:00Z"
RUN_END = "2026-08-04T06:00:00Z"
CURE_START = "2026-08-03T12:00:00Z"
CURE_END = "2026-08-04T00:00:00Z"

# ---- strand jacking force ------------------------------------------------
STRAND_AREA_IN2 = {0.500: 0.153, 0.600: 0.217}
F_PU_KSI = 270.0
JACK_FRACTION = 0.75
SEATING_LOSS_PCT = {
    "LONG_LINE_PRESTRESS": 2.5,
    "SELF_STRESSING_FORM": 4.5,
    "FLAT_BED_RC": 0.0,
}
STRENGTH_CLASS_TEMP_ADJ_PCT = {"C40": 0.0, "C50": 0.0, "C60": 1.5, "C70": 1.5}
MIN_JACK_KIPS_PER_STRAND = 32.0
STRAND_MODULUS_KSI = 28500.0
ELONGATION_TOLERANCE_PCT = 5.0

# ---- cylinder strength ---------------------------------------------------
PI = 3.14159265358979
AREA_4IN = 12.566370614359172
AREA_6IN = 28.274333882308138
OUTLIER_TOLERANCE_PCT = 10.0

# ---- curing energy -------------------------------------------------------
AMBIENT_F = 60.0
COOLDOWN_RATE_F_PER_HR = 20.0
THERM_PER_BHP_HOUR = 0.335
ENERGY_VARIANCE_TOLERANCE_PCT = 15.0

# ---- bed run cost allocation --------------------------------------------
STRAND_COST_CENTS_PER_KIP = 145
BED_TYPE_SETUP_CENTS = {
    "LONG_LINE_PRESTRESS": 180000,
    "SELF_STRESSING_FORM": 240000,
    "FLAT_BED_RC": 90000,
}
OVERHEAD_TIER_1_CENTS = 500000
OVERHEAD_TIER_2_CENTS = 1000000

# ---- load metrics and permit fee ----------------------------------------
TRACTOR_TARE_LB = 32000
LEGAL_WIDTH_FT = 8.50
LEGAL_HEIGHT_FT = 13.50
LEGAL_LENGTH_FT = 53.00
LEGAL_GROSS_WEIGHT_LB = 80000
WIDTH_RATE_DOLLARS_PER_FT = 12.75
HEIGHT_RATE_DOLLARS_PER_FT = 21.40
LENGTH_RATE_DOLLARS_PER_FT = 3.66
PERMIT_BASE_CENTS = 8500
ESCORT_CENTS_EACH = 27500

# ---- repair loop ---------------------------------------------------------
MAX_REINSPECTION_FAILS = 2

# ---- pagination ----------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---- canonical break loads (4.00 in cylinders) ---------------------------
# load_lbf / AREA_4IN rounded half up to whole psi
LBF_2900_PSI = 36443
LBF_3200_PSI = 40213
LBF_3400_PSI = 42726
LBF_3499_PSI = 43970
LBF_3500_PSI = 43983
LBF_3550_PSI = 44611
LBF_3600_PSI = 45239
LBF_4100_PSI = 51523
LBF_5000_PSI = 62832
LBF_3000_PSI = 37700
# 6.00 in cylinder reading exactly 3500 psi
LBF_3500_PSI_6IN = 98960

# ---- canonical tensioning result for 24 x 0.500 in on a 400 ft
#      LONG_LINE_PRESTRESS bed with a C40 mix -----------------------------
JACK_FORCE_C40_KIPS = 768.00
THEORETICAL_ELONGATION_C40_IN = 35.225
MEASURED_ELONGATION_IN = 35.500
DEVIATION_C40_PCT = 0.78
JACK_FORCE_C60_KIPS = 773.32
THEORETICAL_ELONGATION_C60_IN = 35.469
DEVIATION_C60_PCT = 0.09

# ---- canonical curing profile results ------------------------------------
MODELED_THERMS_40BHP = 142.38
ENERGY_COST_MODELED_CENTS = 13526
