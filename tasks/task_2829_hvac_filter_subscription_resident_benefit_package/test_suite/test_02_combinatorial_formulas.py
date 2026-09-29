"""
The two combinatorial formulas: the monthly fee assembled from three
independently rounded annual components, and the cancellation settlement whose
relief tier is keyed on the gross credit rather than on the net.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import OPERATOR


class TestMonthlyFeeComponentRounding:
    """monthly_fee_cents is a sum of roundings, never a rounding of a sum."""

    def test_monthly_fee_adds_three_independently_rounded_components(self, api):
        """
        The canonical enrolment prices at 3546 cents, which is 745 + 201 + 2600 —
        each annual component divided by twelve and rounded on its own. Rounding
        the summed annual figure once instead yields 3545, so the two orders are
        observably different and only the first is correct.

        PRD §3.3: "Now divide each of the three annual components by twelve and round each quotient half up to whole cents **separately** — three independent roundings — and add the three rounded monthly figures with plain integer addition."

        Design: Difficulty/combinatorial_formula/monthly_fee_nested_rounding_per_component_not_on_the_sum
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        sku = fx.create_sku(api)
        prop = fx.create_property(api)
        unit = fx.create_unit(api, prop["id"])
        fx.activate_property(api, prop["id"])
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")

        created = validate_success(
            api.create_subscription(
                f.subscription_payload(resident["id"], unit["id"]), OPERATOR
            ),
            201,
        )

        # The inputs the three components are built from.
        assert created["assigned_sku_id"] == sku["id"]
        assert created["ship_cadence_days"] == 75
        assert created["filters_per_shipment"] == 2
        assert created["entitled_benefit_codes"] == [
            "AIR_QUALITY_GUARANTEE",
            "CREDIT_REPORTING",
            "DAMAGE_WAIVER",
            "RENTERS_INSURANCE",
        ]

        # 745 (filters) + 201 (logistics) + 2600 (benefits) = 3546.
        a.assert_cents(created["monthly_fee_cents"], 3546, "monthly_fee_cents")
        assert created["monthly_fee_cents"] != 3545, (
            "3545 is the single-rounding answer and must not be returned"
        )
        assert created["status"] == "PENDING_SETUP"
        assert created["version"] == 1

    def test_component_rounding_still_decides_the_fee_for_a_thinner_benefit_bundle(self, api):
        """
        A BASIC property with both riders switched off entitles CREDIT_REPORTING
        alone, so the benefit component becomes an exact 300 and the fee is
        745 + 201 + 300 = 1246; rounding the summed annual figure once would give
        1245 instead.

        PRD §3.3: "Summing the three annual components first and rounding once at the end is a different number for most inputs and is not what this system computes."

        Design: Difficulty/combinatorial_formula/monthly_fee_nested_rounding_per_component_not_on_the_sum
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.create_sku(api)
        prop = fx.create_property(
            api,
            benefit_tier="BASIC",
            damage_waiver_enabled=False,
            aqg_enabled=False,
        )
        unit = fx.create_unit(api, prop["id"])
        fx.activate_property(api, prop["id"])
        resident = fx.create_resident(api)
        fx.set_clock(api, "2026-08-05T00:00:00Z")

        created = validate_success(
            api.create_subscription(
                f.subscription_payload(resident["id"], unit["id"]), OPERATOR
            ),
            201,
        )

        assert created["entitled_benefit_codes"] == ["CREDIT_REPORTING"]
        assert created["ship_cadence_days"] == 75
        assert created["filters_per_shipment"] == 2
        a.assert_cents(created["monthly_fee_cents"], 1246, "monthly_fee_cents")
        assert created["monthly_fee_cents"] != 1245, (
            "1245 is the single-rounding answer and must not be returned"
        )


def _exposed_env(api):
    """
    Fixture A carrying two exposed shipments: shipment 1 DELIVERED and a
    cadence-adjacent shipment 2 SHIPPED, with the clock at 2026-09-01.
    """
    env = fx.build_base_env(api)
    fx.deliver_first_shipment(api, env.subscription_id, "2026-08-06T00:00:00Z")

    second = validate_success(
        api.create_shipment(
            env.subscription_id, f.shipment_payload("2026-10-19", 2), OPERATOR
        ),
        201,
    )
    validate_success(
        api.ship_shipment(second["id"], f.ship_payload("TRK-A-0002"), OPERATOR)
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    first = fx.first_shipment(api, env.subscription_id)
    return env, first, second


class TestCancellationSettlementTier:
    """The relief tier reads step one's gross credit, never step five's net."""

    def test_settlement_preview_tiers_on_the_gross_credit(self, api):
        """
        Previewing a 2026-09-11 cancellation exposes the whole waterfall: 10 used
        and 20 unused days, a gross credit of 2364, two exposed shipments worth
        2720 gross, the 0.25 tier that 2364 falls into, a relieved fee of 2040 and
        a net of 324 — not the -356 that keying the tier on the net would produce.

        PRD §3.9: "**Step three** picks the waiver-relief tier, and it is keyed **only** on step one's output."

        Design: Difficulty/combinatorial_formula/cancellation_settlement_tier_keyed_on_gross_credit_not_on_net
        """
        env, _first, _second = self._env(api)

        preview = validate_success(
            api.get_settlement(
                env.subscription_id, OPERATOR, {"effective_date": "2026-09-11"}
            )
        )
        assert preview["subscription_id"] == env.subscription_id
        assert preview["used_days"] == 10
        assert preview["unused_days"] == 20
        a.assert_cents(preview["gross_prorated_credit_cents"], 2364, "gross_prorated_credit_cents")
        assert preview["exposed_shipment_count"] == 2
        a.assert_cents(preview["unreturned_fee_gross_cents"], 2720, "unreturned_fee_gross_cents")
        a.assert_decimal_string(preview["waiver_credit_pct"], "0.25", "waiver_credit_pct")
        a.assert_cents(preview["unreturned_fee_net_cents"], 2040, "unreturned_fee_net_cents")
        a.assert_cents(preview["net_settlement_cents"], 324, "net_settlement_cents")
        assert preview["net_settlement_cents"] != -356, (
            "-356 is the answer produced by keying the tier on the net settlement"
        )

    def test_cancellation_books_the_relieved_fee_and_moves_the_shipments_afterwards(self, api):
        """
        Cancelling on the same date freezes the same five figures, posts a
        PRORATION_CREDIT of -2364 and an UNRETURNED_SHIPMENT_FEE of +2040 — the
        relieved figure, not the 2720 gross — recalls both exposed shipments and
        leaves the property owing 5264.

        PRD §3.9: "**Step four** relieves the fee: multiply `unreturned_fee_gross_cents` by one minus the relief percentage and round half up once to whole cents, giving `unreturned_fee_net_cents`."

        Design: Difficulty/combinatorial_formula/cancellation_settlement_tier_keyed_on_gross_credit_not_on_net
        """
        env, first, second = self._env(api)

        cancelled = validate_success(
            api.cancel_subscription(
                env.subscription_id,
                f.cancel_payload("2026-09-11", "RESIDENT_MOVE_OUT"),
                OPERATOR,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        a.assert_cents(cancelled["gross_prorated_credit_cents"], 2364, "frozen gross credit")
        a.assert_cents(cancelled["unreturned_fee_gross_cents"], 2720, "frozen gross fee")
        a.assert_cents(cancelled["unreturned_fee_net_cents"], 2040, "frozen net fee")
        a.assert_cents(cancelled["net_settlement_cents"], 324, "frozen net settlement")

        rows = fx.read_ledger(api, env.subscription_id)
        credits = a.find_ledger_rows(rows, "PRORATION_CREDIT")
        assert len(credits) == 1
        a.assert_ledger_row(
            credits[0], "PRORATION_CREDIT", -2364, "PROPERTY_MANAGER", env.subscription_id
        )
        fees = a.find_ledger_rows(rows, "UNRETURNED_SHIPMENT_FEE")
        assert len(fees) == 1
        a.assert_ledger_row(fees[0], "UNRETURNED_SHIPMENT_FEE", 2040, "PROPERTY_MANAGER")
        assert fees[0]["memo"] == "cancellation unreturned reconciliation"

        # The settlement was computed over the pre-cancellation statuses; only
        # afterwards were both shipments recalled.
        assert validate_success(api.get_shipment(first["id"], OPERATOR))["status"] == (
            "RETURN_REQUESTED"
        )
        assert validate_success(api.get_shipment(second["id"], OPERATOR))["status"] == (
            "RETURN_REQUESTED"
        )
        assert a.property_balance(api, env.property_id, OPERATOR) == 5264

    def _env(self, api):
        return _exposed_env(api)
