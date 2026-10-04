"""Placement accrual, mileage true-up, maintenance burden and the lessee ledger.

The per-diem meter, the mileage true-up and the maintenance split all read the
placement's own snapshotted terms rather than the contract's current ones, and
the lessee balance aggregates only the settled events. Each expected figure
below is recomputed from the PRD's stated formulas against the placement the
fixture actually builds.
"""

from test_helpers import (
    CLOCK_START_ISO,
    api_client,
    assert_lessee_outstanding_balance,
    create_assignment,
    create_return,
    get_success_data,
    set_clock,
    settle_return,
)

from test_calculations_support import (
    ADMIN,
    LEASE,
    commercial,
    flat_car_catalogue,
    held_cars,
)


def _placed_car(catalogue, pair, start_date, end_date, mileage_allowance):
    """Two HELD cars placed under ``pair``'s contract.

    The producing order is deliberately released with no contract and no
    ``lessee_id``, so the retained-order credit term of the lessee balance
    reconciliation cannot be attributed to ``pair``'s lessee under either
    reading of PRD 3.9.  The contract still governs the placement itself.
    """
    world = held_cars(
        catalogue,
        car_count=2,
        changeover_start="2026-09-02",
        completion_date="2026-09-04",
        required_delivery_date="2026-09-20",
    )
    world["assignment"] = create_assignment(
        world["car"],
        pair["contract"],
        pair["lessee"],
        start_date=start_date,
        end_date=end_date,
        mileage_allowance=mileage_allowance,
    )
    return world


def test_per_diem_accrual_deducts_the_utilization_credit(api):
    """PRD §3.6: "The number of days is that end minus the `start_date`, with the
    end date exclusive, and the gross accrual is those days multiplied by the
    placement's snapshotted `per_diem_rate_cents`. The utilization percentage is
    the placement's `mileage_used` divided by one hundred and floored to a whole
    number, so every full one hundred miles adds one point. The credit is the
    gross accrual multiplied by 12 and divided by 100, floored to a whole cent,
    but only when the lessee's `utilization_threshold_pct` is at or below the
    computed utilization percentage; otherwise the credit is exactly zero."
    PRD §3.6: "The placement's `per_diem_accrued_cents` is the gross accrual
    minus the credit."

    A thirty-day placement at 2000 cents per day with 6000 miles run accrues a
    gross of 60000, meets the lessee's 50-percent threshold at
    floor(6000 / 100) == 60, and deducts the 7200-cent credit to land on 52800.
    The same return's mileage true-up is a separate figure: one block of 5000
    included miles leaves 1000 overage miles at 12 cents.

    Design: Corner/calculations/assignment_per_diem_accrual_correct_result_utilization_credit_applied
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    pair = commercial("Perdiem Rail Co", credit_tier="B", utilization_threshold_pct=50)
    world = _placed_car(catalogue, pair, "2026-09-04", "2026-10-04", 5000)

    # The return is recorded on the day the placement closes, so the logical
    # clock has to have reached it; the restated accrual clips to the window
    # ending at the current clock date.
    set_clock("2026-10-04T00:00:00Z")
    car_return = create_return(
        world["car"],
        world["assignment"],
        return_date="2026-10-04",
        mileage_since_last=6000,
        condition_grade="A",
    )
    placement = get_success_data(
        api_client.get_car_assignment(world["assignment"]["id"], LEASE)
    )

    assert placement["status"] == "COMPLETED"
    assert placement["per_diem_rate_cents"] == 2000, (
        "the rate is the snapshot taken at placement time"
    )
    assert placement["per_diem_accrued_cents"] == 52800, (
        "60000 gross less the floor(60000 * 12 / 100) == 7200 credit"
    )
    assert car_return["mileage_overage_cents"] == 12000


def test_mileage_true_up_regrants_the_allowance_once_per_block(api):
    """PRD §3.7: "That figure is divided by thirty and rounded up to a whole
    number to give the number of allowance blocks; the included miles are those
    blocks multiplied by the placement's `mileage_allowance`. The overage miles
    are the placement's `mileage_used` minus the included miles, or zero when
    that difference is negative — an overage of exactly zero produces a charge of
    exactly zero."
    PRD §3.7: "The charge is the overage miles multiplied by the overage rate of
    12 cents per mile, and it is written to the return's `mileage_overage_cents`
    and to the placement's `mileage_charge_cents`."

    A sixty-day placement with a 1000-mile allowance re-grants the allowance
    once per thirty-day block, so ceil(60 / 30) == 2 blocks include 2000 miles
    and 2500 miles used leave 500 overage miles — 6000 cents, not the 18000 a
    single-grant reading would produce.

    Design: Corner/calculations/mileage_true_up_settlement_correct_result_two_block_proration
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    pair = commercial("Trueup Rail Co", credit_tier="B")
    world = _placed_car(catalogue, pair, "2026-09-04", "2026-11-03", 1000)

    car_return = create_return(
        world["car"],
        world["assignment"],
        return_date="2026-11-03",
        mileage_since_last=2500,
        condition_grade="A",
    )
    placement = get_success_data(
        api_client.get_car_assignment(world["assignment"]["id"], LEASE)
    )

    assert placement["mileage_allowance"] == 1000, (
        "the placement's own allowance, not the contract's rate"
    )
    assert car_return["mileage_overage_cents"] == 6000
    assert placement["mileage_charge_cents"] == 6000, (
        "the placement stores the same true-up the return records"
    )


def test_lessor_liable_return_attributes_the_whole_parts_bill(api):
    """PRD §3.7: "The parts cost for the return is read from the condition grade:
    grade `A` maps to 0 cents, grade `B` to 200,000 cents, grade `C` to 400,000
    cents and grade `D` to 600,000 cents, and that figure is written to the
    return's `maintenance_parts_cents`."
    PRD §3.7: "When the bearer is `LESSOR`, the lessor absorbs the entire parts
    cost and the lessee's share is zero."
    PRD §3.7: "The placement's `maintenance_cost_cents` stores the lessor's
    share"

    A grade-C return on a LESSOR-liable contract reads 400000 cents of parts and
    attributes the whole 400000 to the placement, while the mileage term stays at
    zero because 500 miles used sit inside the single block's 1000 included
    miles.

    Design: Corner/calculations/maintenance_burden_allocation_correct_result_lessor_absorbs_parts
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    pair = commercial("Burden Rail Co", credit_tier="B", liability_bearer="LESSOR")
    world = _placed_car(catalogue, pair, "2026-09-04", "2026-10-04", 1000)

    car_return = create_return(
        world["car"],
        world["assignment"],
        return_date="2026-10-04",
        mileage_since_last=500,
        condition_grade="C",
    )
    placement = get_success_data(
        api_client.get_car_assignment(world["assignment"]["id"], LEASE)
    )
    car = get_success_data(api_client.get_lease_fleet_car(world["car"]["id"], ADMIN))

    assert car_return["maintenance_parts_cents"] == 400000
    assert placement["maintenance_cost_cents"] == 400000, (
        "the LESSOR branch absorbs the whole bill and never evaluates the cap"
    )
    assert car_return["mileage_overage_cents"] == 0
    assert placement["status"] == "COMPLETED"
    assert car["status"] == "UNDER_REPAIR"


def test_only_settled_returns_move_the_lessee_balance(api):
    """PRD §3.7: "Until a return is settled, its mileage overage does not count
    toward the lessee's balance, because the reconciliation aggregates only
    settled returns."
    PRD §3.9: "A lessee's `outstanding_balance_cents` is the sum of the
    `mileage_overage_cents` of its returns whose `settlement_status` is
    `SETTLED`"

    A return born pending leaves the balance at zero; settling it moves exactly
    its 12000-cent mileage charge onto the ledger, and the component split shows
    the charge with no credit applied.

    Design: Corner/calculations/lessee_balance_reconciliation_correct_result_settled_charge
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    pair = commercial("Balance Rail Co", credit_tier="B")
    world = _placed_car(catalogue, pair, "2026-09-04", "2026-10-04", 1000)

    car_return = create_return(
        world["car"],
        world["assignment"],
        return_date="2026-10-04",
        mileage_since_last=2000,
        condition_grade="A",
    )
    assert car_return["settlement_status"] == "PENDING"
    assert car_return["mileage_overage_cents"] == 12000

    pending = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], ADMIN)
    )
    assert pending["outstanding_balance_cents"] == 0

    settled = settle_return(car_return["id"])
    assert settled["settlement_status"] == "SETTLED"

    balance = get_success_data(
        api_client.get_lessee_outstanding_balance(pair["lessee"]["id"], ADMIN)
    )
    assert_lessee_outstanding_balance(balance)
    assert balance["outstanding_balance_cents"] == 12000
    assert balance["settled_charges_cents"] == 12000
    assert balance["credits_applied_cents"] == 0


def test_utilization_credit_is_floored_not_rounded(api):
    """PRD §3.6: "The credit is the gross accrual multiplied by 12 and divided by
    100, floored to a whole cent"
    PRD §2.6: "Rounding half-up is never used: every rounding step in this system
    is either a ceiling to a whole unit or a floor to a whole unit."

    A five-day placement at the odd rate of 2001 cents per day has a gross of
    10005 and a credit of floor(10005 * 12 / 100) == floor(1200.6) == 1200, so
    the accrued figure is 8805; rounding would have produced 1201 and 8804. The
    utilization percentage is exactly 50 against a 50-percent threshold, which is
    the inclusive boundary at which the credit is granted.

    Design: Corner/calculations/assignment_per_diem_accrual_precision_floor_on_credit
    """
    set_clock(CLOCK_START_ISO)
    catalogue = flat_car_catalogue()
    pair = commercial(
        "Precision Rail Co",
        credit_tier="B",
        utilization_threshold_pct=50,
        per_diem_rate_cents=2001,
    )
    world = _placed_car(catalogue, pair, "2026-09-04", "2026-09-09", 1000)

    # The clock reaches the return date before the placement is closed.
    set_clock("2026-09-09T00:00:00Z")
    car_return = create_return(
        world["car"],
        world["assignment"],
        return_date="2026-09-09",
        mileage_since_last=5000,
        condition_grade="A",
    )
    placement = get_success_data(
        api_client.get_car_assignment(world["assignment"]["id"], LEASE)
    )

    assert placement["per_diem_accrued_cents"] == 8805, (
        "10005 gross less the floored 1200-cent credit"
    )
    assert placement["per_diem_accrued_cents"] == 5 * 2001 - 1200
    assert car_return["mileage_overage_cents"] == 48000, (
        "ceil(5 / 30) == 1 block includes 1000 miles, leaving 4000 * 12"
    )


def test_net_lease_shorter_than_the_placement_grants_the_allowance_once(api):
    """PRD §3.7: "This is the `monthly_prorated` basis, in which the allowance is
    re-granted for every thirty-day block."
    PRD §3.7: "One variant overrides the block treatment. When the governing
    contract is a `NET` lease whose term is shorter than the placement itself,
    the allowance is granted once for the whole term rather than per block: the
    included miles become the placement's `mileage_allowance` alone."

    Two identical sixty-day placements run the same 2500 miles against the same
    1000-mile allowance. The FULL_SERVICE contract's term outlasts the placement,
    so it re-grants per block and charges 6000 cents; the NET contract's
    thirty-day term is shorter than the placement, so the allowance is granted
    once and the charge is 18000 — a divergence of exactly the 1000 extra overage
    miles at 12 cents.

    Design: Corner/calculations/mileage_true_up_settlement_variant_divergence_block_vs_term_allowance
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
    block_pair = commercial(
        "Block Rail Co",
        lease_type="FULL_SERVICE",
        term_start_date="2026-09-01",
        term_end_date="2027-09-01",
    )
    trailing_pair = commercial(
        "Trailing Rail Co",
        lease_type="NET",
        term_start_date="2026-09-04",
        term_end_date="2026-10-04",
    )

    block_placement = create_assignment(
        world["cars"][0],
        block_pair["contract"],
        block_pair["lessee"],
        start_date="2026-09-04",
        end_date="2026-11-03",
        mileage_allowance=1000,
    )
    trailing_placement = create_assignment(
        world["cars"][1],
        trailing_pair["contract"],
        trailing_pair["lessee"],
        start_date="2026-09-04",
        end_date="2026-11-03",
        mileage_allowance=1000,
    )

    block_return = create_return(
        world["cars"][0],
        block_placement,
        return_date="2026-11-03",
        mileage_since_last=2500,
        condition_grade="A",
    )
    trailing_return = create_return(
        world["cars"][1],
        trailing_placement,
        return_date="2026-11-03",
        mileage_since_last=2500,
        condition_grade="A",
    )

    assert block_return["mileage_overage_cents"] == 6000, (
        "two thirty-day blocks include 2000 miles, leaving 500 overage miles"
    )
    assert trailing_return["mileage_overage_cents"] == 18000, (
        "a NET term shorter than the placement grants the allowance once"
    )
    assert (
        trailing_return["mileage_overage_cents"] - block_return["mileage_overage_cents"]
        == 12000
    )


def test_liability_bearer_selects_the_capped_lessor_share(api):
    """PRD §3.7: "When the bearer is `LESSEE`, the lessor's share is the parts
    cost multiplied by the smaller of the lessee parts share of 1 percent and
    its ceiling of 5 percent, divided by one hundred and floored to a whole cent,
    and the lessee absorbs the remainder — the total minus the lessor's share."
    PRD §3.7: "The placement's `maintenance_cost_cents` stores the lessor's
    share, so a `LESSOR`-liable return attributes the full cost to the placement
    and a `LESSEE`-liable return attributes only the capped sliver."

    Two grade-C returns carry the same 400000-cent parts bill; the LESSOR-liable
    placement stores all 400000 of it and the LESSEE-liable one stores
    floor(400000 * min(1, 5) / 100) == 4000, leaving 396000 to the lessee.

    Design: Corner/calculations/maintenance_burden_allocation_variant_divergence_lessor_vs_lessee
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
    lessor_pair = commercial("Lessor Liable Rail Co", liability_bearer="LESSOR")
    lessee_pair = commercial("Lessee Liable Rail Co", liability_bearer="LESSEE")

    lessor_placement = create_assignment(
        world["cars"][0],
        lessor_pair["contract"],
        lessor_pair["lessee"],
        start_date="2026-09-04",
        end_date="2026-10-04",
        mileage_allowance=1000,
    )
    lessee_placement = create_assignment(
        world["cars"][1],
        lessee_pair["contract"],
        lessee_pair["lessee"],
        start_date="2026-09-04",
        end_date="2026-10-04",
        mileage_allowance=1000,
    )

    lessor_return = create_return(
        world["cars"][0],
        lessor_placement,
        return_date="2026-10-04",
        mileage_since_last=500,
        condition_grade="C",
    )
    lessee_return = create_return(
        world["cars"][1],
        lessee_placement,
        return_date="2026-10-04",
        mileage_since_last=500,
        condition_grade="C",
    )

    lessor_read = get_success_data(
        api_client.get_car_assignment(lessor_placement["id"], LEASE)
    )
    lessee_read = get_success_data(
        api_client.get_car_assignment(lessee_placement["id"], LEASE)
    )

    assert lessor_return["maintenance_parts_cents"] == 400000
    assert lessee_return["maintenance_parts_cents"] == 400000
    assert lessor_read["maintenance_cost_cents"] == 400000
    assert lessee_read["maintenance_cost_cents"] == 4000, (
        "one percent of the bill, under the five-percent ceiling"
    )
    assert 400000 - lessee_read["maintenance_cost_cents"] == 396000, (
        "the lessee absorbs the remainder by subtraction"
    )
