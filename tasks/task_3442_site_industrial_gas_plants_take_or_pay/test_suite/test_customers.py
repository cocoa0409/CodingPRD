"""Customer onboarding: creation defaults, retrieval round-trip, not-found
handling, and the error envelope shape."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_customer,
    create_customer,
    create_customer_payload,
    set_logical_clock,
    validate_error,
    validate_success,
)


def test_customer_create_applies_defaults_and_system_fields():
    """PRD section 3.1: "A `PlatformAdmin` onboards each customer with a legal
    `name`, a market `segment` — one of `ELECTRONICS`, `MEDICAL`, `METALS`, or
    `CHEMICAL` — and two optional fields: `credit_standing`, one of `PRIME`,
    `STANDARD`, or `WATCH` and defaulting to `STANDARD` when omitted, and
    `blackout_windows`, a list of production blackout periods each carrying a
    `start_iso` and an `end_iso` timestamp and defaulting to an empty list."
    PRD section 4: "Operations that create a new, stand-alone resource answer
    `201 Created`."

    Design: Corner/entities/customer_create_applies_defaults_and_system_fields
    """
    set_logical_clock()
    response = api_client.create_customer(
        create_customer_payload(), TEST_USERS["platform_admin_headers"]
    )
    data = validate_success(response, 201)
    assert_customer(data)
    assert data["credit_standing"] == "STANDARD", (
        f"credit_standing default must be STANDARD, got {data['credit_standing']}"
    )
    assert data["blackout_windows"] == [], (
        f"blackout_windows default must be [], got {data['blackout_windows']}"
    )


def test_customer_get_roundtrips_stored_configuration():
    """PRD section 3.1: "`blackout_windows`, a list of production blackout
    periods each carrying a `start_iso` and an `end_iso` timestamp and
    defaulting to an empty list."
    PRD section 2.2: "The `data` field contains the resource object or an array
    of resource objects."

    Design: Corner/entities/customer_get_roundtrips_stored_configuration
    """
    set_logical_clock()
    windows = [
        {"start_iso": "2027-03-10T00:00:00Z", "end_iso": "2027-03-20T00:00:00Z"},
        {"start_iso": "2027-09-01T00:00:00Z", "end_iso": "2027-09-05T00:00:00Z"},
    ]
    created = create_customer(
        name="Fabrikam Chips", segment="ELECTRONICS",
        credit_standing="PRIME", blackout_windows=windows,
    )
    response = api_client.get_customer(created["id"], TEST_USERS["supply_planner_headers"])
    data = validate_success(response)
    assert_customer(data)
    assert data["name"] == "Fabrikam Chips"
    assert data["segment"] == "ELECTRONICS"
    assert data["credit_standing"] == "PRIME"
    assert len(data["blackout_windows"]) == 2, (
        f"expected 2 blackout windows to round-trip, got {len(data['blackout_windows'])}"
    )
    assert data["blackout_windows"][0]["start_iso"] == "2027-03-10T00:00:00Z"
    assert data["blackout_windows"][0]["end_iso"] == "2027-03-20T00:00:00Z"
    assert data["blackout_windows"][1]["start_iso"] == "2027-09-01T00:00:00Z"


def test_customer_not_found_returns_404():
    """PRD section 2.8: "Existence: path identifiers resolve, validated left to
    right — customer, then evaluation, contract, plant, network, connection,
    tank, delivery, certificate, turnaround — each failure producing its
    resource-specific 404 (`ERR_CUSTOMER_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`,
    `ERR_CONNECTION_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, or `ERR_TURNAROUND_NOT_FOUND`)."

    Design: Corner/entities/customer_not_found_returns_404
    """
    set_logical_clock()
    response = api_client.get_customer(
        NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)


def test_error_envelope_shape_on_not_found():
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD section 2.2: "The `message` provides a human-readable explanation of
    what went wrong."

    Design: Corner/endpoints/error_envelope_shape_on_not_found
    """
    set_logical_clock()
    response = api_client.get_customer(
        NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"]
    )
    error_data = validate_error(response, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)
    assert response.status_code == 404
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(error_data["message"], str) and error_data["message"].strip()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str) and meta["api_request_timestamp"]
