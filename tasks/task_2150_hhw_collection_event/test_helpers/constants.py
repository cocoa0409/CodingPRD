"""Domain constants: thresholds, the logical-clock epoch and scenario defaults."""

# ─── Containment screen (PRD §3.2) ────────────────────
CONTAINMENT_THRESHOLDS = {
    "MIN_SECONDARY_CONTAINMENT_LITERS": 2000,
    "MIN_STORM_DRAIN_DISTANCE_M": 15.0,
}

# ─── Capacity and scheduling geometry (PRD §3.3, §3.4) ─
THRESHOLDS = {
    "VEHICLES_PER_LANE_HOUR": 12,
    "STAFF_HOURS_PER_VEHICLE": 0.25,
    "LITERS_PER_VEHICLE": 40,
    "REMEDIATED_DERATE": 0.5,
    "SITE_BUFFER_HOURS": 48,
    "SITE_MONTHLY_EVENT_CAP": 2,
    "STAFFER_DECON_BUFFER_MINUTES": 30,
    "MAX_SHIFT_HOURS": 12.0,
    "SLOT_ALIGNMENT_MINUTES": 15,
    "NO_SHOW_SUSPENSION_STRIKES": 2,
    "DEFICIENCY_FREEZE_COUNT": 2,
    "UTILISATION_RESTRICT_PERCENT": 85,
}

# ─── Cost report tiers (PRD §3.9) ─────────────────────
VOLUME_TIERS = {
    "TIER_1_MOBILIZATION_CENTS": 250000,
    "TIER_1_REBATE_PERCENT": 0,
    "TIER_2_FLOOR_KG": 2000.0,
    "TIER_2_MOBILIZATION_CENTS": 180000,
    "TIER_2_REBATE_PERCENT": 3,
    "TIER_3_FLOOR_KG": 8000.0,
    "TIER_3_MOBILIZATION_CENTS": 120000,
    "TIER_3_REBATE_PERCENT": 6,
    "CONTINGENCY_PERCENT": 8,
}

# ─── Logical clock (PRD §2.9) ─────────────────────────
CLOCK_EPOCH_UTC = "2026-08-01T00:00:00.000Z"

# ─── Canonical scenario values ────────────────────────
TEST_DEFAULTS = {
    "PROGRAM_NAME": "Jeffco HHW Program",
    "FISCAL_YEAR": 2027,
    "BUDGET_CENTS": 40_000_000,
    "CEILING_CENTS": 500_000,
    "STAFF_HOURLY_RATE_CENTS": 4200,
    "JURISDICTIONS": ["CO-DEN", "CO-ARV"],
    "SITE_NAME": "Arvada Public Works Yard",
    "SITE_ADDRESS": "5100 Ralston Road",
    "SECONDARY_CONTAINMENT_LITERS": 2000,
    "STORM_DRAIN_DISTANCE_M": 15.0,
    "LANE_COUNT": 4,
    "WINDOW_START_UTC": "2026-09-12T08:00:00.000Z",
    "WINDOW_END_UTC": "2026-09-12T20:00:00.000Z",
    "EVENT_DATE": "2026-09-12",
    "SLOT_START_UTC": "2026-09-12T09:00:00.000Z",
    "SECOND_SLOT_START_UTC": "2026-09-12T09:15:00.000Z",
    "EVENT_DAY_INSTANT": "2026-09-12T09:00:00.000Z",
    "AFTER_WINDOW_INSTANT": "2026-09-12T21:00:00.000Z",
    "HAZWOPER_EXPIRY": "2027-06-30",
    "TSDF_EPA_ID": "COD991300484",
}

# Latex paint — the canonical accepted category.
LATEX = {
    "code": "LATEX_PAINT",
    "display_name": "Latex Paint",
    "acceptance_policy": "ACCEPTED_WITH_LIMIT",
    "compatibility_class": "TOXIC",
    "dot_hazard_class": "NA",
    "max_kg_per_resident_per_event": 25.0,
    "max_kg_per_resident_per_year": 60.0,
    "disposal_rate_cents_per_kg": 155,
}

# Paint solvent — flammable, used for the quantity-limit boundaries.
SOLVENT = {
    "code": "SOLVENT",
    "display_name": "Paint Solvent",
    "acceptance_policy": "ACCEPTED_WITH_LIMIT",
    "compatibility_class": "FLAMMABLE",
    "dot_hazard_class": "3",
    "max_kg_per_resident_per_event": 25.0,
    "max_kg_per_resident_per_year": 60.0,
    "disposal_rate_cents_per_kg": 310,
}

# Pool acid — a second rate class for blended-rate arithmetic.
POOL_ACID = {
    "code": "POOL_ACID",
    "display_name": "Pool Acid",
    "acceptance_policy": "ACCEPTED_WITH_LIMIT",
    "compatibility_class": "CORROSIVE_ACID",
    "dot_hazard_class": "8",
    "max_kg_per_resident_per_event": 20.0,
    "max_kg_per_resident_per_year": 40.0,
    "disposal_rate_cents_per_kg": 480,
}

# Explosives — never accepted at an event.
EXPLOSIVE = {
    "code": "EXPLOSIVE",
    "display_name": "Explosives and Ammunition",
    "acceptance_policy": "REJECTED_ALWAYS",
    "compatibility_class": "OXIDIZER",
    "dot_hazard_class": "1.1",
    "max_kg_per_resident_per_event": 1.0,
    "max_kg_per_resident_per_year": 1.0,
    "disposal_rate_cents_per_kg": 0,
}

# Bulk latex — large ceilings, used to reach the mobilisation tier boundary.
BULK_LATEX = {
    "code": "BULK_LATEX",
    "display_name": "Bulk Latex Paint",
    "acceptance_policy": "ACCEPTED_WITH_LIMIT",
    "compatibility_class": "TOXIC",
    "dot_hazard_class": "NA",
    "max_kg_per_resident_per_event": 3000.0,
    "max_kg_per_resident_per_year": 5000.0,
    "disposal_rate_cents_per_kg": 100,
}
