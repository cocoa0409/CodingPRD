"""Task metering: trigger factors, latency bands, and the two overage figures."""
from test_helpers import (
    api_client, get_success_data,
    add_workflow, dispatch_run, setup_basic_scenario, setup_polling_charge,
)


class TestOveragesTwoFaces:
    def test_overage_base_variant_charges_current_epoch_at_closing_rate(self, api):
        """PRD §2.5: "The first is `overage_amount_cents`, the *base* figure returned
        when reading the account directly. It covers the current metering epoch only,
        and it charges every task that exceeded `task_allowance` at the
        `closer_cost_per_task_cents` rate — the CLOSING-step rate."

        Design: Difficulty/dual_variant_calc/dv_overage_base_vs_maximum_variant
        """
        scenario = setup_polling_charge(allowance=1, closer=1, opening=3, overage_enabled=True)
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        # 8 tasks charged, allowance 1 -> 7 beyond: 100 * 7 + 50 * 8
        assert account["tasks_used_current"] == 8
        assert account["overage_amount_cents"] == 1100

    def test_overage_maximum_variant_recharges_every_epoch_at_the_higher_rate(self, api):
        """PRD §2.5: "It covers **every** epoch — current and previous — and it
        re-charges every historical excess at the higher of the account's two step
        rates, that is, at whichever of `closer_cost_per_task_cents` or
        `opening_cost_per_task_cents` is larger."

        Design: Difficulty/dual_variant_calc/dv_overage_base_vs_maximum_variant
        """
        scenario = setup_polling_charge(allowance=1, closer=1, opening=3, overage_enabled=True)
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        usage = get_success_data(
            api_client.get_account_usage(scenario["account"]["id"], scenario["owner_headers"]))
        # 7 beyond at max(1, 3) = 3 dollars: 300 * 7 + 50 * 8
        assert usage["projected_overage_amount_cents"] == 2500
        assert usage["projected_overage_amount_cents"] != usage["overage_amount_cents"]


class TestTriggerFactors:
    def test_instant_webhook_action_charges_a_single_task(self, api):
        """PRD §2.6: "An `INSTANT_WEBHOOK` trigger contributes one quarter: four
        instant-webhook actions together consume a single task, and the fraction is
        never resolved until the whole product is rounded up at charge time."

        Design: Difficulty/dual_variant_calc/dv_metering_factor_polling_vs_instant_webhook
        """
        scenario = setup_basic_scenario(allowance=100, trigger_type="INSTANT_WEBHOOK")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 1

    def test_polling_action_charges_eight_tasks_while_instant_costs_one(self, api):
        """PRD §2.6: "the default polled workflow sits exactly on the 900-second band
        boundary and therefore carries both the 4× trigger factor and the 2× latency
        multiplier, so a single polled action at the default cadence charges eight
        whole tasks."

        Design: Difficulty/dual_variant_calc/dv_metering_factor_polling_vs_instant_webhook
        """
        scenario = setup_basic_scenario(allowance=100, trigger_type="POLLING")
        add_workflow(scenario, name="Instant", trigger_type="INSTANT_WEBHOOK")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        instant = [w for w in api_client.list_workflows(
            scenario["owner_headers"], params={"account_id": scenario["account"]["id"]}
        ).json()["data"] if w["trigger_type"] == "INSTANT_WEBHOOK"][0]
        dispatch_run(instant["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 9
        assert account["overage_tasks_used"] == 0

    def test_webhook_charge_uses_unit_metering_factor(self, api):
        """PRD §2.6: "A `WEBHOOK` trigger contributes 1." PRD §2.6: "a `WEBHOOK`
        workflow with 30".

        Design: Corner/calculations/cal_webhook_charge_uses_unit_metering_factor
        """
        scenario = setup_basic_scenario(allowance=10, trigger_type="WEBHOOK")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 1
        assert account["overage_tasks_used"] == 0


class TestChargeWholeTasks:
    def test_single_polled_action_charges_exactly_eight_whole_tasks(self, api):
        """PRD §2.6: "a single polled action at the default cadence charges eight
        whole tasks."

        Design: Difficulty/combinatorial_formula/cf_charge_task_nested_rounding_ceiling_order
        """
        scenario = setup_polling_charge(allowance=10)
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 8
        assert account["overage_tasks_used"] == 0
        assert account["overage_amount_cents"] == 0

    def test_each_polled_charge_adds_exactly_eight_whole_tasks(self, api):
        """PRD §2.6: "one polled action consumes four tasks." PRD §2.6: "so a single
        polled action at the default cadence charges eight whole tasks."

        Design: Difficulty/combinatorial_formula/cf_charge_task_nested_rounding_ceiling_order
        """
        scenario = setup_basic_scenario(allowance=100, trigger_type="POLLING")
        second = add_workflow(scenario, name="Second Polled")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        dispatch_run(second["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 16
        assert account["overage_tasks_used"] == 0


class TestOverageSplit:
    def test_overage_split_derived_from_post_increment_counter(self, api):
        """PRD §2.5: "it charges every task that exceeded `task_allowance`" PRD §2.5:
        "the count of whole tasks beyond the allowance after the charge, minus the
        count beyond the allowance before it."

        Design: Difficulty/combinatorial_formula/cf_charge_task_increment_then_overage_split_order
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=True, trigger_type="POLLING")
        second = add_workflow(scenario, name="Second Polled")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        dispatch_run(second["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 16
        assert account["overage_tasks_used"] == 15

    def test_two_full_charges_accumulate_sixteen_whole_tasks(self, api):
        """PRD §2.5: "Increments to `overage_amount_cents` during charging use the
        CLOSING rate expressed at the `USD_CENTS` scale of 100" PRD §2.5: "every whole
        task charged carries a fixed 50-cent retry surcharge."

        Design: Difficulty/combinatorial_formula/cf_charge_task_increment_then_overage_split_order
        """
        scenario = setup_basic_scenario(allowance=1, overage_enabled=True, trigger_type="POLLING")
        second = add_workflow(scenario, name="Second Polled")
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        dispatch_run(second["workflow"]["id"], scenario["owner"]["id"], charge="success")
        account = get_success_data(
            api_client.get_account(scenario["account"]["id"], scenario["owner_headers"]))
        assert account["tasks_used_current"] == 16
        # 15 tasks beyond the allowance at 100 cents + 50 cents on all 16 tasks
        assert account["overage_amount_cents"] == 2300


class TestUsageReport:
    def test_usage_report_matches_account_counters(self, api):
        """PRD §3.4: "the increment to `overage_tasks_used` by exactly those tasks
        that fall beyond the allowance on this charge, and the increment to
        `overage_amount_cents` — is specified in §2.5."

        Design: Corner/endpoints/ep_usage_report_matches_account_counters
        """
        scenario = setup_polling_charge(allowance=3)
        dispatch_run(scenario["workflow"]["id"], scenario["owner"]["id"], charge="success")
        usage = get_success_data(
            api_client.get_account_usage(scenario["account"]["id"], scenario["owner_headers"]))
        assert usage["tasks_used_current"] == 8
        assert usage["overage_tasks_used"] == 5
        # 5 tasks beyond the allowance at the 100-cent CLOSING rate, plus the 50-cent
        # surcharge on every whole task charged: 100*5 + 50*8
        assert usage["overage_amount_cents"] == 900