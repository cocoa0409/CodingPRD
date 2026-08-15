"""Domain thresholds and numeric constants from the PRD's calculation rules.

Sources: PRD section 2.7 (risk index), 3.2 (inspection tolerance), 3.4
(welding heat dose), 3.6 (UN38.3 composite score), 3.7 (SOC bands),
3.8 (carrier charge), 3.9 (safe discharge and recall severity).
"""

# --- PRD section 2.7: compliance risk index ---
RISK_INDEX_INITIAL = 100
RISK_INDEX_FLOOR = 0
RISK_DECREMENT_LOT_FAIL_HARD = 3
RISK_DECREMENT_DOSSIER_FAIL = 5
SEVERITY_WEIGHT = {"CLASS_I": 15, "CLASS_II": 8, "CLASS_III": 3}

# --- PRD section 3.2: receiving inspection ---
SOC_TOLERANCE_PERCENT = 2.0
RETEST_CYCLE_LIMIT = 2

# --- PRD section 3.4: welding heat dose ---
WELD_BASE_DOSE_PER_PROFILE = {
    "WELD_PROFILE_A": 12.0,
    "WELD_PROFILE_B": 18.0,
    "WELD_PROFILE_C": 25.0,
}
WELD_PROFILE_CEILING_J = {
    "WELD_PROFILE_A": 450.0,
    "WELD_PROFILE_B": 700.0,
    "WELD_PROFILE_C": 1050.0,
}
NOMINAL_FORCE_N = 30.0
FORCE_FACTOR_MIN = 0.7
FORCE_FACTOR_MAX = 1.4

# --- PRD section 3.3: BOM energy ---
NOMINAL_CELL_VOLTAGE = 3.6

# --- PRD section 3.6: UN38.3 composite score ---
UN_WEIGHTS = {"T1": 10, "T2": 15, "T3": 12, "T4": 13, "T5": 15, "T6": 15, "T7": 10, "T8": 10}
PASS_THRESHOLD = 85.0
REF_ALT_KPA = 11.6
REF_THERMAL_CYCLES = 10
REF_VIBRATION_MIN = 180
REF_SHOCK_G = 150

# --- PRD section 3.7: SOC bands ---
SOC_LOW_MAX_EXCLUSIVE = 30.0
SOC_MID_MAX_INCLUSIVE = 60.0
HYSTERESIS_PERCENT = 2.0

# --- PRD section 3.8: carrier charge ---
CARRIER_TIERS = [
    (0, 500, 0.12),
    (500, 2000, 0.09),
    (2000, 5000, 0.06),
    (5000, None, 0.04),
]
DG_MULTIPLIER = {"UN3480": 1.25, "UN3481": 1.15, "UN3090": 1.35, "UN3091": 1.20}
WEIGHT_SURCHARGE_CENTS_PER_KG = 40

# --- PRD section 3.9: safe discharge ---
SAFE_DISCHARGE_MAX_PERCENT = 30.0

# --- Shared test data conventions ---
# A 4-cell BOM at 3000 mAh per cell yields 4 * 3000 * 3.6 / 1000 = 43.20 Wh.
DEFAULT_RATED_CAPACITY_MAH = 3000
DEFAULT_CELLS_REQUIRED = 4
DEFAULT_PACK_ENERGY_WH = 43.20
DEFAULT_RECEIVING_SOC = 40.0  # SOC_MID under the plain threshold variant

# Standard passing UN38.3 matrix: every numeric at its reference ceiling and
# every boolean true, yielding a composite score of exactly 100.
STANDARD_PASSING_MATRIX = {
    "altitude_sim_kpa": 11.6,
    "thermal_cycles": 10,
    "vibration_minutes": 180,
    "shock_g_peak": 150.0,
    "external_short_circuit_ok": True,
    "impact_crush_ok": True,
    "overcharge_ok": True,
    "forced_discharge_ok": True,
}

# Standard under-ceiling weld (profile A): 8 * 80.0 * 0.015 * 12.0 * 1.0 = 115.20 J.
STANDARD_WELD = {
    "weld_count": 8,
    "current_amps": 80.0,
    "pulse_ms": 15,
    "electrode_force_n": 30.0,
}
STANDARD_WELD_HEAT_DOSE_J = 115.20
