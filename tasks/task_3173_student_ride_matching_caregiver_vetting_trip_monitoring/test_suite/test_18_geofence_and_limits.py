"""Geofence registration and the district issuance limit."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_geofence_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)


def test_a_registered_geofence_is_discoverable_from_its_district():
    """PRD §3.9: "A `DistrictAdmin` registers a geofence with the owning
    `district_id`, a human `label`, a centre latitude and longitude in
    `center_lat` and `center_lon`, and a `radius_miles`; the platform stamps the
    date the fence took effect as `registered_on`."
    PRD §2.11: "When a path addresses a child collection under a parent — a
    district's trips, a trip's alerts, a driver's background checks, a
    geofence's checks — the platform first resolves the leading identifier, then
    the child collection within it, and only then the addressed child."

    Design: Corner/entities/geofence_create_requires_the_district_key_and_surfaces_it_on_read
    """
    set_clock("2026-09-01T00:00:00Z")
    district = get_success_data(
        api_client.create_district(
            {
                "name": "Aldine ISD",
                "billing_email": "ap@aldine.example",
                "contract_rate_per_ride_cents": 5300,
                "contract_rate_per_mile_cents": 215,
            },
            TEST_USERS["anonymous_headers"],
        ),
        201,
    )

    fence = validate_success(
        api_client.create_geofence(
            create_geofence_payload(district["id"]), TEST_USERS["district_admin_headers"]
        ),
        201,
    )
    assert fence["district_id"] == district["id"]
    assert fence["radius_miles"] == 1.0
    assert fence["label"] == "Lincoln campus"
    assert fence["registered_on"]

    listed = validate_success(
        api_client.list_district_geofences(
            district["id"], TEST_USERS["district_admin_headers"]
        )
    )
    assert len(listed) == 1
    assert listed[0]["id"] == fence["id"]


def test_a_geofence_against_an_unresolved_district_is_not_found():
    """PRD §2.11: "The first identifier that does not resolve produces
    `ERR_NOT_FOUND` (HTTP 404), and no later identifier in the same path is
    consulted. The same ordering governs writes: a mutation addressed to a
    nested resource whose parent does not exist, or exists outside the addressed
    district, is rejected as not found before any business rule attached to the
    mutation is evaluated."

    Design: Corner/entities/geofence_create_requires_the_district_key_and_surfaces_it_on_read
    """
    resp = api_client.create_geofence(
        {
            "district_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "label": "Ghost campus",
            "center_lat": 0.0,
            "center_lon": 0.0,
            "radius_miles": 1.0,
        },
        TEST_USERS["district_admin_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
