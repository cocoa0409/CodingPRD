"""Domain thresholds and logical-clock constants (all values from the PRD)."""

# --- Logical clock (PRD §2.4) ---
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
# Canonical starting instant for the composite fixture chains: campaigns plan
# their windows from this instant and seed execution begins at it.
FIXTURE_CLOCK_START = "2026-10-01T00:00:00Z"

# --- allocated_hours block granularities (PRD §3.2) ---
SEED_SHIFT_HOURS = 8
PRODUCTION_BLOCK_HOURS = 24
CHANGEOVER_BLOCK_HOURS = 4

# --- Seed train timing windows (PRD §3.3) ---
TRANSFER_WINDOW_HOURS = 36
INOCULATION_WINDOW_HOURS = 24

# --- Batch yield (PRD §3.4) ---
DESIGN_TITER_G_PER_L = 2.0
UNITS_PER_GRAM = 125
PROVISIONAL_RECOVERY_FACTOR = 0.8

# --- Excursion detection guards (PRD §3.6) ---
# A new reading flips a shipment to EXCURSION_HOLD when any guard trips.
EXCURSION_SPIKE_GUARD_C = 5.0    # above max_storage_temp_c + 5.0
EXCURSION_FREEZE_GUARD_C = 0.5   # below min_storage_temp_c - 0.5
EXCURSION_COUNT_GUARD = 2        # more than 2 readings above max_storage_temp_c

# --- Excursion evaluation (PRD §3.6) ---
DELTA_H_KJ_MOL = 83.14472
R_GAS = 0.008314472
MKT_KINETIC_RATIO = 10000.0  # DELTA_H_KJ_MOL / R_GAS, exact
MKT_ALLOWANCE_C = 1.0
SPIKE_ALLOWANCE_C = 5.0
FREEZE_ALLOWANCE_C = 0.5
SCREENING_MAX_EXCURSION_COUNT = 2

# --- Expiry dating / disposition shelf-life gate (PRD §3.5, §3.6) ---
MIN_REMAINING_SHELF_LIFE_HOURS = 720

# --- Comparability equivalence (PRD §3.7) ---
EXCLUSION_SIGMA = 1.5
ABS_MARGIN = 1.5
REL_MARGIN = 0.03

# --- Site release posture (PRD §2.9) ---
CRITICAL_DEVIATION_FREEZE_THRESHOLD = 2

# --- Material coverage overage (PRD §3.3) ---
OVERAGE_FACTOR = 0.10
