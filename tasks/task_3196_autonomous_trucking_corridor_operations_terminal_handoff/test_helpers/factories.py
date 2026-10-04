"""Payload factories — input fields only, one factory per entity."""

DEFAULTS = {
    "CORRIDOR_NAME": "Sun Belt I-10",
    "ROUTE_CODE": "I10-EAST-01",
    "WAYPOINT_COUNT": 14,
    "TERMINAL_CODE_ORIGIN": "PHX-WEST",
    "TERMINAL_CODE_DEST": "TUS-HUB",
    "STATE_CODE": "AZ",
    "APRON_CAPACITY": 40,
    "HIGHWAY_MILES": 120,
    "POSTED_PER_MILE_CENTS": 225,
    "SHIPPER_FLOOR_PER_MILE_CENTS": 100,
    "COMMITTED_SLOTS": 5,
    "CARRIER_NAME": "Aurora Freight Systems",
    "DOT_NUMBER": "DOT-3196001",
    "PROSPECT_NAME": "Dana Whitfield",
    "WINDOW_START_DAY": 1,
    "WINDOW_END_DAY": 3,
    "CURATED_AT": "2026-09-01T00:00:00Z",
    "WEATHER_CLEARANCE_HOURS": 120,
    "EPOCH_START": "2026-09-01T00:00:00Z",
    "EPOCH_END": "2026-10-01T00:00:00Z",
    "TRAILER_COUNT": 2,
}


# ─── Platform administration ────────────────────────────────────────────────

def create_clock_payload(current_utc="2026-09-01T00:00:00Z"):
    return {"current_utc": current_utc}


def create_ledger_checkpoint_payload(**overrides) -> dict:
    defaults = {
        "checkpoint_code": "EPOCH-SEP",
        "epoch_start_at": DEFAULTS["EPOCH_START"],
        "epoch_end_at": DEFAULTS["EPOCH_END"],
        "hours_per_epoch": 24,
    }
    defaults.update(overrides)
    return defaults


# ─── Terminals ──────────────────────────────────────────────────────────────

def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "terminal_code": DEFAULTS["TERMINAL_CODE_ORIGIN"],
        "terminal_name": "Phoenix West Hub",
        "state_code": DEFAULTS["STATE_CODE"],
        "apron_capacity": DEFAULTS["APRON_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_destination_terminal_payload(**overrides) -> dict:
    defaults = {
        "terminal_code": DEFAULTS["TERMINAL_CODE_DEST"],
        "terminal_name": "Tucson Transfer Hub",
        "state_code": "AZ",
        "apron_capacity": 30,
    }
    defaults.update(overrides)
    return defaults


# ─── Corridors ──────────────────────────────────────────────────────────────

def create_corridor_payload(origin_terminal_id, destination_terminal_id, **overrides) -> dict:
    defaults = {
        "corridor_name": DEFAULTS["CORRIDOR_NAME"],
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "highway_segment_miles": DEFAULTS["HIGHWAY_MILES"],
        "mapped_route": {
            "route_code": DEFAULTS["ROUTE_CODE"],
            "waypoint_count": DEFAULTS["WAYPOINT_COUNT"],
            "has_hov_lane": True,
            "requires_tunnel_clearance": False,
        },
        "weather_profile": "CLEAR_DEFAULT",
        "weather_risk_score": 20,
    }
    defaults.update(overrides)
    return defaults


# ─── Safety cases ───────────────────────────────────────────────────────────

def create_safety_case_payload(corridor_id, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "safety_case_version": 1,
        "hazard_count": 2,
        "open_hazard_count": 0,
    }
    defaults.update(overrides)
    return defaults


def file_safety_case_payload(**overrides) -> dict:
    defaults = {"filed_date": "2026-09-10T00:00:00Z"}
    defaults.update(overrides)
    return defaults


# ─── Launch readiness checks ────────────────────────────────────────────────

def create_readiness_check_payload(**overrides) -> dict:
    defaults = {
        "check_type": "SENSOR_CALIBRATION",
        "check_result": "PASS",
        "suite_latitude": 37.0,
        "suite_longitude": 38.0,
        "valid_window_days": 180,
        "correlation_key": "CAL-01",
    }
    defaults.update(overrides)
    return defaults


def create_load_securement_payload(**overrides) -> dict:
    defaults = {
        "check_type": "LOAD_SECUREMENT",
        "check_result": "PASS",
        "load_payload_lbs": 44000,
        "valid_window_days": 180,
        "correlation_key": "SEC-01",
    }
    defaults.update(overrides)
    return defaults


# ─── Carriers ───────────────────────────────────────────────────────────────

def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "dot_number": DEFAULTS["DOT_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


# ─── Shipper commitments ────────────────────────────────────────────────────

def create_shipper_commitment_payload(**overrides) -> dict:
    defaults = {
        "shipper_name": "Rio Grande Distribution",
        "shipper_floor_per_mile_cents": DEFAULTS["SHIPPER_FLOOR_PER_MILE_CENTS"],
        "reserved_window_start_epoch_day": 0,
        "reserved_window_end_epoch_day": 30,
        "committed_slots": DEFAULTS["COMMITTED_SLOTS"],
    }
    defaults.update(overrides)
    return defaults


# ─── Driver prospects / transitions ─────────────────────────────────────────

def create_driver_prospect_payload(home_terminal_id, **overrides) -> dict:
    defaults = {
        "prospect_name": DEFAULTS["PROSPECT_NAME"],
        "home_terminal_id": home_terminal_id,
        "pathway": "FIRST_LAST_MILE",
    }
    defaults.update(overrides)
    return defaults


def create_driver_transition_payload(prospect_id, terminal_id, **overrides) -> dict:
    defaults = {
        "prospect_id": prospect_id,
        "terminal_id": terminal_id,
        "pathway": "RIDE_ALONG_EVALUATOR",
        "transition_start_epoch_day": 12,
        "transition_days_count": 3,
        "hours_recorded": 8,
    }
    defaults.update(overrides)
    return defaults


# ─── Run plans ──────────────────────────────────────────────────────────────

def create_run_plan_payload(corridor_id, carrier_id, origin_terminal_id,
                            destination_terminal_id, shipper_commitment_id,
                            hauler_team_id, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "carrier_id": carrier_id,
        "origin_terminal_id": origin_terminal_id,
        "destination_terminal_id": destination_terminal_id,
        "shipper_commitment_id": shipper_commitment_id,
        "window_start_epoch_day": 10,
        "window_end_epoch_day": 12,
        "trailer_count": DEFAULTS["TRAILER_COUNT"],
        "posted_per_mile_cents": DEFAULTS["POSTED_PER_MILE_CENTS"],
        "hauler_team_id": hauler_team_id,
        "sacra_loadboard_slot_held": True,
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_ready_payload(expected_run_plan_version) -> dict:
    return {"expected_run_plan_version": expected_run_plan_version}


def create_validate_corridor_payload(expected_corridor_version) -> dict:
    return {"expected_corridor_version": expected_corridor_version}


def create_validate_check_payload(expected_check_version) -> dict:
    return {"expected_check_version": expected_check_version}


# ─── Service windows ────────────────────────────────────────────────────────

def create_service_window_payload(run_plan_id, **overrides) -> dict:
    defaults = {
        "run_plan_id": run_plan_id,
        "service_type": "HANDOFF_OUTBOUND",
        "window_start_minute": 100,
        "window_end_minute": 160,
        "handoff_duration_minutes": 20,
        "buffer_minutes": 0,
        "yield_to_transit": False,
    }
    defaults.update(overrides)
    return defaults


# ─── Remote support assignments ─────────────────────────────────────────────

def create_remote_support_payload(corridor_id, run_plan_id, remote_operator_id,
                                  safety_support_operator_id, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "run_plan_id": run_plan_id,
        "monitoring_start_at": "2026-09-01T00:30:00Z",
        "monitoring_end_at": "2026-09-01T04:00:00Z",
        "remote_operator_id": remote_operator_id,
        "safety_support_operator_id": safety_support_operator_id,
        "geofence_type": "GEOFENCE_ONLY",
        "intervention_protocol": "MONITOR_ONLY",
    }
    defaults.update(overrides)
    return defaults


# ─── Incident reports ───────────────────────────────────────────────────────

def create_incident_report_payload(corridor_id, run_plan_id, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "run_plan_id": run_plan_id,
        "severity": "MODERATE",
        "recordable_incidents": 0,
        "corrective_action_count": 0,
        "review_days_allowed": 5,
        "logs_populated": True,
    }
    defaults.update(overrides)
    return defaults


def corrective_action_payload(corrective_action_count=1) -> dict:
    return {"corrective_action_count": corrective_action_count}


# ─── Fleet units / maintenance ──────────────────────────────────────────────

def create_fleet_unit_payload(home_terminal_id, **overrides) -> dict:
    defaults = {
        "unit_id": "AUR-2214",
        "fleet_name": "Aurora Long Haul",
        "home_terminal_id": home_terminal_id,
        "curated_at": DEFAULTS["CURATED_AT"],
        "inspection_anchor_at": "2026-09-01T00:00:00Z",
        "weather_clearance_hours": DEFAULTS["WEATHER_CLEARANCE_HOURS"],
        "is_watch_squad": False,
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_program_payload(fleet_unit_id, **overrides) -> dict:
    defaults = {
        "program_name": "AZ Hardware Inspection",
        "fleet_unit_id": fleet_unit_id,
        "state_code": "AZ",
        "inspection_interval_days": 5,
        "inspection_odometer_miles": 0,
        "inspection_anchor_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── State authorities / regulatory engagements ─────────────────────────────

def create_state_authority_payload(**overrides) -> dict:
    defaults = {
        "state_code": "AZ",
        "authority_name": "Arizona DOT Autonomous Freight Office",
        "autonomous_hours_allowed": 24,
        "requires_safety_case_filed": True,
        "engagement_window_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_regulatory_engagement_payload(corridor_id, state_authority_id, **overrides) -> dict:
    defaults = {
        "corridor_id": corridor_id,
        "state_authority_id": state_authority_id,
        "engagement_type": "SAFETY_BRIEFING",
        "autonomous_hours_requested": 4,
        "autonomous_hours_logged": 0,
        "engaged_at": "2026-09-01T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── Security records / clause variants / agreement codes ───────────────────

def create_security_record_payload(origin_terminal_id, **overrides) -> dict:
    defaults = {
        "security_code": "AZ-ROAD-0001",
        "origin_terminal_id": origin_terminal_id,
        "security_classification": "SENSITIVE",
        "clearance_required": True,
        "high_consequence_clearance": False,
        "convention_status": "SENSITIVE",
        "consignor_code": "AZ-ROAD-0001",
    }
    defaults.update(overrides)
    return defaults


def create_clause_variant_payload(**overrides) -> dict:
    defaults = {"clause_stem": "ARB-12-34-STD", "wildcard": False}
    defaults.update(overrides)
    return defaults


def create_agreement_code_payload(**overrides) -> dict:
    defaults = {"code_value": "HOS-AGREEMENT-001", "display_value": "HOS Agreement 001"}
    defaults.update(overrides)
    return defaults


# ─── Shipping instructions / container units ────────────────────────────────

def create_shipping_instruction_payload(run_plan_id, container_unit_ids, **overrides) -> dict:
    defaults = {
        "run_plan_id": run_plan_id,
        "container_unit_ids": container_unit_ids,
    }
    defaults.update(overrides)
    return defaults


def create_container_unit_payload(**overrides) -> dict:
    defaults = {
        "container_number": "MSCU1234567",
        "length_feet": 40,
        "gross_weight_kg": 12000.0,
        "verified_gross_mass_kg": 0,
    }
    defaults.update(overrides)
    return defaults


# ─── Multi-day holds ────────────────────────────────────────────────────────

def create_multi_day_hold_payload(**overrides) -> dict:
    defaults = {
        "hold_start_epoch_day": 5,
        "hold_end_epoch_day": 7,
        "single_day_hold": False,
        "hold_type": "WINDOW_BLOCK",
    }
    defaults.update(overrides)
    return defaults


# ─── Chassis ────────────────────────────────────────────────────────────────

def create_chassis_payload(**overrides) -> dict:
    defaults = {"chassis_code": "CHS-2201", "coverage_days": 3}
    defaults.update(overrides)
    return defaults