"""Entity schemas: field sets, per-entity defaults and row construction.

Read from SCAFFOLD.yaml §1.1 and PRD §2.10 (`id`, `created_at`, `updated_at`,
`version` on every entity; the read-only derived readings are ordinary computed
fields on the same row).
"""

import db
from core import D, now_iso, new_id, rhu

# entity key -> table name
TABLE = {
    "Corridor": "corridors",
    "Terminal": "terminals",
    "DriverProspect": "driver_prospects",
    "StateAuthority": "state_authorities",
    "LaunchReadinessCheck": "launch_readiness_checks",
    "RunPlan": "run_plans",
    "Carrier": "carriers",
    "ShipperCommitment": "shipper_commitments",
    "TerminalServiceWindow": "terminal_service_windows",
    "RemoteSupportAssignment": "remote_support_assignments",
    "IncidentReport": "incident_reports",
    "RegulatoryEngagement": "regulatory_engagements",
    "SafetyCase": "safety_cases",
    "MaintenanceProgram": "maintenance_programs",
    "MultiDayHold": "multi_day_holds",
    "DriverTransition": "driver_transitions",
    "LedgerCheckpoint": "ledger_checkpoints",
    "FleetUnit": "fleet_units",
    "RunPlanChassis": "run_plan_chassis",
    "ShippingInstruction": "shipping_instructions",
    "ContainerUnit": "container_units",
    "RunPlanHauler": "run_plan_haulers",
    "SecurityRecord": "security_records",
    "ClauseVariant": "clause_variants",
    "AgreementCode": "agreement_codes",
}

# entity key -> {input field: default}.  A field whose default is REQUIRED must
# be supplied by the client (§2.11 malformed-request rule).
REQUIRED = object()

INPUT_FIELDS = {
    "Corridor": {
        "corridor_name": REQUIRED,
        "origin_terminal_id": REQUIRED,
        "destination_terminal_id": REQUIRED,
        "highway_segment_miles": REQUIRED,
        "mapped_route": REQUIRED,
        "weather_profile": REQUIRED,
        "weather_risk_score": 0,
    },
    "Terminal": {
        "terminal_code": REQUIRED,
        "terminal_name": REQUIRED,
        "state_code": REQUIRED,
        "apron_capacity": REQUIRED,
    },
    "DriverProspect": {
        "prospect_name": REQUIRED,
        "home_terminal_id": REQUIRED,
        "pathway": REQUIRED,
    },
    "StateAuthority": {
        "state_code": REQUIRED,
        "authority_name": REQUIRED,
        "autonomous_hours_allowed": 24,
        "requires_safety_case_filed": True,
        "engagement_window_days": 30,
    },
    "LaunchReadinessCheck": {
        "corridor_id": REQUIRED,
        "check_type": REQUIRED,
        "check_result": REQUIRED,
        "suite_latitude": 0,
        "suite_longitude": 0,
        "load_payload_lbs": 0,
        "prior_run_plan_id": None,
        "valid_window_days": 180,
        "is_test_payload": False,
        "correlation_key": REQUIRED,
    },
    "RunPlan": {
        "corridor_id": REQUIRED,
        "carrier_id": REQUIRED,
        "origin_terminal_id": REQUIRED,
        "destination_terminal_id": REQUIRED,
        "shipper_commitment_id": REQUIRED,
        "window_start_epoch_day": REQUIRED,
        "window_end_epoch_day": REQUIRED,
        "trailer_count": REQUIRED,
        "hauler_team_id": REQUIRED,
        "sacra_loadboard_slot_held": False,
        "posted_per_mile_cents": REQUIRED,
    },
    "Carrier": {
        "carrier_name": REQUIRED,
        "dot_number": REQUIRED,
        "backup_carrier_id": None,
    },
    "ShipperCommitment": {
        "shipper_name": REQUIRED,
        "shipper_floor_per_mile_cents": REQUIRED,
        "reserved_window_start_epoch_day": REQUIRED,
        "reserved_window_end_epoch_day": REQUIRED,
        "committed_slots": REQUIRED,
    },
    "TerminalServiceWindow": {
        "terminal_id": REQUIRED,
        "run_plan_id": REQUIRED,
        "service_type": REQUIRED,
        "window_start_minute": REQUIRED,
        "window_end_minute": REQUIRED,
        "handoff_duration_minutes": 0,
        "buffer_minutes": 0,
        "yield_to_transit": False,
    },
    "RemoteSupportAssignment": {
        "corridor_id": REQUIRED,
        "run_plan_id": REQUIRED,
        "monitoring_start_at": REQUIRED,
        "monitoring_end_at": REQUIRED,
        "remote_operator_id": REQUIRED,
        "safety_support_operator_id": REQUIRED,
        "geofence_type": REQUIRED,
        "intervention_protocol": REQUIRED,
    },
    "IncidentReport": {
        "corridor_id": REQUIRED,
        "run_plan_id": REQUIRED,
        "severity": REQUIRED,
        "recordable_incidents": 0,
        "corrective_action_count": 0,
        "review_days_allowed": 0,
        "reproduction_case_kind": None,
        "logs_populated": False,
    },
    "RegulatoryEngagement": {
        "corridor_id": REQUIRED,
        "state_authority_id": REQUIRED,
        "engagement_type": REQUIRED,
        "autonomous_hours_requested": REQUIRED,
        "autonomous_hours_logged": 0,
        "engaged_at": REQUIRED,
    },
    "SafetyCase": {
        "corridor_id": REQUIRED,
        "safety_case_version": REQUIRED,
        "hazard_count": REQUIRED,
        "open_hazard_count": 0,
        "filed_date": None,
    },
    "MaintenanceProgram": {
        "program_name": REQUIRED,
        "fleet_unit_id": REQUIRED,
        "state_code": REQUIRED,
        "inspection_interval_days": REQUIRED,
        "inspection_odometer_miles": 0,
        "inspection_anchor_at": REQUIRED,
    },
    "MultiDayHold": {
        "coverage_date": None,
        "hold_start_epoch_day": REQUIRED,
        "hold_end_epoch_day": REQUIRED,
        "single_day_hold": REQUIRED,
        "hold_type": REQUIRED,
    },
    "DriverTransition": {
        "prospect_id": REQUIRED,
        "terminal_id": REQUIRED,
        "pathway": REQUIRED,
        "transition_start_epoch_day": REQUIRED,
        "transition_days_count": REQUIRED,
        "hours_recorded": 0,
    },
    "LedgerCheckpoint": {
        "checkpoint_code": REQUIRED,
        "epoch_start_at": REQUIRED,
        "epoch_end_at": REQUIRED,
        "hours_per_epoch": 24,
    },
    "FleetUnit": {
        "unit_id": REQUIRED,
        "fleet_name": REQUIRED,
        "home_terminal_id": REQUIRED,
        "curated_at": REQUIRED,
        "inspection_anchor_at": REQUIRED,
        "weather_clearance_hours": REQUIRED,
        "is_watch_squad": False,
    },
    "RunPlanChassis": {
        "run_plan_id": REQUIRED,
        "chassis_code": REQUIRED,
        "coverage_days": REQUIRED,
    },
    "ShippingInstruction": {
        "run_plan_id": REQUIRED,
        "container_unit_ids": REQUIRED,
    },
    "ContainerUnit": {
        "instruction_id": None,
        "container_number": REQUIRED,
        "length_feet": REQUIRED,
        "gross_weight_kg": REQUIRED,
        "verified_gross_mass_kg": 0,
    },
    "RunPlanHauler": {
        "run_plan_id": REQUIRED,
        "driver_transition_id": REQUIRED,
        "hauler_role": REQUIRED,
    },
    "SecurityRecord": {
        "security_code": REQUIRED,
        "origin_terminal_id": REQUIRED,
        "destination_terminal_id": None,
        "security_classification": REQUIRED,
        "clearance_required": False,
        "high_consequence_clearance": False,
        "convention_status": REQUIRED,
        "consignor_code": REQUIRED,
        "outbound_lane_code": None,
    },
    "ClauseVariant": {
        "clause_stem": REQUIRED,
        "wildcard": False,
        "decline_reason": None,
    },
    "AgreementCode": {
        "code_value": REQUIRED,
        "display_value": REQUIRED,
    },
}

# Status / derived fields initialised at creation, per §1.1 `source: system` and
# `source: computed` declarations.
INITIAL = {
    "Corridor": {
        "corridor_status": "PLANNED", "posture": "FROZEN", "check_pass_count": 0,
        "check_count": 0, "has_blocking_incident": False,
        "route_validation_calculated_at": None, "launch_authorized_at": None,
        "readiness_score": D(0),
    },
    "Terminal": {
        "reserved_apron_units": D(0), "terminal_state": "COMMISSIONING",
        "staffing_status": "UNDERSTAFFED", "transfer_turnaround_minutes": 0,
        "total_handoff_minutes": 0, "approved_window_count": 0,
    },
    "DriverProspect": {
        "hours_worked": 0, "enrollments_on_file": 0,
        "safety_reliability_score": 1000,
    },
    "StateAuthority": {
        "hours_used": 0, "remaining_autonomous_hours": 24,
        "filing_required_next": False,
    },
    "LaunchReadinessCheck": {
        "calibration_variance_ms": D(0), "valid_window_start_at": None,
        "check_status": "INITIALIZED", "check_contribution": D(0),
        "epoch_start_at": None,
    },
    "RunPlan": {
        "run_status": "DRAFT", "per_mile_rate_cents": D(0),
        "committed_rate_cents": D(0), "scenario_rate_cents": D(0),
        "run_window_rate_cents": D(0), "safety_score": 50, "safety_band": "MEDIUM",
    },
    "Carrier": {
        "safety_score": 500, "rate_settlement_cents": D(0),
        "safety_tier": "MEDIUM", "committed_discount_cents": 15,
        "recordable_incidents_last_epoch": 0, "previous_epoch_incidents": 0,
        "incident_band": "CLEAN", "backup_carrier_score": 0,
        "carrier_status": "ONBOARDING",
    },
    "ShipperCommitment": {
        "ride_along_credit_cents": D(0), "billed_ride_along_cents": D(0),
        "consumed_slots": 0, "remaining_slots": 0, "verified_ride_along_count": 0,
        "commitment_status": "DRAFT", "shipped_at": None,
    },
    "TerminalServiceWindow": {
        "window_status": "REQUESTED", "buffer_seconds": 0,
    },
    "RemoteSupportAssignment": {
        "intervention_count": 0, "safe_stop_required": False,
        "safe_stop_fee_cents": D(0), "assignment_status": "SCHEDULED",
        "closure_source": None,
    },
    "IncidentReport": {
        "incident_tier": None, "report_status": "FILED",
        "regulatory_notice_required": False, "report_sequence_number": 0,
    },
    "RegulatoryEngagement": {
        "engagement_status": "DRAFT", "state_status": None,
        "hours_charge_allowed": False,
    },
    "SafetyCase": {
        "case_status": "DRAFT", "residual_risk_score": D(0),
        "case_status_summary": None,
    },
    "MaintenanceProgram": {
        "standard_inspection_due_date": None, "inspection_programs_status": None,
        "program_status": "DRAFT", "last_inspection_at": None,
    },
    "MultiDayHold": {
        "sequence_in_chain": 0, "hold_status": "REQUESTED",
    },
    "DriverTransition": {
        "transition_end_epoch_day": 0, "credential_event_count": 0,
        "transition_status": "ENROLLED",
    },
    "LedgerCheckpoint": {
        "adopted_at": None, "checkpoint_status": "OPEN", "rolled_over_at": None,
    },
    "FleetUnit": {
        "hours_posted_total": 0, "route_driven_hours_cents": D(0),
        "maint_projection_cents": D(0), "maint_charges": 0, "remain_hours": 0,
        "unit_status": "ACTIVE",
    },
    "RunPlanChassis": {
        "holding_rate_cents": D(0), "chassis_status": "HELD",
    },
    "ShippingInstruction": {
        "booked_vgm_kg_sum": D(0), "booked_line_total_cents": D(0),
        "vgm_override_fee_cents": D(0), "container_discount_cents": D(0),
        "instruction_status": "BOOKED",
    },
    "ContainerUnit": {
        "unit_rate_cents": D(0), "unit_status": "PENDING",
    },
    "RunPlanHauler": {
        "hauler_status": "TRUCK_HOLDER_BLENDED",
    },
    "SecurityRecord": {
        "record_status": "PENDING",
    },
    "ClauseVariant": {
        "variant_code": None, "variant_status": "PENDING",
        "variant_status_summary": "NOT_ELECTED",
    },
    "AgreementCode": {
        "code_status": "ACTIVE", "exec_sequence": 0, "order_sentinel": "AA",
    },
}


def base_row(entity, payload):
    stamp = now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(INITIAL.get(entity, {}))
    row.update(payload)
    if "created_at" in row:  # kept from payload only when the caller sets it
        row["created_at"] = stamp
    return row


def create(entity, payload):
    """Persist a new row built from `payload` (already validated + defaulted)."""
    row = base_row(entity, payload)
    db.put(TABLE[entity], row)
    db.note_fresh(row)
    if entity == "LedgerCheckpoint":
        _register_checkpoint(row)
    return row


def _register_checkpoint(row):
    import core
    core.register_checkpoint(row)


def pg(entity):
    """The table name for an entity key."""
    return TABLE[entity]


def missing_public(entity, payload, public):
    """Return the first required input field absent from a payload pruned to the
    endpoint's declared public schema."""
    for field, default in INPUT_FIELDS[entity].items():
        if public is not None and field not in public:
            continue
        if default is REQUIRED and field not in payload:
            return field
    return None


def defaults_payload(entity, body):
    """Apply declared defaults for every field the client omitted."""
    body = body or {}
    out = {}
    for field, default in INPUT_FIELDS[entity].items():
        if field in body:
            out[field] = body[field]
        elif default is not REQUIRED:
            out[field] = default
    return out


def missing_required(entity, payload):
    """Return the first required input field absent from `payload`."""
    for field, default in INPUT_FIELDS[entity].items():
        if default is REQUIRED and field not in payload:
            return field
    return None


def as_float_weight(value):
    return rhu(D(value), 2)