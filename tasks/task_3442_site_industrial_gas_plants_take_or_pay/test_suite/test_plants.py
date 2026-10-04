"""Dedicated on-site plants: the contract-state gate on creation, the
construction ladder, and the one-live-plant rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_plant,
    api_client,
    assert_plant,
    create_draft_contract,
    create_plant_payload,
    set_logical_clock,
    setup_standard_onsite_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_plant_create_requires_active_contract(api):
    """PRD section 3.3: "Creation is gated: the contract must be `ACTIVE`
    (`ERR_CONTRACT_NOT_ACTIVE`), its mode must be `ONSITE_PLANT`
    (`ERR_MODE_MISMATCH`), and at most one live plant may exist per contract —
    attempting a second while a non-`DECOMMISSIONED` one exists is refused with
    `ERR_PLANT_ALREADY_EXISTS`."

    Design: Difficulty/cross_entity_state_dependency/plant_create_requires_active_contract
    """
    set_logical_clock()
    bundle = create_draft_contract(
        {"name": "Fabrikam Chips", "segment": "ELECTRONICS", "credit_standing": "PRIME"}
    )
    contract = bundle["contract"]
    response = api_client.create_plant(
        create_plant_payload(contract["id"]), TEST_USERS["plant_operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)
    plants, meta = validate_paginated(api_client.list_plants(
        TEST_USERS["plant_operator_headers"],
        params={"contract_id": contract["id"]},
    ))
    assert plants == [] and meta["total_count"] == 0, (
        "no plant may be persisted against a DRAFT contract"
    )


def test_plant_advance_ladder_then_invalid(api):
    """PRD section 3.3: "Construction proceeds one stage per advance action:
    `PROPOSED` to `UNDER_CONSTRUCTION`, then `COMMISSIONING`, then `OPERATING`
    — the moment effective capacity rises to the nameplate value. From
    `OPERATING` there are exactly two ways out."
    PRD section 2.8: "State guards: the stale-version checks of §2.7, the
    evaluation-accepted requirement, from-state legality for the requested
    transition (`ERR_INVALID_STATE_TRANSITION`), the contract-active
    requirement (`ERR_CONTRACT_NOT_ACTIVE`), the plant-operating requirement
    (`ERR_PLANT_NOT_OPERATING`), and the delivery-delivered requirement
    (`ERR_DELIVERY_NOT_DELIVERED`)."

    Design: Corner/state_machines/plant_advance_ladder_then_invalid
    """
    bundle = setup_standard_onsite_scenario(operating=False)
    plant = bundle["plant"]
    advance_plant(plant["id"])
    advance_plant(plant["id"])
    operating = advance_plant(plant["id"])
    assert_plant(operating)
    assert operating["status"] == "OPERATING"
    assert operating["effective_capacity_nm3h"] == 6000, (
        f"effective capacity must rise to nameplate on reaching OPERATING, "
        f"got {operating['effective_capacity_nm3h']}"
    )
    response = api_client.advance_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    after = validate_success(api_client.get_plant(
        plant["id"], TEST_USERS["plant_operator_headers"]
    ))
    assert after["status"] == "OPERATING"


def test_plant_already_exists_rejected(api):
    """PRD section 3.3: "at most one live plant may exist per contract —
    attempting a second while a non-`DECOMMISSIONED` one exists is refused with
    `ERR_PLANT_ALREADY_EXISTS`."

    Design: Corner/validations/plant_already_exists_rejected
    """
    bundle = setup_standard_onsite_scenario(operating=False)
    contract = bundle["contract"]
    response = api_client.create_plant(
        create_plant_payload(
            contract["id"], name="FAB-1 ASU-2", nameplate_capacity_nm3h=3000,
            capital_cost_cents=60000000, power_kwh_per_nm3=0.45,
        ),
        TEST_USERS["plant_operator_headers"],
    )
    validate_error(response, ApiErrorId.ERR_PLANT_ALREADY_EXISTS)
