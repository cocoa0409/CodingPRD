"""Territory transfers: valuation bands, OCC, negotiation cycle, approve gate,
execute cascade."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    ApiErrorId,
    validate_error,
    validate_paginated,
    get_success_data,
    set_clock_default,
    create_brand_owner,
    create_territory,
    seed_active_agreement,
    create_customer,
    create_equipment,
    create_territory_transfer,
    valuate_transfer,
    ops_headers,
    make_customer_manager_headers,
)

PA = TEST_USERS["platform_admin_headers"]
BOA = TEST_USERS["brand_owner_admin_headers"]


def test_territory_valuation_low_band_uses_four_percent_reserve(api):
    """PRD §3.6: "First, the reserve rate is selected from the reported EBITDA
    band: four percent when `reported_ebitda_cents` is below 500,000,000 cents
    (five million dollars), and six percent at or above that threshold. Second,
    the equipment reserve is computed as the reported EBITDA — not the
    normalized figure — multiplied by that rate, rounded half-up to whole
    cents. Third, normalized EBITDA is the reported EBITDA minus the equipment
    reserve. Fourth, `valuation_cents` is seven times the normalized EBITDA —
    the EBITDA multiple — as an integer number of cents."

    Design: Corner/calculations/territory_valuation_low_band_uses_four_percent_reserve
    """
    set_clock_default()
    bo = create_brand_owner()
    ter = create_territory(bo["id"])
    env = {"bo": bo, "territory": ter}
    tt = create_territory_transfer(env, reported_ebitda_cents=400000000)
    valuated = valuate_transfer(tt["id"], tt["version"])
    # reserve = round(400000000 * 0.04) = 16000000; normalized = 384000000; x7
    assert valuated["valuation_cents"] == 2688000000
    assert valuated["status"] == "VALUED"
    assert valuated["valuation_round"] == 1


def test_territory_valuation_high_band_uses_six_percent_reserve(api):
    """PRD §3.6: "First, the reserve rate is selected from the reported EBITDA
    band: four percent when `reported_ebitda_cents` is below 500,000,000 cents
    (five million dollars), and six percent at or above that threshold."
    PRD §3.6: "Each valuation increments `valuation_round` by 1 and the
    transfer's `version` by 1, and moves the transfer to `VALUED`."

    Design: Difficulty/non_linear_state_machine/territory_transfer_negotiation_cycle_revaluation
    """
    env = seed_active_agreement()
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuated = valuate_transfer(tt["id"], tt["version"])
    # reserve = 600000000 * 0.06 = 36000000; normalized 564000000; x7
    assert valuated["valuation_cents"] == 3948000000
    assert valuated["status"] == "VALUED"
    assert valuated["valuation_round"] == 1


def test_territory_transfer_negotiation_cycle_revaluation(api):
    """PRD §3.6: "A `PlatformAdmin` may **counter** a `VALUED` transfer, moving
    it to `NEGOTIATING`. From `NEGOTIATING`, the brand owner's staff may
    valuate again — recomputing `valuation_cents` against the current
    `reported_ebitda_cents` and bumping `valuation_round` once more —
    producing the cyclic negotiation loop `VALUED → NEGOTIATING → VALUED`."

    Design: Difficulty/non_linear_state_machine/territory_transfer_negotiation_cycle_revaluation
    """
    env = seed_active_agreement()
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuated = valuate_transfer(tt["id"], tt["version"])
    r = api_client.counter_transfer(tt["id"], PA)
    assert r.status_code == 200
    countered = get_success_data(r)
    assert countered["status"] == "NEGOTIATING"
    revaluated = valuate_transfer(tt["id"], countered["version"])
    assert revaluated["status"] == "VALUED"
    assert revaluated["valuation_round"] == 2
    assert revaluated["valuation_cents"] == 3948000000


def test_transfer_valuate_with_stale_transfer_version_rejected(api):
    """PRD §2.8: "Valuating a territory transfer requires the request to carry
    `expected_transfer_version`, holding the caller's last observed `version`
    of the `TerritoryTransfer`. If the transfer's current `version` has
    advanced beyond that value — because a prior valuation or a counter has
    already moved the negotiation — the valuation is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/transfer_valuate_with_stale_transfer_version_rejected
    """
    set_clock_default()
    bo = create_brand_owner()
    ter = create_territory(bo["id"])
    env = {"bo": bo, "territory": ter}
    tt = create_territory_transfer(env, reported_ebitda_cents=400000000)
    valuate_transfer(tt["id"], tt["version"])  # bumps to version 2
    r = api_client.valuate_transfer(
        tt["id"], {"expected_transfer_version": tt["version"]}, BOA
    )
    validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)
    assert r.status_code == 412
    after = get_success_data(api_client.get_territory_transfer(tt["id"], PA))
    assert after["valuation_round"] == 1, "rejected re-valuation must not run"


def test_transfer_approve_blocked_by_disputed_customer(api):
    """PRD §3.6: "**Approval** by the brand owner's staff moves a `VALUED`
    transfer to `APPROVED`, but only while no customer of the territory's
    current agreement is `DISPUTED`; a disputed customer anywhere in the book
    blocks approval with `ERR_TRANSFER_CUSTOMERS_DISPUTED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_blocked_by_disputed_customer
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuate_transfer(tt["id"], tt["version"])
    r = api_client.dispute_customer(cust["id"], make_customer_manager_headers(cust["id"]))
    assert r.status_code == 200
    r = api_client.approve_transfer(tt["id"], BOA)
    validate_error(r, ApiErrorId.ERR_TRANSFER_CUSTOMERS_DISPUTED.value)
    assert r.status_code == 409
    after = get_success_data(api_client.get_territory_transfer(tt["id"], PA))
    assert after["status"] == "VALUED"


def test_transfer_approve_succeeds_after_dispute_resolved(api):
    """PRD §3.6: "**Approval** by the brand owner's staff moves a `VALUED`
    transfer to `APPROVED`, but only while no customer of the territory's
    current agreement is `DISPUTED`; a disputed customer anywhere in the book
    blocks approval with `ERR_TRANSFER_CUSTOMERS_DISPUTED` (HTTP 409)."
    PRD §3.4: "A `CustomerManager` acting as the customer may raise a
    **dispute**, moving the customer from `ACTIVE` to `DISPUTED`, and may later
    **resolve** it back to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/transfer_approve_blocked_by_disputed_customer
    """
    env = seed_active_agreement()
    cust = create_customer(env)
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuate_transfer(tt["id"], tt["version"])
    r = api_client.dispute_customer(cust["id"], make_customer_manager_headers(cust["id"]))
    assert r.status_code == 200
    r = api_client.approve_transfer(tt["id"], BOA)
    validate_error(r, ApiErrorId.ERR_TRANSFER_CUSTOMERS_DISPUTED.value)
    r = api_client.resolve_dispute(cust["id"], make_customer_manager_headers(cust["id"]))
    assert r.status_code == 200
    r = api_client.approve_transfer(tt["id"], BOA)
    assert r.status_code == 200, "approve must succeed once the dispute is resolved"
    assert get_success_data(r)["status"] == "APPROVED"


def test_transfer_execute_is_terminal_and_successor_owning_agreement_differs(api):
    """PRD §3.6: "**Execution** by a `PlatformAdmin` moves an `APPROVED`
    transfer to the terminal `EXECUTED` state and fires the refranchise
    cascade."
    PRD §3.6: "Execution creates a successor bottler agreement for the same
    territory, already `ACTIVE`, whose `bottler_name` is the transfer's
    `buyer_name` and whose `concentrate_base_index` and
    `marketing_accrual_basis` are copied from the prior agreement."

    Design: Difficulty/transitive_cascade/transfer_execute_refranchises_agreement_and_moves_assets
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuate_transfer(tt["id"], tt["version"])
    r = api_client.approve_transfer(tt["id"], BOA)
    assert r.status_code == 200
    r = api_client.execute_transfer(tt["id"], PA)
    assert r.status_code == 200
    executed = get_success_data(r)
    assert executed["status"] == "EXECUTED"
    # successor agreement discoverable in the same territory, distinct id
    data, meta = validate_paginated(
        api_client.list_territory_agreements(env["territory"]["id"], PA)
    )
    successors = [a for a in data if a["status"] == "ACTIVE" and a["id"] != ag_id]
    assert len(successors) == 1, "exactly one ACTIVE successor agreement must exist"
    assert successors[0]["bottler_name"] == "Peachtree Consolidated"
    assert successors[0]["territory_id"] == env["territory"]["id"]


def test_transfer_execute_refranchises_agreement_and_moves_assets(api):
    """PRD §3.6: "Execution creates a successor bottler agreement for the same
    territory, already `ACTIVE`, whose `bottler_name` is the transfer's
    `buyer_name` and whose `concentrate_base_index` and
    `marketing_accrual_basis` are copied from the prior agreement. The prior
    agreement is moved from `ACTIVE` to its terminal `REFRANCHISED` state, and
    the territory's status becomes `REFRANCHISED`. Every customer of the prior
    agreement is reassigned to the successor agreement, with each reassigned
    customer's `version` incrementing; every cold-drink equipment unit of the
    prior agreement flips its `agreement_id` to the successor while its
    placement fields remain unchanged."

    Design: Difficulty/transitive_cascade/transfer_execute_refranchises_agreement_and_moves_assets
    """
    env = seed_active_agreement()
    ag_id = env["agreement"]["id"]
    ter_id = env["territory"]["id"]
    cust = create_customer(env)
    eq = create_equipment(env)
    tt = create_territory_transfer(env, reported_ebitda_cents=600000000)
    valuate_transfer(tt["id"], tt["version"])
    r = api_client.approve_transfer(tt["id"], BOA)
    assert r.status_code == 200
    r = api_client.execute_transfer(tt["id"], PA)
    assert r.status_code == 200
    executed = get_success_data(r)
    assert executed["status"] == "EXECUTED"
    old_ag = get_success_data(api_client.get_agreement(ag_id, PA))
    assert old_ag["status"] == "REFRANCHISED"
    ter = get_success_data(api_client.get_territory(ter_id, PA))
    assert ter["status"] == "REFRANCHISED"
    customer = get_success_data(api_client.get_customer(cust["id"], PA))
    assert customer["agreement_id"] != ag_id, "customer must be reassigned to successor"
    equipment = get_success_data(api_client.get_equipment(eq["id"], PA))
    assert equipment["agreement_id"] != ag_id, "equipment must be reassigned to successor"
    assert equipment["agreement_id"] == customer["agreement_id"]
    successor = get_success_data(api_client.get_agreement(customer["agreement_id"], PA))
    assert successor["bottler_name"] == "Peachtree Consolidated"
    assert successor["status"] == "ACTIVE"
    assert successor["concentrate_base_index"] == pytest.approx(100.0)
    assert successor["marketing_accrual_basis"] == "CASE_VOLUME"
