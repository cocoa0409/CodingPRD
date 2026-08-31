"""Domain thresholds and reusable test literals drawn from the PRD narrative."""

# A well-formed UUID the server never mints; used for every not-found probe.
MISSING_UUID = "00000000-0000-4000-8000-0000000000ff"

# §2.5 — the logical clock reads exactly this at process start.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# The instant every scenario pins the logical clock to before doing work.
CLOCK_BASE = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # §3.6 markup tier ladder, keyed on the base amount in cents.
    "MARKUP_TIER_1_UPPER": 50_000,      # base < 50000 -> 60 percent
    "MARKUP_TIER_2_UPPER": 250_000,     # base < 250000 -> 45 percent
    "MARKUP_TIER_3_UPPER": 1_000_000,   # base < 1000000 -> 32 percent
    "MARKUP_PCT_TIER_1": 60,
    "MARKUP_PCT_TIER_2": 45,
    "MARKUP_PCT_TIER_3": 32,
    "MARKUP_PCT_TIER_4": 22,
    # §3.6 high-cost line cap and correction threshold.
    "HIGH_COST_CAP_HEADROOM_CENTS": 750_000,
    "CORRECTION_VARIANCE_CENTS": 25_000,
    # §3.7 registry gate and deadline.
    "REGISTRY_COMPLETENESS_MIN": 80,
    "REGISTRY_DEADLINE_DAYS": 30,
    "REGISTRY_PROMPT_TURNAROUND_HOURS": 72,
    # §3.7 completeness component weights.
    "SCORE_UDI_BOTH": 30,
    "SCORE_UDI_PARTIAL": 15,
    "SCORE_CONSENT_GRANTED": 25,
    "SCORE_SITE_AND_LATERALITY": 20,
    "SCORE_PROMPT_VERIFICATION": 15,
    "SCORE_LOT_EXPIRY_PRESENT": 10,
    "SCORE_RECALLED_PENALTY": 20,
    # §3.3 occupancy geometry.
    "PATIENT_RECOVERY_BUFFER_MINUTES": 120,
    # §3.8 outreach windows in days, keyed on action_class.
    "OUTREACH_DAYS_CLASS_I": 7,
    "OUTREACH_DAYS_CLASS_II": 30,
    "OUTREACH_DAYS_CLASS_III": 90,
    # §3.11 ops-run rotation window and escalation limit.
    "ROTATION_WINDOW_DAYS": 45,
    "NOTIFICATION_ESCALATION_LIMIT": 2,
    # §3.9 explant credit tiers in whole days.
    "CREDIT_TIER_FULL_MAX_DAYS": 30,
    "CREDIT_TIER_MID_MAX_DAYS": 180,
    "CREDIT_PCT_FULL": 100,
    "CREDIT_PCT_MID": 75,
    "CREDIT_PCT_LOW": 50,
    # §3.10 settlement credit-cap ladder, keyed on gross amount due.
    "CREDIT_CAP_TIER_1_UPPER": 500_000,
    "CREDIT_CAP_TIER_2_UPPER": 2_500_000,
    "CREDIT_CAP_PCT_TIER_1": 20,
    "CREDIT_CAP_PCT_TIER_2": 35,
    "CREDIT_CAP_PCT_TIER_3": 50,
    # §2.9 basis-point scale.
    "BPS_SCALE": 10_000,
    # §3.1 agreement defaults.
    "DEFAULT_INVOICE_TOLERANCE_BPS": 150,
    "DEFAULT_REPLENISHMENT_DAYS": 14,
    # §2.3 pagination bounds.
    "PAGE_LIMIT_DEFAULT": 10,
    "PAGE_LIMIT_MIN": 1,
    "PAGE_LIMIT_MAX": 100,
}

TEST_DEFAULTS = {
    "VENDOR_NAME": "Ortholux Medical",
    "VENDOR_CODE": "ORTHO-1",
    "AGREEMENT_CODE": "AGR-A",
    "PERIOD_START_UTC": "2026-09-01T00:00:00Z",
    "PERIOD_END_UTC": "2026-12-31T23:59:59.999Z",
    "DEVICE_IDENTIFIER": "00812345678905",
    "DESCRIPTION": "Ti Femoral Stem",
    "CHARGE_CODE": "CDM-77140",
    "LIST_CHARGE_CENTS": 600_000,
    "SHELF_LIFE_DAYS": 1095,
    "LOT_NUMBER": "L-4401",
    "EXPIRATION_DATE": "2027-06-30",
    "UDI_SERIAL": "SN-0001",
    "ACQUISITION_COST_CENTS": 400_000,
    "MRN": "MRN-1001",
    "PATIENT_NAME": "Pat One",
    "CASE_NUMBER": "CASE-1",
    "OR_ROOM_CODE": "OR-3",
    "SCHEDULED_START_UTC": "2026-09-10T08:00:00Z",
    "SCHEDULED_END_UTC": "2026-09-10T10:00:00Z",
    "SURGEON_CODE": "SURG-9",
    "ANATOMIC_SITE": "FEMUR_PROXIMAL",
}
