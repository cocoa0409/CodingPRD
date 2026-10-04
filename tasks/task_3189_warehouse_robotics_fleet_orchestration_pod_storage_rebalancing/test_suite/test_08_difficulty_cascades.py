"""Queue A (difficulty) translations: transitive cascades.

Covers rule_id transitive_cascade:
- human_entry_permit_cascades_zone_units_picktasks (2 tests)
- release_promotion_cascades_prior_release_and_fleet (2 tests)
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    set_clock,
    create_zone,
    create_drive_unit,
    create_pod,
    create_sku,
    create_pick_station,
    create_order_with_line,
    create_pick_task_payload,
    create_human_entry_permit_payload,
    create_and_grant_permit,
    setup_triaged_human_exception,
    setup_release_in_status,
    get_zone,
    get_drive_unit,
    get_station_version,
    stow_units,
    TEST_USERS,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
FLOW = TEST_USERS["flow_controller_headers"]
SUPERVISOR = TEST_USERS["floor_supervisor_headers"]


def _setup_permit_cascade_scenario():
    """Z1 (occupancy 1) holds pod P1 stocked with 5 units of SKU1 and home
    unit DU1; Z2 holds station ST2 where PT1 is QUEUED against P1. Z1 has a
    TRIAGED_HUMAN exception and a REQUESTED permit for it."""
    set_clock("2026-09-01T08:00:00Z")
    z1 = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                     max_human_occupancy=1)
    z2 = create_zone(zone_code="Z2", grid_x=10, grid_y=0, width=10, height=10,
                     max_human_occupancy=1)
    du = create_drive_unit(z1["id"], unit_code="DU1")
    pod = create_pod(z1["id"], pod_code="P1", slot_capacity=5)
    sku = create_sku(sku_code="SKU1", velocity_class="LOW")
    station = create_pick_station(z2["id"], station_code="ST2", max_queue=10)
    stow_units(sku, quantity=5)
    order, line = create_order_with_line(sku["id"], quantity=1)
    task = get_success_data(
        api_client.create_pick_task(
            create_pick_task_payload(
                order["id"], line["id"], pod["id"], station["id"], quantity=1
            ),
            FLOW,
        )
    )
    get_success_data(
        api_client.sequence_pick_task(task["id"], get_station_version(station["id"]), FLOW)
    )
    exception = setup_triaged_human_exception(z1)
    permit = get_success_data(
        api_client.create_human_entry_permit(
            create_human_entry_permit_payload(
                z1["id"], exception["id"],
                starts_at="2026-09-01T09:00:00Z",
                ends_at="2026-09-01T10:00:00Z",
            ),
            SUPERVISOR,
        )
    )
    return {
        "z1": z1, "z2": z2, "du": du, "pod": pod, "sku": sku,
        "station": station, "order": order, "task": task,
        "exception": exception, "permit": permit,
    }


def test_permit_grant_freezes_zone(api):
    """PRD §3.6: "Granting cascades: the permit becomes `ACTIVE`, the zone's
    `posture` becomes `FROZEN` and its `version` increments, every unit in
    the zone not already `CHARGING`, `MAINTENANCE`, or `STRANDED` parks, and
    `QUEUED` tasks on pods in the zone are resequenced to other stations when
    any exist, otherwise they remain queued with status unchanged."

    Design: Difficulty/transitive_cascade/human_entry_permit_cascades_zone_units_picktasks
    """
    env = _setup_permit_cascade_scenario()
    granted = get_success_data(
        api_client.grant_human_entry_permit(
            env["permit"]["id"], TEST_USERS["safety_officer_headers"]
        )
    )
    assert granted["status"] == "ACTIVE"
    assert get_zone(env["z1"]["id"])["posture"] == "FROZEN"


def test_permit_grant_parks_zone_units(api):
    """PRD §3.6: "Granting cascades: the permit becomes `ACTIVE`, the zone's
    `posture` becomes `FROZEN` and its `version` increments, every unit in
    the zone not already `CHARGING`, `MAINTENANCE`, or `STRANDED` parks."

    Design: Difficulty/transitive_cascade/human_entry_permit_cascades_zone_units_picktasks
    """
    env = _setup_permit_cascade_scenario()
    get_success_data(
        api_client.grant_human_entry_permit(
            env["permit"]["id"], TEST_USERS["safety_officer_headers"]
        )
    )
    unit_after = get_drive_unit(env["du"]["id"])
    assert unit_after["status"] == "PARKED", (
        f"zone freeze must park the homed unit, got {unit_after['status']}"
    )


def test_release_promotion_rolls_back_prior_floor_live(api):
    """PRD §3.7: "Promotion moves the release `VALIDATED` → `FLOOR_LIVE`,
    rolls any prior `FLOOR_LIVE` release back to `ROLLED_BACK`, and sweeps the
    fleet: every drive unit's `firmware_release_id` is set to the promoted
    release and every unit's `version` increments."

    Design: Difficulty/transitive_cascade/release_promotion_cascades_prior_release_and_fleet
    """
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    create_drive_unit(zone["id"], unit_code="DU1")
    create_drive_unit(zone["id"], unit_code="DU2")
    r1 = setup_release_in_status("FLOOR_LIVE")
    r2 = setup_release_in_status("VALIDATED")
    promoted = get_success_data(api_client.promote_software_release(r2["id"], ADMIN))
    assert promoted["status"] == "FLOOR_LIVE"
    r1_after = get_success_data(api_client.get_software_release(r1["id"], ADMIN))
    assert r1_after["status"] == "ROLLED_BACK", (
        f"prior FLOOR_LIVE release must roll back, got {r1_after['status']}"
    )


def test_release_promotion_sweeps_fleet_firmware(api):
    """PRD §3.7: "Promotion moves the release `VALIDATED` → `FLOOR_LIVE`,
    rolls any prior `FLOOR_LIVE` release back to `ROLLED_BACK`, and sweeps the
    fleet: every drive unit's `firmware_release_id` is set to the promoted
    release and every unit's `version` increments."

    Design: Difficulty/transitive_cascade/release_promotion_cascades_prior_release_and_fleet
    """
    set_clock("2026-09-01T08:00:00Z")
    zone = create_zone(zone_code="Z1", grid_x=0, grid_y=0, width=10, height=10,
                       max_human_occupancy=2)
    du1 = create_drive_unit(zone["id"], unit_code="DU1")
    du2 = create_drive_unit(zone["id"], unit_code="DU2")
    r1 = setup_release_in_status("FLOOR_LIVE")
    r2 = setup_release_in_status("VALIDATED")
    get_success_data(api_client.promote_software_release(r2["id"], ADMIN))
    for du in (du1, du2):
        after = get_drive_unit(du["id"])
        assert after["firmware_release_id"] == r2["id"], (
            f"unit {after['unit_code']} must run the promoted release {r2['id']}, "
            f"got {after['firmware_release_id']}"
        )
        assert after["version"] == du["version"] + 2, (
            f"each promotion increments every unit version by 1; "
            f"{du['version']} -> {after['version']} after two promotions"
        )
