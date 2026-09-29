"""Every derived figure is settled inside the request that moved the money."""

from test_helpers import (
    api_client,
    fixtures,
    validate_success,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
    rows_of_kind,
)
from test_helpers.factories import place_equipment_order_payload

CLOCK = "2026-08-01T00:00:00Z"


def test_the_placement_response_and_every_later_read_already_agree():
    """One placement settles the order, the tranche, the package and three pools.

    PRD 2.12: "Where a cascade writes ledger rows, the rollups on the owning package and
    the balances on the three funding units are recomputed as part of the same request, so
    a client that reads any of them immediately afterwards sees a fully settled picture.
    Consistency is immediate; there is no deferred or eventual reconciliation anywhere in
    this API."

    Design: Corner/consistency_model/corner_consistency_place_response_already_shows_the_ledger_movement
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    package_id = scenario["package_id"]
    tranche_id = scenario["tranche"]["equipment"]["id"]
    space = fixtures.create_lab_space(building_code="BIOL", room_number="14")
    order = fixtures.create_order(package_id, space["id"], quoted_cents=12_000_000,
                                  lead_time_days=45)

    placed = validate_success(
        api_client.place_equipment_order(
            order["id"],
            place_equipment_order_payload(fixtures.read_package(package_id)["version"]),
            fixtures.DEAN_OFFICE,
        )
    )
    assert placed["status"] == "ORDERED"
    assert_instant_equals(placed["placed_on"], CLOCK)
    assert_instant_equals(placed["expected_delivery_on"], "2026-09-15T00:00:00Z")
    assert placed["encumbered_cents"] == 12_000_000
    assert placed["disbursed_cents"] == 0

    assert_tranche_balances(fixtures.read_tranche(tranche_id), encumbered_cents=12_000_000,
                            available_balance_cents=8_000_000)

    package = fixtures.read_package(package_id)
    assert package["total_encumbered_cents"] == 12_000_000
    assert package["total_available_cents"] == 8_000_000
    assert_spend_down_ratio(package["spend_down_ratio"], 0.6)

    summary = fixtures.read_spend_summary(package_id)
    assert summary["total_encumbered_cents"] == 12_000_000
    assert summary["total_available_cents"] == 8_000_000
    assert summary["balance_identity_holds"] is True
    assert summary["dept_share_cents"] == 5_400_000
    assert summary["college_share_cents"] == 4_200_000
    assert summary["dean_share_cents"] == 2_400_000
    assert_spend_down_ratio(summary["spend_down_ratio"], 0.6)

    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         committed_cents=5_400_000, reserved_cents=9_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["college_id"]),
                         committed_cents=4_200_000, reserved_cents=7_000_000)
    assert_unit_balances(fixtures.read_unit(scenario["dean_office_id"]),
                         committed_cents=2_400_000, reserved_cents=4_000_000)
    assert fixtures.read_unit(scenario["department_id"])["available_pool_cents"] == 391_000_000

    rows = rows_of_kind(fixtures.read_ledger(package_id), "ENCUMBRANCE")
    assert len(rows) == 1
    assert rows[0]["amount_cents"] == 12_000_000
    assert rows[0]["source_kind"] == "EQUIPMENT_ORDER"
    assert rows[0]["source_id"] == order["id"]
    assert rows[0]["reverses_transaction_id"] is None
    assert rows[0]["tranche_id"] == tranche_id
