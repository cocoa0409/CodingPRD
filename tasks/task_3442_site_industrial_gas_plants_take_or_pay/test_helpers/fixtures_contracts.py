"""Composite setup helpers: clock, customers, evaluations, contracts,
networks, connections, plants. Re-exported through fixtures.py.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database), uses get_success_data() so setup failures
surface as clear errors, and threads entity-backed identity correctly:
CustomerOps calls always use make_customer_ops_headers(customer["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START_UTC
from .factories import (
    create_connection_payload,
    create_contract_payload,
    create_customer_payload,
    create_evaluation_payload,
    create_network_payload,
    create_plant_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_customer_ops_headers


# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.4)
# ---------------------------------------------------------------------------

def set_logical_clock(current_utc: str = CLOCK_START_UTC):
    """Set the logical clock. Default is the PRD startup instant
    2026-09-01T00:00:00Z; the call itself answers 200 with no data payload."""
    response = api_client.set_clock(
        set_clock_payload(current_utc), TEST_USERS["platform_admin_headers"]
    )
    assert response.status_code == 200, (
        f"Setup failed: clock set to {current_utc} returned {response.status_code}: {response.text}"
    )
    return response


# ---------------------------------------------------------------------------
# Customer / evaluation / contract chain
# ---------------------------------------------------------------------------

def create_customer(**overrides) -> dict:
    """Create a Customer as PlatformAdmin. Optional fields (credit_standing,
    blackout_windows) are omitted unless overridden, so server defaults apply."""
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(**overrides), TEST_USERS["platform_admin_headers"]
        )
    )


def create_evaluation(customer_id: str, **overrides) -> dict:
    """Create (and immediately evaluate) a supply-mode study as SupplyPlanner.
    Status on return is EVALUATED."""
    return get_success_data(
        api_client.create_evaluation(
            create_evaluation_payload(customer_id, **overrides),
            TEST_USERS["supply_planner_headers"],
        )
    )


def accept_evaluation(evaluation_id: str, customer_id: str) -> dict:
    """CustomerOps accepts an evaluation. Identity threading is mandatory:
    X-User-ID must equal the evaluation's customer_id (PRD section 3.1)."""
    return get_success_data(
        api_client.accept_evaluation(evaluation_id, make_customer_ops_headers(customer_id))
    )


def create_customer_with_evaluation(customer_overrides: dict = None,
                                    evaluation_overrides: dict = None) -> tuple:
    """Customer + one EVALUATED evaluation. Returns (customer, evaluation)."""
    customer = create_customer(**(customer_overrides or {}))
    evaluation = create_evaluation(customer["id"], **(evaluation_overrides or {}))
    return customer, evaluation


def create_accepted_evaluation(customer_overrides: dict = None,
                               evaluation_overrides: dict = None) -> tuple:
    """Customer + one ACCEPTED evaluation. Returns (customer, evaluation)."""
    customer, evaluation = create_customer_with_evaluation(
        customer_overrides, evaluation_overrides
    )
    accepted = accept_evaluation(evaluation["id"], customer["id"])
    return customer, accepted


def create_contract(customer_id: str, evaluation_id: str, **overrides) -> dict:
    """Create a DRAFT take-or-pay contract against an ACCEPTED evaluation."""
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(customer_id, evaluation_id, **overrides),
            TEST_USERS["supply_planner_headers"],
        )
    )


def create_draft_contract(customer_overrides: dict = None,
                          evaluation_overrides: dict = None,
                          contract_overrides: dict = None) -> dict:
    """Full chain to a DRAFT contract.
    Returns {"customer", "evaluation", "contract"}."""
    customer, evaluation = create_accepted_evaluation(
        customer_overrides, evaluation_overrides
    )
    contract = create_contract(customer["id"], evaluation["id"], **(contract_overrides or {}))
    return {"customer": customer, "evaluation": evaluation, "contract": contract}


def activate_contract(contract_id: str) -> dict:
    """Activate a DRAFT contract as SupplyPlanner. Returns the ACTIVE contract."""
    return get_success_data(
        api_client.activate_contract(contract_id, TEST_USERS["supply_planner_headers"])
    )


def create_active_contract(customer_overrides: dict = None,
                           evaluation_overrides: dict = None,
                           contract_overrides: dict = None,
                           network: dict = None,
                           primary_reserved_flow_nm3h: int = 6000) -> dict:
    """Full chain to an ACTIVE contract.

    PIPELINE mode gate (PRD section 3.2): activation requires an ACTIVE
    PRIMARY connection. When the evaluation recommends PIPELINE, pass an
    existing PipelineNetwork via `network`; a PRIMARY connection is created
    while the contract is still DRAFT (connections allow DRAFT or ACTIVE),
    then the contract is activated.
    Returns {"customer", "evaluation", "contract", "connection" or None}.
    """
    bundle = create_draft_contract(
        customer_overrides, evaluation_overrides, contract_overrides
    )
    connection = None
    if bundle["evaluation"]["recommended_mode"] == "PIPELINE":
        assert network is not None, (
            "Setup failed: PIPELINE-mode activation needs a network for the PRIMARY connection"
        )
        connection = create_connection(
            network["id"],
            bundle["contract"]["id"],
            reserved_flow_nm3h=primary_reserved_flow_nm3h,
            purpose="PRIMARY",
        )
    bundle["contract"] = activate_contract(bundle["contract"]["id"])
    bundle["connection"] = connection
    return bundle


# ---------------------------------------------------------------------------
# Pipeline network / connection
# ---------------------------------------------------------------------------

def create_network(**overrides) -> dict:
    """Create a PipelineNetwork as PlatformAdmin."""
    return get_success_data(
        api_client.create_network(
            create_network_payload(**overrides), TEST_USERS["platform_admin_headers"]
        )
    )


def create_connection(network_id: str, contract_id: str, **overrides) -> dict:
    """Reserve firm capacity for a contract (born ACTIVE after admission)."""
    return get_success_data(
        api_client.create_connection(
            create_connection_payload(network_id, contract_id, **overrides),
            TEST_USERS["pipeline_dispatcher_headers"],
        )
    )


def release_connection(connection_id: str) -> dict:
    """Release a connection as PipelineDispatcher (compensating action)."""
    return get_success_data(
        api_client.release_connection(
            connection_id, TEST_USERS["pipeline_dispatcher_headers"]
        )
    )


# ---------------------------------------------------------------------------
# Onsite plant
# ---------------------------------------------------------------------------

def create_plant(contract_id: str, **overrides) -> dict:
    """Create a dedicated plant (PROPOSED) for an ACTIVE ONSITE_PLANT contract."""
    return get_success_data(
        api_client.create_plant(
            create_plant_payload(contract_id, **overrides),
            TEST_USERS["plant_operator_headers"],
        )
    )


def advance_plant(plant_id: str) -> dict:
    """Advance construction one stage."""
    return get_success_data(
        api_client.advance_plant(plant_id, TEST_USERS["plant_operator_headers"])
    )


def advance_plant_to_operating(plant_id: str) -> dict:
    """Walk PROPOSED -> UNDER_CONSTRUCTION -> COMMISSIONING -> OPERATING;
    effective capacity rises to nameplate on the third advance."""
    advance_plant(plant_id)
    advance_plant(plant_id)
    return advance_plant(plant_id)


def create_operating_plant(contract_id: str, **overrides) -> dict:
    """Create a plant and advance it to OPERATING. Returns the plant."""
    plant = create_plant(contract_id, **overrides)
    return advance_plant_to_operating(plant["id"])


# ---------------------------------------------------------------------------
# Standard composite scenario
# ---------------------------------------------------------------------------

def setup_standard_onsite_scenario(with_plant: bool = True, operating: bool = True,
                                   customer_overrides: dict = None,
                                   evaluation_overrides: dict = None,
                                   contract_overrides: dict = None,
                                   plant_overrides: dict = None) -> dict:
    """The canonical dedicated-plant scenario: clock pinned at startup, a PRIME
    customer, an ACCEPTED ONSITE_PLANT evaluation (avg 5000 Nm3/h), an ACTIVE
    120-month take-or-pay contract starting 2026-10-01, and (optionally) a
    plant walked to OPERATING.
    Returns {"customer", "evaluation", "contract", "connection", "plant"}."""
    set_logical_clock()
    merged_customer = {"credit_standing": "PRIME"}
    merged_customer.update(customer_overrides or {})
    bundle = create_active_contract(
        customer_overrides=merged_customer,
        evaluation_overrides=evaluation_overrides,
        contract_overrides=contract_overrides,
    )
    plant = None
    if with_plant:
        if operating:
            plant = create_operating_plant(bundle["contract"]["id"], **(plant_overrides or {}))
        else:
            plant = create_plant(bundle["contract"]["id"], **(plant_overrides or {}))
    bundle["plant"] = plant
    return bundle


__all__ = [
    "set_logical_clock",
    "create_customer",
    "create_evaluation",
    "accept_evaluation",
    "create_customer_with_evaluation",
    "create_accepted_evaluation",
    "create_contract",
    "create_draft_contract",
    "activate_contract",
    "create_active_contract",
    "create_network",
    "create_connection",
    "release_connection",
    "create_plant",
    "advance_plant",
    "advance_plant_to_operating",
    "create_operating_plant",
    "setup_standard_onsite_scenario",
]
