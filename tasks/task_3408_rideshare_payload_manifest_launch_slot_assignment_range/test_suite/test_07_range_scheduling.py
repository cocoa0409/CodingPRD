"""Range scheduling: slot reservation turnaround buffer, confirmation gates
(license, COLA, containment), and dispenser-port uniqueness."""
from test_helpers import (
    ApiErrorId,
    confirm_slot,
    create_customer,
    create_granted_mission_license,
    create_mission,
    create_port,
    create_range_slot,
    get_mission,
    publish_exclusion_window,
    reserve_slot,
    set_clock,
    setup_locked_mission,
    validate_error,
    validate_success,
    api_client,
)
from test_helpers.test_users import TEST_USERS

MOPS = TEST_USERS["mission_ops_headers"]
RO = TEST_USERS["range_officer_headers"]


def _setup_locked_with_reserved_slot():
    ctx = setup_locked_mission()
    slot = create_range_slot(ctx["mission"]["id"])
    reserve_slot(slot["id"])
    return ctx, slot


def test_range_confirm_blocked_until_launch_license_granted(api):
    """PRD §3.5: "The mission must hold a `GRANTED` license of kind
    `LAUNCH_AUTHORIZATION` whose `valid_until` is on or after the slot's
    `window_close_utc`, else `ERR_LICENSE_NOT_GRANTED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/range_confirm_blocked_until_launch_license_granted
    """
    ctx, slot = _setup_locked_with_reserved_slot()
    resp = api_client.confirm_range_slot(slot["id"], RO)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_GRANTED)
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RESERVED", "the rejected confirm leaves the slot RESERVED"


def test_range_confirm_succeeds_after_grant_and_advances_mission(api):
    """PRD §3.5: "On success the slot becomes `CONFIRMED` with a version
    increment, and the mission automatically advances from `MANIFEST_LOCKED` to
    `RANGE_SCHEDULED`, incrementing the mission's `version` as well."
    PRD §3.4: "The system immediately computes `composite_score` as one-half of
    `debris_score` plus three-tenths of `spectrum_score` plus one-fifth of
    `operator_history_score`, rounded half up to a whole integer"

    Design: Difficulty/cross_entity_state_dependency/range_confirm_blocked_until_launch_license_granted
    """
    ctx, slot = _setup_locked_with_reserved_slot()
    resp = api_client.confirm_range_slot(slot["id"], RO)
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_GRANTED)

    lic = create_granted_mission_license(ctx["mission"]["id"])
    assert lic["composite_score"] == 87, "0.5x90 + 0.3x80 + 0.2x90 = 87"

    confirmed = confirm_slot(slot["id"])
    assert confirmed["status"] == "CONFIRMED"
    mission = get_mission(ctx["mission"]["id"])
    assert mission["status"] == "RANGE_SCHEDULED", (
        "the confirm auto-advances the mission"
    )


def test_range_reserve_rejects_44_minute_gap(api):
    """PRD §3.5: "on at least one side, a clear gap of 45 minutes or more must
    separate the two windows — either the new window's `window_close_utc` plus 45
    minutes falls on or before the existing window's `window_open_utc`, or the
    existing window's `window_close_utc` plus 45 minutes falls on or before the
    new window's `window_open_utc`. A gap of exactly 45 minutes passes; anything
    shorter is a conflict, rejected with `ERR_RANGE_WINDOW_CONFLICT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/range_reserve_respects_exactly_45_minute_turnaround
    """
    set_clock()
    m1 = create_mission()
    s1 = create_range_slot(m1["id"], window_open_utc="2026-10-10T00:00:00Z",
                           window_close_utc="2026-10-12T00:00:00Z")
    reserve_slot(s1["id"])
    m2 = create_mission(
        mission_name="Transporter-X4",
        window_open_utc="2026-10-12T00:00:00Z",
        window_close_utc="2026-10-16T00:00:00Z",
        mass_capacity_kg=50,
        volume_capacity_m3=1.0,
    )
    s2 = create_range_slot(m2["id"], window_open_utc="2026-10-12T00:44:00Z",
                           window_close_utc="2026-10-14T00:00:00Z")
    resp = api_client.reserve_range_slot(s2["id"], RO)
    validate_error(resp, ApiErrorId.ERR_RANGE_WINDOW_CONFLICT)
    slots = validate_success(
        api_client.list_mission_range_slots(m2["id"], RO), 200
    )
    assert slots[0]["status"] == "REQUESTED", (
        "a failed reserve never occupies the range"
    )


def test_range_reserve_allows_exactly_45_minute_gap(api):
    """PRD §3.5: "A gap of exactly 45 minutes passes; anything shorter is a
    conflict, rejected with `ERR_RANGE_WINDOW_CONFLICT` (HTTP 422). Slots in
    `REQUESTED`, `RELEASED`, or `CONSUMED` never participate in the conflict
    check."

    Design: Difficulty/resource_temporal_overlap/range_reserve_respects_exactly_45_minute_turnaround
    """
    set_clock()
    m1 = create_mission()
    s1 = create_range_slot(m1["id"], window_open_utc="2026-10-10T00:00:00Z",
                           window_close_utc="2026-10-12T00:00:00Z")
    reserve_slot(s1["id"])
    m2 = create_mission(
        mission_name="Transporter-X4",
        window_open_utc="2026-10-12T00:00:00Z",
        window_close_utc="2026-10-16T00:00:00Z",
        mass_capacity_kg=50,
        volume_capacity_m3=1.0,
    )
    s3 = create_range_slot(m2["id"], window_open_utc="2026-10-12T00:45:00Z",
                           window_close_utc="2026-10-14T00:00:00Z")
    reserved = reserve_slot(s3["id"])
    assert reserved["status"] == "RESERVED", (
        "the 45-minute boundary belongs to the allowed side"
    )


def _setup_two_locked_missions_for_cola():
    """Two SSO missions, each locked with one CONFIRMED-then-INTEGRATED
    assignment and a GRANTED launch license (valid_until 2026-12-31).

    The second mission carries a CUBESAT payload on a port whose supported
    interface classes include CUBESAT, so the assignment is interface-legal.
    """
    ctx1 = setup_locked_mission()
    create_granted_mission_license(ctx1["mission"]["id"])
    ctx2 = setup_locked_mission(
        mission_overrides={"mission_name": "Transporter-X5"},
        port_specs=[{"supported_interface_classes": ["RING_15", "RING_24", "CUBESAT"]}],
        payload_specs=[{"payload_name": "PL2", "mass_kg": 50, "volume_m3": 1.0,
                        "interface_class": "CUBESAT"}],
    )
    create_granted_mission_license(ctx2["mission"]["id"])
    return ctx1, ctx2


def test_cola_touching_slot_confirms(api):
    """PRD §3.5: "No `COLA` exclusion window scoped to the mission's
    `target_orbit` may intersect the slot window under half-open semantics —
    intersection meaning the slot's `window_open_utc` is strictly before the
    exclusion window's `end_utc` and the exclusion window's `start_utc` is
    strictly before the slot's `window_close_utc`; windows that merely touch,
    the slot closing exactly as the exclusion opens or opening exactly as the
    exclusion closes, do not conflict — else `ERR_COLA_CONFLICT` (422)."

    Design: Difficulty/resource_temporal_overlap/cola_touching_slot_confirms_overlapping_slot_rejected
    """
    ctx1, _ctx2 = _setup_two_locked_missions_for_cola()
    publish_exclusion_window(
        scope_type="ORBIT", scope_value="SSO", kind="COLA",
        start_utc="2026-10-21T00:00:00Z", end_utc="2026-10-23T00:00:00Z",
    )
    s1 = create_range_slot(
        ctx1["mission"]["id"], range_code="CCAFS",
        window_open_utc="2026-10-09T00:00:00Z", window_close_utc="2026-10-21T00:00:00Z",
    )
    reserve_slot(s1["id"])
    confirmed = confirm_slot(s1["id"])
    assert confirmed["status"] == "CONFIRMED", (
        "slot close 2026-10-21T00:00:00Z == COLA start: touching half-open intervals do not intersect"
    )
    assert get_mission(ctx1["mission"]["id"])["status"] == "RANGE_SCHEDULED"


def test_cola_overlapping_slot_confirm_rejected(api):
    """PRD §3.5: "No `COLA` exclusion window scoped to the mission's
    `target_orbit` may intersect the slot window under half-open semantics —
    intersection meaning the slot's `window_open_utc` is strictly before the
    exclusion window's `end_utc` and the exclusion window's `start_utc` is
    strictly before the slot's `window_close_utc`; windows that merely touch,
    the slot closing exactly as the exclusion opens or opening exactly as the
    exclusion closes, do not conflict — else `ERR_COLA_CONFLICT` (422)."

    Design: Difficulty/resource_temporal_overlap/cola_touching_slot_confirms_overlapping_slot_rejected
    """
    ctx1, ctx2 = _setup_two_locked_missions_for_cola()
    publish_exclusion_window(
        scope_type="ORBIT", scope_value="SSO", kind="COLA",
        start_utc="2026-10-21T00:00:00Z", end_utc="2026-10-23T00:00:00Z",
    )
    s1 = create_range_slot(
        ctx1["mission"]["id"], range_code="CCAFS",
        window_open_utc="2026-10-09T00:00:00Z", window_close_utc="2026-10-21T00:00:00Z",
    )
    reserve_slot(s1["id"])
    confirm_slot(s1["id"])

    publish_exclusion_window(
        scope_type="ORBIT", scope_value="SSO", kind="COLA",
        start_utc="2026-10-20T12:00:00Z", end_utc="2026-10-23T00:00:00Z",
    )
    s2 = create_range_slot(
        ctx2["mission"]["id"], range_code="VAFB",
        window_open_utc="2026-10-09T00:00:00Z", window_close_utc="2026-10-21T00:00:00Z",
    )
    reserve_slot(s2["id"])
    resp = api_client.confirm_range_slot(s2["id"], RO)
    validate_error(resp, ApiErrorId.ERR_COLA_CONFLICT)
    slots = validate_success(
        api_client.list_mission_range_slots(ctx2["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RESERVED"
    assert get_mission(ctx2["mission"]["id"])["status"] == "MANIFEST_LOCKED"


def test_duplicate_port_code_and_stack_position_rejected(api):
    """PRD §3.1: "Both `port_code` and `stack_position` must be unique within
    the mission; reusing either is rejected with `ERR_DUPLICATE_PORT_CODE`
    (HTTP 422)."

    Design: Corner/validations/duplicate_port_code_and_stack_position_rejected
    """
    set_clock()
    mission = create_mission()
    create_port(mission["id"])  # DSP-A at stack_position 4

    r1 = api_client.create_dispenser_port(
        mission["id"],
        {"port_code": "DSP-A", "stack_position": 9, "max_mass_kg": 100,
         "supported_interface_classes": ["CUBESAT"]},
        MOPS,
    )
    validate_error(r1, ApiErrorId.ERR_DUPLICATE_PORT_CODE)

    r2 = api_client.create_dispenser_port(
        mission["id"],
        {"port_code": "DSP-Z", "stack_position": 4, "max_mass_kg": 100,
         "supported_interface_classes": ["CUBESAT"]},
        MOPS,
    )
    validate_error(r2, ApiErrorId.ERR_DUPLICATE_PORT_CODE)

    ports = validate_success(api_client.list_dispenser_ports(mission["id"], MOPS), 200)
    assert len(ports) == 1, "neither duplicate persists a row"


def test_slot_confirm_without_window_containment_rejected(api):
    """PRD §3.5: "And the slot window must contain the mission window: the
    slot's `window_open_utc` on or before the mission's `window_open_utc`, and
    the slot's `window_close_utc` on or after the mission's `window_close_utc`,
    else `ERR_WINDOW_INCOMPATIBLE` (422)."

    Design: Corner/errors/slot_confirm_without_window_containment_rejected
    """
    ctx = setup_locked_mission()
    create_granted_mission_license(ctx["mission"]["id"])
    slot = create_range_slot(
        ctx["mission"]["id"],
        window_open_utc="2026-10-12T00:00:00Z",
        window_close_utc="2026-10-18T00:00:00Z",
    )
    reserve_slot(slot["id"])
    resp = api_client.confirm_range_slot(slot["id"], RO)
    validate_error(resp, ApiErrorId.ERR_WINDOW_INCOMPATIBLE)
    slots = validate_success(
        api_client.list_mission_range_slots(ctx["mission"]["id"], RO), 200
    )
    assert slots[0]["status"] == "RESERVED"
    assert get_mission(ctx["mission"]["id"])["status"] == "MANIFEST_LOCKED"
