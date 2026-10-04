"""Contract creation, supersession history, and optimistic concurrency (PRD §2.4, §3.1)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_contract,
    create_farm,
    get_farm,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]


def test_contracts_list_shows_supersession_history(api):
    """PRD §3.1: "Because a farm has at most one current contract, a successful
    creation moves the farm's previously `ACTIVE` contract — if one exists — to
    `SUPERSEDED`, and the farm's `version` increments by exactly one, a single
    increment covering both the creation and the supersede."

    Design: Corner/endpoints/contracts_list_shows_supersession_history
    """
    farm = create_farm(name="Supersede Farm")
    farm_id = farm["id"]

    ct1 = validate_success(
        api.create_contract(
            farm_id,
            {
                "commodity_base_cents_per_dozen": 150,
                "premium_cents_per_dozen": 90,
                "start_date": "2026-09-01",
                "end_date": "2027-08-31",
                "expected_farm_version": farm["version"],
            },
            NM,
        ),
        201,
    )
    assert ct1["status"] == "ACTIVE"

    ct2 = create_contract(
        farm_id,
        commodity_base_cents_per_dozen=155,
        premium_cents_per_dozen=95,
        start_date="2026-09-01",
        end_date="2028-08-31",
    )
    assert ct2["status"] == "ACTIVE"

    rows, meta = validate_paginated(api.list_contracts(farm_id, NM))
    assert meta["total_count"] == 2, f"expected 2 contracts, got {meta['total_count']}"
    by_id = {row["id"]: row for row in rows}
    assert by_id[ct1["id"]]["status"] == "SUPERSEDED"
    assert by_id[ct2["id"]]["status"] == "ACTIVE"


def test_occ_stale_farm_version_on_contract_create(api):
    """PRD §2.4: "If the farm's current `version` has advanced beyond that value
    — for example because another contract creation already bumped it — the
    caller's view of the farm is stale and the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.1: "a successful creation moves the farm's previously `ACTIVE`
    contract — if one exists — to `SUPERSEDED`"

    Design: Corner/cross_cutting_layers/occ_stale_farm_version_on_contract_create
    """
    farm = create_farm(name="OCC Farm")
    farm_id = farm["id"]
    observed_version = farm["version"]

    ct1 = validate_success(
        api.create_contract(
            farm_id,
            {
                "commodity_base_cents_per_dozen": 150,
                "premium_cents_per_dozen": 90,
                "start_date": "2026-09-01",
                "end_date": "2027-08-31",
                "expected_farm_version": observed_version,
            },
            NM,
        ),
        201,
    )

    # Stale: same pre-first-create version presented again.
    resp_stale = api.create_contract(
        farm_id,
        {
            "commodity_base_cents_per_dozen": 160,
            "premium_cents_per_dozen": 95,
            "start_date": "2026-09-01",
            "end_date": "2028-08-31",
            "expected_farm_version": observed_version,
        },
        NM,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION, 412)

    farm_after = get_farm(farm_id)
    assert farm_after["version"] == observed_version + 1, (
        "the stale attempt must create nothing: farm.version holds the single "
        "increment from the first create"
    )

    # Retry with the fresh version succeeds and supersedes the first contract.
    ct2 = validate_success(
        api.create_contract(
            farm_id,
            {
                "commodity_base_cents_per_dozen": 160,
                "premium_cents_per_dozen": 95,
                "start_date": "2026-09-01",
                "end_date": "2028-08-31",
                "expected_farm_version": farm_after["version"],
            },
            NM,
        ),
        201,
    )
    assert ct2["status"] == "ACTIVE"

    rows, _ = validate_paginated(api.list_contracts(farm_id, NM))
    by_id = {row["id"]: row for row in rows}
    assert by_id[ct1["id"]]["status"] == "SUPERSEDED"
