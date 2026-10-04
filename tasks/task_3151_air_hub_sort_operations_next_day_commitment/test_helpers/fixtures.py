"""Composite setup helpers.

Every fixture builds its preconditions from scratch through the public API,
because the harness restarts the server before each individual test. Fixtures
use ``get_success_data`` internally so a broken precondition surfaces as a clear
"Setup failed" message rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_1400,
    CLOCK_START,
    LANE_CAPACITY_STANDARD,
    LANE_CAPACITY_WIDE,
    LANE_CERTIFIED_UNTIL,
    LANE_HAZMAT_CERTIFIED_UNTIL,
    SHIFT_NB_CODE,
    SHIFT_NB_END,
    SHIFT_NB_HEADCOUNT,
    SHIFT_NB_START,
    TEST_DEFAULTS,
)
from .factories import (
    create_aircraft_payload,
    create_alternate_hub_payload,
    create_bank_payload,
    create_buildup_payload,
    create_feeder_payload,
    create_hub_payload,
    create_lane_payload,
    create_move_payload,
    create_package_payload,
    create_shift_payload,
)
from .test_users import TEST_USERS

H = TEST_USERS
_API = api_client


# ─── Clock ─────────────────────────────────────────────────────────────────

def set_clock(instant: str):
    """Pin the logical clock. Returns the raw response."""
    return _API.set_clock(instant, H["hub_ops_manager_headers"])


def reset_clock():
    """Pin the clock at the operating night's open instant (minute 1380)."""
    return set_clock(CLOCK_START)


def advance_clock(instant: str):
    return set_clock(instant)


# ─── Single-entity creators ────────────────────────────────────────────────

def create_hub(alternate_hub_id=None, **overrides) -> dict:
    payload = create_hub_payload(**overrides)
    if alternate_hub_id is not None:
        payload["alternate_hub_id"] = alternate_hub_id
    return get_success_data(_API.create_hub(payload, H["hub_ops_manager_headers"]))


def create_alternate_hub(**overrides) -> dict:
    return get_success_data(
        _API.create_hub(create_alternate_hub_payload(**overrides),
                        H["hub_ops_manager_headers"])
    )


def create_lane(hub_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_lane(create_lane_payload(hub_id, **overrides),
                         H["sort_supervisor_headers"])
    )


def create_bank(hub_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_bank(create_bank_payload(hub_id, **overrides),
                         H["hub_ops_manager_headers"])
    )


def create_aircraft(bank_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_aircraft(create_aircraft_payload(bank_id, **overrides),
                             H["gateway_coordinator_headers"])
    )


def create_shift(hub_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_shift(create_shift_payload(hub_id, **overrides),
                          H["sort_supervisor_headers"])
    )


def create_extension_shift(hub_id: str, **overrides) -> dict:
    """The overnight shift that still covers the minutes past the sort window close."""
    return create_shift(
        hub_id,
        shift_code=SHIFT_NB_CODE,
        start_minutes=SHIFT_NB_START,
        end_minutes=SHIFT_NB_END,
        headcount=SHIFT_NB_HEADCOUNT,
        **overrides,
    )


def create_move(hub_id: str, aircraft_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_move(create_move_payload(hub_id, aircraft_id, **overrides),
                         H["load_planner_headers"])
    )


def create_buildup(hub_id: str, load_move_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_buildup(create_buildup_payload(hub_id, load_move_id, **overrides),
                            H["load_planner_headers"])
    )


def create_feeder(hub_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_feeder(create_feeder_payload(hub_id, **overrides),
                           H["feeder_coordinator_headers"])
    )


def create_package(hub_id: str, aircraft_id: str, **overrides) -> dict:
    return get_success_data(
        _API.create_package(create_package_payload(hub_id, aircraft_id, **overrides),
                            H["sort_operator_headers"])
    )


# ─── Read helpers ──────────────────────────────────────────────────────────

def get_hub(hub_id: str) -> dict:
    return get_success_data(_API.get_hub(hub_id, H["hub_ops_manager_headers"]))


def get_package(package_id: str) -> dict:
    return get_success_data(_API.get_package(package_id, H["sort_operator_headers"]))


def get_move(move_id: str) -> dict:
    return get_success_data(_API.get_move(move_id, H["load_planner_headers"]))


def get_buildup(buildup_id: str) -> dict:
    return get_success_data(_API.get_buildup(buildup_id, H["load_planner_headers"]))


def get_lane(lane_id: str) -> dict:
    return get_success_data(_API.get_lane(lane_id, H["sort_operator_headers"]))


def get_shift(shift_id: str) -> dict:
    return get_success_data(_API.get_shift(shift_id, H["sort_supervisor_headers"]))


def get_feeder(feeder_id: str) -> dict:
    return get_success_data(_API.get_feeder(feeder_id, H["feeder_coordinator_headers"]))


def get_bank(bank_id: str) -> dict:
    return get_success_data(_API.get_bank(bank_id, H["sort_supervisor_headers"]))


def list_packages(params=None) -> list:
    return get_success_data(_API.list_packages(H["sort_operator_headers"], params=params or {}))


def failed_error_id(response) -> str:
    """Return the error_id from a response the test expects to be rejected."""
    assert response.status_code >= 400, (
        f"Expected a rejection, got HTTP {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("response_type") == "error", f"Expected an error envelope: {response.text}"
    return body["data"]["error_id"]


# ─── Airside progression ───────────────────────────────────────────────────

def open_unload_face(bank_id: str) -> dict:
    return get_success_data(
        _API.begin_bank_unload(bank_id, H["sort_supervisor_headers"])
    )


def depart_and_land(aircraft_id: str, inbound_weight_grams: int = TEST_DEFAULTS["INBOUND_WEIGHT_GRAMS"]):
    depart_origin(aircraft_id)
    return get_success_data(
        _API.land_aircraft(aircraft_id, {"inbound_weight_grams": inbound_weight_grams},
                           H["gateway_coordinator_headers"])
    )


def depart_origin(aircraft_id: str) -> dict:
    return get_success_data(_API.depart_origin(aircraft_id, H["gateway_coordinator_headers"]))


def begin_aircraft_unload(aircraft_id: str) -> dict:
    return get_success_data(
        _API.begin_aircraft_unload(aircraft_id, H["sort_supervisor_headers"])
    )


def complete_aircraft_unload(aircraft_id: str, minutes: int) -> dict:
    return get_success_data(
        _API.complete_aircraft_unload(aircraft_id, {"unload_completed_minutes": minutes},
                                      H["sort_supervisor_headers"])
    )


def unload_aircraft_full(aircraft_id: str, minutes: int = 1401,
                         inbound_weight_grams: int = TEST_DEFAULTS["INBOUND_WEIGHT_GRAMS"]):
    """Depart, land, open its own unload and complete it."""
    depart_and_land(aircraft_id, inbound_weight_grams)
    begin_aircraft_unload(aircraft_id)
    return complete_aircraft_unload(aircraft_id, minutes)


# ─── Package progression ───────────────────────────────────────────────────

def induct(package_id: str, dimension_weight_grams=None) -> dict:
    pkg = get_package(package_id)
    weight = dimension_weight_grams or pkg["dimension_weight_grams"]
    return get_success_data(
        _API.induct_package(package_id, {"dimension_weight_grams": weight},
                            H["sort_operator_headers"])
    )


def primary_sort(package_id: str, lane_id: str) -> dict:
    return get_success_data(
        _API.primary_sort(package_id, {"lane_id": lane_id}, H["sort_operator_headers"])
    )


def secondary_sort(package_id: str, lane_id: str) -> dict:
    return get_success_data(
        _API.secondary_sort(package_id, {"lane_id": lane_id}, H["sort_operator_headers"])
    )


def sort_through(package_id: str, primary_lane_id: str, secondary_lane_id: str) -> dict:
    """Induct, primary-sort and secondary-sort in one call, returning the final package."""
    induct(package_id)
    primary_sort(package_id, primary_lane_id)
    return secondary_sort(package_id, secondary_lane_id)


# ─── Load move progression ─────────────────────────────────────────────────

def plan_move(move_id: str) -> dict:
    return get_success_data(_API.plan_load(move_id, H["load_planner_headers"]))


def assign_package_to_buildup(move_id: str, package_id: str, buildup_id: str) -> dict:
    return get_success_data(
        _API.assign_buildup(move_id, {"package_id": package_id, "buildup_id": buildup_id},
                            H["load_planner_headers"])
    )


def onboard_package(move_id: str, package_id: str, buildup_id=None) -> dict:
    """Load a secondary-sorted package onto a move, carrying fresh OCC versions."""
    move = get_move(move_id)
    pkg = get_package(package_id)
    payload = {
        "package_id": package_id,
        "expected_load_move_version": move["version"],
        "expected_package_version": pkg["version"],
    }
    if buildup_id is not None:
        payload["buildup_id"] = buildup_id
    return get_success_data(_API.load_package(move_id, payload, H["load_planner_headers"]))


def offboard_package(move_id: str, package_id: str) -> dict:
    return get_success_data(
        _API.unload_package(move_id, {"package_id": package_id}, H["load_planner_headers"])
    )


def onboard_outcome(move_id: str, package_id: str, buildup_id=None):
    """Onboard without asserting success — returns the raw response for error tests."""
    move = get_move(move_id)
    pkg = get_package(package_id)
    payload = {
        "package_id": package_id,
        "expected_load_move_version": move["version"],
        "expected_package_version": pkg["version"],
    }
    if buildup_id is not None:
        payload["buildup_id"] = buildup_id
    return _API.load_package(move_id, payload, H["load_planner_headers"])


# ─── Feeder progression ────────────────────────────────────────────────────

def begin_staging(feeder_id: str) -> dict:
    return get_success_data(_API.begin_staging(feeder_id, H["feeder_coordinator_headers"]))


def reclaim_package(package_id: str) -> dict:
    return get_success_data(
        _API.reclaim_lane(package_id, H["sort_operator_headers"])
    )


def get_concourse_width(params: dict) -> dict:
    return get_success_data(
        _API.get_concourse_width(H["sort_supervisor_headers"], params)
    )


def set_move_tier(move_id: str, tier: str) -> dict:
    return get_success_data(
        _API.set_move_tier(move_id, {"load_plan_tier": tier}, H["load_planner_headers"])
    )


def stage_package(feeder_id: str, package_id: str) -> dict:
    return get_success_data(
        _API.stage_package(feeder_id, {"package_id": package_id},
                           H["feeder_coordinator_headers"])
    )


def begin_feeder_loading(feeder_id: str) -> dict:
    return get_success_data(
        _API.begin_feeder_loading(feeder_id, H["feeder_coordinator_headers"])
    )


# ─── Tier 1/2/3 composite fixtures ─────────────────────────────────────────

def setup_bare_hub(alternate: bool = True) -> dict:
    """Clock at 1380 plus a hub, with no downstream resources."""
    reset_clock()
    ind = create_alternate_hub() if alternate else None
    hub = create_hub(alternate_hub_id=ind["id"] if ind else None)
    return {"hub": hub, "hub_id": hub["id"], "alt_hub": ind,
            "alt_hub_id": ind["id"] if ind else None}


def setup_hub_with_lanes(alternate: bool = True,
                         lane_capacity: int = LANE_CAPACITY_STANDARD) -> dict:
    """Hub plus a PRIMARY GENERAL lane (P-01) and a SECONDARY GENERAL lane (S-01)."""
    ctx = setup_bare_hub(alternate=alternate)
    hub_id = ctx["hub_id"]
    lane_p1 = create_lane(hub_id, lane_code="P-01", lane_kind="PRIMARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=lane_capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1400, turnout_end_minutes=1500)
    lane_s1 = create_lane(hub_id, lane_code="S-01", lane_kind="SECONDARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=lane_capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1400, turnout_end_minutes=1600)
    ctx.update({"lane_p1": lane_p1, "lane_p1_id": lane_p1["id"],
                "lane_s1": lane_s1, "lane_s1_id": lane_s1["id"]})
    return ctx


# Feet of the standard night: the two primary lanes whose turnouts touch at 1500,
# the detached third primary lane, plus secondary, irregular and hazmat lanes.
def setup_standard_lane_set(capacity: int = LANE_CAPACITY_STANDARD) -> dict:
    """The full six-lane concourse used by the geometry scenarios."""
    ctx = setup_bare_hub()
    hub_id = ctx["hub_id"]
    lane_p1 = create_lane(hub_id, lane_code="P-01", lane_kind="PRIMARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1400, turnout_end_minutes=1500)
    lane_p2 = create_lane(hub_id, lane_code="P-02", lane_kind="PRIMARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1500, turnout_end_minutes=1600)
    lane_p3 = create_lane(hub_id, lane_code="P-03", lane_kind="PRIMARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1601, turnout_end_minutes=1700)
    lane_s1 = create_lane(hub_id, lane_code="S-01", lane_kind="SECONDARY",
                          commodity_capability="GENERAL",
                          capacity_weight_grams=capacity,
                          certified_until_minutes=LANE_CERTIFIED_UNTIL,
                          turnout_start_minutes=1400, turnout_end_minutes=1600)
    lane_ir1 = create_lane(hub_id, lane_code="IR-01", lane_kind="IRREGULAR",
                           commodity_capability="IRREGULAR",
                           capacity_weight_grams=40000,
                           certified_until_minutes=LANE_CERTIFIED_UNTIL,
                           turnout_start_minutes=1400, turnout_end_minutes=1600)
    lane_hz1 = create_lane(hub_id, lane_code="HZ-01", lane_kind="HAZMAT",
                           commodity_capability="HAZMAT",
                           capacity_weight_grams=40000,
                           certified_until_minutes=LANE_HAZMAT_CERTIFIED_UNTIL,
                           turnout_start_minutes=1400, turnout_end_minutes=1600)
    ctx.update({
        "lane_p1": lane_p1, "lane_p1_id": lane_p1["id"],
        "lane_p2": lane_p2, "lane_p2_id": lane_p2["id"],
        "lane_p3": lane_p3, "lane_p3_id": lane_p3["id"],
        "lane_s1": lane_s1, "lane_s1_id": lane_s1["id"],
        "lane_ir1": lane_ir1, "lane_ir1_id": lane_ir1["id"],
        "lane_hz1": lane_hz1, "lane_hz1_id": lane_hz1["id"],
    })
    return ctx


def setup_night(alternate: bool = True, lane_capacity: int = LANE_CAPACITY_STANDARD,
                inbound_weight_grams: int = TEST_DEFAULTS["INBOUND_WEIGHT_GRAMS"]) -> dict:
    """Hub + lanes + BANK_A + N701UP landed and unloaded + the baseline shift."""
    ctx = setup_hub_with_lanes(alternate=alternate, lane_capacity=lane_capacity)
    hub_id = ctx["hub_id"]
    bank = create_bank(hub_id)
    ac1 = create_aircraft(bank["id"], tail_number="N701UP", scheduled_arrival_minutes=1395)
    shift = create_shift(hub_id)
    set_clock(CLOCK_1400)
    depart_and_land(ac1["id"], inbound_weight_grams)
    open_unload_face(bank["id"])
    begin_aircraft_unload(ac1["id"])
    complete_aircraft_unload(ac1["id"], 1401)
    ctx.update({"bank": bank, "bank_id": bank["id"],
                "ac1": ac1, "ac1_id": ac1["id"],
                "shift": shift, "shift_id": shift["id"]})
    return ctx


def setup_night_with_second_aircraft(**night_kwargs) -> dict:
    """The baseline night plus a second aircraft N702UP, still on the ground."""
    ctx = setup_night(**night_kwargs)
    ac2 = create_aircraft(ctx["bank_id"], tail_number="N702UP",
                          origin_station_code="ORD", scheduled_arrival_minutes=1402)
    ctx.update({"ac2": ac2, "ac2_id": ac2["id"]})
    return ctx


def land_second_aircraft(ctx: dict, inbound_weight_grams: int = 400000,
                         unload_minutes: int = None, complete: bool = False) -> dict:
    """Depart and land N702UP on the already-open bank.

    The logical clock is left untouched: the caller pins it, and the landing is
    stamped with whatever minute the clock currently reads.  PRD 3.2 gives a bank
    exactly one unload face, so N701UP (which already holds it) must finish its
    unload before N702UP may begin: the face is released by completing N701UP
    first.  The bank therefore returns to UNLOADING with N702UP on the face, so a
    later ``complete_aircraft_unload`` on N702UP still reads as UNLOADING.
    """
    ac2_id = ctx["ac2_id"]
    landed = depart_and_land(ac2_id, inbound_weight_grams)
    begin_aircraft_unload(ac2_id)
    if complete:
        # The unload cannot complete before the aircraft is on the ground, so a
        # caller-supplied minute that precedes the actual arrival is lifted to the
        # arrival itself (PRD 3.2: unload_completed_minutes >= actual_arrival_minutes).
        minute = unload_minutes if unload_minutes is not None else landed["actual_arrival_minutes"]
        minute = max(int(minute), int(landed["actual_arrival_minutes"]))
        complete_aircraft_unload(ac2_id, minute)


def setup_outbound_aircraft(ctx: dict, tail_number: str = "N703UP",
                            bank_code: str = "BANK_C") -> dict:
    """A separate bank plus an outbound aircraft, for move scenarios."""
    hub_id = ctx["hub_id"]
    bank_c = create_bank(hub_id, bank_code=bank_code,
                         scheduled_start_minutes=1400, scheduled_end_minutes=1600)
    ac = create_aircraft(bank_c["id"], tail_number=tail_number,
                         origin_station_code="DFW", scheduled_arrival_minutes=1400,
                         capacity_weight_grams=400000)
    return {"bank_c": bank_c, "bank_c_id": bank_c["id"], "aircraft": ac, "aircraft_id": ac["id"]}


def setup_sorted_package(ctx: dict, tracking_number: str = "1Z-T-0001",
                         aircraft_id: str = None, planned_weight_grams: int = 20000,
                         dimension_weight_grams: int = None, **overrides) -> dict:
    """Create, induct, primary-sort and secondary-sort one GENERAL package."""
    pkg = create_package(
        ctx["hub_id"],
        aircraft_id or ctx["ac1_id"],
        tracking_number=tracking_number,
        planned_weight_grams=planned_weight_grams,
        dimension_weight_grams=dimension_weight_grams or planned_weight_grams,
        **overrides,
    )
    sort_through(pkg["id"], ctx["lane_p1_id"], ctx["lane_s1_id"])
    return get_package(pkg["id"])


def setup_move_with_buildup(ctx: dict, weight_limit_grams: int = 400000,
                            container_limit_grams: int = 70000,
                            hazardous_cap_grams: int = 0,
                            requires_container: bool = False,
                            destination_gateway_code: str = "LAX",
                            aircraft_id: str = None) -> dict:
    """A planned move on the outbound aircraft plus one destination buildup."""
    move = create_move(ctx["hub_id"], aircraft_id or ctx["ac2_id"],
                       weight_limit_grams=weight_limit_grams)
    buildup = create_buildup(ctx["hub_id"], move["id"],
                             destination_gateway_code=destination_gateway_code,
                             container_limit_grams=container_limit_grams,
                             hazardous_cap_grams=hazardous_cap_grams,
                             requires_container=requires_container)
    plan_move(move["id"])
    move = get_move(move["id"])
    return {"move": move, "move_id": move["id"], "buildup": buildup, "buildup_id": buildup["id"]}


def setup_hazmat_package(ctx: dict, tracking_number: str = "1Z-HZ-0001",
                         planned_weight_grams: int = 30000) -> dict:
    """A HAZMAT package routed, primary-sorted and secondary-sorted on hazmat lanes."""
    hub_id = ctx["hub_id"]
    lane_hz_secondary = create_lane(hub_id, lane_code="S-HZ", lane_kind="HAZMAT",
                                    commodity_capability="HAZMAT",
                                    capacity_weight_grams=LANE_CAPACITY_WIDE,
                                    certified_until_minutes=LANE_CERTIFIED_UNTIL,
                                    turnout_start_minutes=1400, turnout_end_minutes=1600)
    pkg = create_package(hub_id, ctx["ac1_id"], tracking_number=tracking_number,
                         commodity_class="HAZMAT",
                         planned_weight_grams=planned_weight_grams,
                         dimension_weight_grams=planned_weight_grams)
    induct(pkg["id"])
    # A HAZMAT package is automatically moved to ROUTED_TO_HAZMAT by the primary
    # sort itself (PRD 3.3); the primary sort admits only NORMAL and
    # ROUTED_TO_IRREGULAR, so an explicit route-hazmat first would be refused.
    primary_sort(pkg["id"], ctx["lane_hz1_id"])
    secondary_sort(pkg["id"], lane_hz_secondary["id"])
    return {"package": get_package(pkg["id"]), "package_id": pkg["id"],
            "lane_hz_secondary": lane_hz_secondary,
            "lane_hz_secondary_id": lane_hz_secondary["id"]}


def setup_six_lane_night(alternate: bool = True) -> dict:
    """The six-lane concourse plus the standard night's bank, aircraft and shift."""
    ctx = setup_standard_lane_set()
    hub_id = ctx["hub_id"]
    bank = create_bank(hub_id)
    ac1 = create_aircraft(bank["id"], tail_number="N701UP", scheduled_arrival_minutes=1395)
    ac2 = create_aircraft(bank["id"], tail_number="N702UP", origin_station_code="ORD",
                          scheduled_arrival_minutes=1402)
    shift = create_shift(hub_id)
    set_clock(CLOCK_1400)
    depart_and_land(ac1["id"], 6000)
    open_unload_face(bank["id"])
    begin_aircraft_unload(ac1["id"])
    complete_aircraft_unload(ac1["id"], 1401)
    ctx.update({"bank": bank, "bank_id": bank["id"],
                "ac1": ac1, "ac1_id": ac1["id"],
                "ac2": ac2, "ac2_id": ac2["id"],
                "shift": shift, "shift_id": shift["id"]})
    return ctx


def declare_contingency(hub_id: str) -> dict:
    return get_success_data(
        _API.declare_contingency(hub_id, H["weather_officer_headers"])
    )


def clear_contingency(hub_id: str) -> dict:
    return get_success_data(
        _API.clear_contingency(hub_id, H["hub_ops_manager_headers"])
    )


def ground_stop(hub_id: str) -> dict:
    return get_success_data(_API.ground_stop(hub_id, H["hub_ops_manager_headers"]))


def package_failures(package_id: str) -> list:
    return get_success_data(
        _API.list_package_failures(package_id, H["refund_adjuster_headers"])
    )


def get_aircraft(aircraft_id: str) -> dict:
    return get_success_data(_API.get_aircraft(aircraft_id, H["gateway_coordinator_headers"]))


def get_failure(failure_id: str) -> dict:
    return get_success_data(_API.get_failure(failure_id, H["refund_adjuster_headers"]))


def run_ops_checkpoint(hub_id: str, minute_of_day: int = 1400, level: str = "MAJOR") -> dict:
    return get_success_data(
        _API.run_ops(hub_id, {"minute_of_day": minute_of_day, "level": level},
                     H["hub_ops_manager_headers"])
    )


def get_ops_run(ops_run_id: str) -> dict:
    return get_success_data(_API.get_ops_run(ops_run_id, H["hub_ops_manager_headers"]))


def advance_ops_run(ops_run_id: str) -> dict:
    return get_success_data(_API.advance_ops_run(ops_run_id, H["hub_ops_manager_headers"]))


def release_ops_run(ops_run_id: str) -> dict:
    return get_success_data(_API.release_ops_run(ops_run_id, H["hub_ops_manager_headers"]))


def downgrade_package(package_id: str) -> dict:
    """Time-downgrade carrying the package's currently observed version."""
    pkg = get_package(package_id)
    return get_success_data(
        _API.downgrade_commitment(package_id, {"expected_package_version": pkg["version"]},
                                  H["commitment_controller_headers"])
    )


def ground_downgrade_package(package_id: str) -> dict:
    return get_success_data(
        _API.ground_downgrade(package_id, H["commitment_controller_headers"])
    )


def diverge_package(package_id: str) -> dict:
    return get_success_data(_API.diverge_package(package_id, H["commitment_controller_headers"]))


def clear_reroute_package(package_id: str) -> dict:
    return get_success_data(_API.clear_reroute(package_id, H["commitment_controller_headers"]))


def cancel_aircraft(aircraft_id: str, cause_code: str = "MECHANICAL") -> dict:
    """Cancel a grounded aircraft (PRD 3.4).

    An aircraft only becomes cancellable once it is on the ground; an in-flight
    one must first be sent to a maintenance station, which is the diversion the
    WeatherOfficer owns.  This helper performs that ground-side setup so the
    caller only has to name the aircraft it means to cancel.
    """
    aircraft = get_success_data(
        _API.get_aircraft(aircraft_id, H["gateway_coordinator_headers"]))
    if aircraft.get("status") == "SCHEDULED":
        get_success_data(_API.depart_origin(aircraft_id, H["gateway_coordinator_headers"]))
        aircraft = get_success_data(
            _API.get_aircraft(aircraft_id, H["gateway_coordinator_headers"]))
    if aircraft.get("status") == "IN_FLIGHT":
        get_success_data(
            _API.land_aircraft(aircraft_id, {"inbound_weight_grams": 40000},
                               H["gateway_coordinator_headers"]))
    return get_success_data(
        _API.cancel_aircraft(aircraft_id, {"cause_code": cause_code},
                             H["hub_ops_manager_headers"])
    )


def get_refund_summary(hub_id: str) -> dict:
    return get_success_data(_API.get_refund_summary(hub_id, H["refund_adjuster_headers"]))


def get_triage(hub_id: str) -> dict:
    return get_success_data(_API.get_triage(hub_id, H["hub_ops_manager_headers"]))


def record_failure(hub_id: str, package_id: str, cause_code: str = "SORT_MISS",
                   failure_minutes: int = 1500) -> dict:
    return get_success_data(
        _API.create_failure({"hub_id": hub_id, "package_id": package_id,
                             "cause_code": cause_code, "failure_minutes": failure_minutes},
                            H["refund_adjuster_headers"])
    )

def wide_secondary_lane(ctx: dict, lane_code: str = "S-WIDE") -> dict:
    """A high-capacity SECONDARY GENERAL lane.

    The standard concourse's secondary lane is deliberately small (so that a
    three-package saturation test can fill it exactly).  Scenarios that sort
    several large packages -- far above that lane's -- need a lane whose
    ``capacity_weight_grams`` is not the binding constraint, otherwise the sort
    is correctly refused and the scenario never reaches its subject rule.
    """
    return create_lane(ctx["hub_id"], lane_code=lane_code, lane_kind="SECONDARY",
                       commodity_capability="GENERAL",
                       capacity_weight_grams=LANE_CAPACITY_WIDE,
                       certified_until_minutes=LANE_CERTIFIED_UNTIL,
                       turnout_start_minutes=1400, turnout_end_minutes=1600)


def wide_primary_lane(ctx: dict, lane_code: str = "P-WIDE") -> dict:
    """A high-capacity PRIMARY GENERAL lane, for scenarios that sort several
    packages far above the standard concourse's 60000-gram primary lane."""
    return create_lane(ctx["hub_id"], lane_code=lane_code, lane_kind="PRIMARY",
                       commodity_capability="GENERAL",
                       capacity_weight_grams=LANE_CAPACITY_WIDE,
                       certified_until_minutes=LANE_CERTIFIED_UNTIL,
                       turnout_start_minutes=1350, turnout_end_minutes=1400)
