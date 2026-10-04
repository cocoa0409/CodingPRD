"""Occupancy geometry: the hour grid, the date grid, and the buffered approach rule."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, api_client
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_basic_scenario,
    setup_active_member,
    declare_vehicle,
    file_stay,
    confirm_stay,
    try_confirm_stay,
    read_stay,
    read_capacity_summary,
    resolve_site_id,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
)


def test_the_occupancy_instants_follow_the_hosts_declared_window_hours(api):
    """PRD §3.4: "The `occupancy_start` is the arrival date plus the host's
    `arrival_window_start_hour`, the hour-level instant at which the rig may roll onto
    the site. The `occupancy_end` is the departure date plus the host's
    `arrival_window_end_hour`, the hour-level instant by which the rig must be gone."
    PRD §3.4: "Subtracting the host's two declared window hours means the same date
    range produces different occupancy instants at different hosts"

    Design: Difficulty/boundary_precision_check/opposite_boundary_disagreement_overlap_versus_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    declare_sites(host["id"], 1, labels=["C1"])
    approve_host(host["id"])
    member, vehicle = setup_active_member(plan_tier="CLASSIC", home_state_code="TX")

    stay = file_stay(host["id"], member["id"], vehicle["id"],
                     arrival_date="2026-06-01", nights=2)
    # departure 2026-06-03; start hour 14, end hour 11 by default.
    assert stay["departure_date"].startswith("2026-06-03")
    assert stay["occupancy_start"].startswith("2026-06-01T14:00")
    assert stay["occupancy_end"].startswith("2026-06-03T11:00"), (
        "the hour grid puts the earlier stay's end at 11:00 and a later stay's start "
        "at 14:00 on the same date"
    )


def test_an_outstanding_first_round_request_holds_the_site_on_the_reserved_basis(api):
    """PRD §2.4: "`committed_sites` is simply the count of the host's stays whose
    `count_toward_capacity` is true."
    PRD §2.4: "`free_sites` is `effective_capacity` minus `committed_sites`, floored at
    zero — it is never negative."

    Design: Difficulty/boundary_precision_check/opposite_boundary_disagreement_overlap_versus_capacity
    """
    set_clock("2026-05-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=1, plan_tier="CLASSIC")
    host_id = parts["host"]["id"]
    stay = file_stay(host_id, parts["member"]["id"], parts["vehicle"]["id"],
                     arrival_date="2026-06-01", nights=2)
    assert stay["count_toward_capacity"] is True, (
        "a first-round request holds a site before the host has answered"
    )
    summary = read_capacity_summary(host_id)
    assert summary["committed_sites_reserved_basis"] == 1
    assert summary["committed_sites_occupied_basis"] == 0
    assert summary["free_sites"] == 0


def _setup_loop_host():
    """TX/ATTRACTION host with a PULL_THROUGH site D1 and a BACK_IN site D2 that
    D1's `blocks_sites` names, then a circulating stay on D1."""
    set_clock("2026-06-01T00:00:00Z")
    host = declare_host(
        category="ATTRACTION", state_code="TX",
        arrival_window_start_hour=11, arrival_window_end_hour=10,
        self_contained_required=False,
    )
    headers = make_host_operator_headers(host["id"])
    validate_success(
        api_client.create_parking_site(
            host["id"],
            {"site_label": "D1", "site_class": "PULL_THROUGH",
             "max_vehicle_length_feet": 45, "has_electric": True,
             "electric_service_code": "ELECTRIC_30A", "blocks_sites": "D2"},
            headers,
        ),
        201,
    )
    validate_success(
        api_client.create_parking_site(
            host["id"],
            {"site_label": "D2", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 45, "has_electric": False,
             "electric_service_code": "NONE"},
            headers,
        ),
        201,
    )
    approve_host(host["id"])
    member, vehicle = setup_active_member(plan_tier="CLASSIC", home_state_code="TX")
    # The circulating stay occupies D1; the later stay sits on a different rig so
    # the vehicle-occupancy rule does not pre-empt the approach rule under test.
    blocking_vehicle = declare_vehicle(member["id"])

    circulating = file_stay(host["id"], member["id"], blocking_vehicle["id"],
                            arrival_date="2026-07-01", nights=4)
    circulating = confirm_stay(host["id"], circulating["id"], site_label="D1")
    assert circulating["request_status"] == "CONFIRMED"
    return host, member, vehicle, circulating


def test_a_circulating_stay_blocks_a_neighbouring_sites_assignment(api):
    """PRD §3.4: "a site may not be assigned while any site whose `blocks_sites` list
    names it is occupied by a circulating stay over the new interval widened by a
    two-hour buffer on each side, and a violation is reported as
    `ERR_SITE_APPROACH_BLOCKED` (HTTP 409)."
    PRD §3.4: "A stay circulates when the site it is assigned to has the
    `PULL_THROUGH` class"

    Design: Difficulty/resource_temporal_overlap/blocked_approach_hour_interval_with_two_hour_buffer
    """
    host, member, vehicle, circulating = _setup_loop_host()
    host_id = host["id"]
    # The circulating stay occupies D1 until 2026-07-05T10:00; a new stay starting
    # 2026-07-05T11:00 falls inside the 12:00 buffered edge.
    next_stay = file_stay(host_id, member["id"], vehicle["id"],
                          arrival_date="2026-07-05", nights=2)
    resp = try_confirm_stay(host_id, next_stay["id"], site_label="D2")
    validate_error(resp, ApiErrorId.ERR_SITE_APPROACH_BLOCKED, 409)
    assert read_stay(next_stay["id"], host_id)["request_status"] == "REQUESTED"


def test_the_site_availability_read_names_the_blocking_site(api):
    """PRD §3.9: "It reports the site's `site_id`, the `occupied_intervals` on it over
    that range, the labels of the sites currently blocking it as
    `blocked_by_site_labels`, and a boolean `is_assignable` summarising whether the
    site could be handed to a new stay at that instant."
    PRD §3.9: "This is the read that explains why a confirmation failed with a
    blocked-approach refusal, since the blocking site is a different site from the one
    being assigned."

    Design: Difficulty/resource_temporal_overlap/blocked_approach_hour_interval_with_two_hour_buffer
    """
    host, member, vehicle, circulating = _setup_loop_host()
    host_id = host["id"]
    site_d2 = resolve_site_id(host_id, "D2")

    # Move the clock inside the circulating stay's buffered interval, where the
    # "at that instant" reading and the "over the supplied range" reading of
    # `is_assignable` agree that D2 cannot be handed out.
    set_clock("2026-07-03T00:00:00Z")

    availability = validate_success(
        api.get_site_availability(
            host_id, site_d2, make_host_operator_headers(host_id),
            {"from_date": "2026-07-01", "to_date": "2026-07-10"},
        )
    )
    assert availability["site_id"] == site_d2
    assert "D1" in availability["blocked_by_site_labels"]
    assert availability["is_assignable"] is False