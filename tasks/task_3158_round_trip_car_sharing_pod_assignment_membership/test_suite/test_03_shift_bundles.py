"""Relocation bundles: band selection order, the fee floor and bay conservation."""
from test_helpers import (
    api_client,
    apply_bundle,
    assert_pod,
    assert_pod_shift_bundle,
    create_pod,
    create_vehicle,
    validate_success,
)
from test_helpers.fixtures import FLEET


def test_three_source_vehicles_into_an_empty_pod_take_the_balanced_band():
    """PRD §3.5: "otherwise 3200 cents when the absolute difference between the source
    available count and the destination available count is at most 1"
    PRD §3.5: "Moving 3 source-campus vehicles into an empty destination pod leaves both
    counts at 0, so the surcharge is 3200 and the fee is 15000 plus 3200, equal to 18200
    cents."

    Design: Difficulty/combinatorial_formula/shift_bundle_fee_tier_band_ordering_mode_a
    """
    dest = create_pod(name="North Campus", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    source = create_pod(name="Airport Hub", site_type="AIRPORT", capacity=6, fuel_floor_pct=35)
    moved = [create_vehicle(source["id"]) for _ in range(3)]

    bundle = apply_bundle(
        source["id"], dest["id"], [v["id"] for v in moved], dest["version"]
    )

    assert_pod_shift_bundle(bundle)
    assert bundle["bundle_fee_cents"] == 18200, (
        f"Three vehicles at 5000 cents plus the 3200 balanced surcharge is 18200, got "
        f"{bundle['bundle_fee_cents']}"
    )
    assert bundle["bundle_fee_cents"] != 34600, (
        "An empty destination must not be read as the highest band; 15000 + 19600 is the "
        "figure this system explicitly does not produce here"
    )


def test_balanced_band_relocation_updates_both_pods_bay_accounting():
    """PRD §3.5: "When a bundle is applied, every relocated vehicle's `pod_id` and
    `home_pod_id` are set to `dest_pod_id`, and both the source pod's and the destination
    pod's `utilization_score` and `available_bays` are recomputed."

    Design: Difficulty/combinatorial_formula/shift_bundle_fee_tier_band_ordering_mode_a
    """
    dest = create_pod(name="North Campus II", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    source = create_pod(name="Airport Hub II", site_type="AIRPORT", capacity=6, fuel_floor_pct=35)
    moved = [create_vehicle(source["id"]) for _ in range(3)]

    apply_bundle(source["id"], dest["id"], [v["id"] for v in moved], dest["version"])

    dest_after = validate_success(api_client.get_pod(dest["id"], FLEET), 200)
    source_after = validate_success(api_client.get_pod(source["id"], FLEET), 200)
    assert_pod(dest_after)
    assert_pod(source_after)
    assert dest_after["available_bays"] == 3, (
        f"A capacity-6 pod holding three relocated vehicles reports 3 bays, got "
        f"{dest_after['available_bays']}"
    )
    assert source_after["available_bays"] == 6, (
        f"The drained source pod reports all six bays free, got {source_after['available_bays']}"
    )
    for vehicle in moved:
        moved_vehicle = validate_success(api_client.get_vehicle(vehicle["id"], FLEET), 200)
        assert moved_vehicle["home_pod_id"] == dest["id"], (
            f"Relocation must move home_pod_id to the destination, got "
            f"{moved_vehicle['home_pod_id']}"
        )
        assert moved_vehicle["use_status"] == "AVAILABLE", (
            f"Relocation is a self-loop that preserves use_status, got {moved_vehicle['use_status']}"
        )


def test_empty_bundle_registers_the_row_and_applies_the_fee_floor():
    """PRD §3.5: "The long-haul surcharge is then selected: 19600 cents when the bundle
    vehicle count is 0, in which case the row still registers and the fee floor applies"

    Design: Difficulty/boundary_precision_check/pod_capacity_zero_bay_boundary
    """
    tight = create_pod(name="Tight Lot", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)
    create_vehicle(tight["id"])
    empty = create_pod(name="Empty Lot", site_type="NEIGHBORHOOD", capacity=3, fuel_floor_pct=25)

    bundle = apply_bundle(tight["id"], empty["id"], [], empty["version"])

    assert_pod_shift_bundle(bundle)
    assert bundle["bundle_fee_cents"] == 19600, (
        f"A zero-vehicle bundle takes the first matching row, whose fee floor is 19600, got "
        f"{bundle['bundle_fee_cents']}"
    )
    assert bundle["monthly_pods"] == [], "The recorded bundle must carry the empty move list"


def test_pod_at_capacity_reports_zero_bays_and_refuses_placement():
    """PRD §2.4: "The pod's `available_bays` is its `capacity` minus the parked count, and it
    is never negative — a pod whose parked vehicles already meet or exceed its capacity
    reports zero available bays."
    PRD §3.5: "requires that pod's `available_bays` to be greater than 0; a pod already at
    capacity, or a pod created with `capacity` of 0, accepts no vehicle and the placement is
    refused with `ERR_POD_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/pod_capacity_zero_bay_boundary
    """
    tight = create_pod(name="Tight Lot II", site_type="NEIGHBORHOOD", capacity=1, fuel_floor_pct=25)
    create_vehicle(tight["id"])

    tight_after = validate_success(api_client.get_pod(tight["id"], FLEET), 200)
    assert tight_after["available_bays"] == 0, (
        f"A capacity-1 pod holding one vehicle reports zero bays rather than a negative "
        f"count, got {tight_after['available_bays']}"
    )

    refused = api_client.create_vehicle(
        {"pod_id": tight["id"], "vin": "VIN3158-TIGHT-2", "model": "Yaris", "capacity_seats": 5},
        FLEET,
    )
    assert refused.status_code == 409, (
        f"Expected HTTP 409 for a placement into a full pod, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_POD_CAPACITY_EXCEEDED"


def test_one_vehicle_relocation_moves_exactly_one_service_bay():
    """PRD §2.4: "The pod's `available_bays` is its `capacity` minus the parked count"
    PRD §3.5: "Relocation is a self-loop on the vehicle's posture: `use_status` is preserved
    unchanged while the home-pod assignment that every bay computation reads changes
    underneath it."

    Design: Difficulty/compensating_invariant/service_bay_conservation_across_relocation
    """
    source = create_pod(name="Bay Source", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    dest = create_pod(name="Bay Dest", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    vehicles = [create_vehicle(source["id"]) for _ in range(3)]

    apply_bundle(source["id"], dest["id"], [vehicles[0]["id"]], dest["version"])

    source_after = validate_success(api_client.get_pod(source["id"], FLEET), 200)
    dest_after = validate_success(api_client.get_pod(dest["id"], FLEET), 200)
    assert source_after["available_bays"] == 4, (
        f"The source pod keeps four of six bays, got {source_after['available_bays']}"
    )
    assert dest_after["available_bays"] == 5, (
        f"The destination pod gives up exactly one bay, got {dest_after['available_bays']}"
    )


def test_relocation_conserves_the_total_occupied_bay_count():
    """PRD §2.4: "The parked count of a pod is the number of vehicles whose `home_pod_id` is
    that pod and whose `use_status` is anything other than `RETIRED`."

    Design: Difficulty/compensating_invariant/service_bay_conservation_across_relocation
    """
    source = create_pod(name="Bay Source II", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    dest = create_pod(name="Bay Dest II", site_type="CAMPUS", capacity=6, fuel_floor_pct=20)
    vehicles = [create_vehicle(source["id"]) for _ in range(3)]

    moved = apply_bundle(source["id"], dest["id"], [vehicles[0]["id"]], dest["version"])

    source_after = validate_success(api_client.get_pod(source["id"], FLEET), 200)
    dest_after = validate_success(api_client.get_pod(dest["id"], FLEET), 200)
    relocated = validate_success(api_client.get_vehicle(vehicles[0]["id"], FLEET), 200)

    assert relocated["home_pod_id"] == dest["id"], (
        "The relocated vehicle must call the destination pod home"
    )
    assert source_after["available_bays"] + dest_after["available_bays"] == 9, (
        f"Two capacity-6 pods holding three live vehicles keep nine free bays between them; "
        f"got {source_after['available_bays']} + {dest_after['available_bays']}"
    )
    assert moved["status"] == "APPLIED", (
        f"APPLIED is the only value the bundle status can take, got {moved['status']}"
    )
    assert len(moved["monthly_pods"]) == 1, (
        f"The bundle records exactly the relocated set, got {moved['monthly_pods']}"
    )