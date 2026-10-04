"""Secondary-market sale gain or loss against a daily-depreciated book value.

The book value is the car's acquisition cost less 2500 cents for every day since
its build date, and the gain or loss is the sale price less that book value less
whatever liability is written back. The two bases differ by exactly the
writeback liability on the same car at the same price.

Every expected figure below is recomputed from the PRD's stated formula.
"""

from test_helpers import (
    CLOCK_START_ISO,
    api_client,
    create_assignment,
    create_sale,
    get_success_data,
    set_clock,
    suspend_assignment,
)

from test_calculations_support import (
    ADMIN,
    LEASE,
    commercial,
    flat_car_catalogue,
    held_cars,
)


def test_sale_books_gain_against_the_depreciated_book_value(api):
    """PRD §3.9: "The car's age in days is the sale date minus the car's
    `built_date`. The book value is the car's `acquisition_cost_cents` minus that
    age multiplied by the daily depreciation of 2,500 cents. The sale's
    `gain_loss_cents` is the `sale_price_cents` minus that book value minus the
    sale's `writeback_liability_cents`"
    PRD §2.6: "The sale gain-or-loss computation applies no rounding step at all,
    because every operand is already an integer number of cents."

    A car acquired at 71000 cents and sold ten days later for 50000 cents books
    at 71000 - 10 * 2500 == 46000 and realizes 4000. The sale is provisional at
    creation, and the car leaves the live fleet.

    Design: Corner/calculations/sale_gain_loss_correct_result_depreciated_book_gain
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    assert world["cars"][0]["acquisition_cost_cents"] == 71000
    assert world["cars"][0]["built_date"] == "2026-09-04"

    sale = create_sale(
        world["cars"][0],
        sale_price_cents=50000,
        sale_date="2026-09-14",
        writeback_liability_cents=0,
    )
    car = get_success_data(
        api_client.get_lease_fleet_car(world["cars"][0]["id"], ADMIN)
    )

    assert sale["net_book_value_cents"] == 46000, (
        "71000 of acquisition cost less ten days at 2500 cents"
    )
    assert sale["gain_loss_cents"] == 4000
    assert sale["status"] == "PENDING_SETTLEMENT", (
        "no ledger gain is booked until the sale settles"
    )
    assert car["status"] == "SOLD"
    assert car["lease_contract_id"] is None


def test_net_basis_writeback_lowers_the_gain_by_exactly_that_liability(api):
    """PRD §3.9: "On a full-service sale the `writeback_liability_cents` is zero,
    so the gain or loss is simply the sale price minus the book value. On a
    net-lease sale the accrued lessee liability is written back and subtracted,
    so the gain or loss is strictly lower by exactly the writeback liability —
    the two bases diverge by precisely that amount on the same car at the same
    price."

    Two cars of the same order, both sold on the same day at the same 50000-cent
    price, book the same 46000. The sale with no writeback realizes 4000; the
    net-lease sale that writes back 5000 realizes -1000, and the 5000-cent gap is
    exactly the liability.

    Design: Corner/calculations/sale_gain_loss_variant_divergence_full_service_vs_net
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    pair = commercial(
        "Net Basis Rail Co",
        lease_type="NET",
        liability_bearer="LESSEE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
    )
    placement = create_assignment(
        world["cars"][1],
        pair["contract"],
        pair["lessee"],
        start_date="2026-09-04",
        end_date="2026-10-04",
        mileage_allowance=1000,
    )
    suspend_assignment(placement["id"], suspend_date="2026-09-05")
    assert get_success_data(
        api_client.get_lease_fleet_car(world["cars"][1]["id"], ADMIN)
    )["status"] == "HELD", "suspension pulls the car back to the free fleet"

    full_service = create_sale(
        world["cars"][0],
        sale_price_cents=50000,
        sale_date="2026-09-14",
        writeback_liability_cents=0,
    )
    net = create_sale(
        world["cars"][1],
        sale_price_cents=50000,
        sale_date="2026-09-14",
        writeback_liability_cents=5000,
        lease_contract_id=pair["contract"]["id"],
    )

    contract = get_success_data(
        api_client.get_lease_contract(pair["contract"]["id"], LEASE)
    )
    assert contract["lease_type"] == "NET"

    assert full_service["net_book_value_cents"] == 46000
    assert net["net_book_value_cents"] == 46000
    assert full_service["gain_loss_cents"] == 4000
    assert net["gain_loss_cents"] == -1000
    assert (
        full_service["gain_loss_cents"] - net["gain_loss_cents"]
        == net["writeback_liability_cents"]
        == 5000
    )
    assert full_service["status"] == "PENDING_SETTLEMENT"
    assert net["status"] == "PENDING_SETTLEMENT"
