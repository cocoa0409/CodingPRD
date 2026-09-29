"""Undo paths that must land back on the exact figure they started from.

PRD 3.7: cancelling a contract "recomputes the branch's
buyback_liability_usd_cents from scratch as the sum of liability_usd_cents over the
branch's contracts that are still ISSUED or PARTIALLY_REDEEMED".
PRD 3.5: "Reversal is a full compensation, not a status flip" - the notes are
restored "so that total_minor_units returns to exactly its pre-settlement value",
the vault figures are recomputed from the restored mix, and the surveillance
aggregates "all fall back to their pre-settlement values".
"""

from test_helpers import (
    assertions as a,
    factories as f,
    fixtures as fx,
    validate_success,
)

MIX = [f.denom(2000, 10), f.denom(5000, 10), f.denom(10000, 20)]
DEAL = [f.denom(10000, 1), f.denom(5000, 1), f.denom(2000, 2)]


def _two_contract_world(api, teller_headers):
    """Customer 1 has settled the 21626-cent deal and holds contract A; customer 2 has
    settled the 91054-cent deal and holds nothing yet."""
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=20_000_000,
        position_mix=MIX,
        customer_overrides={"full_name": "Karin Holm", "nationality_code": "NO"},
    )
    second_customer = fx.identified_customer(
        api, full_name="Luis Mora", nationality_code="MX", id_document_number="MX-55021"
    )

    first_txn = fx.settled_deal(api, world, denominations=DEAL, headers=teller_headers)
    contract_a = fx.issue_contract(api, world["customer"]["id"], first_txn["id"])

    second_txn = fx.settled_deal(
        api,
        world,
        denominations=[f.denom(10000, 8)],
        headers=teller_headers,
        customer_id=second_customer["id"],
    )
    world.update(
        {
            "second_customer": second_customer,
            "first_txn": first_txn,
            "contract_a": contract_a,
            "second_txn": second_txn,
        }
    )
    return world


def test_cancelling_a_contract_returns_the_branch_liability_to_its_earlier_figure(
    api, teller_headers, manager_headers
):
    """With contract A alone the branch owes 19576 cents; issuing contract B for the
    91054-cent deal lifts that to 101999 and cancelling B returns it to exactly 19576
    rather than to some drifted remainder.

    Design: Difficulty/compensating_invariant/buyback_issue_then_cancel_restores_branch_liability
    """
    world = _two_contract_world(api, teller_headers)
    before = fx.read_branch(api, world["branch"]["id"])
    assert before["buyback_liability_usd_cents"] == 19576

    contract_b = fx.issue_contract(
        api, world["second_customer"]["id"], world["second_txn"]["id"], headers=teller_headers
    )
    a.assert_buyback_contract(contract_b)
    assert contract_b["fee_usd_cents"] == 2732
    assert contract_b["locked_fx_minor_units"] == 80000
    assert contract_b["liability_usd_cents"] == 82423
    assert (
        fx.read_branch(api, world["branch"]["id"])["buyback_liability_usd_cents"] == 101999
    )

    cancelled = fx.cancel_contract(
        api, contract_b["id"], "customer changed travel plans", manager_headers
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["remaining_fx_minor_units"] == 0
    assert cancelled["liability_usd_cents"] == 0

    after = fx.read_branch(api, world["branch"]["id"])
    assert after["buyback_liability_usd_cents"] == before["buyback_liability_usd_cents"]
    assert after["buyback_liability_usd_cents"] == 19576


def test_the_unrelated_contract_and_the_origin_deal_survive_the_cancellation(
    api, teller_headers, manager_headers
):
    """Contract A keeps its 970600-micro lock, its 19000 minor units and its 19576-cent
    liability throughout B's lifecycle, and B's cancellation clears
    buyback_contract_id on its own origin transaction so that deal is reversible again.

    Design: Difficulty/compensating_invariant/buyback_issue_then_cancel_restores_branch_liability
    """
    world = _two_contract_world(api, teller_headers)
    contract_a = fx.read_contract(api, world["contract_a"]["id"])
    assert contract_a["fee_usd_cents"] == 649
    assert contract_a["locked_buy_rate_micros"] == 970600
    assert contract_a["locked_fx_minor_units"] == 19000
    assert contract_a["liability_usd_cents"] == 19576

    contract_b = fx.issue_contract(
        api, world["second_customer"]["id"], world["second_txn"]["id"], headers=teller_headers
    )
    assert (
        fx.read_transaction(api, world["second_txn"]["id"])["buyback_contract_id"]
        == contract_b["id"]
    )

    fx.cancel_contract(api, contract_b["id"], headers=manager_headers)

    assert fx.read_transaction(api, world["second_txn"]["id"])["buyback_contract_id"] is None
    still_issued = fx.read_contract(api, world["contract_a"]["id"])
    assert still_issued["status"] == "ISSUED"
    assert still_issued["liability_usd_cents"] == 19576


def _settled_sale_world(api, teller_headers):
    """A 270000-minor-unit EUR position with one 19000-unit sale settled against it."""
    world = fx.trading_world(
        api,
        vault_limit_usd_cents=20_000_000,
        position_mix=MIX,
        customer_overrides={"full_name": "Mina Farouk", "nationality_code": "EG"},
    )
    opening = fx.read_position(api, world["position"]["id"])
    assert opening["total_minor_units"] == 270000
    assert opening["usd_equivalent_cents"] == 293478

    txn = fx.settled_deal(api, world, denominations=DEAL, headers=teller_headers)
    after_settle = fx.read_position(api, world["position"]["id"])
    assert after_settle["total_minor_units"] == 251000
    assert after_settle["usd_equivalent_cents"] == 272826
    assert fx.read_branch(api, world["branch"]["id"])["vault_utilization_bps"] == 136

    world["transaction"] = txn
    world["opening"] = opening
    return world


def test_reversal_restores_the_per_denomination_note_inventory_and_the_vault(
    api, teller_headers, manager_headers
):
    """Reversing the sale puts back 1 x 10000, 1 x 5000 and 2 x 2000 notes: the mix
    counts return to 20, 10 and 10, the total returns to 270000 minor units worth
    293478 cents, and the branch is back at 293478 cents, 147 bps and OPEN.

    Design: Difficulty/compensating_invariant/settlement_then_reversal_restores_position_note_inventory
    """
    world = _settled_sale_world(api, teller_headers)

    reversed_txn = fx.reverse_deal(
        api,
        world["transaction"]["id"],
        manager_headers,
        "teller keyed the wrong denomination mix",
    )
    assert reversed_txn["settlement_status"] == "REVERSED"
    a.assert_timestamp_equals(reversed_txn["reversed_at"], "2026-08-01T00:00:00Z")

    position = fx.read_position(api, world["position"]["id"])
    a.assert_position_mix_invariants(position)
    a.assert_mix_counts(position, 10000, available=20)
    a.assert_mix_counts(position, 5000, available=10)
    a.assert_mix_counts(position, 2000, available=10)
    assert position["total_minor_units"] == world["opening"]["total_minor_units"]
    assert position["usd_equivalent_cents"] == world["opening"]["usd_equivalent_cents"]

    branch = fx.read_branch(api, world["branch"]["id"])
    a.assert_vault_state(branch, 293478, 147, "OPEN")


def test_reversal_also_walks_the_surveillance_aggregates_back_to_zero(
    api, teller_headers, manager_headers, compliance_headers
):
    """A reversed row contributes nothing to the settled population, so the customer's
    rolling total, score and tier fall back to 0, 0 and NORMAL after the reversal.

    Design: Difficulty/compensating_invariant/settlement_then_reversal_restores_position_note_inventory
    """
    world = _settled_sale_world(api, teller_headers)
    before = fx.read_customer(api, world["customer"]["id"], compliance_headers)
    assert before["rolling_30d_settled_usd_cents"] == 21626

    fx.reverse_deal(api, world["transaction"]["id"], manager_headers)

    after = fx.read_customer(api, world["customer"]["id"], compliance_headers)
    a.assert_customer(after)
    assert after["rolling_30d_settled_usd_cents"] == 0
    assert after["calendar_month_settled_usd_cents"] == 0
    assert after["near_threshold_txn_count"] == 0
    assert after["distinct_branch_count"] == 0
    assert after["structuring_risk_score"] == 0
    assert after["structuring_risk_tier"] == "NORMAL"
    assert (
        validate_success(
            api.get_exchange_transaction(world["transaction"]["id"], manager_headers)
        )["settlement_status"]
        == "REVERSED"
    )
