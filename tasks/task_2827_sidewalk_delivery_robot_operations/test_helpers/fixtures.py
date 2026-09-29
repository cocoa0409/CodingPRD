"""Composite setup helpers.

Every helper builds its state from scratch through PRD-declared endpoints only,
because each test runs against an empty database. The backbone is
``build_scenario(stage)``: one canonical chain from an empty database up to a
completed delivery, stoppable at any named stage, with per-stage overrides.

Chain, in order:

    zone -> mapped_segment -> approved_segment -> two_segments -> segments
    -> permitted -> merchant -> robot -> order -> mission -> loaded
    -> plan -> active_plan -> en_route -> arrived -> completed

The four segments S1 (WALKWAY 320.0 m), S2 (SIGNALIZED CROSSING 14.0 m),
S3 (WALKWAY 260.0 m) and S5 (WALKWAY 180.0 m) form one contiguous chain whose
last element is the order's dropoff segment.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    clock_payload,
    create_bay_reservation_payload,
    create_delivery_mission_payload,
    create_delivery_order_payload,
    create_depot_bay_payload,
    create_incident_report_payload,
    create_intervention_event_payload,
    create_merchant_payload,
    create_robot_payload,
    create_route_plan_payload,
    create_segment_closure_payload,
    create_service_zone_payload,
    create_sidewalk_segment_payload,
    duty_transition_payload,
    health_transition_payload,
    incident_transition_payload,
    integration_transition_payload,
    intervention_transition_payload,
    load_payload,
    mission_transition_payload,
    permit_transition_payload,
    plan_transition_payload,
    reservation_transition_payload,
    segment_transition_payload,
    telemetry_payload,
)
from .test_users import (
    TEST_USERS,
    make_merchant_operator_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["fleet_dispatcher_headers"]
OPERATOR = TEST_USERS["remote_operator_headers"]
OFFICER = TEST_USERS["safety_officer_headers"]
SUPPORT = TEST_USERS["customer_support_headers"]

BASE_CLOCK_UTC = "2026-08-03T09:00:00.000Z"
ARRIVAL_CLOCK_UTC = "2026-08-03T09:12:00.000Z"

#: Geometry of the canonical contiguous chain. Each entry is
#: (segment_code, field overrides, list of predecessor codes).
SEGMENT_SPECS = [
    (
        "S1",
        {
            "segment_type": "WALKWAY",
            "length_m": 320.0,
            "measured_clearance_cm": 118.0,
            "surface_grade_pct": 3.0,
            "sightline_m": 40.0,
            "pedestrian_flow_per_min": 6.0,
            "curb_ramp_present": True,
        },
        [],
    ),
    (
        "S2",
        {
            "segment_type": "CROSSING",
            "crossing_control": "SIGNALIZED",
            "length_m": 14.0,
            "measured_clearance_cm": 150.0,
            "surface_grade_pct": 1.5,
            "sightline_m": 35.0,
            "pedestrian_flow_per_min": 10.0,
            "curb_ramp_present": True,
        },
        ["S1"],
    ),
    (
        "S3",
        {
            "segment_type": "WALKWAY",
            "length_m": 260.0,
            "measured_clearance_cm": 104.0,
            "surface_grade_pct": 4.0,
            "sightline_m": 25.0,
            "pedestrian_flow_per_min": 12.0,
            "curb_ramp_present": False,
        },
        ["S2"],
    ),
    (
        "S5",
        {
            "segment_type": "WALKWAY",
            "length_m": 180.0,
            "measured_clearance_cm": 92.0,
            "surface_grade_pct": 6.5,
            "sightline_m": 30.0,
            "pedestrian_flow_per_min": 5.0,
            "curb_ramp_present": True,
        },
        ["S3"],
    ),
]

STAGES = [
    "zone",
    "mapped_segment",
    "approved_segment",
    "two_segments",
    "segments",
    "permitted",
    "merchant",
    "robot",
    "order",
    "mission",
    "loaded",
    "plan",
    "active_plan",
    "en_route",
    "arrived",
    "completed",
]


# --------------------------------------------------------------------------
# Primitive helpers
# --------------------------------------------------------------------------

def set_clock(instant: str, headers=None) -> None:
    """Move the logical clock to an explicit instant."""
    get_success_data(api_client.set_current_utc(clock_payload(instant), headers or ADMIN))


def read_zone(zone_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_service_zone(zone_id, headers or ADMIN))


def read_segment(segment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_sidewalk_segment(segment_id, headers or ADMIN))


def read_closure(closure_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_segment_closure(closure_id, headers or ADMIN))


def read_merchant(merchant_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, headers or ADMIN))


def read_robot(robot_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_robot(robot_id, headers or ADMIN))


def read_bay(bay_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_depot_bay(bay_id, headers or ADMIN))


def read_reservation(reservation_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_bay_reservation(reservation_id, headers or ADMIN))


def read_order(order_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_order(order_id, headers or ADMIN))


def read_mission(mission_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_delivery_mission(mission_id, headers or ADMIN))


def read_plan(plan_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_route_plan(plan_id, headers or ADMIN))


def read_intervention(event_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_intervention_event(event_id, headers or ADMIN))


def read_incident(report_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_incident_report(report_id, headers or ADMIN))


def read_economics(zone_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_zone_economics(zone_id, headers or ADMIN))


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def provision_zone(**overrides) -> dict:
    """Provision one service zone and return the created row."""
    return get_success_data(
        api_client.create_service_zone(create_service_zone_payload(**overrides), ADMIN)
    )


def map_segment(zone_id: str, segment_code: str, connected_segment_ids=None, **overrides) -> dict:
    """Map one segment into a zone. Leaves it in its initial status."""
    payload = create_sidewalk_segment_payload(zone_id, segment_code, **overrides)
    if connected_segment_ids is not None:
        payload["connected_segment_ids"] = list(connected_segment_ids)
    return get_success_data(api_client.create_sidewalk_segment(payload, ADMIN))


def survey_segment(segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.segment_transition(
            segment_id, segment_transition_payload("SURVEY", **overrides), ADMIN
        )
    )


def approve_segment(segment_id: str) -> dict:
    return get_success_data(
        api_client.segment_transition(segment_id, segment_transition_payload("APPROVE"), ADMIN)
    )


def add_segment(
    zone_id: str,
    segment_code: str,
    connected_segment_ids=None,
    survey: bool = True,
    approve: bool = True,
    survey_overrides=None,
    **overrides,
) -> dict:
    """Map a segment and walk it as far as requested. Returns the latest row."""
    segment = map_segment(zone_id, segment_code, connected_segment_ids, **overrides)
    if survey:
        segment = survey_segment(segment["id"], **(survey_overrides or {}))
    if survey and approve:
        segment = approve_segment(segment["id"])
    return segment


def activate_permit(zone_id: str) -> dict:
    return get_success_data(
        api_client.zone_permit_transition(
            zone_id, permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
        )
    )


def add_merchant(zone_id: str, activate: bool = True, **overrides) -> dict:
    """Onboard a merchant and optionally activate its integration."""
    merchant = get_success_data(
        api_client.create_merchant(create_merchant_payload(zone_id, **overrides), ADMIN)
    )
    if activate:
        merchant = get_success_data(
            api_client.merchant_integration_transition(
                merchant["id"], integration_transition_payload("ACTIVATE"), ADMIN
            )
        )
    return merchant


def add_robot(
    zone_id: str,
    asset_tag: str = "RBT-001",
    stage: bool = True,
    make_available: bool = True,
    **overrides,
) -> dict:
    """Register a robot and walk its duty dimension as far as requested."""
    robot = get_success_data(
        api_client.create_robot(create_robot_payload(zone_id, asset_tag, **overrides), ADMIN)
    )
    if stage:
        robot = get_success_data(
            api_client.robot_duty_transition(
                robot["id"], duty_transition_payload("STAGE"), DISPATCHER
            )
        )
    if stage and make_available:
        robot = get_success_data(
            api_client.robot_duty_transition(
                robot["id"], duty_transition_payload("MAKE_AVAILABLE"), DISPATCHER
            )
        )
    return robot


def add_order(merchant_id: str, dropoff_segment_id: str, headers=None, **overrides) -> dict:
    """Place an order. The caller identity defaults to the owning merchant."""
    return get_success_data(
        api_client.create_delivery_order(
            create_delivery_order_payload(merchant_id, dropoff_segment_id, **overrides),
            headers or make_merchant_operator_headers(merchant_id),
        )
    )


def dispatch_mission(order: dict, robot_id: str, headers=None) -> dict:
    """Dispatch a named robot against a received order."""
    return get_success_data(
        api_client.create_delivery_mission(
            create_delivery_mission_payload(order["id"], robot_id, order["version"]),
            headers or DISPATCHER,
        )
    )


def load_mission(mission_id: str, merchant_id: str, actual_payload_liters: float, **overrides) -> dict:
    """Record the merchant handoff as the owning merchant."""
    return get_success_data(
        api_client.load_delivery_mission(
            mission_id,
            load_payload(actual_payload_liters, **overrides),
            make_merchant_operator_headers(merchant_id),
        )
    )


def submit_route_plan(mission: dict, segment_sequence, headers=None) -> dict:
    """Submit a candidate route pinned to the mission's current version."""
    return get_success_data(
        api_client.create_route_plan(
            create_route_plan_payload(mission["id"], segment_sequence, mission["version"]),
            headers or DISPATCHER,
        )
    )


def validate_plan(plan_id: str) -> dict:
    return get_success_data(
        api_client.route_plan_transition(plan_id, plan_transition_payload("VALIDATE"), DISPATCHER)
    )


def activate_plan(plan_id: str) -> dict:
    return get_success_data(
        api_client.route_plan_transition(plan_id, plan_transition_payload("ACTIVATE"), DISPATCHER)
    )


def validate_and_activate_plan(plan_id: str) -> dict:
    validate_plan(plan_id)
    return activate_plan(plan_id)


def mission_action(mission_id: str, action: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.mission_transition(
            mission_id,
            mission_transition_payload(action, **overrides),
            headers or DISPATCHER,
        )
    )


def add_depot_bay(zone_id: str, bay_code: str = "BAY-1", **overrides) -> dict:
    return get_success_data(
        api_client.create_depot_bay(create_depot_bay_payload(zone_id, bay_code, **overrides), ADMIN)
    )


def reserve_bay(bay: dict, robot_id: str, headers=None, **overrides) -> dict:
    """Reserve a bay window pinned to the bay's current version."""
    return get_success_data(
        api_client.create_bay_reservation(
            create_bay_reservation_payload(bay["id"], robot_id, bay["version"], **overrides),
            headers or DISPATCHER,
        )
    )


def reservation_action(reservation_id: str, action: str, headers=None) -> dict:
    return get_success_data(
        api_client.bay_reservation_transition(
            reservation_id, reservation_transition_payload(action), headers or DISPATCHER
        )
    )


def add_closure(segment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_segment_closure(
            create_segment_closure_payload(segment_id, **overrides), ADMIN
        )
    )


def activate_closure(closure_id: str) -> dict:
    return get_success_data(
        api_client.closure_transition(closure_id, {"action": "ACTIVATE"}, ADMIN)
    )


def lift_closure(closure_id: str) -> dict:
    return get_success_data(api_client.closure_transition(closure_id, {"action": "LIFT"}, ADMIN))


def send_telemetry(robot_id: str, headers=None, **frame) -> dict:
    """Ingest a telemetry frame carrying only the named fields."""
    return get_success_data(
        api_client.ingest_telemetry(robot_id, telemetry_payload(**frame), headers or DISPATCHER)
    )


def set_battery(robot_id: str, battery_pct: float, headers=None) -> dict:
    """Drive the stored state of charge to an explicit percentage."""
    return send_telemetry(robot_id, headers=headers, battery_pct=battery_pct)


def health_action(robot_id: str, action: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.robot_health_transition(
            robot_id, health_transition_payload(action, **overrides), headers or OFFICER
        )
    )


def duty_action(robot_id: str, action: str, headers=None) -> dict:
    return get_success_data(
        api_client.robot_duty_transition(
            robot_id, duty_transition_payload(action), headers or DISPATCHER
        )
    )


def open_intervention(mission_id: str, autonomy_confidence_pct: int, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_intervention_event(
            create_intervention_event_payload(mission_id, autonomy_confidence_pct, **overrides),
            headers or OPERATOR,
        )
    )


def intervention_action(event_id: str, action: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.intervention_transition(
            event_id, intervention_transition_payload(action, **overrides), headers or OPERATOR
        )
    )


def run_full_takeover(mission_id: str, autonomy_confidence_pct: int, headers=None) -> dict:
    """Open a takeover, acknowledge, assume and release it as one operator."""
    operator = headers or OPERATOR
    event = open_intervention(mission_id, autonomy_confidence_pct, headers=operator)
    intervention_action(event["id"], "ACKNOWLEDGE", headers=operator)
    intervention_action(event["id"], "ASSUME", headers=operator)
    return intervention_action(event["id"], "RELEASE", headers=operator)


def file_incident(zone_id: str, robot_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_incident_report(
            create_incident_report_payload(zone_id, robot_id, **overrides), headers or OPERATOR
        )
    )


def incident_action(report_id: str, action: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.incident_transition(
            report_id, incident_transition_payload(action, **overrides), headers or OFFICER
        )
    )


def abort_mission(mission_id: str, reason_code: str = "DISPATCH_CANCELLED") -> dict:
    return mission_action(mission_id, "ABORT", reason_code=reason_code)


def _remember_segment(ctx: dict, code: str, segment: dict) -> None:
    ctx["segments"][code] = segment
    ctx[code.lower()] = segment["id"]


# --------------------------------------------------------------------------
# The canonical chain
# --------------------------------------------------------------------------

def build_scenario(
    stage: str = "completed",
    *,
    clock: str = BASE_CLOCK_UTC,
    zone_overrides=None,
    segment_overrides=None,
    merchant_overrides=None,
    activate_merchant: bool = True,
    robot_overrides=None,
    order_overrides=None,
    load_liters=None,
    route_sequence=None,
    arrival_clock: str = ARRIVAL_CLOCK_UTC,
) -> dict:
    """Walk the canonical chain from an empty database up to ``stage``.

    ``segment_overrides`` is keyed by segment code, e.g.
    ``{"S5": {"measured_clearance_cm": 90.0}}``. The returned context carries
    the zone (``z``/``zone``), each segment id under its lowercased code
    (``s1``..``s5``) and row under ``segments``, the merchant (``m``,
    ``merchant``, ``merchant_headers``), the robot (``r``, ``robot``), the order
    (``o``, ``order``), the mission (``mi``, ``mission``), the minted lid code
    (``lid``) and the route plan (``p``, ``plan``).
    """
    assert stage in STAGES, f"unknown stage {stage!r}"
    stop = STAGES.index(stage)
    seg_over = segment_overrides or {}
    ctx: dict = {"segments": {}}

    set_clock(clock)
    zone = provision_zone(**(zone_overrides or {}))
    ctx["zone"] = zone
    ctx["z"] = zone["id"]
    if stop == 0:
        return ctx

    code, spec, _ = SEGMENT_SPECS[0]
    fields = dict(spec)
    fields.update(seg_over.get(code, {}))
    segment = map_segment(ctx["z"], code, None, **fields)
    _remember_segment(ctx, code, segment)
    if stop == 1:
        return ctx

    survey_segment(segment["id"])
    _remember_segment(ctx, code, approve_segment(segment["id"]))
    if stop == 2:
        return ctx

    for code, spec, preds in SEGMENT_SPECS[1:]:
        needed = 3 if code == "S2" else 4
        if stop < needed:
            return ctx
        fields = dict(spec)
        fields.update(seg_over.get(code, {}))
        connected = [ctx["segments"][p]["id"] for p in preds]
        _remember_segment(ctx, code, add_segment(ctx["z"], code, connected, **fields))
    if stop <= 4:
        return ctx

    activate_permit(ctx["z"])
    ctx["zone"] = read_zone(ctx["z"])
    if stop == 5:
        return ctx

    merchant = add_merchant(ctx["z"], activate=activate_merchant, **(merchant_overrides or {}))
    ctx["merchant"] = merchant
    ctx["m"] = merchant["id"]
    ctx["merchant_headers"] = make_merchant_operator_headers(merchant["id"])
    if stop == 6:
        return ctx

    robot = add_robot(ctx["z"], **(robot_overrides or {}))
    ctx["robot"] = robot
    ctx["r"] = robot["id"]
    if stop == 7:
        return ctx

    order = add_order(ctx["m"], ctx["s5"], **(order_overrides or {}))
    ctx["order"] = order
    ctx["o"] = order["id"]
    ctx["o_v"] = order["version"]
    if stop == 8:
        return ctx

    mission = dispatch_mission(order, ctx["r"])
    ctx["mission"] = mission
    ctx["mi"] = mission["id"]
    if stop == 9:
        return ctx

    liters = order["payload_liters"] if load_liters is None else load_liters
    mission = load_mission(ctx["mi"], ctx["m"], liters)
    ctx["mission"] = mission
    ctx["mi_v"] = mission["version"]
    ctx["lid"] = mission["lid_access_code"]
    if stop == 10:
        return ctx

    sequence = route_sequence or [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    plan = submit_route_plan(mission, sequence)
    ctx["plan"] = plan
    ctx["p"] = plan["id"]
    if stop == 11:
        return ctx

    ctx["plan"] = validate_and_activate_plan(ctx["p"])
    if stop == 12:
        return ctx

    ctx["mission"] = mission_action(ctx["mi"], "DEPART")
    if stop == 13:
        return ctx

    set_clock(arrival_clock)
    ctx["mission"] = mission_action(ctx["mi"], "ARRIVE")
    if stop == 14:
        return ctx

    ctx["mission"] = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])
    ctx["order"] = read_order(ctx["o"])
    return ctx


# --------------------------------------------------------------------------
# Named stage shortcuts
# --------------------------------------------------------------------------

def setup_zone(**kwargs) -> dict:
    """Logical clock set and one provisioned zone."""
    return build_scenario("zone", **kwargs)


def setup_mapped_segment(**kwargs) -> dict:
    """Zone plus S1 in its initial mapping state."""
    return build_scenario("mapped_segment", **kwargs)


def setup_approved_segment(**kwargs) -> dict:
    """Zone plus one approved segment S1."""
    return build_scenario("approved_segment", **kwargs)


def setup_two_approved_segments(**kwargs) -> dict:
    """Zone plus approved S1 and the adjacent approved crossing S2."""
    return build_scenario("two_segments", **kwargs)


def setup_route_segments(**kwargs) -> dict:
    """Zone plus the whole approved contiguous chain S1, S2, S3, S5."""
    return build_scenario("segments", **kwargs)


def setup_permitted_zone(**kwargs) -> dict:
    """Approved chain plus an activated operating permit."""
    return build_scenario("permitted", **kwargs)


def setup_active_merchant(**kwargs) -> dict:
    """Permitted zone plus one merchant with an active integration."""
    return build_scenario("merchant", **kwargs)


def setup_available_robot(**kwargs) -> dict:
    """Active merchant plus one registered, staged, available robot."""
    return build_scenario("robot", **kwargs)


def setup_received_order(**kwargs) -> dict:
    """Available robot plus one received order dropping off on S5."""
    return build_scenario("order", **kwargs)


def setup_planned_mission(**kwargs) -> dict:
    """Received order dispatched onto the robot; mission not yet loaded."""
    return build_scenario("mission", **kwargs)


def setup_loaded_mission(**kwargs) -> dict:
    """Planned mission with the merchant handoff recorded and the lid minted."""
    return build_scenario("loaded", **kwargs)


def setup_draft_route_plan(**kwargs) -> dict:
    """Loaded mission with a submitted candidate route."""
    return build_scenario("plan", **kwargs)


def setup_active_route_plan(**kwargs) -> dict:
    """Loaded mission whose route has been validated and activated."""
    return build_scenario("active_plan", **kwargs)


def setup_en_route_mission(**kwargs) -> dict:
    """Mission departed on its active route."""
    return build_scenario("en_route", **kwargs)


def setup_handoff_ready_mission(**kwargs) -> dict:
    """Mission arrived at the dropoff, twelve minutes after departure."""
    return build_scenario("arrived", **kwargs)


def setup_completed_delivery(**kwargs) -> dict:
    """Full lifecycle through a completed mission and a delivered order."""
    return build_scenario("completed", **kwargs)


# --------------------------------------------------------------------------
# Derived scenarios
# --------------------------------------------------------------------------

def setup_blocked_mission(blocking_code: str = "S3", **kwargs) -> dict:
    """En-route mission stopped by an operator-reported blockage."""
    ctx = setup_en_route_mission(**kwargs)
    ctx["mission"] = mission_action(
        ctx["mi"],
        "REPORT_BLOCKAGE",
        headers=OPERATOR,
        blocking_segment_id=ctx["segments"][blocking_code]["id"],
    )
    return ctx


def setup_exception_order(reason_code: str = "DISPATCH_CANCELLED", **kwargs) -> dict:
    """Loaded mission aborted, leaving the order in an exception with a latched
    reason. ``DISPATCH_CANCELLED`` latches a robot-fault exception."""
    ctx = setup_loaded_mission(**kwargs)
    ctx["mission"] = abort_mission(ctx["mi"], reason_code)
    ctx["order"] = read_order(ctx["o"])
    return ctx


def setup_late_delivery(promised_by_utc: str = "2026-08-03T09:05:00.000Z", **kwargs) -> dict:
    """Completed delivery whose completion instant is past the promise, so the
    order carries the late latch and qualifies for a remedy."""
    order_overrides = dict(kwargs.pop("order_overrides", None) or {})
    order_overrides.setdefault("promised_by_utc", promised_by_utc)
    return setup_completed_delivery(order_overrides=order_overrides, **kwargs)


def setup_other_zone(
    name: str = "Bayview",
    segment_code: str = "B1",
    permit: bool = True,
    with_merchant: bool = False,
    with_robot: bool = False,
    **zone_overrides,
) -> dict:
    """A second, independently permitted zone with one approved segment.

    Used wherever a rule has to be exercised across a zone boundary.
    """
    zone = provision_zone(name=name, **zone_overrides)
    ctx: dict = {"zone": zone, "z": zone["id"], "segments": {}}
    segment = add_segment(
        zone["id"],
        segment_code,
        None,
        length_m=200.0,
        measured_clearance_cm=120.0,
        surface_grade_pct=2.0,
        sightline_m=40.0,
        pedestrian_flow_per_min=4.0,
        curb_ramp_present=True,
    )
    _remember_segment(ctx, segment_code, segment)
    ctx["segment"] = segment
    if permit:
        activate_permit(zone["id"])
        ctx["zone"] = read_zone(zone["id"])
    if with_merchant:
        merchant = add_merchant(zone["id"], name=f"{name} Deli")
        ctx["merchant"] = merchant
        ctx["m"] = merchant["id"]
        ctx["merchant_headers"] = make_merchant_operator_headers(merchant["id"])
    if with_robot:
        robot = add_robot(zone["id"], asset_tag=f"{segment_code}-RBT-1")
        ctx["robot"] = robot
        ctx["r"] = robot["id"]
    return ctx


def setup_charge_bay_reservation(
    window_start_utc: str = "2026-08-03T10:00:00.000Z",
    window_end_utc: str = "2026-08-03T11:00:00.000Z",
    **kwargs,
) -> dict:
    """Available robot plus one open charge bay holding one reservation."""
    ctx = setup_available_robot(**kwargs)
    bay = add_depot_bay(ctx["z"], "BAY-1", bay_type="CHARGE", power_kw=7.5)
    reservation = reserve_bay(
        bay,
        ctx["r"],
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
    )
    ctx["bay"] = read_bay(bay["id"])
    ctx["b"] = bay["id"]
    ctx["reservation"] = reservation
    ctx["res"] = reservation["id"]
    return ctx


def setup_second_robot(ctx: dict, asset_tag: str = "RBT-002", **overrides) -> dict:
    """Register one more robot into the scenario's zone and return it."""
    return add_robot(ctx["z"], asset_tag=asset_tag, **overrides)


def setup_quarantined_robot(**kwargs) -> dict:
    """En-route mission whose robot is quarantined by a tamper telemetry frame,
    which runs the quarantine cascade end to end."""
    ctx = setup_en_route_mission(**kwargs)
    send_telemetry(ctx["r"], tamper_flag=True)
    ctx["robot"] = read_robot(ctx["r"])
    ctx["mission"] = read_mission(ctx["mi"])
    ctx["order"] = read_order(ctx["o"])
    return ctx
