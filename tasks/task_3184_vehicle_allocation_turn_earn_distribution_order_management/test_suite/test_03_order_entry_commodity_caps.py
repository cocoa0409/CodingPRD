"""Dealer order entry, commodity caps, and the accept/cancel pool invariant (PRD §3.6, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    config_with,
    create_accepted_order,
    create_scheduled_order,
    get_dealer_allocation,
    make_dealer_headers,
    setup_dealer_run,
    setup_restricted_line,
    submit_order,
    validate_error,
    validate_success,
)

SCHED = TEST_USERS["scheduler_headers"]


class TestCommodityCapEvaluationOrder:
    def test_first_feature_order_admitted_by_pre_accept_evaluation(self, api):
        """PRD §3.6: "The cap admits the order if and only if `F + 1` is at most `floor((A + 1) * install_rate_pct / 100)`, evaluated with the pre-accept values of `A` and `F`."

        Design: Difficulty/combinatorial_formula/commodity_cap_circular_evaluation_order
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        # Seed one plain order: A=1, F=0 before the feature order.
        plain = create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        assert plain["state"] == "ACCEPTED"
        # First feature order: F+1=1 <= floor((1+1)*50/100)=1 -> accepted.
        feature = create_accepted_order(
            dealer["id"], line["id"], run["id"], configuration=config_with([code])
        )
        assert feature["state"] == "ACCEPTED"

    def test_cap_violation_rejected_with_commodity_cap_exceeded(self, api):
        """PRD §3.6: "The cap admits the order if and only if `F + 1` is at most `floor((A + 1) * install_rate_pct / 100)`, evaluated with the pre-accept values of `A` and `F`. An `install_rate_pct` of 100 never binds; an `install_rate_pct` of 0 forbids any order carrying the feature. Failure is `ERR_COMMODITY_CAP_EXCEEDED`."

        Design: Difficulty/combinatorial_formula/commodity_cap_circular_evaluation_order
        """
        fx = setup_restricted_line(install_rate_pct=50, allow_partial_build=True, base_units=4)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([]))
        create_accepted_order(dealer["id"], line["id"], run["id"], configuration=config_with([code]))
        # Third order also carrying the feature: A=2, F=1 -> 1+1 <= floor(3*50/100)=1 is false.
        resp = submit_order(dealer["id"], line["id"], run["id"], configuration=config_with([code]))
        validate_error(resp, ApiErrorId.ERR_COMMODITY_CAP_EXCEEDED, 422)


class TestPartialBuildGate:
    def test_without_feature_rejected_when_partial_build_not_allowed(self, api):
        """PRD §3.7: "When the order carries a commodity that has an `ACTIVE` restriction on its line and the scheduler requests `WITHOUT_FEATURE`, the restriction must have `allow_partial_build` true; otherwise the build is rejected with `ERR_PARTIAL_BUILD_NOT_ALLOWED`."

        Design: Corner/validations/partial_build_without_allow_flag_rejected
        """
        fx = setup_restricted_line(install_rate_pct=100, allow_partial_build=False, base_units=3)
        dealer = fx["dealer"]
        line = fx["model_line"]
        run = fx["run"]
        code = fx["commodity"]["code"]
        order = create_scheduled_order(
            dealer["id"], line["id"], run["id"], configuration=config_with([code])
        )
        resp = api.build_order(order["id"], {"build_mode": "WITHOUT_FEATURE"}, SCHED)
        validate_error(resp, ApiErrorId.ERR_PARTIAL_BUILD_NOT_ALLOWED, 422)


class TestPoolConservation:
    def test_accept_then_cancel_restores_pool(self, api):
        """PRD §3.6: "From `ACCEPTED`, cancellation additionally releases the pool: the order's `consumed_units` becomes 0, the parent `DealerAllocation`'s `consumed_units` decrements by 1 (and `retail_consumed_units` decrements by 1 for a `RETAIL` order), the `DealerAllocation`'s `version` bumps by 1, and the dealer's `avg_inventory_units` is recomputed."

        Design: Difficulty/compensating_invariant/accept_cancel_pool_conservation
        """
        fx = setup_dealer_run(num_dealers=1, base_units=5)
        dealer = fx["dealers"][0]
        run = fx["run"]
        line = fx["model_line"]
        da_before = get_dealer_allocation(run["id"], dealer["id"])
        assert da_before["consumed_units"] == 0
        order = create_accepted_order(dealer["id"], line["id"], run["id"])
        da_mid = get_dealer_allocation(run["id"], dealer["id"])
        assert da_mid["consumed_units"] == 1
        cancelled = validate_success(
            api.cancel_order(order["id"], make_dealer_headers(dealer["id"]),
                             {"cancel_reason": "customer backed out"}),
            200,
        )
        assert cancelled["state"] == "CANCELLED"
        assert cancelled["consumed_units"] == 0
        da_after = get_dealer_allocation(run["id"], dealer["id"])
        assert da_after["consumed_units"] == 0
        assert da_after["final_units"] - da_after["consumed_units"] == da_before["final_units"]

    def test_retail_cancel_restores_retail_pool(self, api):
        """PRD §3.6: "From `ACCEPTED`, cancellation additionally releases the pool: the order's `consumed_units` becomes 0, the parent `DealerAllocation`'s `consumed_units` decrements by 1 (and `retail_consumed_units` decrements by 1 for a `RETAIL` order), the `DealerAllocation`'s `version` bumps by 1, and the dealer's `avg_inventory_units` is recomputed."

        Design: Difficulty/compensating_invariant/accept_cancel_pool_conservation
        """
        fx = setup_dealer_run(num_dealers=1, base_units=6, retail_priority_pct=50)
        dealer = fx["dealers"][0]
        run = fx["run"]
        line = fx["model_line"]
        order = create_accepted_order(
            dealer["id"], line["id"], run["id"], order_kind="RETAIL", customer_ref="CUST-1"
        )
        da_mid = get_dealer_allocation(run["id"], dealer["id"])
        assert da_mid["retail_consumed_units"] == 1
        validate_success(api.cancel_order(order["id"], make_dealer_headers(dealer["id"])), 200)
        da_after = get_dealer_allocation(run["id"], dealer["id"])
        assert da_after["consumed_units"] == 0
        assert da_after["retail_consumed_units"] == 0
