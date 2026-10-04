"""Optimistic concurrency control on the three version-guarded write paths."""
from test_helpers import (
    OPERATOR,
    api_client,
    get_success_data,
    make_member_headers,
    return_vehicle,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)


def test_stale_vehicle_version_is_refused_while_the_refreshed_version_succeeds():
    """PRD §2.10: "Creating a reservation requires `expected_vehicle_version`, carrying the
    client's last observed `version` of the target `Vehicle`. A mismatch means another writer
    has advanced the vehicle's version since the client last read it, and the create is
    rejected with `ERR_STALE_VERSION`."
    PRD §2.12: "and finally the stale-version guard (`ERR_STALE_VERSION`), which is evaluated
    last of all so that a request failing an earlier check reports that earlier failure"

    Design: Corner/cross_cutting_layers/occ_stale_vehicle_version_on_reservation_create
    """
    setup = setup_confirmed_reservation(
        pod_name="Stale Lot", start_at="2026-09-05T09:00:00Z", end_at="2026-09-05T13:00:00Z"
    )
    # The create's own confirmation cascade advances the vehicle past the version
    # captured at creation, so that captured value is by definition stale; it is
    # retained here as the observation under test.
    stale_version = setup["vehicle"]["version"]

    # PRD §3.6/§2.10: the target vehicle must be AVAILABLE before the version guard
    # is reached — the confirmation cascade the setup already ran left it RESERVED,
    # so the observation being tested is taken against a vehicle that could be
    # booked again.
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")
    return_vehicle(
        setup["member"]["id"], setup["reservation"]["id"], setup["pod"]["id"],
        odometer_miles=36000, fuel_level_pct=70,
    )
    observed = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    assert observed["version"] != stale_version, (
        f"The vehicle must have advanced past the observation under test: still "
        f"{observed['version']}"
    )

    refused = api_client.create_reservation(
        {
            "member_id": setup["member"]["id"],
            "pod_id": setup["pod"]["id"],
            "vehicle_id": setup["vehicle"]["id"],
            "start_at": "2026-09-06T09:00:00Z",
            "end_at": "2026-09-06T13:00:00Z",
            "reserved_hours": 4,
            "expected_vehicle_version": stale_version,
        },
        make_member_headers(setup["member"]["id"]),
    )

    assert refused.status_code == 412, (
        f"Expected HTTP 412 for a stale parent version, got {refused.status_code}: "
        f"{refused.text[:200]}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_STALE_VERSION", (
        f"Got {refused.json()['data']['error_id']}"
    )

    current = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    accepted = validate_success(
        api_client.create_reservation(
            {
                "member_id": setup["member"]["id"],
                "pod_id": setup["pod"]["id"],
                "vehicle_id": setup["vehicle"]["id"],
                "start_at": "2026-09-07T09:00:00Z",
                "end_at": "2026-09-07T13:00:00Z",
                "reserved_hours": 4,
                "expected_vehicle_version": current["version"],
            },
            make_member_headers(setup["member"]["id"]),
        ),
        201,
    )
    assert accepted["status"] == "CONFIRMED", (
        f"The refreshed version must be accepted, got {accepted['status']}"
    )


def test_replayed_party_split_version_is_refused():
    """PRD §2.10: "Splitting responsibility on an incident requires `expected_incident_version`,
    carrying the client's last observed `version` of the target `Incident`. A mismatch means a
    prior split has already re-derived the fee and the insurance layer since the client last
    read it, and the split is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_layers/occ_stale_incident_version_on_party_split
    """
    # PRD §3.13: the raw score is T1 + T2 + T3 and the high-severity branch fires at
    # 4, so the fixture carries an anchor of 2 alongside the repair cost's own term;
    # that is the branch whose outcome the replay is asserted to leave standing.
    setup = setup_confirmed_reservation(pod_name="Split Lot",
                                        member_kwargs={"last_accident_fee_block": 2})
    incident = get_success_data(
        api_client.create_incident(
            {
                "reservation_id": setup["reservation"]["id"],
                "vehicle_id": setup["vehicle"]["id"],
                "member_id": setup["member"]["id"],
                "incident_type": "DAMAGE",
                "repair_cost_cents": 12000,
            },
            OPERATOR,
        ),
        201,
    )
    first_version = incident["version"]
    validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": first_version}, OPERATOR
        ),
        200,
    )

    replayed = api_client.party_split(
        incident["id"], {"expected_incident_version": first_version}, OPERATOR
    )

    assert replayed.status_code == 412, (
        f"Replaying the earlier version must be refused with 412, got {replayed.status_code}: "
        f"{replayed.text[:200]}"
    )
    assert replayed.json()["data"]["error_id"] == "ERR_STALE_VERSION", (
        f"Got {replayed.json()['data']['error_id']}"
    )
    incident_after = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)
    assert incident_after["status"] == "FEE_CHARGED", (
        f"The first split's outcome must stand, got {incident_after['status']}"
    )