"""Corner-queue tests for the read routes: echo fidelity, listing and not-found."""
from test_helpers import (
    api_client,
    assert_contract,
    award_contract,
    contract_payload,
    create_standard,
    get_success_data,
    register_municipality,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId

# A well-formed identifier that no contract can carry.
UNKNOWN_CONTRACT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_contract_read_echoes_the_creation_response(api):
    """PRD §4: "An operation that reads or modifies an existing resource responds with 200 OK."
    PRD §3.1: "A newly awarded contract begins its life at `AWARDED`."
    PRD §2.4: "Every persisted resource in this API carries an `id` minted by the server as a UUID with no type prefix"

    Design: Corner/endpoints/contract_get_matches_the_creation_response
    """
    municipality, municipality_headers = register_municipality()
    created, contract_headers = award_contract(municipality, municipality_headers)

    fetched = validate_success(api_client.get_contract(created["id"], contract_headers))

    assert fetched["id"] == created["id"]
    assert fetched["annual_fee_cents"] == 40000000
    assert fetched["status"] == "AWARDED"
    assert fetched["baseline_frozen"] is False
    assert_contract(fetched)


def test_municipality_contract_list_filters_by_status_and_reports_totals(api):
    """PRD §2.3: "Several list endpoints additionally accept an optional filter — for example a `status`, `role_code`, `asset_class`, `condition_band`, `work_type`, `event_type`, `severity`, `permit_type`, `obligation_type`, `round_number`, `is_critical` or `asset_id` discriminator — and the filter narrows `total_count` accordingly."
    PRD §2.3: "List responses include four pagination fields inside `meta`: `limit` (the effective page size actually applied), `offset` (the effective offset actually applied), `total_count` (the count of records matching the filter before pagination), and `has_more` (true when further records exist beyond the returned page)."

    Design: Corner/endpoints/contract_list_filters_by_status_and_paginates
    """
    municipality, municipality_headers = register_municipality()
    award_contract(municipality, municipality_headers)
    second, second_headers = award_contract(
        municipality,
        municipality_headers,
        title="Water Treatment O&M",
        annual_fee_cents=32000000,
        operator_penalty_share_pct=0.5,
        award_date="2026-04-02T00:00:00Z",
    )
    create_standard(second["id"], second_headers, activate=True)
    moved = validate_success(api_client.mobilize_contract(second["id"], second_headers))
    assert moved["status"] == "MOBILIZING"

    response = api_client.list_municipality_contracts(
        municipality["id"], municipality_headers, params={"status": "MOBILIZING"}
    )
    data, meta = validate_paginated(response)

    assert meta["total_count"] == 1, "the filter narrows the count before pagination"
    assert meta["has_more"] is False
    assert len(data) == 1
    assert data[0]["id"] == second["id"]
    assert data[0]["status"] == "MOBILIZING"


def test_unknown_contract_id_is_reported_as_contract_not_found(api):
    """PRD §2.6: "The not-found catalogue is exhaustive and per-entity: `ERR_MUNICIPALITY_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, ..."
    PRD §3.10: "Any request whose path or payload names a municipality, contract, permit, standard, measurement, asset, assessment, employee, staffing commitment, work order, schedule, emergency event, penalty allocation, renewal proposal or transition obligation that does not exist is rejected with the matching not-found error from §2.6."

    Design: Corner/endpoints/missing_contract_id_returns_contract_not_found
    """
    # The OperatorAdmin actor must be bound to a real contract; the read itself
    # names a contract that does not exist.
    municipality, municipality_headers = register_municipality()
    _, contract_headers = award_contract(municipality, municipality_headers)

    response = api_client.get_contract(UNKNOWN_CONTRACT_ID, contract_headers)
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_FOUND)


def test_municipality_contract_list_returns_only_its_own_contracts(api):
    """PRD §2.6: "Most resources in this API are addressed through their parent."
    PRD §2.1: "Ownership checks on any resource that references a `Municipality` compare the resource's foreign-key field (for example a contract's `municipality_id`) to `X-User-ID`."

    Design: Corner/endpoints/municipality_contract_list_returns_contract_children
    """
    first_municipality, first_headers = register_municipality()
    second_municipality, second_headers = register_municipality(
        name="Lakemoor",
        state_code="WI",
        population_served=90000,
        owns_treatment_works=False,
    )

    contract, _ = award_contract(first_municipality, first_headers)
    award_contract(
        second_municipality,
        second_headers,
        title="Water Treatment O&M",
        annual_fee_cents=12000000,
        operator_penalty_share_pct=0.4,
        benchmark_index_baseline=0.0002,
        award_date="2026-04-05T00:00:00Z",
    )

    response = api_client.list_municipality_contracts(
        first_municipality["id"], first_headers
    )
    data, meta = validate_paginated(response)

    assert meta["total_count"] == 1, (
        "only the contracts awarded by this municipality are reachable from it"
    )
    assert data[0]["id"] == contract["id"]
    assert data[0]["title"] == "Wastewater O&M"
