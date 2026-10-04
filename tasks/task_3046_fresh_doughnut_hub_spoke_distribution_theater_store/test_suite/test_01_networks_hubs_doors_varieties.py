"""Networks, hubs, doors, varieties: creation defaults, required fields,
territory integrity, listing pagination, computed-field handling."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_hub,
    assert_network,
    create_door_payload,
    create_hub_payload,
    create_network_payload,
    create_variety_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import create_door, create_hub, create_network

NA = TEST_USERS["network_admin_headers"]
HM = TEST_USERS["hub_manager_headers"]


def test_network_create_returns_201_with_defaults(api):
    """PRD §3.1: "The new network starts with `network_posture` set to `OPEN`
    and an `ops_run_index` of zero — a monotonic heartbeat counter that only
    advances at ops-run checkpoints."
    PRD §4: "Operations that create a new resource return `201 Created`".

    Design: Corner/entities/network_create_returns_201_with_defaults
    """
    resp = api.create_network(create_network_payload(network_code="NX", display_name="Net X"), NA)
    data = validate_success(resp, expected_status=201)
    assert_network(data)
    assert data["network_posture"] == "OPEN"
    assert data["ops_run_index"] == 0
    assert data["version"] == 1
    assert data["created_at"]


def test_network_create_returns_open_posture_and_zero_index_on_read_back(api):
    """PRD §3.1: "The new network starts with `network_posture` set to `OPEN`
    and an `ops_run_index` of zero — a monotonic heartbeat counter that only
    advances at ops-run checkpoints."

    Design: Corner/entities/network_create_returns_201_with_defaults
    """
    network = create_network(network_code="NX2", display_name="Net X2")
    fetched = validate_success(api.get_network(network["id"], NA))
    assert fetched["network_posture"] == "OPEN"
    assert fetched["ops_run_index"] == 0
    assert fetched["version"] == 1


def test_network_create_missing_network_code_returns_invalid_request(api):
    """PRD §2.1: "any request carrying a missing required field, a malformed
    value, or an enum value outside its declared range is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A `NetworkAdmin` begins by creating a network with a globally
    unique `network_code` and a human-readable `display_name`."

    Design: Corner/entities/network_create_missing_network_code_returns_invalid_request
    """
    resp = api.create_network({"display_name": "No Code Net"}, NA)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_variety_inverted_window_rejected(api):
    """PRD §3.3: "a selling window from `active_from` (inclusive) to
    `active_until` (exclusive, and strictly later than `active_from` — an
    inverted window is rejected with `ERR_WINDOW_OVERLAP`)".

    Design: Corner/entities/variety_inverted_window_rejected
    """
    network = create_network(network_code="NV", display_name="Net V")
    resp = api.create_variety(
        network["id"],
        create_variety_payload(
            variety_code="BAD",
            active_from="2026-09-10T00:00:00Z",
            active_until="2026-09-01T00:00:00Z",
        ),
        NA,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)


def test_door_invalid_enum_kind_rejected(api):
    """PRD §2.1: "any request carrying a missing required field, a malformed
    value, or an enum value outside its declared range is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A door is created with a `door_kind` of `THEATER`, `SPOKE`,
    `GROCERY`, or `PARTNER`".

    Design: Corner/entities/door_invalid_enum_kind_rejected
    """
    network = create_network(network_code="NE", display_name="Net E")
    resp = api.create_door(
        network["id"],
        create_door_payload(door_kind="KIOSK", ownership="COMPANY", territory_region="R"),
        NA,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_nonexistent_network_returns_not_found(api):
    """PRD §2.7: "The first identifier that does not resolve to an existing
    resource produces `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/entities/get_nonexistent_network_returns_not_found
    """
    resp = api.get_network("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", NA)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_list_doors_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter bounds the number of returned items:
    it defaults to 10 when omitted... The `offset` parameter says how many
    items to skip and defaults to 0... Paginated responses expose `limit`,
    `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope."

    Design: Corner/entities/list_doors_pagination_envelope
    """
    network = create_network(network_code="NP", display_name="Net P")
    create_door(network["id"], door_kind="THEATER", ownership="COMPANY", region="RP")
    create_door(network["id"], door_kind="GROCERY", ownership="COMPANY", region="RP")
    resp = api.list_doors(network["id"], NA)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert len(data) == 2


def test_computed_fields_input_ignored(api):
    """PRD §3.1: "The hub also tracks `committed_dozens_today`, the dozens
    committed by batches against the current calendar day; this figure is
    recomputed on every batch commit, cancel, or completion and is the pivot
    of the capacity check at commit time."

    Design: Corner/entities/computed_fields_input_ignored
    """
    network = create_network(network_code="NC", display_name="Net C")
    payload = create_hub_payload(hub_code="HC", daily_capacity_dozens=300, territory_region="RC")
    payload["committed_dozens_today"] = 999  # client-supplied computed field
    resp = api.create_hub(network["id"], payload, NA)
    data = validate_success(resp, expected_status=201)
    assert_hub(data)
    assert data["committed_dozens_today"] == 0, (
        f"computed input must be ignored, got {data['committed_dozens_today']}"
    )


def test_franchise_door_territory_mismatch_rejected(api):
    """PRD §3.1: "a `FRANCHISE` door's `territory_region` must equal the
    `territory_region` of its supplying hub, while `COMPANY` doors are exempt
    from that match... Violating any of these territory rules is rejected
    with `ERR_TERRITORY_VIOLATION` (HTTP 422)."

    Design: Corner/state_machines/franchise_door_territory_mismatch_rejected
    """
    network = create_network(network_code="NTR", display_name="Net TR")
    hub = create_hub(network["id"], hub_code="HTR", region="RA")
    # FRANCHISE door with mismatched territory -> rejected
    resp = api.create_door(
        network["id"],
        create_door_payload(
            door_kind="SPOKE", ownership="FRANCHISE", territory_region="RB", hub_id=hub["id"]
        ),
        NA,
    )
    validate_error(resp, ApiErrorId.ERR_TERRITORY_VIOLATION)
    # COMPANY door with the same mismatch -> accepted (exempt)
    resp2 = api.create_door(
        network["id"],
        create_door_payload(
            door_kind="SPOKE", ownership="COMPANY", territory_region="RB", hub_id=hub["id"]
        ),
        NA,
    )
    data = validate_success(resp2, expected_status=201)
    assert data["territory_region"] == "RB"
