"""Boundary precision on the posture band, the electric ladder and occupancy."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, api_client
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_active_member,
    setup_basic_scenario,
    file_stay,
    try_file_stay,
    confirm_stay,
    try_confirm_stay,
    decline_stay,
    read_stay,
    read_capacity_summary,
    resolve_site_id,
    host_version,
    set_clock,
    make_host_operator_headers,
    make_member_headers,
)


def test_two_free_sites_of_five_sit_above_the_rounded_up_band(api):
    """PRD §2.4: "otherwise, when `free_sites` is at most the value of 20 percent of
    `effective_capacity` rounded up to the next whole number, `posture` is `LIMITED`"
    PRD §2.4: "the same host with 3 free sites is `OPEN`"

    Design: Difficulty/boundary_precision_check/posture_band_boundary_free_sites_two_of_ten
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=5)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    # Two first-round requests are confirmed and a third stays REQUESTED: the
    # reserved basis holds three of the five sites.
    stays = [
        file_stay(host_id, member_id, vehicle_id, arrival_date=f"2026-06-{5 + 2 * i}",
                  nights=1)
        for i in range(3)
    ]
    confirm_stay(host_id, stays[0]["id"], site_label="S1")
    confirm_stay(host_id, stays[1]["id"], site_label="S2")

    summary = read_capacity_summary(host_id)
    assert summary["committed_sites_reserved_basis"] == 3
    assert summary["effective_capacity"] == 5
    assert summary["free_sites"] == 2
    assert summary["posture"] == "OPEN", (
        "two free sites of five exceeds ceil(5 * 0.20) = 1, so the band does not bind"
    )


def test_the_band_binds_when_the_last_free_site_is_exhausted(api):
    """PRD §2.4: "when `free_sites` is less than 1, `posture` is `LIMITED`"
    PRD §3.4: "A request that cannot be admitted is refused with
    `ERR_HOST_CAPACITY_FULL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/posture_band_boundary_free_sites_two_of_ten
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=5)
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    stays = [
        file_stay(host_id, member_id, vehicle_id, arrival_date=f"2026-06-{5 + 2 * i}",
                  nights=1)
        for i in range(5)
    ]
    for i in range(5):
        confirmed = confirm_stay(host_id, stays[i]["id"], site_label=f"S{i + 1}")
        assert confirmed["request_status"] == "CONFIRMED"

    summary = read_capacity_summary(host_id)
    assert summary["committed_sites_reserved_basis"] == 5
    assert summary["free_sites"] == 0
    assert summary["posture"] == "LIMITED", (
        "zero free sites of five is inside the ceiling of the band"
    )

    resp = try_file_stay(
        host_id, member_id, vehicle_id, arrival_date="2026-06-25", nights=1,
    )
    validate_error(resp, ApiErrorId.ERR_HOST_CAPACITY_FULL, 409)


def _setup_ampere_host():
    """TX/FARM host with an ELECTRIC_50A site Y1 and an ELECTRIC_30A site Y2."""
    set_clock("2026-06-01T00:00:00Z")
    host = declare_host(category="FARM", state_code="TX",
                        self_contained_required=False)
    host_headers = make_host_operator_headers(host["id"])
    validate_success(
        api_client.create_parking_site(
            host["id"],
            {"site_label": "Y1", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 45, "has_electric": True,
             "electric_service_code": "ELECTRIC_50A"},
            host_headers,
        ),
        201,
    )
    validate_success(
        api_client.create_parking_site(
            host["id"],
            {"site_label": "Y2", "site_class": "BACK_IN",
             "max_vehicle_length_feet": 45, "has_electric": True,
             "electric_service_code": "ELECTRIC_30A"},
            host_headers,
        ),
        201,
    )
    host = approve_host(host["id"])
    member, vehicle = setup_active_member(plan_tier="CLASSIC", home_state_code="TX")
    return host, member, vehicle


def test_the_electric_ladder_admits_equality_on_the_requested_code(api):
    """PRD §3.4: "when the request asks for shore power at all, the assigned site
    must have an electric pedestal, and that pedestal's `electric_service_code` must
    be at least as capable as the requested code under the ordering `NONE`, then
    `ELECTRIC_30A`, then `ELECTRIC_50A`"
    PRD §3.4: "A request for `ELECTRIC_30A` costs 700 cents per night."

    Design: Difficulty/boundary_precision_check/electric_code_ordering_boundary_at_fifty_amp
    """
    host, member, vehicle = _setup_ampere_host()
    low = file_stay(
        host["id"], member["id"], vehicle["id"], arrival_date="2026-06-05",
        nights=2, electric_request_code="ELECTRIC_30A",
    )
    low = confirm_stay(host["id"], low["id"], site_label="Y1")
    assert low["ancillary_charge_cents"] == 1400, (
        "an ELECTRIC_30A request satisfied by a 50A pedestal is admitted at the "
        "700-cent nightly rate for two nights"
    )
    assert low["request_status"] == "CONFIRMED"


def test_a_pedestal_one_rung_below_the_requested_code_is_refused(api):
    """PRD §3.4: "a request for 50-ampere service may therefore be satisfied only by
    a 50-ampere pedestal, while a 30-ampere request is satisfied by either. An
    incompatible match is refused with `ERR_SITE_ELECTRIC_INCOMPATIBLE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/electric_code_ordering_boundary_at_fifty_amp
    """
    host, member, vehicle = _setup_ampere_host()
    high = file_stay(
        host["id"], member["id"], vehicle["id"], arrival_date="2026-06-09",
        nights=2, electric_request_code="ELECTRIC_50A",
    )
    resp = try_confirm_stay(host["id"], high["id"], site_label="Y2")
    validate_error(resp, ApiErrorId.ERR_SITE_ELECTRIC_INCOMPATIBLE, 422)

    # The same request assigned to the 50A pedestal is admitted, proving the
    # refusal was the pedestal's capability and not the request.
    ok = confirm_stay(host["id"], high["id"], site_label="Y1")
    assert ok["request_status"] == "CONFIRMED"
    assert ok["ancillary_charge_cents"] == 1800, (
        "a CLASS_C rig pays the 900-cent trailer rate on an identical payload"
    )


def test_adjacent_dates_on_one_rig_are_a_clear_gap(api):
    """PRD §3.4: "Two stays on the same rig may not have occupancy intervals that
    touch or overlap, and this is judged over the half-open date interval running from
    the arrival date at midnight UTC up to, but not including, the departure date at
    midnight UTC. Because the upper bound is excluded and the lower bound is included,
    a same-day turnaround — one stay departing on the morning another arrives — counts
    as touching and is therefore a conflict"

    Design: Difficulty/resource_temporal_overlap/vehicle_occupancy_half_open_date_interval_no_buffers
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2, labels=["V1", "V2"])
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    first = file_stay(host_id, member_id, vehicle_id, arrival_date="2026-06-06",
                      nights=2)
    confirm_stay(host_id, first["id"], site_label="V1")

    # Departure 2026-06-08; a stay arriving 2026-06-09 is a clean gap.
    gap = file_stay(host_id, member_id, vehicle_id, arrival_date="2026-06-09",
                    nights=2)
    assert gap["request_status"] == "REQUESTED", (
        "the intervals do not touch, so the request is admitted"
    )


def test_a_same_day_turnaround_on_one_rig_is_a_collision(api):
    """PRD §3.4: "Because the upper bound is excluded and the lower bound is included,
    a same-day turnaround — one stay departing on the morning another arrives — counts
    as touching and is therefore a conflict, refused with
    `ERR_VEHICLE_OCCUPANCY_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vehicle_occupancy_half_open_date_interval_no_buffers
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_basic_scenario(site_count=2, labels=["V1", "V2"])
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]
    vehicle_id = parts["vehicle"]["id"]

    first = file_stay(host_id, member_id, vehicle_id, arrival_date="2026-06-06",
                      nights=2)
    confirm_stay(host_id, first["id"], site_label="V1")

    # Departure 2026-06-08; a stay arriving the same day touches the interval.
    resp = try_file_stay(host_id, member_id, vehicle_id,
                         arrival_date="2026-06-08", nights=2)
    validate_error(resp, ApiErrorId.ERR_VEHICLE_OCCUPANCY_OVERLAP, 409)

    stays = validate_success(
        api.list_stay_requests(
            make_member_headers(member_id),
            {"member_id": member_id, "limit": 50, "offset": 0},
        )
    )
    assert len(stays) == 1, "the colliding payload left no partial row"