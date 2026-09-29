"""The two version guards, and the carryforward eligibility threshold."""

from test_helpers import (
    api_client,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_no_rows_of_kind,
    assert_row_amount_and_shares,
    assert_spend_down_ratio,
    assert_tranche_balances,
    assert_unit_balances,
    rows_of_kind,
)
from test_helpers.factories import (
    create_space_assignment_payload,
    place_equipment_order_payload,
)

CLOCK = "2026-08-01T00:00:00Z"
FY2027_END = "2027-07-01T00:00:00Z"


def test_a_space_version_invalidated_by_a_utility_upgrade_rejects_the_assignment():
    """The room's own state permits the proposal; only the captured version is stale.

    PRD 2.10: "POST /space-assignments must carry expected_space_version holding the
    client's last observed version of the LabSpace named by space_id. If that value does
    not equal the room's current version, the create is rejected with
    ERR_STALE_SPACE_VERSION (HTTP 412)."

    Design: Corner/complexity_layers/corner_cx_stale_space_version_on_assignment_create_is_rejected
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    space = fixtures.create_lab_space(building_code="BIOL", room_number="77")
    stale_version = space["version"]
    assert stale_version == 1

    upgraded = fixtures.upgrade_utilities(space["id"])
    fresh_version = upgraded["version"]
    assert fresh_version == 2
    assert upgraded["status"] == "AVAILABLE"
    assert upgraded["allocated_share_pct"] == 0

    def propose(expected_version):
        return api_client.create_space_assignment(
            create_space_assignment_payload(space["id"], scenario["faculty_id"],
                                            expected_version, share_pct=50),
            fixtures.DEAN_OFFICE,
        )

    validate_error(propose(stale_version), "ERR_STALE_SPACE_VERSION", expected_status=412)

    listed, meta = validate_paginated(
        api_client.list_space_assignments(fixtures.FACILITIES, {"space_id": space["id"]})
    )
    assert listed == []
    assert meta["total_count"] == 0

    rejected_room = fixtures.read_space(space["id"])
    assert rejected_room["allocated_share_pct"] == 0
    assert rejected_room["version"] == fresh_version

    accepted = validate_success(propose(fresh_version), expected_status=201)
    assert accepted["share_pct"] == 50
    assert fixtures.read_space(space["id"])["allocated_share_pct"] == 50


def test_replaying_one_package_version_across_two_placements_is_rejected():
    """The waterfall covers both orders, so only the guard stops the second one.

    PRD 2.10: "POST /equipment-orders/{id}/place must carry expected_package_version
    holding the client's last observed version of the StartupPackage that funds the order.
    If that value does not equal the package's current version, the placement is rejected
    with ERR_STALE_PACKAGE_VERSION (HTTP 412)."

    Design: Corner/complexity_layers/corner_cx_stale_package_version_on_second_order_place_is_rejected
    """
    scenario = fixtures.setup_mini_active(clock=CLOCK)
    package_id = scenario["package_id"]
    tranche_id = scenario["tranche"]["equipment"]["id"]
    space = fixtures.create_lab_space(building_code="BIOL", room_number="81")

    order_a = fixtures.create_order(package_id, space["id"], quoted_cents=6_000_000)
    order_b = fixtures.create_order(package_id, space["id"], quoted_cents=7_000_000)
    stale_version = fixtures.read_package(package_id)["version"]

    first = validate_success(
        api_client.place_equipment_order(
            order_a["id"], place_equipment_order_payload(stale_version), fixtures.DEAN_OFFICE
        )
    )
    assert first["status"] == "ORDERED"
    assert fixtures.read_package(package_id)["version"] == stale_version + 1

    rows = rows_of_kind(fixtures.read_ledger(package_id), "ENCUMBRANCE")
    assert len(rows) == 1
    assert_row_amount_and_shares(rows[0], 6_000_000, 2_700_000, 2_100_000, 1_200_000)

    validate_error(
        api_client.place_equipment_order(
            order_b["id"], place_equipment_order_payload(stale_version), fixtures.DEAN_OFFICE
        ),
        "ERR_STALE_PACKAGE_VERSION", expected_status=412,
    )

    unplaced = fixtures.read_order(order_b["id"])
    assert unplaced["status"] == "REQUESTED"
    assert unplaced["placed_on"] is None
    assert_tranche_balances(fixtures.read_tranche(tranche_id), encumbered_cents=6_000_000,
                            available_balance_cents=14_000_000)
    assert len(rows_of_kind(fixtures.read_ledger(package_id), "ENCUMBRANCE")) == 1

    fresh_version = fixtures.read_package(package_id)["version"]
    validate_success(
        api_client.place_equipment_order(
            order_b["id"], place_equipment_order_payload(fresh_version), fixtures.DEAN_OFFICE
        )
    )
    assert_tranche_balances(fixtures.read_tranche(tranche_id), encumbered_cents=13_000_000,
                            available_balance_cents=7_000_000)


TWO_YEAR_EQUIPMENT_SPECS = [
    {
        "key": "fy2027",
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": 25_000_000,
        "available_on": "2026-07-01T00:00:00Z",
        "expires_on": FY2027_END,
        "carryforward_policy": "FULL",
    },
    {
        "key": "fy2028",
        "category": "EQUIPMENT",
        "fiscal_year": 2028,
        "amount_cents": 15_000_000,
        "available_on": FY2027_END,
        "expires_on": "2028-07-01T00:00:00Z",
        "carryforward_policy": "NONE",
    },
]


def _forty_million_package_with_one_order(quoted_cents):
    """An ACTIVE two-year EQUIPMENT schedule with one order placed in FY2027."""
    scenario = fixtures.setup_active_package(
        tranche_specs=TWO_YEAR_EQUIPMENT_SPECS, clock=CLOCK,
        proposed_total_cents=40_000_000,
    )
    space = fixtures.create_lab_space(building_code="CHEM", room_number="505")
    fixtures.setup_placed_order(scenario["package_id"], space["id"],
                               quoted_cents=quoted_cents)
    return scenario


def test_a_ratio_one_ten_thousandth_below_the_floor_loses_the_whole_carryforward():
    """A FULL policy and a valid destination cannot rescue an ineligible package.

    PRD 3.9: "Carryforward is permitted only when that ratio is **at or above 0.5000** — a
    package that has committed or spent half of its total commitment has earned the right
    to roll money forward. At the boundary the ratio is eligible; 0.4999 is not."

    Design: Corner/complexity_layers/corner_cx_carryforward_eligibility_threshold_at_the_boundary
    """
    scenario = _forty_million_package_with_one_order(19_996_000)
    package_id = scenario["package_id"]
    source = scenario["tranche"]["fy2027"]
    destination = scenario["tranche"]["fy2028"]
    assert_spend_down_ratio(fixtures.read_package(package_id)["spend_down_ratio"], 0.4999)

    fixtures.set_clock(FY2027_END)
    fixtures.rollover_fiscal_year(package_id, 2027)

    ledger = fixtures.read_ledger(package_id)
    assert_no_rows_of_kind(ledger, "CARRYFORWARD_OUT")
    assert_no_rows_of_kind(ledger, "CARRYFORWARD_IN")

    assert_tranche_balances(fixtures.read_tranche(source["id"]), status="OBLIGATED",
                            encumbered_cents=19_996_000, available_balance_cents=0,
                            carried_out_cents=0, expired_cents=5_004_000)
    assert_tranche_balances(fixtures.read_tranche(destination["id"]), status="OPEN",
                            carried_in_cents=0, available_balance_cents=15_000_000)

    expiries = rows_of_kind(ledger, "EXPIRY")
    assert len(expiries) == 1
    assert_row_amount_and_shares(expiries[0], 5_004_000, 2_251_800, 1_751_400, 1_000_800)

    package = fixtures.read_package(package_id)
    assert package["total_committed_cents"] == 40_000_000
    assert package["total_expired_cents"] == 5_004_000
    assert package["total_available_cents"] == 15_000_000
    assert_spend_down_ratio(package["spend_down_ratio"], 0.4999)


def test_a_ratio_of_exactly_one_half_carries_the_whole_remaining_balance():
    """Four thousand cents more encumbrance flips the entire year-end outcome.

    PRD 3.9: "Carryforward is permitted only when that ratio is **at or above 0.5000** — a
    package that has committed or spent half of its total commitment has earned the right
    to roll money forward. At the boundary the ratio is eligible; 0.4999 is not."

    Design: Corner/complexity_layers/corner_cx_carryforward_eligibility_threshold_at_the_boundary
    """
    scenario = _forty_million_package_with_one_order(20_000_000)
    package_id = scenario["package_id"]
    source = scenario["tranche"]["fy2027"]
    destination = scenario["tranche"]["fy2028"]
    assert_spend_down_ratio(fixtures.read_package(package_id)["spend_down_ratio"], 0.5)

    fixtures.set_clock(FY2027_END)
    fixtures.rollover_fiscal_year(package_id, 2027)

    ledger = fixtures.read_ledger(package_id)
    assert_no_rows_of_kind(ledger, "EXPIRY")
    carried_out = rows_of_kind(ledger, "CARRYFORWARD_OUT")
    carried_in = rows_of_kind(ledger, "CARRYFORWARD_IN")
    assert len(carried_out) == 1
    assert len(carried_in) == 1
    assert carried_out[0]["amount_cents"] == 5_000_000
    assert carried_in[0]["amount_cents"] == 5_000_000

    assert_tranche_balances(fixtures.read_tranche(source["id"]), status="OBLIGATED",
                            encumbered_cents=20_000_000, available_balance_cents=0,
                            carried_out_cents=5_000_000, expired_cents=0)
    assert_tranche_balances(fixtures.read_tranche(destination["id"]), status="OPEN",
                            carried_in_cents=5_000_000,
                            available_balance_cents=20_000_000)

    package = fixtures.read_package(package_id)
    assert package["total_available_cents"] == 20_000_000
    assert package["total_expired_cents"] == 0
    # PRD 2.9 exposes total_carried_out_cents on the package's spend-summary read.
    assert fixtures.read_spend_summary(package_id)["total_carried_out_cents"] == 5_000_000
    assert_unit_balances(fixtures.read_unit(scenario["department_id"]),
                         reserved_cents=18_000_000, refunded_cents=0)


def test_the_eligibility_test_reads_the_rounded_ratio_not_the_exact_rational():
    """A ratio of 0.49995 is rendered 0.5000 at four places and is therefore eligible.

    PRD 3.4: "Finally, spend_down_ratio is total_disbursed_cents plus
    total_encumbered_cents, divided by total_committed_cents, rounded half up to four
    decimal places, and defined as 0.0 when total_committed_cents is 0."

    Design: Corner/complexity_layers/corner_cx_carryforward_eligibility_threshold_at_the_boundary
    """
    scenario = _forty_million_package_with_one_order(19_998_000)
    package_id = scenario["package_id"]
    assert_spend_down_ratio(fixtures.read_package(package_id)["spend_down_ratio"], 0.5)

    fixtures.set_clock(FY2027_END)
    fixtures.rollover_fiscal_year(package_id, 2027)

    ledger = fixtures.read_ledger(package_id)
    assert_no_rows_of_kind(ledger, "EXPIRY")
    assert len(rows_of_kind(ledger, "CARRYFORWARD_OUT")) == 1

    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["fy2027"]["id"]),
                            status="OBLIGATED", encumbered_cents=19_998_000,
                            available_balance_cents=0, carried_out_cents=5_002_000,
                            expired_cents=0)
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["fy2028"]["id"]),
                            status="OPEN", carried_in_cents=5_002_000,
                            available_balance_cents=20_002_000)
