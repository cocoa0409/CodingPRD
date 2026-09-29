"""Balancing, imbalance penalties and cash-out: the conservation identity that
ties the physical book to the commercial one, the two settlement gates, the
shipper's reconciled exposure, the two settlement methods over one identical
ledger, the credit-suspension cascade onto a sibling contract, and the reversal
that conserves the money without conserving the schedule."""

from types import SimpleNamespace

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_CASH_OUT_PERIOD_SETTLED,
    ERR_NOTHING_TO_CASH_OUT,
)
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_error_envelope,
    assert_field_derived_block,
    assert_ledger_entry,
    assert_money,
    assert_ok,
    assert_ticket_charges,
    assert_volume,
    assert_whole_dth,
)
from test_helpers.constants import (
    CASH_OUT_DAILY_RATCHET,
    CASH_OUT_MONTHLY_AGGREGATE,
    CONTRACT_ACTIVE,
    CONTRACT_SUSPENDED,
    CREDIT_GOOD,
    CREDIT_SUSPENDED,
    DIRECTION_INJECTION,
    LEDGER_CASH_OUT,
    LEDGER_CASH_OUT_REVERSAL,
    LEDGER_CURTAILMENT_CREDIT,
    LEDGER_DAILY_IMBALANCE,
    NOMINATION_CONFIRMED,
    NOMINATION_CURTAILED,
    TICKET_CONFIRMED,
    TIER_4,
)
from test_helpers.fixtures import (
    add_sibling_contract,
    confirm_ticket,
    confirmed_nomination,
    create_active_contract,
    create_shipper,
    create_std_field,
    create_well,
    ledger_entries,
    moved_gas,
    open_ticket,
    read_contract,
    read_field,
    read_nomination,
    read_shipper,
    read_ticket,
    set_clock,
)
from test_helpers.test_users import SCHEDULING_COORDINATOR


def _cash_out(api, contract_id, period_start_date, period_end_date):
    """Settle a period, returning the raw response so the caller decides whether
    it is a success or a refusal."""
    return api.cash_out(
        contract_id,
        F.cash_out_payload(period_start_date, period_end_date),
        SCHEDULING_COORDINATOR,
    )


def _cash_out_reversal(api, contract_id, reason="Metering correction accepted by the shipper"):
    return api.cash_out_reversal(
        contract_id, F.cash_out_reversal_payload(reason), SCHEDULING_COORDINATOR
    )


def _two_method_world(api):
    """One reservoir, one shipper and two contracts that differ in nothing but
    `cash_out_method`, each carrying the identical three-day imbalance history.

    Gas days 2026-08-05, 06 and 07 are each nominated at 80,000 Dth and metered at
    67,655 / 70,135 / 83,210 Dth on both contracts, so both ledgers hold the same
    three `DAILY_IMBALANCE` rows: -12,345.000, -9,865.000 and +3,210.000.
    """
    field = create_std_field(api)
    well = create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000)
    shipper = create_shipper(api, penalty_threshold_usd=500000.00)
    monthly = create_active_contract(
        api, shipper["id"], field["id"],
        contract_code="CD-MONTHLY", cash_out_method=CASH_OUT_MONTHLY_AGGREGATE,
    )
    ratchet = create_active_contract(
        api, shipper["id"], field["id"],
        contract_code="CE-RATCHET", cash_out_method=CASH_OUT_DAILY_RATCHET,
    )
    history = [("2026-08-05", 67655), ("2026-08-06", 70135), ("2026-08-07", 83210)]
    for contract in (monthly, ratchet):
        for gas_day, metered in history:
            moved_gas(
                api, contract["id"], shipper["id"], field["id"], well["id"], metered,
                gas_day=gas_day, direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
            )
    return SimpleNamespace(
        field=field, well=well, shipper=shipper,
        monthly=monthly, ratchet=ratchet, history=history,
    )


def _suspension_cascade_world(api):
    """Two contracts of one shipper whose penalty threshold is only 50,000.00 USD.

    `CD-RATCHET` carries a single metered gas day (2026-08-05, 80,000 Dth confirmed
    against 67,655 Dth measured) whose cash-out will breach the threshold, while the
    sibling `CE-MONTHLY` carries an untouched confirmed nomination for 2026-08-25.
    """
    field = create_std_field(api)
    well = create_well(api, field["id"], well_name="AUR-1", rated_rate_dth_per_day=600000)
    shipper = create_shipper(api, penalty_threshold_usd=50000.00)
    ratchet = create_active_contract(
        api, shipper["id"], field["id"],
        contract_code="CD-RATCHET", cash_out_method=CASH_OUT_DAILY_RATCHET,
    )
    monthly = create_active_contract(
        api, shipper["id"], field["id"],
        contract_code="CE-MONTHLY", cash_out_method=CASH_OUT_MONTHLY_AGGREGATE,
    )
    moved = moved_gas(
        api, ratchet["id"], shipper["id"], field["id"], well["id"], 67655,
        gas_day="2026-08-05", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
    )
    exposed = confirmed_nomination(
        api, monthly["id"], shipper["id"],
        gas_day="2026-08-25", direction=DIRECTION_INJECTION, nominated_volume_dth=50000,
    )
    return SimpleNamespace(
        field=field, well=well, shipper=shipper,
        ratchet=ratchet, monthly=monthly, spared=moved, exposed=exposed,
    )


class TestConservationIdentity:
    """The physical and the commercial books are tied by one equality."""

    def test_working_gas_equals_the_opening_plus_balances_plus_retained_fuel(self, api, mini_world):
        """Two movements whose measured volumes straddle their confirmed volumes in
        opposite directions -- 76,000 against 80,000 and 84,000 against 80,000, the
        latter sitting exactly on the 5 percent overrun ceiling -- leave the reservoir
        holding 410,000 Dth, which is its 250,000 Dth opening plus the contract's
        158,080.000 Dth balance plus the 1,920.000 Dth of retained fuel, while the
        contract's signed imbalance nets to exactly zero over two non-zero rows.

        PRD §2.9: "a field's `working_gas_inventory_dth` always equals its
        `opening_working_gas_dth`, plus the sum of `inventory_balance_dth` across all
        contracts written against that field, plus the field's
        `retained_fuel_pool_dth`, minus the field's `fuel_gas_used_dth`."

        Design: Corner/calculations/field_inventory_equals_opening_plus_contract_balances_plus_retained_fuel
        """
        first = moved_gas(
            api, mini_world.contract_id, mini_world.shipper_id,
            mini_world.field_id, mini_world.well_id, 76000,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        second = moved_gas(
            api, mini_world.contract_id, mini_world.shipper_id,
            mini_world.field_id, mini_world.well_id, 84000,
            gas_day="2026-08-21", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )

        assert_ticket_charges(
            first.ticket, fuel_retention=912.000, net_volume=75088.000,
            commodity=3420.00, discount=0.00, fuel_charge=3146.40, total=6566.40,
        )
        assert_ticket_charges(
            second.ticket, fuel_retention=1008.000, net_volume=82992.000,
            commodity=3780.00, discount=0.00, fuel_charge=3477.60, total=7257.60,
        )

        field = read_field(api, mini_world.field_id)
        assert_field_derived_block(
            field, working_gas=410000.000, inventory_pct=82.00, pressure=1948,
            tier=TIER_4, withdrawal_rate=246000, injection_rate=54000,
        )
        assert_volume(field["retained_fuel_pool_dth"], 1920.000, "retained_fuel_pool_dth")
        assert_volume(field["fuel_gas_used_dth"], 0.000, "fuel_gas_used_dth")

        contract = read_contract(api, mini_world.contract_id)
        assert_volume(contract["inventory_balance_dth"], 158080.000, "inventory_balance_dth")
        assert_volume(contract["imbalance_dth"], 0.000, "imbalance_dth")

        identity = (
            field["opening_working_gas_dth"]
            + contract["inventory_balance_dth"]
            + field["retained_fuel_pool_dth"]
            - field["fuel_gas_used_dth"]
        )
        assert_volume(field["working_gas_inventory_dth"], identity, "working_gas_inventory_dth")

        rows, meta = validate_paginated(
            api.list_ledger_entries(mini_world.contract_id, SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert meta["total_count"] == 2, (
            f"Two confirms must append exactly two rows, got {meta['total_count']}"
        )
        assert_created_at_ascending(rows)
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=-4000.000, gas_day="2026-08-20",
        )
        assert_ledger_entry(
            rows[1], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=4000.000, gas_day="2026-08-21",
        )


class TestCashOutPeriodGates:
    """Two adjacent settlement gates fail for opposite reasons."""

    def test_a_settled_period_is_refused_apart_from_an_empty_one(self, api, mini_world):
        """A reversal attempted before anything has been settled and a September period
        that holds no daily rows are both refused as `ERR_NOTHING_TO_CASH_OUT`, while a
        period restarting inside the already-settled August is refused as
        `ERR_CASH_OUT_PERIOD_SETTLED` -- and once August is settled, September is still
        refused under the emptiness gate rather than the settled-date gate.

        PRD §2.11 rung 36: "**Settled period.** A cash-out's `period_start_date` is
        strictly after the contract's `cash_out_through_date` whenever that date is set
        — otherwise `ERR_CASH_OUT_PERIOD_SETTLED` (409)." Rung 37: "**Something to
        settle.** A cash-out requires at least one `DAILY_IMBALANCE` ledger entry in the
        requested period, and a cash-out reversal requires an unreversed `CASH_OUT`
        entry to exist — otherwise `ERR_NOTHING_TO_CASH_OUT` (422)."

        Design: Corner/validations/cash_out_requires_unsettled_days_and_refuses_an_overlapping_period
        """
        moved_gas(
            api, mini_world.contract_id, mini_world.shipper_id,
            mini_world.field_id, mini_world.well_id, 76000,
            gas_day="2026-08-20", direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
        )
        contract_id = mini_world.contract_id
        assert_volume(read_contract(api, contract_id)["imbalance_dth"], -4000.000, "imbalance_dth")

        assert_error_envelope(
            _cash_out_reversal(api, contract_id, "Nothing has been settled yet"),
            ERR_NOTHING_TO_CASH_OUT,
        )
        assert_error_envelope(
            _cash_out(api, contract_id, "2026-09-01", "2026-09-30"),
            ERR_NOTHING_TO_CASH_OUT,
        )

        settled = assert_ok(_cash_out(api, contract_id, "2026-08-01", "2026-08-31"))
        assert_money(settled["cash_out_amount_usd"], 8280.00, "cash_out_amount_usd")
        assert settled["cash_out_through_date"] == "2026-08-31", (
            f"cash_out_through_date: expected 2026-08-31, got {settled['cash_out_through_date']}"
        )
        assert_volume(settled["imbalance_dth"], 0.000, "imbalance_dth")

        assert_error_envelope(
            _cash_out(api, contract_id, "2026-08-15", "2026-08-31"),
            ERR_CASH_OUT_PERIOD_SETTLED,
        )
        assert_error_envelope(
            _cash_out(api, contract_id, "2026-09-01", "2026-09-30"),
            ERR_NOTHING_TO_CASH_OUT,
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(contract_id, SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert meta["total_count"] == 2, (
            f"Only the daily row and one settlement row may exist, got {meta['total_count']}"
        )
        assert_created_at_ascending(rows)
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=-4000.000, gas_day="2026-08-20",
        )
        assert_ledger_entry(
            rows[1], entry_type=LEDGER_CASH_OUT, amount_usd=8280.00, gas_day=None
        )

        shipper = read_shipper(api, mini_world.shipper_id)
        assert_money(shipper["outstanding_penalty_usd"], 8280.00, "outstanding_penalty_usd")
        assert shipper["credit_status"] == CREDIT_GOOD, (
            f"8280.00 is far below the 500000.00 threshold, got {shipper['credit_status']}"
        )


class TestOutstandingPenaltyReconciliation:
    """The shipper's exposure is re-summed from the ledger, never patched."""

    def test_the_exposure_re_sums_across_two_contracts_and_one_reversal(self, api, mini_world):
        """Two sibling contracts of one shipper each settle 8,280.00 USD, so the
        shipper's exposure walks 0.00 -> 8,280.00 -> 16,560.00 and then back to exactly
        8,280.00 when the second assessment is negated by a new row rather than deleted:
        neither 0.00, which would over-reverse, nor 16,560.00, which would skip the
        reconciliation.

        PRD §2.9: "`outstanding_penalty_usd` on the shipper is the sum of `amount_usd`
        over every ledger entry whose `entry_type` is `CASH_OUT` or
        `CASH_OUT_REVERSAL`, taken across **all** contracts of that shipper and not
        merely the one being settled, rounded half up to 2 decimal places."

        Design: Corner/cross_cutting_complexity_layers/outstanding_penalty_usd_is_reconciled_across_two_cash_outs_and_one_reversal
        """
        first_contract = mini_world.contract
        second_contract = add_sibling_contract(api, mini_world, contract_code="CN-2")

        fresh = read_shipper(api, mini_world.shipper_id)
        assert_money(fresh["outstanding_penalty_usd"], 0.00, "outstanding_penalty_usd")
        assert fresh["credit_status"] == CREDIT_GOOD, (
            "A shipper with no ledger rows carries 0.00 exposure and GOOD credit, "
            f"got {fresh['credit_status']}"
        )

        booked = []
        for contract, gas_day in ((first_contract, "2026-08-02"), (second_contract, "2026-08-03")):
            booked.append(
                confirmed_nomination(
                    api, contract["id"], mini_world.shipper_id,
                    gas_day=gas_day, direction=DIRECTION_INJECTION, nominated_volume_dth=80000,
                )
            )
        set_clock(api, "2026-08-04T00:00:00Z")
        for nomination in booked:
            ticket = open_ticket(api, nomination["id"], mini_world.well_id, 84000)
            confirm_ticket(api, ticket["id"], mini_world.field_id)

        for contract in (first_contract, second_contract):
            assert_volume(
                read_contract(api, contract["id"])["imbalance_dth"], 4000.000, "imbalance_dth"
            )
        metered = read_shipper(api, mini_world.shipper_id)
        assert_money(metered["outstanding_penalty_usd"], 0.00, "outstanding_penalty_usd")
        assert metered["credit_status"] == CREDIT_GOOD

        settled_first = assert_ok(_cash_out(api, first_contract["id"], "2026-08-01", "2026-08-03"))
        assert_money(settled_first["cash_out_amount_usd"], 8280.00, "cash_out_amount_usd")
        assert settled_first["cash_out_through_date"] == "2026-08-03"
        assert_volume(settled_first["imbalance_dth"], 0.000, "imbalance_dth")
        after_first = read_shipper(api, mini_world.shipper_id)
        assert_money(after_first["outstanding_penalty_usd"], 8280.00, "outstanding_penalty_usd")
        assert after_first["credit_status"] == CREDIT_GOOD

        settled_second = assert_ok(_cash_out(api, second_contract["id"], "2026-08-01", "2026-08-03"))
        assert_money(settled_second["cash_out_amount_usd"], 8280.00, "cash_out_amount_usd")
        after_second = read_shipper(api, mini_world.shipper_id)
        assert_money(after_second["outstanding_penalty_usd"], 16560.00, "outstanding_penalty_usd")
        assert after_second["credit_status"] == CREDIT_GOOD

        reversed_contract = assert_ok(_cash_out_reversal(api, second_contract["id"]))
        assert_money(reversed_contract["cash_out_amount_usd"], 0.00, "cash_out_amount_usd")
        assert reversed_contract["cash_out_through_date"] is None, (
            "The reversal restores the through-date the contract held before the cash-out, "
            f"got {reversed_contract['cash_out_through_date']}"
        )
        assert_volume(reversed_contract["imbalance_dth"], 4000.000, "imbalance_dth")

        after_reversal = read_shipper(api, mini_world.shipper_id)
        assert_money(after_reversal["outstanding_penalty_usd"], 8280.00, "outstanding_penalty_usd")
        assert after_reversal["credit_status"] == CREDIT_GOOD
        assert_money(
            read_contract(api, first_contract["id"])["cash_out_amount_usd"],
            8280.00, "cash_out_amount_usd",
        )

        rows, meta = validate_paginated(
            api.list_ledger_entries(second_contract["id"], SCHEDULING_COORDINATOR, {"limit": 100})
        )
        assert meta["total_count"] == 3, (
            f"The reversal appends a row instead of deleting one, got {meta['total_count']}"
        )
        assert_created_at_ascending(rows)
        assert_ledger_entry(
            rows[0], entry_type=LEDGER_DAILY_IMBALANCE,
            volume_dth=4000.000, gas_day="2026-08-03",
        )
        assert_ledger_entry(rows[1], entry_type=LEDGER_CASH_OUT, amount_usd=8280.00, gas_day=None)
        assert_ledger_entry(
            rows[2], entry_type=LEDGER_CASH_OUT_REVERSAL, amount_usd=-8280.00, gas_day=None
        )

        for contract in (first_contract, second_contract):
            assert read_contract(api, contract["id"])["status"] == CONTRACT_ACTIVE, (
                "The suspension cascade never fired, so both contracts stay ACTIVE"
            )


class TestSettlementMethodDivergence:
    """`cash_out_method` is the only difference between the two contracts, and it
    is worth 42,693.76 USD on the identical three-day history."""

    def test_monthly_aggregate_nets_the_period_and_prices_it_once(self, api):
        """Both ledgers hold -12,345.000, -9,865.000 and +3,210.000, so both contracts
        sit at -19,000.000 before settlement. Netting first leaves 19,000.000 of
        deviation against a 240,000 Dth scheduled total, so the tolerance is 4,800.000,
        the billable volume is 14,200.000, the single percentage is 5.9167 -- the second
        band -- and the assessment is 14,200.000 x 3.4500 x 1.25 = 61,237.50, which the
        day-by-day method does not reproduce.

        PRD §3.7: "Under `MONTHLY_AGGREGATE`, the period is netted first and priced
        once. The scheduled total is the sum of the scheduled volumes across the
        period's gas days, and the net imbalance is the sum of the signed daily
        imbalances across those same days, so a day short and a day long cancel each
        other."

        Design: Difficulty/dual_variant_calc/cash_out_monthly_aggregate_vs_daily_ratchet_over_identical_imbalance_ledger
        """
        world = _two_method_world(api)
        expected_history = [
            ("2026-08-05", -12345.000),
            ("2026-08-06", -9865.000),
            ("2026-08-07", 3210.000),
        ]
        for contract in (world.monthly, world.ratchet):
            rows = ledger_entries(api, contract["id"], entry_type=LEDGER_DAILY_IMBALANCE)
            assert len(rows) == 3, f"Expected three daily rows, got {len(rows)}"
            for row, (gas_day, volume) in zip(rows, expected_history):
                assert_ledger_entry(
                    row, entry_type=LEDGER_DAILY_IMBALANCE, volume_dth=volume, gas_day=gas_day
                )
            assert_volume(
                read_contract(api, contract["id"])["imbalance_dth"], -19000.000, "imbalance_dth"
            )

        netted = assert_ok(_cash_out(api, world.monthly["id"], "2026-08-01", "2026-08-31"))
        assert_money(netted["cash_out_amount_usd"], 61237.50, "cash_out_amount_usd")
        ratcheted = assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))
        assert_money(ratcheted["cash_out_amount_usd"], 103931.26, "cash_out_amount_usd")
        assert netted["cash_out_amount_usd"] != ratcheted["cash_out_amount_usd"], (
            "The two methods must produce genuinely different totals from identical history"
        )

        settled_rows = ledger_entries(api, world.monthly["id"], entry_type=LEDGER_CASH_OUT)
        assert len(settled_rows) == 1, (
            f"Settlement appends exactly one CASH_OUT row, got {len(settled_rows)}"
        )
        assert_ledger_entry(
            settled_rows[0], entry_type=LEDGER_CASH_OUT, amount_usd=61237.50, gas_day=None
        )

    def test_the_daily_ratchet_rounds_every_day_before_it_sums(self, api):
        """Priced day by day, the same history bills each absolute deviation against its
        own tolerance and its own band -- 10,745.000 at 13.4313 percent, 8,265.000 at
        10.3313 percent and 1,610.000 at 2.0125 percent -- yielding 55,605.38 + 42,771.38
        + 5,554.50 = 103,931.26. Summing the unrounded daily products would give
        103,931.25, one cent low.

        PRD §3.7: "the day's amount is the day's billable volume multiplied by
        `index_price_usd_per_dth`, multiplied by the multiplier that day's own percentage
        selects, **rounded half up to 2 decimal places at that point**. The assessment is
        the sum of those already-rounded daily amounts, itself rounded half up to 2
        decimal places. Summing unrounded daily products and rounding once at the end is
        forbidden and yields a total that differs in cents."

        Design: Difficulty/dual_variant_calc/cash_out_monthly_aggregate_vs_daily_ratchet_over_identical_imbalance_ledger
        """
        world = _two_method_world(api)
        netted = assert_ok(_cash_out(api, world.monthly["id"], "2026-08-01", "2026-08-31"))
        ratcheted = assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))

        assert_money(ratcheted["cash_out_amount_usd"], 103931.26, "cash_out_amount_usd")
        assert_money(
            ratcheted["cash_out_amount_usd"], 55605.38 + 42771.38 + 5554.50, "cash_out_amount_usd"
        )
        assert ratcheted["cash_out_amount_usd"] != 103931.25, (
            "103931.25 is the forbidden sum-then-round order: each day must be rounded first"
        )
        settled_rows = ledger_entries(api, world.ratchet["id"], entry_type=LEDGER_CASH_OUT)
        assert len(settled_rows) == 1, (
            f"Settlement appends exactly one CASH_OUT row, got {len(settled_rows)}"
        )
        assert_ledger_entry(
            settled_rows[0], entry_type=LEDGER_CASH_OUT, amount_usd=103931.26, gas_day=None
        )

        for contract, amount in ((world.monthly, 61237.50), (world.ratchet, 103931.26)):
            reread = read_contract(api, contract["id"])
            assert_money(reread["cash_out_amount_usd"], amount, "cash_out_amount_usd")
            assert reread["cash_out_through_date"] == "2026-08-31", (
                f"cash_out_through_date: expected 2026-08-31, got {reread['cash_out_through_date']}"
            )
            assert_volume(reread["imbalance_dth"], 0.000, "imbalance_dth")
            assert reread["status"] == CONTRACT_ACTIVE, (
                f"165168.76 stays below the 500000.00 threshold, got {reread['status']}"
            )

        shipper = read_shipper(api, world.shipper["id"])
        assert_money(
            shipper["outstanding_penalty_usd"],
            netted["cash_out_amount_usd"] + ratcheted["cash_out_amount_usd"],
            "outstanding_penalty_usd",
        )
        assert_money(shipper["outstanding_penalty_usd"], 165168.76, "outstanding_penalty_usd")
        assert shipper["credit_status"] == CREDIT_GOOD, (
            f"165168.76 is below the 500000.00 threshold, got {shipper['credit_status']}"
        )


class TestCreditSuspensionCascade:
    """One contract's assessment suspends the shipper, which suspends the sibling
    contract, which curtails the sibling's nomination."""

    def test_the_assessment_suspends_every_contract_and_curtails_the_sibling(self, api):
        """The 55,605.38 USD priced from CD-RATCHET's own single gas day reaches the
        shipper's 50,000.00 threshold, so credit flips to SUSPENDED, both contracts move
        ACTIVE -> SUSPENDED, and the untouched 2026-08-25 nomination on CE-MONTHLY is
        curtailed to zero with a -50,000.000 credit -- a cascade that lands three levels
        away from the settled ledger.

        PRD §3.7: "When the recomputed exposure reaches the shipper's
        `penalty_threshold_usd`, `credit_status` becomes `SUSPENDED` and every `ACTIVE`
        contract of that shipper — not merely the one settled — moves from `ACTIVE` to
        `SUSPENDED`."

        Design: Difficulty/transitive_cascade/cash_out_credit_suspension_cascades_to_a_sibling_contract_nomination
        """
        world = _suspension_cascade_world(api)
        assert_volume(
            read_contract(api, world.ratchet["id"])["imbalance_dth"], -12345.000, "imbalance_dth"
        )

        settled = assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))
        assert_money(settled["cash_out_amount_usd"], 55605.38, "cash_out_amount_usd")
        assert settled["cash_out_through_date"] == "2026-08-31"
        settled_rows = ledger_entries(api, world.ratchet["id"], entry_type=LEDGER_CASH_OUT)
        assert len(settled_rows) == 1, f"Expected one CASH_OUT row, got {len(settled_rows)}"
        assert_ledger_entry(
            settled_rows[0], entry_type=LEDGER_CASH_OUT, amount_usd=55605.38, gas_day=None
        )

        shipper = read_shipper(api, world.shipper["id"])
        assert_money(shipper["outstanding_penalty_usd"], 55605.38, "outstanding_penalty_usd")
        assert shipper["credit_status"] == CREDIT_SUSPENDED, (
            "55605.38 reaches the 50000.00 threshold, and the boundary suspends: got "
            f"{shipper['credit_status']}"
        )
        for contract in (world.ratchet, world.monthly):
            assert read_contract(api, contract["id"])["status"] == CONTRACT_SUSPENDED, (
                "Every ACTIVE contract of the shipper must suspend, not merely the settled one"
            )

        swept = read_nomination(api, world.exposed["id"])
        assert swept["status"] == NOMINATION_CURTAILED, (
            f"The sibling's untouched nomination must be curtailed, got {swept['status']}"
        )
        assert swept["confirmed_volume_dth"] == 0, (
            f"confirmed_volume_dth: expected 0, got {swept['confirmed_volume_dth']}"
        )
        assert swept["curtailed_volume_dth"] == 50000, (
            f"curtailed_volume_dth: expected 50000, got {swept['curtailed_volume_dth']}"
        )
        credits = ledger_entries(api, world.monthly["id"], entry_type=LEDGER_CURTAILMENT_CREDIT)
        assert len(credits) == 1, f"Expected exactly one curtailment credit, got {len(credits)}"
        assert_ledger_entry(
            credits[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-50000.000, amount_usd=0.00, gas_day="2026-08-25",
        )
        assert_whole_dth(
            read_contract(api, world.monthly["id"])["scheduled_injection_dth"],
            0, "scheduled_injection_dth",
        )

    def test_the_nomination_that_already_moved_gas_is_spared(self, api):
        """CD-RATCHET's own 2026-08-05 nomination survives the sweep it paid for,
        because it carries a confirmed movement ticket: it stays CONFIRMED at 80,000 Dth,
        the contract keeps 80,000 Dth of scheduled injection, and no curtailment credit is
        written against it -- the last hop of the cascade excludes it selectively.

        PRD §2.8 phase A: "The candidate set is every nomination in `CONFIRMED` status,
        on a contract written against the field being re-postured (in the
        credit-suspension form, on any contract of the suspended shipper), whose
        `gas_day` is today or later and which has no confirmed movement ticket."

        Design: Difficulty/transitive_cascade/cash_out_credit_suspension_cascades_to_a_sibling_contract_nomination
        """
        world = _suspension_cascade_world(api)
        assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))

        spared = read_nomination(api, world.spared.nomination["id"])
        assert spared["status"] == NOMINATION_CONFIRMED, (
            f"A nomination with a confirmed ticket is not a candidate, got {spared['status']}"
        )
        assert spared["confirmed_volume_dth"] == 80000, (
            f"confirmed_volume_dth: expected 80000, got {spared['confirmed_volume_dth']}"
        )
        assert spared["curtailed_volume_dth"] == 0, (
            f"curtailed_volume_dth: expected 0, got {spared['curtailed_volume_dth']}"
        )
        assert read_ticket(api, world.spared.ticket["id"])["status"] == TICKET_CONFIRMED

        settled_contract = read_contract(api, world.ratchet["id"])
        assert_whole_dth(
            settled_contract["scheduled_injection_dth"], 80000, "scheduled_injection_dth"
        )
        assert_volume(settled_contract["imbalance_dth"], 0.000, "imbalance_dth")
        assert not ledger_entries(
            api, world.ratchet["id"], entry_type=LEDGER_CURTAILMENT_CREDIT
        ), "The settled contract's own nomination earns no curtailment credit"

        field = read_field(api, world.field["id"])
        assert_volume(
            field["working_gas_inventory_dth"], 3067655.000, "working_gas_inventory_dth"
        )


class TestCashOutReversalConservesMoneyOnly:
    """The reversal is a deliberately partial compensation."""

    def test_the_money_is_conserved_and_both_contracts_return_to_active(self, api):
        """Reversing the 55,605.38 USD assessment writes a -55,605.38 row rather than
        editing the original, drives the shipper's exposure back to 0.00 and credit back
        to GOOD, returns both contracts to ACTIVE, clears `cash_out_amount_usd` and the
        through-date, and brings the settled gas day back into the unsettled position at
        -12,345.000.

        PRD §3.7: "It appends one `CASH_OUT_REVERSAL` ledger entry whose `amount_usd` is
        the negation of the cash-out amount, resets `cash_out_amount_usd` to 0.00,
        restores `cash_out_through_date` to the value it held before the cash-out, and
        recomputes `imbalance_dth` — which, because the reversal removes the settlement
        boundary, brings the previously settled daily entries back into the unsettled
        position."

        Design: Difficulty/compensating_invariant/cash_out_reversal_restores_credit_and_contract_status_without_restoring_the_schedule
        """
        world = _suspension_cascade_world(api)
        assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))

        restored = assert_ok(
            _cash_out_reversal(
                api, world.ratchet["id"], "Index price restated by the pipeline; assessment withdrawn."
            )
        )
        assert_money(restored["cash_out_amount_usd"], 0.00, "cash_out_amount_usd")
        assert restored["cash_out_through_date"] is None, (
            "The through-date returns to the null it held before the cash-out, got "
            f"{restored['cash_out_through_date']}"
        )
        assert_volume(restored["imbalance_dth"], -12345.000, "imbalance_dth")

        money_rows = [
            row for row in ledger_entries(api, world.ratchet["id"])
            if row["entry_type"] in (LEDGER_CASH_OUT, LEDGER_CASH_OUT_REVERSAL)
        ]
        assert len(money_rows) == 2, (
            f"The original row survives alongside its negation, got {len(money_rows)}"
        )
        assert_created_at_ascending(money_rows)
        assert_ledger_entry(
            money_rows[0], entry_type=LEDGER_CASH_OUT, amount_usd=55605.38, gas_day=None
        )
        assert_ledger_entry(
            money_rows[1], entry_type=LEDGER_CASH_OUT_REVERSAL, amount_usd=-55605.38, gas_day=None
        )

        shipper = read_shipper(api, world.shipper["id"])
        assert_money(shipper["outstanding_penalty_usd"], 0.00, "outstanding_penalty_usd")
        assert shipper["credit_status"] == CREDIT_GOOD, (
            f"0.00 is below the 50000.00 threshold, got {shipper['credit_status']}"
        )
        for contract in (world.ratchet, world.monthly):
            assert read_contract(api, contract["id"])["status"] == CONTRACT_ACTIVE, (
                "Credit returning to GOOD moves every SUSPENDED contract back to ACTIVE"
            )

    def test_the_curtailed_schedule_is_deliberately_not_restored(self, api):
        """The nomination the suspension swept away stays CURTAILED at zero and its
        -50,000.000 credit stays on the ledger, so the sibling's scheduled injection
        remains 0 even though its contract is ACTIVE again -- while the physical books
        never moved at all during either money operation.

        PRD §3.7: "Nominations that were curtailed or rejected by the suspension are
        **not** restored: only the money quantity is conserved through a reversal, never
        the schedule."

        Design: Difficulty/compensating_invariant/cash_out_reversal_restores_credit_and_contract_status_without_restoring_the_schedule
        """
        world = _suspension_cascade_world(api)
        assert_ok(_cash_out(api, world.ratchet["id"], "2026-08-01", "2026-08-31"))
        assert_ok(_cash_out_reversal(api, world.ratchet["id"], "Assessment withdrawn"))

        swept = read_nomination(api, world.exposed["id"])
        assert swept["status"] == NOMINATION_CURTAILED, (
            f"An implementation that undoes everything wrongly resurrects it, got {swept['status']}"
        )
        assert swept["confirmed_volume_dth"] == 0, (
            f"confirmed_volume_dth: expected 0, got {swept['confirmed_volume_dth']}"
        )
        assert swept["curtailed_volume_dth"] == 50000, (
            f"curtailed_volume_dth: expected 50000, got {swept['curtailed_volume_dth']}"
        )
        credits = ledger_entries(api, world.monthly["id"], entry_type=LEDGER_CURTAILMENT_CREDIT)
        assert len(credits) == 1, f"The curtailment credit remains, got {len(credits)} rows"
        assert_ledger_entry(
            credits[0], entry_type=LEDGER_CURTAILMENT_CREDIT,
            volume_dth=-50000.000, gas_day="2026-08-25",
        )
        assert_whole_dth(
            read_contract(api, world.monthly["id"])["scheduled_injection_dth"],
            0, "scheduled_injection_dth",
        )

        spared = read_nomination(api, world.spared.nomination["id"])
        assert spared["status"] == NOMINATION_CONFIRMED
        assert read_ticket(api, world.spared.ticket["id"])["status"] == TICKET_CONFIRMED
        field = read_field(api, world.field["id"])
        assert_volume(
            field["working_gas_inventory_dth"], 3067655.000, "working_gas_inventory_dth"
        )
        assert_volume(field["retained_fuel_pool_dth"], 811.860, "retained_fuel_pool_dth")
