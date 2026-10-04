"""Contract activation gates: the evaluation-accepted state gate, the
minimum-volume floors, the fiscal credit gate, and their tier ordering."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_evaluation,
    api_client,
    create_accepted_evaluation,
    create_contract,
    create_customer,
    create_evaluation,
    set_logical_clock,
    validate_error,
    validate_success,
)


def _watchco_with_contract():
    """WATCH-standing customer + ACCEPTED onsite evaluation + DRAFT contract."""
    customer = create_customer(name="WatchCo", segment="METALS",
                               credit_standing="WATCH")
    evaluation = create_evaluation(
        customer["id"], site_label="MILL-1", demand_avg_nm3h=5000,
        demand_peak_nm3h=7000, required_purity_percent=99.9,
        required_product="H2", pipeline_available=True,
    )
    accept_evaluation(evaluation["id"], customer["id"])
    contract = create_contract(customer["id"], evaluation["id"])
    return customer, evaluation, contract


def test_activate_requires_evaluation_accepted(api):
    """PRD section 3.1: "Should an `ACCEPTED` evaluation later be superseded by
    a sibling's acceptance, a contract already created from it keeps its
    `evaluation_id` but cannot activate while the evaluation is no longer
    `ACCEPTED`."
    PRD section 3.2: "The referenced evaluation must be `ACCEPTED` — at
    creation and again at activation — or the call fails with
    `ERR_EVALUATION_NOT_ACCEPTED`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_evaluation_accepted
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    contract = create_contract(customer["id"], evaluation["id"])
    sibling = create_evaluation(customer["id"], demand_avg_nm3h=5100,
                                demand_peak_nm3h=7100)
    accept_evaluation(sibling["id"], customer["id"])

    response = api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_EVALUATION_NOT_ACCEPTED)

    evaluations = validate_success(api_client.list_customer_evaluations(
        customer["id"], TEST_USERS["supply_planner_headers"]
    ))
    first = [e for e in evaluations if e["id"] == evaluation["id"]][0]
    assert first["status"] == "SUPERSEDED", (
        f"accepting the sibling must supersede the original, got {first['status']}"
    )
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert contract_after["status"] == "DRAFT"


def test_activate_state_beats_fiscal(api):
    """PRD section 2.8: "Every request is checked against a fixed sequence of
    priority tiers, and a failure at an earlier tier masks every later check:"
    PRD section 3.2: "Activation moves `DRAFT` to `ACTIVE` behind four gates,
    which fire in the tier order of §2.8: the state-level evaluation gate
    first, the constraint-level connection and volume gates next, and the
    fiscal credit gate last."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_fiscal
    """
    set_logical_clock()
    customer, evaluation, contract = _watchco_with_contract()
    sibling = create_evaluation(
        customer["id"], site_label="MILL-1", demand_avg_nm3h=5200,
        demand_peak_nm3h=7200, required_purity_percent=99.9,
        required_product="H2", pipeline_available=True,
    )
    accept_evaluation(sibling["id"], customer["id"])

    response = api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    error_data = validate_error(response, ApiErrorId.ERR_EVALUATION_NOT_ACCEPTED)
    assert response.status_code == 409
    assert error_data["error_id"] != "ERR_CUSTOMER_CREDIT_WATCH", (
        "the state gate (tier 4) must mask the fiscal credit gate (tier 8)"
    )
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert contract_after["status"] == "DRAFT"


def test_activate_min_volume_exact_floor_allowed(api):
    """PRD section 3.2: "The monthly minimum must meet its mode floor —
    2,000,000 Nm3 for `ONSITE_PLANT`, 800,000 Nm3 for `PIPELINE`, 150,000 Nm3
    for `BULK_LIQUID`, and no floor at all for `CYLINDER` — or activation is
    refused with `ERR_MIN_VOLUME_BELOW_FLOOR`."

    Design: Corner/validations/activate_min_volume_exact_floor_allowed
    """
    set_logical_clock()
    customer, evaluation = create_accepted_evaluation(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    contract_ok = create_contract(customer["id"], evaluation["id"],
                                  min_monthly_volume_nm3=2000000)
    second = create_evaluation(
        customer["id"], site_label="FAB-2", demand_avg_nm3h=4500,
        demand_peak_nm3h=6000, required_purity_percent=99.99,
        required_product="N2", pipeline_available=True,
    )
    accept_evaluation(second["id"], customer["id"])
    contract_low = create_contract(customer["id"], second["id"],
                                   min_monthly_volume_nm3=1999999)

    activated = validate_success(api_client.activate_contract(
        contract_ok["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert activated["status"] == "ACTIVE", (
        "a minimum exactly at the 2,000,000 floor meets it and activates"
    )
    response = api_client.activate_contract(
        contract_low["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_MIN_VOLUME_BELOW_FLOOR)
    low_after = validate_success(api_client.get_contract(
        contract_low["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert low_after["status"] == "DRAFT"


def test_credit_watch_blocks_activation_solo(api):
    """PRD section 3.2: "Finally, the customer's `credit_standing` must not be
    `WATCH` (`ERR_CUSTOMER_CREDIT_WATCH`)."
    PRD section 3.1: "A customer whose standing is `WATCH` can be registered
    and evaluated normally, but the standing blocks contract activation later
    (§3.2)."

    Design: Corner/validations/credit_watch_blocks_activation_solo
    """
    set_logical_clock()
    _, _, contract = _watchco_with_contract()
    response = api_client.activate_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CUSTOMER_CREDIT_WATCH)
    contract_after = validate_success(api_client.get_contract(
        contract["id"], TEST_USERS["supply_planner_headers"]
    ))
    assert contract_after["status"] == "DRAFT"
