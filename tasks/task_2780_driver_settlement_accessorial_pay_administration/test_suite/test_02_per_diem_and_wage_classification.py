"""Per diem allocation and the wage-classification identity.

Per diem reclassifies money rather than creating it, so these tests pin both the
two allocation methods and the identity that must survive an approval and the
compensating void that undoes it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    CLERK_HEADERS,
    api_client,
    assert_wage_identity,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.constants import PER_DIEM_DAILY_CENTS
from test_helpers.types import (
    DriverType,
    LineType,
    MileageGuide,
    PayStatus,
    PerDiemMethod,
    SettlementStatus,
    VoidReasonCode,
)


def _per_diem_environment(per_diem_method, legal_name, package_name):
    """A leased-operator package on the given per diem method, an elected driver, one
    delivered load spanning two calendar dates, and a DRAFT settlement over the period."""
    package = fixtures.active_package(
        driver_type=DriverType.LEASED_OPERATOR,
        mileage_guide=MileageGuide.PRACTICAL,
        per_diem_method=per_diem_method,
        name=package_name,
    )
    driver = fixtures.active_driver(
        package["id"],
        driver_type=DriverType.LEASED_OPERATOR,
        per_diem_elected=True,
        legal_name=legal_name,
        home_state="TX",
    )
    load = fixtures.delivered_load(driver["id"], stop_count=1)
    fixtures.set_clock(fixtures.TS_SETTLE)
    settlement = fixtures.open_settlement(driver["id"])
    return {"package": package, "driver": driver, "load": load, "settlement": settlement}


class TestPerDiemMethodDecidesTheSplit:
    """The same gross splits differently under the two per diem methods."""

    def test_day_based_per_diem_is_a_daily_rate_over_the_days_out_count(self):
        """Two calendar dates on the road reclassify two days at 6,900 cents, leaving the
        remainder of the identical gross as taxable wages.

        PRD 3.7: "Under `DAY_BASED`, the gross per diem is `days_out_count` multiplied by
        6,900 cents per day, so the allocation scales with days on the road and is
        completely independent of how much the loads paid".
        PRD 3.7: "Finally, `taxable_wages_cents` is `gross_pay_cents` less
        `per_diem_non_taxable_cents`."

        Design: Difficulty/dual_variant_calc/per_diem_method_variant_day_based_vs_percent
        """
        env = _per_diem_environment(
            PerDiemMethod.DAY_BASED, "Dana Daybased", "Leased Day Per Diem"
        )

        prepared = validate_success(
            api_client.prepare_settlement(env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        assert prepared["gross_pay_cents"] == 46080
        assert prepared["days_out_count"] == 2
        assert prepared["per_diem_non_taxable_cents"] == 2 * PER_DIEM_DAILY_CENTS == 13800
        assert prepared["taxable_wages_cents"] == 32280
        assert prepared["per_diem_excess_taxable_cents"] == 0
        assert_wage_identity(prepared)

    def test_percent_of_linehaul_per_diem_is_a_share_of_the_linehaul_total(self):
        """On the identical load the percentage method reclassifies 2,800 basis points of
        the linehaul total instead, producing a different split of the same gross.

        PRD 3.7: "Under `PERCENT_OF_LINEHAUL`, `days_out_count` is still recorded on the
        statement but is not used in the amount; the gross per diem is instead
        `linehaul_total_cents` multiplied by 2,800 basis points, divided by 10,000 and
        rounded half up, so the identical set of loads produces a different
        `per_diem_non_taxable_cents`".

        Design: Difficulty/dual_variant_calc/per_diem_method_variant_day_based_vs_percent
        """
        env = _per_diem_environment(
            PerDiemMethod.PERCENT_OF_LINEHAUL, "Pat Percent", "Leased Percent Per Diem"
        )

        prepared = validate_success(
            api_client.prepare_settlement(env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        assert prepared["gross_pay_cents"] == 46080
        assert prepared["days_out_count"] == 2, (
            "days_out_count is still recorded under the percentage method"
        )
        assert prepared["per_diem_non_taxable_cents"] == 12902
        assert prepared["taxable_wages_cents"] == 33178
        assert prepared["per_diem_excess_taxable_cents"] == 0
        assert_wage_identity(prepared)

    def test_per_diem_reclassifies_without_changing_net_pay_under_either_method(self):
        """The per diem line is a reclassification, so net pay is the same 46080 under both
        methods even though the taxable split differs.

        PRD 3.7: "The `PER_DIEM` line is excluded both from gross and from the deduction
        total, because per diem is a reclassification rather than a payment."

        Design: Difficulty/dual_variant_calc/per_diem_method_variant_day_based_vs_percent
        """
        day_env = _per_diem_environment(
            PerDiemMethod.DAY_BASED, "Dana Daybased", "Leased Day Per Diem"
        )
        day_prepared = validate_success(
            api_client.prepare_settlement(day_env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        pct_env = _per_diem_environment(
            PerDiemMethod.PERCENT_OF_LINEHAUL, "Pat Percent", "Leased Percent Per Diem"
        )
        pct_prepared = validate_success(
            api_client.prepare_settlement(pct_env["settlement"]["id"], {}, CLERK_HEADERS)
        )

        assert day_prepared["net_pay_cents"] == 46080
        assert pct_prepared["net_pay_cents"] == 46080
        assert (
            day_prepared["per_diem_non_taxable_cents"]
            != pct_prepared["per_diem_non_taxable_cents"]
        ), "the two methods must reclassify different amounts"
        assert day_prepared["deduction_total_cents"] == 0
        assert pct_prepared["deduction_total_cents"] == 0

        day_lines = fixtures.read_settlement_lines(day_env["settlement"]["id"])
        per_diem_lines = [
            line for line in day_lines if line["line_type"] == LineType.PER_DIEM
        ]
        assert len(per_diem_lines) == 1
        assert per_diem_lines[0]["taxable"] is False
        assert per_diem_lines[0]["amount_cents"] == 13800


class TestWageClassificationIdentitySurvivesTheVoid:
    """Approval posts the reclassified wages to the driver; the void must take them back."""

    def _approved_environment(self):
        env = _per_diem_environment(
            PerDiemMethod.DAY_BASED, "Tess Taxable", "Leased Wage Identity"
        )
        fixtures.prepare(env["settlement"]["id"])
        fixtures.approve(env["settlement"]["id"])
        env["settlement"] = fixtures.read_settlement(env["settlement"]["id"])
        return env

    def test_approval_posts_the_reclassified_wages_to_the_year_to_date_accumulators(self):
        """After approval the three year-to-date accumulators carry the statement's gross,
        taxable wages and non-taxable per diem, and they reconcile to one another.

        PRD 3.8: "The driver's `ytd_gross_pay_cents`, `ytd_taxable_wages_cents` and
        `ytd_per_diem_non_taxable_cents` are recomputed, because this settlement now counts
        toward them."
        PRD 3.7: "Per diem never creates money: gross pay always equals taxable wages plus
        non-taxable per diem, and that identity is expected to hold on every statement the
        system produces."

        Design: Difficulty/compensating_invariant/wage_classification_identity_restored_on_void
        """
        env = self._approved_environment()
        settlement = env["settlement"]

        assert settlement["gross_pay_cents"] == 46080
        assert settlement["per_diem_non_taxable_cents"] == 13800
        assert settlement["taxable_wages_cents"] == 32280
        assert_wage_identity(settlement)

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["ytd_gross_pay_cents"] == 46080
        assert driver["ytd_taxable_wages_cents"] == 32280
        assert driver["ytd_per_diem_non_taxable_cents"] == 13800
        assert (
            driver["ytd_gross_pay_cents"]
            == driver["ytd_taxable_wages_cents"] + driver["ytd_per_diem_non_taxable_cents"]
        ), "the year-to-date accumulators must reconcile to the same identity"

    def test_voiding_an_approved_settlement_zeroes_all_three_accumulators(self):
        """The void recomputes the accumulators with the settlement excluded, so none of the
        reclassified per diem is left stranded on the driver.

        PRD 3.8: "and it recomputes `ytd_gross_pay_cents`, `ytd_taxable_wages_cents` and
        `ytd_per_diem_non_taxable_cents` with this settlement excluded."

        Design: Difficulty/compensating_invariant/wage_classification_identity_restored_on_void
        """
        env = self._approved_environment()

        voided = validate_success(
            api_client.void_settlement(
                env["settlement"]["id"],
                factories.void_payload(VoidReasonCode.CLERICAL_ERROR),
                ADMIN_HEADERS,
            )
        )

        assert voided["status"] == SettlementStatus.VOIDED
        assert voided["void_reason_code"] == VoidReasonCode.CLERICAL_ERROR

        driver = fixtures.read_driver(env["driver"]["id"])
        assert driver["ytd_gross_pay_cents"] == 0
        assert driver["ytd_taxable_wages_cents"] == 0
        assert driver["ytd_per_diem_non_taxable_cents"] == 0
        assert (
            driver["ytd_gross_pay_cents"]
            == driver["ytd_taxable_wages_cents"] + driver["ytd_per_diem_non_taxable_cents"]
        ), "the identity must still hold once the accumulators are back at zero"

    def test_voiding_releases_the_swept_load_back_onto_the_accrual_pile(self):
        """The load the voided statement had settled returns to ACCRUED with its settlement
        reference cleared, so it can be paid on a later statement.

        PRD 3.8: "returns every swept load on the pay axis `SETTLED` → `ACCRUED` with its
        `settlement_id` cleared to null, making it eligible for a later settlement again".

        Design: Difficulty/compensating_invariant/wage_classification_identity_restored_on_void
        """
        env = self._approved_environment()

        settled_load = fixtures.read_load(env["load"]["id"])
        assert settled_load["pay_status"] == PayStatus.SETTLED
        assert settled_load["settlement_id"] == env["settlement"]["id"]

        validate_success(
            api_client.void_settlement(
                env["settlement"]["id"],
                factories.void_payload(VoidReasonCode.CLERICAL_ERROR),
                ADMIN_HEADERS,
            )
        )

        released_load = fixtures.read_load(env["load"]["id"])
        assert released_load["pay_status"] == PayStatus.ACCRUED
        assert released_load["settlement_id"] is None

        voided = fixtures.read_settlement(env["settlement"]["id"])
        assert voided["line_count"] == 0
        assert voided["gross_pay_cents"] == 0
        assert voided["net_pay_cents"] == 0
