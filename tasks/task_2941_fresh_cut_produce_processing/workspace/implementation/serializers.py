"""Entity serializers. Field lists mirror SCAFFOLD entities exactly."""

COMMON = ("created_at", "updated_at", "version")

PRODUCT = (
    "id",
    "code",
    "name",
    "commodity_class",
    "allergen_group",
    "min_dwell_seconds",
    "min_spin_rpm",
    "min_antimicrobial_ppm",
    "base_shelf_life_days",
    "min_yield_pct",
    "hold_and_release_required",
    "active_spec_count",
) + COMMON

CUSTOMER_SPEC = (
    "id",
    "product_id",
    "customer_code",
    "channel",
    "spec_revision",
    "status",
    "superseded_at",
    "max_shelf_life_days_offered",
    "min_remaining_shelf_life_days_at_ship",
    "atmosphere_required",
    "case_net_weight_lb",
    "code_date_format",
) + COMMON

GROWER_LOT = (
    "id",
    "grower_code",
    "ranch_block",
    "commodity_class",
    "harvest_datetime",
    "water_source",
    "adjacent_animal_operation",
    "preharvest_test_result",
    "prior_rejected_receipt_count",
    "status",
    "preharvest_risk_score",
    "trailing_risk_score",
    "out_of_spec_receipt_count",
    "env_positive_run_count",
    "recalled_at",
) + COMMON

RAW_RECEIPT = (
    "id",
    "grower_lot_id",
    "received_at",
    "pulp_temp_c",
    "gross_weight_lb",
    "tare_weight_lb",
    "net_weight_lb",
    "trim_loss_lb",
    "accepted_lb",
    "remaining_lb",
    "temp_grade",
    "shelf_life_deduction_days",
    "status",
    "override_justification",
    "dispositioned_by_user_id",
) + COMMON

LINE = (
    "id",
    "line_code",
    "required_disassembly_component_count",
    "max_atp_rlu",
    "posture",
    "open_corrective_action_count",
    "last_validated_sanitation_at",
    "last_run_allergen_group",
    "last_run_ended_at",
) + COMMON

WASH_SYSTEM = (
    "id",
    "system_code",
    "water_volume_gal",
    "max_concurrent_runs",
    "status",
    "last_changeout_at",
    "weighted_load_lb",
    "organic_load_index",
    "target_free_chlorine_ppm",
    "changeout_count",
    "reading_sequence_high_water",
) + COMMON

READING = (
    "id",
    "wash_system_id",
    "sequence_no",
    "reading_at",
    "free_chlorine_ppm",
    "ph",
    "orp_mv",
    "turbidity_ntu",
    "taken_by_user_id",
    "organic_load_index_at_reading",
    "target_free_chlorine_ppm_at_reading",
    "topup_ppm_required",
    "below_target",
    "created_at",
)

PROCESS_RUN = (
    "id",
    "line_id",
    "product_id",
    "customer_spec_id",
    "wash_system_id",
    "rework_source_run_id",
    "planned_start_at",
    "planned_end_at",
    "crew_size",
    "run_status",
    "disposition_status",
    "started_at",
    "closed_at",
    "target_ppm_at_start",
    "required_dwell_seconds_at_start",
    "actual_dwell_seconds",
    "spin_rpm",
    "spin_seconds",
    "atmosphere_actual",
    "water_gal_used",
    "cases_produced",
    "input_lb",
    "output_lb",
    "yield_pct",
    "min_ppm_observed",
    "antimicrobial_excursion_count",
    "allergen_changeover_required",
    "provisional_shelf_life_days",
    "provisional_code_date",
    "final_shelf_life_days",
    "final_code_date",
    "total_run_cost_cents",
    "per_case_cost_cents",
    "cost_remainder_cents",
    "cases_available",
    "cases_on_hold",
    "cases_shipped",
    "cases_destroyed",
) + COMMON

LOT_CONSUMPTION = (
    "id",
    "process_run_id",
    "raw_receipt_id",
    "consumed_lb",
    "status",
    "recorded_by_user_id",
    "voided_at",
) + COMMON

FINISHED_CASE = (
    "id",
    "process_run_id",
    "case_sequence",
    "case_code",
    "net_weight_lb",
    "code_date",
    "code_date_label",
    "allocated_cost_cents",
    "status",
    "shipped_at",
) + COMMON

HOLD_RECORD = (
    "id",
    "process_run_id",
    "reason",
    "status",
    "test_round",
    "latest_test_type",
    "latest_test_result",
    "latest_apc_cfu_g",
    "resulted_by_user_id",
    "released_by_user_id",
    "cases_held_count",
    "shipped_case_count",
    "opened_at",
    "closed_at",
) + COMMON

SANITATION_EVENT = (
    "id",
    "line_id",
    "shift",
    "scheduled_for",
    "is_allergen_changeover",
    "sequence_no",
    "status",
    "performed_by_user_id",
    "validated_by_user_id",
    "disassembled_component_count",
    "atp_rlu",
    "allergen_swab_result",
    "attempt_count",
    "failed_reason",
    "validated_at",
) + COMMON

ENV_SWAB = (
    "id",
    "line_id",
    "zone",
    "site_code",
    "organism",
    "collected_at",
    "result",
    "resulted_at",
    "resulted_by_user_id",
) + COMMON

CORRECTIVE_ACTION = (
    "id",
    "line_id",
    "source_type",
    "source_ref_id",
    "severity",
    "status",
    "action_taken",
    "implemented_by_user_id",
    "verified_by_user_id",
    "reopen_count",
    "opened_at",
    "verified_at",
) + COMMON


def _shape(fields):
    def serialize(row):
        return {name: row.get(name) for name in fields}

    return serialize


product = _shape(PRODUCT)
customer_spec = _shape(CUSTOMER_SPEC)
grower_lot = _shape(GROWER_LOT)
raw_receipt = _shape(RAW_RECEIPT)
line = _shape(LINE)
wash_system = _shape(WASH_SYSTEM)
reading = _shape(READING)
process_run = _shape(PROCESS_RUN)
lot_consumption = _shape(LOT_CONSUMPTION)
finished_case = _shape(FINISHED_CASE)
hold_record = _shape(HOLD_RECORD)
sanitation_event = _shape(SANITATION_EVENT)
environmental_swab = _shape(ENV_SWAB)
corrective_action = _shape(CORRECTIVE_ACTION)
