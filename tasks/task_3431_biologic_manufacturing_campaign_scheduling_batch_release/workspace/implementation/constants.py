"""All named constants for the Biologic Campaign Batch Release API.

Values are pinned by PRD.md / SCAFFOLD.yaml. Every constant referenced
anywhere in the implementation is defined here exactly once.
"""
from decimal import Decimal

# --- Logical clock (PRD 2.4) ---
DEFAULT_CLOCK_STR = "2026-09-01T00:00:00Z"

# --- allocated_hours calculation ---
SEED_SHIFT_HOURS = 8
PRODUCTION_BLOCK_HOURS = 24
CHANGEOVER_BLOCK_HOURS = 4

# --- seed_train_timing calculation ---
TRANSFER_WINDOW_HOURS = 36
INOCULATION_WINDOW_HOURS = 24

# --- batch_yield calculation ---
DESIGN_TITER_G_PER_L = Decimal("2.0")
UNITS_PER_GRAM = Decimal("125")
PROVISIONAL_RECOVERY_FACTOR = Decimal("0.8")

# --- excursion_evaluation calculation ---
DELTA_H_KJ_MOL = 83.14472
R_GAS = 0.008314472
KINETIC_RATIO = 10000.0  # DELTA_H_KJ_MOL / R_GAS, exactly 10000.0
MKT_ALLOWANCE_C = Decimal("1.0")
SPIKE_ALLOWANCE_C = Decimal("5.0")
FREEZE_ALLOWANCE_C = Decimal("0.5")
SCREENING_MAX_EXCURSION_COUNT = 2
# detection guards (Shipment IN_TRANSIT -> EXCURSION_HOLD)
DETECT_SPIKE_ABOVE_MAX_C = Decimal("5.0")
DETECT_FREEZE_BELOW_MIN_C = Decimal("0.5")
DETECT_MAX_EXCURSION_COUNT = 2

# --- expiry_dating calculation ---
MIN_REMAINING_SHELF_LIFE_HOURS = 720

# --- comparability_equivalence calculation ---
EXCLUSION_SIGMA = Decimal("1.5")
ABS_MARGIN = Decimal("1.5")
REL_MARGIN = Decimal("0.03")

# --- site_release_posture calculation ---
CRITICAL_DEVIATION_FREEZE_THRESHOLD = 2

# --- material_coverage calculation ---
OVERAGE_FACTOR = Decimal("0.10")

# --- Enum vocabularies ---
AUTHORITIES = ("FDA", "EMA", "PMDA", "MHRA")
MOLECULE_TYPES = ("MONOCLONAL_ANTIBODY", "FUSION_PROTEIN", "RECOMBINANT_ENZYME")
MARKET_SCOPES = ("CLINICAL_ONLY", "COMMERCIAL_ONLY", "BOTH")
DEMAND_TYPES = ("CLINICAL", "COMMERCIAL")
TEST_TYPES = ("CELL_VIABILITY", "TITER", "PURITY", "STERILITY", "ENDOTOXIN")
TEST_PHASES = ("UPSTREAM", "DOWNSTREAM")
DEVIATION_KINDS_MANUAL = ("PROCESS", "COMPLAINT")
DEVIATION_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
FINDING_SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
CHANGE_TYPES = ("PROCESS_CHANGE", "SITE_TRANSFER", "SCALE_UP")
CAMPAIGN_ADVANCE_TARGETS = ("ALLOCATED", "PROPOSED", "SEED_IN_PROGRESS", "PRODUCTION_IN_PROGRESS")
SEED_STAGE_ADVANCE_TARGETS = ("RUNNING", "COMPLETED", "FAILED")
BATCH_ADVANCE_TARGETS = ("DOWNSTREAM", "PROCESS_COMPLETE", "TERMINATED")
SHIPMENT_ACTIONS = ("SHIP", "DELIVER", "CANCEL")
DEVIATION_ACTIONS = ("CLOSE", "REOPEN")
INSPECTION_ACTIONS = ("ISSUE_FINDINGS", "CLOSE")
STUDY_ACTIONS = ("APPROVE_PROTOCOL", "RECORD_ASSESSMENT", "SUBMIT_FILING")
DISPOSITION_DECISIONS = ("RELEASED", "REJECTED")

# Campaign statuses that occupy a train window / count as predecessors
WINDOW_STATUSES = ("PROPOSED", "ALLOCATED", "SEED_IN_PROGRESS", "PRODUCTION_IN_PROGRESS")
# Campaign statuses that consume firm monthly capacity
FIRM_CONSUMING_STATUSES = ("ALLOCATED", "SEED_IN_PROGRESS", "PRODUCTION_IN_PROGRESS")
# Deviation statuses that count as open
OPEN_DEVIATION_STATUSES = ("OPEN", "REOPENED")
# Shipment statuses that encumber batch available_to_ship_units
ENCUMBERING_SHIPMENT_STATUSES = ("PLANNED", "IN_TRANSIT", "EXCURSION_HOLD", "DELIVERED")

# Conclusion admissibility per deviation kind
CONCLUSIONS_BY_KIND = {
    "OOS": ("INVALIDATED_TEST", "CONFIRMED_OOS"),
    "PROCESS": ("CAPA_COMPLETED", "NO_ACTION_REQUIRED"),
    "COMPLAINT": ("CONFIRMED", "UNCONFIRMED"),
}

SYSTEM_USER = "system"
