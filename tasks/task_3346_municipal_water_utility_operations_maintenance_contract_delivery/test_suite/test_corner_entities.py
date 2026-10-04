"""Corner-queue tests for entity creation: minted identity, defaults and constraints."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_municipality,
    asset_payload,
    award_contract,
    contract_payload,
    get_success_data,
    is_valid_uuid,
    municipality_payload,
    register_municipality,
    setup_operating_contract,
    validate_error,
    validate_success,
    work_order_payload,
)
from test_helpers.api_errors import ApiErrorId


def test_municipality_registration_mints_identity_and_zeroes_the_running_totals(api):
    """PRD §3.1: "Two running totals are initialised at registration and are never set directly by a client: `benchmark_index_baseline` starts at 0.0, and `total_operator_penalty_cents` starts at 0."
    PRD §2.4: "`version` starts at 1 on creation and is incremented by exactly one on every mutation."

    Design: Corner/entities/municipality_creation_returns_server_minted_identity_fields
    """
    response = api_client.register_municipality(
        municipality_payload(), TEST_USERS["platform_admin_headers"]
    )
    municipality = validate_success(response, 201)

    assert is_valid_uuid(municipality["id"]), "identity is server-minted as a UUID"
    assert municipality["version"] == 1
    assert municipality["total_operator_penalty_cents"] == 0, (
        "the penalty total is initialised at registration, never set by a client"
    )
    assert municipality["benchmark_index_baseline"] == 0.0, (
        "the benchmark index starts at 0.0 for a municipality with no live contracts"
    )
    assert_municipality(municipality)


def test_contract_award_rejects_an_inverted_operating_window(api):
    """PRD §3.1: "The `contract_end_date` must be strictly after the `contract_start_date`; a payload that inverts or equalises them is rejected with `ERR_INVALID_DATE_WINDOW` (HTTP 400)."

    Design: Corner/entities/contract_creation_rejects_inverted_operating_window
    """
    municipality, municipality_headers = register_municipality()

    response = api_client.award_contract(
        municipality["id"],
        contract_payload(
            contract_start_date="2027-05-01T00:00:00Z",
            contract_end_date="2027-04-30T00:00:00Z",
        ),
        municipality_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_DATE_WINDOW)

    contracts = get_success_data(
        api_client.list_municipality_contracts(municipality["id"], municipality_headers)
    )
    assert contracts == [], "a rejected award must not create a contract row"


def test_new_asset_carries_the_system_applied_condition_defaults(api):
    """PRD §3.2: "A new asset starts at `REGISTERED` with a `condition_score` of 100.0 and a `condition_band` of `EXCELLENT`."

    Design: Corner/entities/asset_creation_defaults_condition_score_and_band
    """
    municipality, municipality_headers = register_municipality()
    contract, contract_headers = award_contract(municipality, municipality_headers)

    asset = validate_success(
        api_client.register_asset(contract["id"], asset_payload(), municipality_headers), 201
    )

    assert asset["condition_score"] == 100.0
    assert asset["condition_band"] == "EXCELLENT"
    assert asset["status"] == "REGISTERED"


def test_raised_work_order_expense_class_is_computed_by_the_server(api):
    """PRD §3.6: "A newly raised work order is `DRAFT` and its `expense_class` is computed immediately by the boundary rule below."
    PRD §3.6: "Otherwise, a work order whose estimated cost is at least 2,500,000 cents is a capital candidate: if the current calendar year is at or after the asset's `install_year` plus its `useful_life_years`, it is classified `CAPITAL_LIFE_EVENT`, and if not, it is classified `CAPITAL_THRESHOLD`."

    Design: Corner/entities/work_order_expense_class_is_computed_and_ignores_client_input
    """
    scenario = setup_operating_contract(
        assets=[
            {
                "asset_tag": "PMP-102",
                "asset_class": "PUMP",
                "install_year": 2011,
                "useful_life_years": 15,
                "criticality_rank": 1,
            }
        ]
    )

    order = validate_success(
        api_client.raise_work_order(
            scenario.asset["id"],
            work_order_payload(work_type="CORRECTIVE", estimated_cost_cents=3000000),
            scenario.con_h,
        ),
        201,
    )

    assert order["expense_class"] == "CAPITAL_LIFE_EVENT", (
        "the server classifies the work order from the asset's elapsed service life"
    )
    assert order["actual_cost_cents"] == 0, "no cost has been finalized yet"
    assert order["status"] == "DRAFT"
