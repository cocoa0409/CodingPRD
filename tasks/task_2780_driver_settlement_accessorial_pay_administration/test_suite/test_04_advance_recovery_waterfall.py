"""The advance recovery waterfall and its self-referential cap.

The recovery ceiling is a share of net pay while net pay depends on the recovery,
so the evaluation order is what decides the answer.
"""

from test_helpers import (
    APPROVER_HEADERS,
    CLERK_HEADERS,
    api_client,
    assert_advance_principal_conserved,
    fixtures,
    validate_success,
)
from test_helpers.constants import ADVANCE_RECOVERY_CAP_BPS
from test_helpers.types import (
    AdvanceStatus,
    AdvanceType,
    DriverType,
    LineType,
    MileageGuide,
    PerDiemMethod,
)


def _waterfall_environment():
    """A leased operator with an escrow-bearing package, one 46080-cent load, a cash
    advance issued before a fuel card, and a DRAFT settlement over the period."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=PerDiemMethod.NONE,
        escrow_required=True,
        escrow_target_cents=250000,
        escrow_monthly_deduction_cents=40000,
        name="Leased Waterfall",
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=False,
        legal_name="Fay Fuelcard",
        home_state="TX",
    )
    cash = fixtures.issue_advance(
        driver["id"], 60000, AdvanceType.CASH_ADVANCE, installment_cents=25000
    )
    fuel = fixtures.issue_advance(
        driver["id"], 30000, AdvanceType.FUEL_CARD, installment_cents=30000
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    assert load["linehaul_pay_cents"] == 46080
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    return {
        "driver": driver,
        "cash": cash,
        "fuel": fuel,
        "load": load,
        "settlement": settlement,
    }


class TestRecoveryCapEvaluationOrder:
    """The pinned four-step order is the whole of the arithmetic."""

    def test_pool_is_a_quarter_of_the_provisional_net_before_recovery_is_subtracted(self):
        """The pool is a quarter of gross less escrow, which is 10599, and not a quarter of
        the final net nor a quarter of gross.

        PRD 3.6: "First, a provisional net is computed as the settlement's `gross_pay_cents`
        less its `escrow_deduction_cents`, with recovery deliberately excluded."
        PRD 3.6: "Second, the recovery pool is that provisional net multiplied by 2,500 basis
        points — one quarter — divided by 10,000 and rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        env = _waterfall_environment()

        prepared = validate_success(
            api_client.prepare_settlement(env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        assert prepared["gross_pay_cents"] == 46080
        assert prepared["escrow_deduction_cents"] == 3686
        provisional_net = prepared["gross_pay_cents"] - prepared["escrow_deduction_cents"]
        assert provisional_net == 42394
        assert prepared["advance_recovery_cents"] == 10599, (
            "the pool is 2500 bps of the provisional net, rounded half up"
        )
        assert prepared["advance_recovery_cents"] != 7949, (
            "reading the cap off the final net is wrong and yields a smaller recovery"
        )
        assert prepared["advance_recovery_cents"] != 11520, (
            "reading the cap off gross would ignore the escrow deduction"
        )
        # PRD 2.6: a basis-point division is "rounded **half up** to the nearest whole
        # cent", which integer (x * bps + 5000) // 10000 expresses exactly. Python's
        # round() is half-to-even and would answer 10598 on this exact half cent.
        assert (
            prepared["advance_recovery_cents"]
            == (provisional_net * ADVANCE_RECOVERY_CAP_BPS + 5000) // 10000
        )

    def test_net_pay_is_the_provisional_net_less_the_total_recovered(self):
        """Only after the waterfall has run is net pay computed, so the statement nets to
        31795 with a deduction total of 14285.

        PRD 3.6: "Fourth, and only then, `net_pay_cents` is the provisional net less the total
        recovered."

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        env = _waterfall_environment()

        prepared = validate_success(
            api_client.prepare_settlement(env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        assert prepared["deduction_total_cents"] == 14285
        assert prepared["net_pay_cents"] == 31795
        assert (
            prepared["net_pay_cents"]
            == prepared["gross_pay_cents"] - prepared["deduction_total_cents"]
        )

    def test_waterfall_exhausts_the_pool_on_cash_before_reaching_the_fuel_card(self):
        """Cash comes first in the fixed order, and it absorbs the whole pool, so the fuel
        card is skipped and keeps its full principal outstanding.

        PRD 3.6: "in a fixed order: first every `CASH_ADVANCE`, ordered by `created_at`
        ascending, then every `FUEL_CARD`, ordered by `created_at` ascending."
        PRD 3.6: "For each advance in turn, the amount taken is the least of three quantities:
        the advance's `installment_cents`, its `outstanding_cents`, and whatever remains in the
        pool."

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        env = _waterfall_environment()

        fixtures.prepare(env["settlement"]["id"])

        lines = fixtures.read_settlement_lines(env["settlement"]["id"])
        recovery_lines = [
            line for line in lines if line["line_type"] == LineType.ADVANCE_RECOVERY
        ]
        assert len(recovery_lines) == 1, "a skipped advance emits no line"
        assert recovery_lines[0]["reference_type"] == "ADVANCE"
        assert recovery_lines[0]["reference_id"] == env["cash"]["id"]
        assert recovery_lines[0]["amount_cents"] == 10599

        cash = fixtures.read_advance(env["cash"]["id"])
        fuel = fixtures.read_advance(env["fuel"]["id"])
        assert cash["recovered_cents"] == 10599
        assert cash["outstanding_cents"] == 49401
        assert fuel["recovered_cents"] == 0
        assert fuel["outstanding_cents"] == 30000
        assert_advance_principal_conserved(cash)
        assert_advance_principal_conserved(fuel)

    def test_approval_moves_the_partly_recovered_advance_to_recovering(self):
        """The status axis advances at approval: a partly recovered cash advance becomes
        RECOVERING while the untouched fuel card stays ISSUED.

        PRD 3.6: "an advance that was `ISSUED` and is only partly recovered — the allocated
        amount is greater than zero and less than its `outstanding_cents` — moves `ISSUED` →
        `RECOVERING`".
        PRD 3.6: "Whatever is not recovered stays in the advance's `outstanding_cents` and
        carries into the next settlement".

        Design: Difficulty/combinatorial_formula/advance_recovery_cap_evaluation_order
        """
        env = _waterfall_environment()
        fixtures.prepare(env["settlement"]["id"])

        validate_success(
            api_client.approve_settlement(env["settlement"]["id"], APPROVER_HEADERS)
        )

        cash = fixtures.read_advance(env["cash"]["id"])
        fuel = fixtures.read_advance(env["fuel"]["id"])
        assert cash["status"] == AdvanceStatus.RECOVERING
        assert fuel["status"] == AdvanceStatus.ISSUED

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["advance_outstanding_cents"] == 79401, (
            "the driver exposure is the sum of the two outstanding balances"
        )
        assert driver["escrow_balance_cents"] == 3686
