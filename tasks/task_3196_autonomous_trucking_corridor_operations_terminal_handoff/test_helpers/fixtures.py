"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against a freshly started
server, so it uses only PRD-declared endpoints. ``get_success_data`` (lenient)
is used internally so a setup failure surfaces as a clear "setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_clock_payload, create_ledger_checkpoint_payload, create_terminal_payload,
    create_destination_terminal_payload, create_corridor_payload, create_safety_case_payload,
    file_safety_case_payload, create_readiness_check_payload, create_load_securement_payload,
    create_carrier_payload, create_shipper_commitment_payload, create_driver_prospect_payload,
    create_driver_transition_payload, create_run_plan_payload, create_dispatch_ready_payload,
    create_validate_corridor_payload, create_validate_check_payload,
    create_service_window_payload, create_remote_support_payload,
    create_incident_report_payload, corrective_action_payload, create_fleet_unit_payload,
    create_maintenance_program_payload, create_state_authority_payload,
    create_regulatory_engagement_payload, create_security_record_payload,
    create_shipping_instruction_payload, create_container_unit_payload,
    create_multi_day_hold_payload, create_chassis_payload, create_clause_variant_payload,
    create_agreement_code_payload,
)
from .constants import THRESHOLDS, TEST_DEFAULTS
from .test_users import TEST_USERS, make_remote_support_operator_headers

CLOCK_START = TEST_DEFAULTS["EPOCH_START"]
EPOCH_START = TEST_DEFAULTS["EPOCH_START"]
EPOCH_END = TEST_DEFAULTS["EPOCH_END"]


# ─── Tier 1: state progression / primitives ─────────────────────────────────

def set_clock(current_utc=CLOCK_START):
    """Advance the logical clock. No business field is mutated."""
    return get_success_data(api_client.set_current_utc(
        create_clock_payload(current_utc), TEST_USERS["platform_admin_headers"]))


def open_epoch(adopt=True, start=EPOCH_START, end=EPOCH_END, hours=24, code="EPOCH-SEP"):
    """Open a ledger epoch and (by default) adopt it as the active epoch."""
    ck = get_success_data(api_client.create_ledger_checkpoint(
        create_ledger_checkpoint_payload(checkpoint_code=code, epoch_start_at=start,
                                         epoch_end_at=end, hours_per_epoch=hours),
        TEST_USERS["platform_admin_headers"]))
    if adopt:
        ck = get_success_data(api_client.adopt_ledger_checkpoint(
            ck["id"], TEST_USERS["platform_admin_headers"]))
    return ck


def make_operational_terminal(code="PHX-WEST", name="Phoenix West Hub", capacity=40):
    """Commission a terminal and move it into service."""
    if code == "TUS-HUB":
        t = get_success_data(api_client.create_terminal(
            create_destination_terminal_payload(terminal_code=code, terminal_name=name,
                                                apron_capacity=capacity),
            TEST_USERS["terminal_manager_headers"]))
    else:
        t = get_success_data(api_client.create_terminal(
            create_terminal_payload(terminal_code=code, terminal_name=name,
                                    apron_capacity=capacity),
            TEST_USERS["terminal_manager_headers"]))
    return get_success_data(api_client.operate_terminal(
        t["id"], TEST_USERS["terminal_manager_headers"]))


def make_carrier(name="Aurora Freight Systems", dot="DOT-3196001", active=False):
    carrier = get_success_data(api_client.create_carrier(
        create_carrier_payload(carrier_name=name, dot_number=dot),
        TEST_USERS["compliance_officer_headers"]))
    if active:
        carrier = get_success_data(api_client.activate_carrier(
            carrier["id"], TEST_USERS["compliance_officer_headers"]))
    return carrier


def make_commitment(confirm=False, **overrides):
    commitment = get_success_data(api_client.create_shipper_commitment(
        create_shipper_commitment_payload(**overrides),
        TEST_USERS["shipper_partnership_headers"]))
    if confirm:
        commitment = get_success_data(api_client.confirm_shipper_commitment(
            commitment["id"], TEST_USERS["shipper_partnership_headers"]))
    return commitment


def make_prospect(home_terminal_id, name="Dana Whitfield", pathway="FIRST_LAST_MILE"):
    return get_success_data(api_client.create_driver_prospect(
        create_driver_prospect_payload(home_terminal_id, prospect_name=name, pathway=pathway),
        TEST_USERS["driver_outreach_headers"]))


def make_corridor(origin_terminal_id, destination_terminal_id, **overrides):
    return get_success_data(api_client.create_corridor(
        create_corridor_payload(origin_terminal_id, destination_terminal_id, **overrides),
        TEST_USERS["corridor_manager_headers"]))


def make_state_authority(**overrides):
    return get_success_data(api_client.create_state_authority(
        create_state_authority_payload(**overrides),
        TEST_USERS["regulatory_liaison_headers"]))


def file_safety_case(corridor_id, version=1, hazard_count=2, filed_date="2026-09-10T00:00:00Z"):
    """Open, submit and file a safety case so the launching corridor has a CURRENT case."""
    sc = get_success_data(api_client.create_safety_case(
        create_safety_case_payload(corridor_id, safety_case_version=version,
                                   hazard_count=hazard_count, open_hazard_count=0),
        TEST_USERS["safety_case_author_headers"]))
    get_success_data(api_client.submit_safety_case(sc["id"], TEST_USERS["safety_case_author_headers"]))
    return get_success_data(api_client.file_safety_case(
        sc["id"], file_safety_case_payload(filed_date=filed_date),
        TEST_USERS["regulatory_liaison_headers"]))


def record_check(corridor_id, check_type="SENSOR_CALIBRATION", result="PASS",
                 latitude=37.0, longitude=38.0, correlation_key="CAL-01",
                 load_payload_lbs=None, **overrides):
    """Record a readiness check and drive it to CALIBRATION_PASSED."""
    payload = {"check_type": check_type, "check_result": result,
               "suite_latitude": latitude, "suite_longitude": longitude,
               "valid_window_days": 180, "correlation_key": correlation_key}
    if load_payload_lbs is not None:
        payload["load_payload_lbs"] = load_payload_lbs
    payload.update(overrides)
    check = get_success_data(api_client.create_readiness_check(
        corridor_id, payload, TEST_USERS["corridor_manager_headers"]))
    return get_success_data(api_client.calibrate_check(
        check["id"], TEST_USERS["corridor_manager_headers"]))


# ─── Tier 2: entity hierarchy / standard stack ──────────────────────────────

def setup_stack(adopt_epoch=True, origin_capacity=40, dest_capacity=30,
                carrier_active=True, confirm_commitment=True, commitment_overrides=None,
                weather_profile="CLEAR_DEFAULT", weather_risk_score=20,
                highway_segment_miles=120, has_hov_lane=True,
                requires_tunnel_clearance=False, clock=CLOCK_START,
                **corridor_overrides):
    """Epoch + two OPERATIONAL terminals + carrier + commitment + hauler prospect.

    Returns a dict of the created ids/objects. The corridor is *not* created here.
    """
    set_clock(clock)
    if adopt_epoch:
        ck = open_epoch()
    else:
        ck = None
    t_phx = make_operational_terminal("PHX-WEST", "Phoenix West Hub", origin_capacity)
    t_tus = make_operational_terminal("TUS-HUB", "Tucson Transfer Hub", dest_capacity)
    carrier = make_carrier(active=carrier_active)
    commitment = make_commitment(confirm=confirm_commitment,
                                 **(commitment_overrides or {}))
    prospect = make_prospect(t_phx["id"], name="Dana Whitfield", pathway="FIRST_LAST_MILE")
    return {
        "epoch": ck, "origin": t_phx, "destination": t_tus, "carrier": carrier,
        "commitment": commitment, "prospect": prospect,
        "weather_profile": weather_profile, "weather_risk_score": weather_risk_score,
        "highway_segment_miles": highway_segment_miles,
    }


def add_corridor(stack, launch=False, **overrides):
    """Create a corridor on an existing stack; optionally drive it through the gate."""
    corridor = make_corridor(
        stack["origin"]["id"], stack["destination"]["id"],
        weather_profile=overrides.pop("weather_profile", stack["weather_profile"]),
        weather_risk_score=overrides.pop("weather_risk_score", stack["weather_risk_score"]),
        highway_segment_miles=overrides.pop("highway_segment_miles",
                                            stack["highway_segment_miles"]),
        mapped_route=overrides.pop("mapped_route", {
            "route_code": "I10-EAST-01", "waypoint_count": 14,
            "has_hov_lane": True, "requires_tunnel_clearance": False}),
        **overrides)
    stack["corridor"] = corridor
    if launch:
        stack["corridor"] = launch_corridor(corridor["id"])
    return stack["corridor"]


# ─── Tier 3: full lifecycle shortcuts ───────────────────────────────────────

def launch_corridor(corridor_id, sensor_lat=37.0, sensor_long=38.0,
                    load_payload_lbs=44000, filed_date="2026-09-10T00:00:00Z",
                    with_load_check=True, with_route_check=True):
    """Drive a corridor from its current state through the launch gate to ACTIVE.

    start review -> record checks -> calibrate -> validate route -> file safety case
    -> pass the launch gate.
    """
    get_success_data(api_client.start_launch_readiness(
        corridor_id, TEST_USERS["corridor_manager_headers"]))
    record_check(corridor_id, "SENSOR_CALIBRATION", "PASS", sensor_lat, sensor_long, "CAL-01")
    if with_load_check:
        record_check(corridor_id, "LOAD_SECUREMENT", "PASS", 0.0, 0.0, "SEC-01",
                     load_payload_lbs=load_payload_lbs)
    if with_route_check:
        rte = record_check(corridor_id, "ROUTE_VALIDATION", "PASS", sensor_lat, sensor_long, "RTE-01")
        rte = get_success_data(api_client.validate_check(
            rte["id"], TEST_USERS["corridor_manager_headers"],
            create_validate_check_payload(rte["version"])))
    file_safety_case(corridor_id, filed_date=filed_date)
    corridor = get_success_data(api_client.get_corridor(
        corridor_id, TEST_USERS["any_headers"]))
    return get_success_data(api_client.validate_launch_readiness(
        corridor_id, TEST_USERS["corridor_manager_headers"],
        create_validate_corridor_payload(corridor["version"])))


def setup_launched_corridor(weather_profile="CLEAR_DEFAULT", weather_risk_score=20,
                            highway_segment_miles=120, **stack_kwargs):
    """Standard stack + an ACTIVE/OPEN corridor launched through the gate."""
    stack = setup_stack(weather_profile=weather_profile,
                        weather_risk_score=weather_risk_score,
                        highway_segment_miles=highway_segment_miles,
                        **stack_kwargs)
    add_corridor(stack, launch=True)
    return stack


def create_run(stack, window_start_epoch_day=10, window_end_epoch_day=12,
               trailer_count=None, posted_per_mile_cents=None, **overrides):
    """Create a DRAFT run plan against the stack's corridor/commitment/prospect."""
    payload = create_run_plan_payload(
        stack["corridor"]["id"], stack["carrier"]["id"],
        stack["origin"]["id"], stack["destination"]["id"],
        stack["commitment"]["id"], stack["prospect"]["id"], **overrides)
    if window_start_epoch_day is not None:
        payload["window_start_epoch_day"] = window_start_epoch_day
    if window_end_epoch_day is not None:
        payload["window_end_epoch_day"] = window_end_epoch_day
    if trailer_count is not None:
        payload["trailer_count"] = trailer_count
    if posted_per_mile_cents is not None:
        payload["posted_per_mile_cents"] = posted_per_mile_cents
    return get_success_data(api_client.create_run_plan(
        payload, TEST_USERS["carrier_dispatcher_headers"]))


def request_window(terminal_id, run_plan_id, start_minute=100, end_minute=160,
                   service_type="HANDOFF_OUTBOUND", handoff_duration_minutes=20,
                   buffer_minutes=0, yield_to_transit=False):
    return get_success_data(api_client.create_service_window(
        terminal_id,
        create_service_window_payload(run_plan_id, service_type=service_type,
                                      window_start_minute=start_minute,
                                      window_end_minute=end_minute,
                                      handoff_duration_minutes=handoff_duration_minutes,
                                      buffer_minutes=buffer_minutes,
                                      yield_to_transit=yield_to_transit),
        TEST_USERS["terminal_manager_headers"]))


def submit_run(run_plan_id):
    return get_success_data(api_client.submit_run_plan(
        run_plan_id, TEST_USERS["carrier_dispatcher_headers"]))


def dispatch_run(run_plan_id):
    rp = get_success_data(api_client.get_run_plan(run_plan_id, TEST_USERS["any_headers"]))
    return get_success_data(api_client.dispatch_ready_run_plan(
        run_plan_id, TEST_USERS["carrier_dispatcher_headers"],
        create_dispatch_ready_payload(rp["version"])))


def setup_dispatch_ready_run(window_start_minute=100, window_end_minute=160, **stack_kwargs):
    """Launched corridor + one DISPATCH_READY run behind an APPROVED apron window.

    Returns (stack, run_plan, window).
    """
    stack = setup_launched_corridor(**stack_kwargs)
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"],
                            window_start_minute, window_end_minute)
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = get_success_data(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


def setup_in_transit_run(**stack_kwargs):
    """Launched corridor + one IN_TRANSIT run (approved window moved to IN_SERVICE)."""
    stack, run, window = setup_dispatch_ready_run(**stack_kwargs)
    run = get_success_data(api_client.start_highway_segment(
        run["id"], TEST_USERS["carrier_dispatcher_headers"]))
    return stack, run, window


def setup_monitoring_window(run, stack, operator_prospect, support_prospect,
                            start_at="2026-09-01T00:30:00Z", end_at="2026-09-01T04:00:00Z",
                            geofence_type="GEOFENCE_ONLY", protocol="MONITOR_ONLY",
                            acknowledge=True):
    """Schedule a monitoring window; optionally acknowledge into MONITORING."""
    assignment = get_success_data(api_client.create_remote_support_assignment(
        create_remote_support_payload(stack["corridor"]["id"], run["id"],
                                      operator_prospect["id"], support_prospect["id"],
                                      monitoring_start_at=start_at, monitoring_end_at=end_at,
                                      geofence_type=geofence_type,
                                      intervention_protocol=protocol),
        TEST_USERS["remote_support_supervisor_headers"]))
    if acknowledge:
        assignment = get_success_data(api_client.acknowledge_assignment(
            assignment["id"],
            make_remote_support_operator_headers(operator_prospect["id"])))
    return assignment


def make_incident(stack, run, severity="MODERATE", **overrides):
    return get_success_data(api_client.create_incident_report(
        create_incident_report_payload(stack["corridor"]["id"], run["id"],
                                       severity=severity, **overrides),
        TEST_USERS["incident_reviewer_headers"]))


# ─── Tier 4: accumulation / threshold targeting ─────────────────────────────

def setup_restricted_corridor(weather_risk_score=55, **stack_kwargs):
    """Launched corridor whose posture is RESTRICTED (weather weight at/above 40)."""
    stack = setup_launched_corridor(weather_profile="HIGH_WIND",
                                    weather_risk_score=weather_risk_score, **stack_kwargs)
    return stack


def setup_maintenance_limited_corridor(**stack_kwargs):
    """Launched corridor driven ACTIVE -> LIMITED by voiding its unit's programme."""
    stack = setup_launched_corridor(**stack_kwargs)
    unit = get_success_data(api_client.create_fleet_unit(
        create_fleet_unit_payload(stack["origin"]["id"]),
        TEST_USERS["fleet_maintenance_tech_headers"]))
    program = get_success_data(api_client.create_maintenance_program(
        create_maintenance_program_payload(unit["id"]),
        TEST_USERS["fleet_maintenance_tech_headers"]))
    program = get_success_data(api_client.schedule_maintenance_program(
        program["id"], TEST_USERS["fleet_maintenance_tech_headers"]))
    voided = get_success_data(api_client.void_maintenance_program(
        program["id"], TEST_USERS["fleet_maintenance_tech_headers"]))
    stack["fleet_unit"] = unit
    stack["program"] = voided
    return stack


def setup_carrier_with_recordable_incidents(stack, run, count=2, carry_health=None):
    """File one incident report carrying `count` recordable incidents for the carrier.

    Reaching the WATCH band requires the carrier's epoch recordable count to reach 2.
    """
    make_incident(stack, run, severity="MODERATE", recordable_incidents=count)
    return get_success_data(api_client.get_carrier(
        stack["carrier"]["id"], TEST_USERS["any_headers"]))


def setup_engaged_stack(**stack_kwargs):
    """Launched corridor stack that also carries a supervising state authority."""
    stack = setup_launched_corridor(**stack_kwargs)
    authority = make_state_authority()
    stack["state_authority"] = authority
    return stack


def setup_approved_window_boundary_stack(origin_capacity=2, approved_minutes=75,
                                         approved_handoff=20):
    """Launched corridor + DISPATCH_READY run + one APPROVED window of a set length."""
    stack = setup_launched_corridor(origin_capacity=origin_capacity)
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"], 100, 100 + approved_minutes,
                            handoff_duration_minutes=approved_handoff, buffer_minutes=0)
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = get_success_data(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


def setup_turnaround_terminal(handoff_minutes=45):
    """Launched corridor + DISPATCH_READY run + one APPROVED 45-minute window."""
    stack = setup_launched_corridor()
    run = create_run(stack)
    window = request_window(stack["origin"]["id"], run["id"], 100,
                            100 + handoff_minutes,
                            handoff_duration_minutes=handoff_minutes, buffer_minutes=0)
    submit_run(run["id"])
    run = dispatch_run(run["id"])
    window = get_success_data(api_client.get_service_window(
        stack["origin"]["id"], window["id"], TEST_USERS["any_headers"]))
    return stack, run, window


# ─── Tier 5: finalization / terminal state ──────────────────────────────────

def complete_run_with_ride_along(stack, run):
    """Attach a ride-along to a transition, then run the plan to COMPLETED."""
    transition = get_success_data(api_client.create_driver_transition(
        create_driver_transition_payload(stack["prospect"]["id"], stack["origin"]["id"],
                                         pathway="RIDE_ALONG_EVALUATOR",
                                         transition_start_epoch_day=12,
                                         transition_days_count=3, hours_recorded=8),
        TEST_USERS["driver_outreach_headers"]))
    get_success_data(api_client.ride_along_transition(
        transition["id"], {"run_plan_id": run["id"]}, TEST_USERS["driver_outreach_headers"]))
    submit_run(run["id"])
    window = request_window(stack["origin"]["id"], run["id"])
    run = dispatch_run(run["id"])
    run = get_success_data(api_client.start_highway_segment(
        run["id"], TEST_USERS["carrier_dispatcher_headers"]))
    run = get_success_data(api_client.complete_run_plan(
        run["id"], TEST_USERS["carrier_dispatcher_headers"]))
    return run, transition


def make_shipping_instruction(run, units):
    return get_success_data(api_client.create_shipping_instruction(
        create_shipping_instruction_payload(run["id"], [u["id"] for u in units]),
        TEST_USERS["booking_clerk_headers"]))