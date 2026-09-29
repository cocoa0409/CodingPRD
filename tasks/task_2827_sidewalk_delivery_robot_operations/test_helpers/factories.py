"""Payload factories — one per created resource, input fields only.

Money and measurement fields are emitted as JSON numbers, never strings, and
every instant is a full ISO-8601 UTC instant with three fractional digits.
"""

DEFAULTS = {
    "ZONE_NAME": "Mission District",
    "MUNICIPALITY_CODE": "SF",
    "ORDINANCE_MIN_CLEARANCE_CM": 90.0,
    "ORDINANCE_MAX_SPEED_CM_S": 160,
    "WINDOW_START": "0700",
    "WINDOW_END": "2100",
    "MAX_CONCURRENT_ROBOTS": 2,
    "PLANNING_HAUL_M": 800.0,
    "PLANNING_CROSSINGS": 2,
    "REMEDY_BUDGET_CENTS": 50000,
    "MERCHANT_NAME": "Corner Bakery",
    "HANDOFF_SLA_SECONDS": 300,
    "ROBOT_WIDTH_CM": 78.0,
    "ROBOT_CAPACITY_LITERS": 60.0,
    "ROBOT_MAX_SPEED_CM_S": 150,
    "CUSTOMER_REF": "C-1",
    "PAYLOAD_LITERS": 22.0,
    "DECLARED_VALUE_CENTS": 9000,
    "PROMISED_BY_UTC": "2026-08-03T09:40:00.000Z",
    "NARRATIVE": "Robot clipped a bollard while yielding to a pedestrian.",
}


# --------------------------------------------------------------- service zone
def create_service_zone_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ZONE_NAME"],
        "municipality_code": DEFAULTS["MUNICIPALITY_CODE"],
        "ordinance_min_clearance_cm": DEFAULTS["ORDINANCE_MIN_CLEARANCE_CM"],
        "ordinance_max_speed_cm_s": DEFAULTS["ORDINANCE_MAX_SPEED_CM_S"],
        "operating_window_start_utc_hhmm": DEFAULTS["WINDOW_START"],
        "operating_window_end_utc_hhmm": DEFAULTS["WINDOW_END"],
        "max_concurrent_robots": DEFAULTS["MAX_CONCURRENT_ROBOTS"],
        "planning_haul_m": DEFAULTS["PLANNING_HAUL_M"],
        "planning_crossings": DEFAULTS["PLANNING_CROSSINGS"],
        "remedy_budget_cents": DEFAULTS["REMEDY_BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def permit_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ sidewalk segment
def create_sidewalk_segment_payload(zone_id: str, segment_code: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "segment_code": segment_code,
        "segment_type": "WALKWAY",
        "length_m": 200.0,
        "measured_clearance_cm": 110.0,
        "surface_grade_pct": 3.0,
        "sightline_m": 40.0,
        "pedestrian_flow_per_min": 6.0,
        "curb_ramp_present": True,
    }
    payload.update(overrides)
    return payload


def segment_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ segment closure
def create_segment_closure_payload(segment_id: str, **overrides) -> dict:
    payload = {
        "segment_id": segment_id,
        "closure_kind": "HARD",
        "cause": "WEATHER",
        "starts_at_utc": "2026-08-03T10:00:00.000Z",
        "ends_at_utc": "2026-08-03T12:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def closure_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# -------------------------------------------------------------------- merchant
def create_merchant_payload(zone_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "name": DEFAULTS["MERCHANT_NAME"],
        "handoff_sla_seconds": DEFAULTS["HANDOFF_SLA_SECONDS"],
        "merchant_grade": "PREFERRED",
    }
    payload.update(overrides)
    return payload


def integration_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------- robot
def create_robot_payload(zone_id: str, asset_tag: str = "RBT-001", **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "asset_tag": asset_tag,
        "width_cm": DEFAULTS["ROBOT_WIDTH_CM"],
        "container_capacity_liters": DEFAULTS["ROBOT_CAPACITY_LITERS"],
        "max_speed_cm_s": DEFAULTS["ROBOT_MAX_SPEED_CM_S"],
    }
    payload.update(overrides)
    return payload


def duty_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def health_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def telemetry_payload(**overrides) -> dict:
    """A telemetry frame. Every field is optional, so the caller names only
    the fields it wants the frame to carry."""
    payload: dict = {}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ depot bay
def create_depot_bay_payload(zone_id: str, bay_code: str = "BAY-1", **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "bay_code": bay_code,
        "bay_type": "CHARGE",
        "power_kw": 7.5,
    }
    payload.update(overrides)
    return payload


def create_bay_reservation_payload(
    bay_id: str, robot_id: str, expected_depot_bay_version: int, **overrides
) -> dict:
    payload = {
        "bay_id": bay_id,
        "robot_id": robot_id,
        "reservation_type": "CHARGE",
        "window_start_utc": "2026-08-03T10:00:00.000Z",
        "window_end_utc": "2026-08-03T11:00:00.000Z",
        "expected_depot_bay_version": expected_depot_bay_version,
    }
    payload.update(overrides)
    return payload


def reservation_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------- delivery order
def create_delivery_order_payload(merchant_id: str, dropoff_segment_id: str, **overrides) -> dict:
    payload = {
        "merchant_id": merchant_id,
        "dropoff_segment_id": dropoff_segment_id,
        "customer_ref": DEFAULTS["CUSTOMER_REF"],
        "payload_liters": DEFAULTS["PAYLOAD_LITERS"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
        "promised_by_utc": DEFAULTS["PROMISED_BY_UTC"],
    }
    payload.update(overrides)
    return payload


def remedy_payload(remedy_kind: str, **overrides) -> dict:
    payload = {"remedy_kind": remedy_kind}
    payload.update(overrides)
    return payload


# ----------------------------------------------------------- delivery mission
def create_delivery_mission_payload(
    order_id: str, robot_id: str, expected_delivery_order_version: int, **overrides
) -> dict:
    payload = {
        "order_id": order_id,
        "robot_id": robot_id,
        "expected_delivery_order_version": expected_delivery_order_version,
    }
    payload.update(overrides)
    return payload


def load_payload(actual_payload_liters: float, lid_seal_confirmed: bool = True, **overrides) -> dict:
    payload = {
        "actual_payload_liters": actual_payload_liters,
        "lid_seal_confirmed": lid_seal_confirmed,
    }
    payload.update(overrides)
    return payload


def mission_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- route plan
def create_route_plan_payload(
    mission_id: str, segment_sequence: list, expected_delivery_mission_version: int, **overrides
) -> dict:
    payload = {
        "mission_id": mission_id,
        "segment_sequence": list(segment_sequence),
        "expected_delivery_mission_version": expected_delivery_mission_version,
    }
    payload.update(overrides)
    return payload


def plan_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# --------------------------------------------------------- intervention event
def create_intervention_event_payload(
    mission_id: str, autonomy_confidence_pct: int, **overrides
) -> dict:
    payload = {
        "mission_id": mission_id,
        "trigger_reason": "LOW_CONFIDENCE",
        "autonomy_confidence_pct": autonomy_confidence_pct,
    }
    payload.update(overrides)
    return payload


def intervention_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ incident report
def create_incident_report_payload(zone_id: str, robot_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "robot_id": robot_id,
        "category": "PEDESTRIAN_CONTACT",
        "severity": "SERIOUS",
        "narrative": DEFAULTS["NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def incident_transition_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------- clock
def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
