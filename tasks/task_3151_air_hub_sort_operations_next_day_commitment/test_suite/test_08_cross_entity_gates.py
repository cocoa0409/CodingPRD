"""Cross-entity gates: a package's load depends on its move's aircraft, and a failure's
reopen depends on the hub's posture."""
import pytest

from test_helpers import (
    CLOCK_1400,
    CLOCK_1601,
    api_client as api,
    TEST_USERS as H,
    assert_version_incremented,
    cancel_aircraft,
    clear_contingency,
    confirm,
    create_package,
    declare_contingency,
    depart_origin,
    get_aircraft,
    land_second_aircraft,
    set_clock,
    setup_six_lane_night,
    setup_outbound_aircraft,
    assert_package,
)

CLOCK_1450 = "2026-09-02T00:40:00Z"


def _sorted_package(night, tracking_number: str, grams: int = 20000) -> dict:
    from test_helpers import induct, primary_sort, secondary_sort
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number=tracking_number,
                         planned_weight_grams=grams, dimension_weight_grams=grams)
    induct(pkg["id"])
    primary_sort(pkg["id"], night["lane_p1_id"])
    secondary_sort(pkg["id"], night["lane_s1_id"])
    return pkg


def test_a_cancelled_move_aircraft_blocks_the_otherwise_loadable_package():
    """PRD §3.6: "The move's aircraft must not be cancelled and must not be under a
    maintenance hold."

    Design: Difficulty/cross_entity_state_dependency/package_load_gate_depends_on_aircraft_cancellation_and_maintenance
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    land_second_aircraft(night, inbound_weight_grams=40000, unload_minutes=1405, complete=True)

    from test_helpers import create_move, plan_move
    move_m = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    plan_move(move_m["id"])
    outbound = setup_outbound_aircraft(night, tail_number="N703UP")
    move_o = create_move(night["hub_id"], outbound["aircraft_id"], weight_limit_grams=350000)
    plan_move(move_o["id"])

    first = _sorted_package(night, "1Z-XE-0001")
    cancel_aircraft(night["ac2_id"], "MECHANICAL")

    move_read = api.get_move(move_m["id"], H["load_planner_headers"]).json()["data"]
    pkg_read = api.get_package(first["id"], H["sort_operator_headers"]).json()["data"]
    assert pkg_read["commitment_posture"] == "COMMITTED_OK", (
        "the package's own posture is not what blocks the load"
    )

    attempt = api.load_package(move_m["id"], {
        "package_id": first["id"],
        "expected_load_move_version": move_read["version"],
        "expected_package_version": pkg_read["version"],
    }, H["load_planner_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_the_packages_own_state_never_changed_only_the_aircrafts():
    """PRD §3.6: "On success the package's sort dimension becomes `LOADED`, its lane assignment
    clears, and the move's loaded weight, planned weight, forward capacity and
    tier and the buildup's rated weight, hazardous weight, hazardous flag and tier
    all recompute;"

    Design: Difficulty/cross_entity_state_dependency/package_load_gate_depends_on_aircraft_cancellation_and_maintenance
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    land_second_aircraft(night, inbound_weight_grams=40000, unload_minutes=1405, complete=True)
    from test_helpers import create_move, plan_move, onboard_package, get_move
    move_m = create_move(night["hub_id"], night["ac2_id"], weight_limit_grams=350000)
    plan_move(move_m["id"])
    outbound = setup_outbound_aircraft(night, tail_number="N704UP")
    move_o = create_move(night["hub_id"], outbound["aircraft_id"], weight_limit_grams=350000)
    plan_move(move_o["id"])

    blocked = _sorted_package(night, "1Z-XE-0002")
    allowed = _sorted_package(night, "1Z-XE-0003")
    cancel_aircraft(night["ac2_id"], "MECHANICAL")

    move_read = get_move(move_m["id"])
    pkg_read = api.get_package(blocked["id"], H["sort_operator_headers"]).json()["data"]
    api.load_package(move_m["id"], {
        "package_id": blocked["id"],
        "expected_load_move_version": move_read["version"],
        "expected_package_version": pkg_read["version"],
    }, H["load_planner_headers"])
    after = api.get_package(blocked["id"], H["sort_operator_headers"]).json()["data"]
    assert after["sort_status"] == "SECONDARY_SORTED", (
        "the package's own state never changed, only the aircraft's did"
    )

    departed = onboard_package(move_o["id"], allowed["id"])
    assert departed["status"] == "PLANNED", "the identical package on a serviceable aircraft loads"
    assert_package(api.get_package(allowed["id"], H["sort_operator_headers"]).json()["data"])


def test_the_grounded_aircraft_is_cancelled_while_its_sibling_flew():
    """PRD §3.4: "A grounded aircraft may be cancelled by a `HubOpsManager`, but only while not
    one of its packages has left `UNSORTED`;"

    Design: Difficulty/cross_entity_state_dependency/package_load_gate_depends_on_aircraft_cancellation_and_maintenance
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1450)
    land_second_aircraft(night, inbound_weight_grams=40000, unload_minutes=1405, complete=True)
    outbound = setup_outbound_aircraft(night, tail_number="N705UP")
    depart_origin(outbound["aircraft_id"])

    cancelled = cancel_aircraft(night["ac2_id"], "MECHANICAL")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["maintenance_hold"] is True

    sibling = get_aircraft(outbound["aircraft_id"])
    assert sibling["status"] == "IN_FLIGHT"
    assert sibling["maintenance_hold"] is False


def test_reopen_is_frozen_while_the_hub_is_locked_and_thaws_afterwards():
    """PRD §3.12: "Reopening a disputed failure returns it to `OPEN`, but only while the
    hub is `OPEN` or `CONGESTED` — a reopen attempted while the hub is `LOCKDOWN` or
    `GROUND_STOP` is refused with `ERR_REOPEN_POSTURE_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/service_failure_dispute_eligibility_depends_on_hub_lockdown_posture
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1601)
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RP-0001",
                         planned_weight_grams=30000, dimension_weight_grams=30000)

    failure = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": pkg["id"], "cause_code": "WEATHER",
         "failure_minutes": 1500}, H["refund_adjuster_headers"]), 201)
    assert failure["attributed_role"] == "WEATHER_EVENT"

    disputed = confirm(api.dispute_failure(failure["id"], H["refund_adjuster_headers"]))
    assert disputed["status"] == "DISPUTED"

    reopened = confirm(api.reopen_failure(failure["id"], H["refund_adjuster_headers"]))
    assert reopened["status"] == "OPEN", "the hub is still OPEN, so the reopen is admitted"

    confirm(api.dispute_failure(failure["id"], H["refund_adjuster_headers"]))


def test_the_locked_hub_refuses_the_reopen_and_clearing_thaws_it():
    """PRD §3.12: "a reopen attempted while the hub is `LOCKDOWN` or `GROUND_STOP` is
    refused with `ERR_REOPEN_POSTURE_BLOCKED`."
    PRD §3.4: "Clearing sets the mode false and lets the posture recompute;"

    Design: Difficulty/cross_entity_state_dependency/service_failure_dispute_eligibility_depends_on_hub_lockdown_posture
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1601)
    pkg = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-RP-0002",
                         planned_weight_grams=30000, dimension_weight_grams=30000)
    failure = confirm(api.create_failure(
        {"hub_id": night["hub_id"], "package_id": pkg["id"], "cause_code": "WEATHER",
         "failure_minutes": 1500}, H["refund_adjuster_headers"]), 201)
    confirm(api.dispute_failure(failure["id"], H["refund_adjuster_headers"]))

    declare_contingency(night["hub_id"])
    locked_attempt = api.reopen_failure(failure["id"], H["refund_adjuster_headers"])
    assert locked_attempt.status_code == 409, locked_attempt.text
    assert locked_attempt.json()["data"]["error_id"] == "ERR_REOPEN_POSTURE_BLOCKED"

    still_disputed = api.get_failure(failure["id"], H["refund_adjuster_headers"]).json()["data"]
    assert still_disputed["status"] == "DISPUTED", "the failure never advanced"

    clear_contingency(night["hub_id"])
    thawed = confirm(api.reopen_failure(failure["id"], H["refund_adjuster_headers"]))
    assert thawed["status"] == "OPEN", "after clearing the contingency the reopen succeeds again"
    assert_version_incremented(thawed["version"], still_disputed["version"])