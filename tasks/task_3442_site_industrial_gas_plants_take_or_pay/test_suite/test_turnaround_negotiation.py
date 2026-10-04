"""Turnaround negotiation: the COUNTER self-loop, OCC on respond, and
turnaround not-found handling."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    agree_turnaround,
    api_client,
    counter_turnaround,
    create_respond_payload,
    create_turnaround,
    make_customer_ops_headers,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_error,
    validate_success,
)


def _get_turnaround(plant_id, turnaround_id):
    turnarounds = validate_success(api_client.list_plant_turnarounds(
        plant_id, TEST_USERS["plant_operator_headers"]
    ))
    match = [t for t in turnarounds if t["id"] == turnaround_id]
    assert len(match) == 1, f"turnaround {turnaround_id} not found on plant"
    return match[0]


def test_turnaround_counter_cycles_proposal_round(api):
    """PRD section 3.7: "A `decision` of `COUNTER` keeps it `PROPOSED` but
    replaces the window with `counter_window_start` and `counter_window_end` —
    both required, the end after the start, the duration again within 24 to 720
    hours, else `ERR_WINDOW_DURATION_INVALID` — increments `proposal_round` by
    1, and increments `version`."
    PRD section 3.7: "A `decision` of `AGREE` moves the turnaround to `AGREED`
    and increments its `version`."

    Design: Corner/state_machines/turnaround_counter_cycles_proposal_round
    """
    bundle = setup_standard_onsite_scenario()
    customer, plant = bundle["customer"], bundle["plant"]
    turnaround = create_turnaround(plant["id"])
    assert turnaround["status"] == "PROPOSED"
    assert turnaround["proposal_round"] == 1

    countered = counter_turnaround(
        turnaround["id"], turnaround["version"], customer["id"],
        counter_window_start="2026-11-10T00:00:00Z",
        counter_window_end="2026-11-14T00:00:00Z",
    )
    assert countered["status"] == "PROPOSED", (
        "COUNTER is a self-loop back into PROPOSED"
    )
    assert countered["proposal_round"] == 2
    assert countered["version"] == turnaround["version"] + 1
    assert countered["window_start"] == "2026-11-10T00:00:00Z"
    assert countered["window_end"] == "2026-11-14T00:00:00Z"

    agreed = agree_turnaround(turnaround["id"], countered["version"], customer["id"])
    assert agreed["status"] == "AGREED"


def test_occ_turnaround_respond_stale_version(api):
    """PRD section 2.7: "Responding to a turnaround proposal likewise requires
    `expected_turnaround_version`, matching the turnaround's current
    `version`."
    PRD section 2.7: "In both cases, if the resource's version has advanced
    past the client's observed value since the client last read it, the write
    is rejected with `ERR_STALE_VERSION` (HTTP 412): the client's picture of
    the commercial terms — or of the turnaround window on the table — is stale
    and must be re-read before writing."

    Design: Corner/complexity_layers/occ_turnaround_respond_stale_version
    """
    bundle = setup_standard_onsite_scenario()
    customer, plant = bundle["customer"], bundle["plant"]
    turnaround = create_turnaround(plant["id"], scope="OCC check")
    counter_turnaround(
        turnaround["id"], turnaround["version"], customer["id"],
        counter_window_start="2026-11-10T00:00:00Z",
        counter_window_end="2026-11-14T00:00:00Z",
    )
    response = api_client.respond_to_turnaround(
        turnaround["id"],
        create_respond_payload("AGREE", turnaround["version"]),
        make_customer_ops_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION)
    after = _get_turnaround(plant["id"], turnaround["id"])
    assert after["status"] == "PROPOSED"
    assert after["window_start"] == "2026-11-10T00:00:00Z"
    assert after["window_end"] == "2026-11-14T00:00:00Z", (
        "the stale AGREE must not disturb the countered window"
    )


def test_turnaround_not_found_on_respond(api):
    """PRD section 2.8: "Existence: path identifiers resolve, validated left to
    right — customer, then evaluation, contract, plant, network, connection,
    tank, delivery, certificate, turnaround — each failure producing its
    resource-specific 404 (`ERR_CUSTOMER_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_PLANT_NOT_FOUND`, `ERR_NETWORK_NOT_FOUND`,
    `ERR_CONNECTION_NOT_FOUND`, `ERR_TANK_NOT_FOUND`, `ERR_DELIVERY_NOT_FOUND`,
    `ERR_CERTIFICATE_NOT_FOUND`, or `ERR_TURNAROUND_NOT_FOUND`)."

    Design: Corner/errors/turnaround_not_found_on_respond
    """
    bundle = setup_standard_onsite_scenario()
    customer, plant = bundle["customer"], bundle["plant"]
    turnaround = create_turnaround(plant["id"], scope="Real one")
    response = api_client.respond_to_turnaround(
        NON_EXISTENT_UUID,
        create_respond_payload("AGREE", turnaround["version"]),
        make_customer_ops_headers(customer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TURNAROUND_NOT_FOUND)
