"""Catalyst condition, the two activity readings and the approval floor.

A charge carries a plain calendar reading of its consumed life and a
severity-adjusted reading that also answers for poisoning. Only the adjusted
reading gates campaign approval, and only the adjusted reading moves when a
charge is regenerated.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_CATALYST_ACTIVITY_TOO_LOW
from test_helpers.assertions import (
    assert_hours,
    assert_integer,
    assert_mmbtu,
    assert_money,
    assert_pct,
    assert_status,
)
from test_helpers.test_users import (
    ENG_APPROVER,
    ENG_AUTHOR,
    ENGINEER,
    make_process_engineer_headers,
)


def _approver_headers():
    """A second engineer, distinct from the campaign's author."""
    return make_process_engineer_headers(ENG_APPROVER)


class TestActivityReadingsDivergeAfterRegeneration:
    def test_poisoning_drives_the_adjusted_reading_below_the_floor(self, api):
        """Revising the poisoning index spends the charge and derates the train.

        Design: Difficulty/dual_variant_calc/catalyst_calendar_vs_severity_adjusted_activity_diverge_after_regeneration
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1100.0,
            design_life_hours=40000.0,
            baseline_operating_hours=18000.0,
            poisoning_index=0.00,
        )
        charge, train = site["charge"], site["train"]

        assert_pct(charge["activity_pct"], 55.00, "charge.activity_pct")
        assert_pct(
            charge["calendar_activity_pct"], 55.00, "charge.calendar_activity_pct"
        )

        patched = validate_success(
            api.patch_catalyst_charge(charge["id"], 0.30, ENGINEER)
        )
        assert_pct(patched["activity_pct"], 48.93, "charge.activity_pct")
        assert_pct(
            patched["calendar_activity_pct"], 55.00, "charge.calendar_activity_pct"
        )
        assert_status(patched, "SPENT", label="charge")

        derated = validate_success(api.get_reformer_train(train["id"], ENGINEER))
        assert_status(derated, "DERATED", label="train")

    def test_regeneration_credits_the_adjusted_reading_only(self, api):
        """The recovery lifts the adjusted reading and leaves the calendar one.

        Design: Difficulty/dual_variant_calc/catalyst_calendar_vs_severity_adjusted_activity_diverge_after_regeneration
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1100.0,
            design_life_hours=40000.0,
            baseline_operating_hours=18000.0,
            poisoning_index=0.00,
        )
        charge = site["charge"]
        validate_success(api.patch_catalyst_charge(charge["id"], 0.30, ENGINEER))

        regenerated = validate_success(
            api.regenerate_catalyst_charge(charge["id"], ENGINEER)
        )

        assert_hours(
            regenerated["cumulative_operating_hours"],
            18000,
            "charge.cumulative_operating_hours",
        )
        assert_integer(
            regenerated["regeneration_count"], 1, "charge.regeneration_count"
        )
        assert_pct(
            regenerated["calendar_activity_pct"], 55.00, "charge.calendar_activity_pct"
        )
        assert_pct(regenerated["activity_pct"], 60.93, "charge.activity_pct")
        assert_pct(
            regenerated["activity_pct"] - regenerated["calendar_activity_pct"],
            5.93,
            "adjusted minus calendar",
        )

    def test_regeneration_returns_the_charge_and_its_train_to_service(self, api):
        """A recovered charge is ACTIVE again and its train falls back to IDLE.

        Design: Difficulty/dual_variant_calc/catalyst_calendar_vs_severity_adjusted_activity_diverge_after_regeneration
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=1100.0,
            design_life_hours=40000.0,
            baseline_operating_hours=18000.0,
            poisoning_index=0.00,
        )
        charge, train = site["charge"], site["train"]
        validate_success(api.patch_catalyst_charge(charge["id"], 0.30, ENGINEER))

        regenerated = validate_success(
            api.regenerate_catalyst_charge(charge["id"], ENGINEER)
        )
        assert_status(regenerated, "ACTIVE", label="charge")

        recovered = validate_success(api.get_reformer_train(train["id"], ENGINEER))
        assert_status(recovered, "IDLE", label="train")
        assert recovered["active_charge_id"] == charge["id"]


class TestApprovalFloorIsInclusive:
    def test_activity_exactly_at_the_floor_still_approves(self, api):
        """A charge sitting precisely on the minimum is good enough to approve.

        Design: Difficulty/boundary_precision_check/catalyst_activity_exactly_at_minimum_permits_run_approval
        """
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=700.0)
        charge = fx.install_charge(
            api,
            train["id"],
            design_life_hours=40000.0,
            baseline_operating_hours=18000.0,
            poisoning_index=0.00,
        )
        assert_pct(charge["activity_pct"], 55.00, "charge.activity_pct")

        run = fx.schedule_run(
            api,
            train["id"],
            author=ENG_AUTHOR,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )
        response = api.approve_production_run(run["id"], _approver_headers())
        approved = validate_success(response, 200)

        assert_status(approved, "APPROVED", label="run")
        assert_money(
            approved["provisional_unit_cost_usd_per_ton"],
            181.10,
            "run.provisional_unit_cost_usd_per_ton",
        )

    def test_activity_one_hundredth_below_the_floor_refuses_approval(self, api):
        """Four extra hours of consumed life put the reading out of reach.

        Design: Difficulty/boundary_precision_check/catalyst_activity_exactly_at_minimum_permits_run_approval
        """
        plant = fx.register_plant(api, spot_gas_index_usd_per_mmbtu=4.2000)
        train = fx.commission_train(api, plant["id"], rated_ammonia_tpd=700.0)
        charge = fx.install_charge(
            api,
            train["id"],
            design_life_hours=40000.0,
            baseline_operating_hours=18004.0,
            poisoning_index=0.00,
        )
        assert_pct(charge["activity_pct"], 54.99, "charge.activity_pct")

        run = fx.schedule_run(
            api,
            train["id"],
            author=ENG_AUTHOR,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )
        response = api.approve_production_run(run["id"], _approver_headers())
        validate_error(response, ERR_CATALYST_ACTIVITY_TOO_LOW, 409)

        blocked = validate_success(api.get_production_run(run["id"], ENGINEER))
        assert_status(blocked, "PLANNED", label="run")
        assert blocked["provisional_unit_cost_usd_per_ton"] is None


class TestApprovalReadsTheChargeOnTheSameTrain:
    def test_a_worn_charge_on_an_idle_train_still_refuses_approval(self, api):
        """The train is free but its charge is too far gone to be approved on.

        Design: Difficulty/cross_entity_state_dependency/run_approval_blocked_by_low_activity_charge_on_same_train
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=600.0,
            design_life_hours=40000.0,
            baseline_operating_hours=30000.0,
            poisoning_index=0.00,
        )
        run = fx.schedule_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )

        response = api.approve_production_run(run["id"], _approver_headers())
        validate_error(response, ERR_CATALYST_ACTIVITY_TOO_LOW, 409)

        blocked = validate_success(api.get_production_run(run["id"], ENGINEER))
        assert_status(blocked, "PLANNED", label="run")
        assert blocked["provisional_unit_cost_usd_per_ton"] is None

    def test_the_refused_approval_leaves_the_charge_and_train_as_they_were(self, api):
        """Reading the charge to refuse the approval does not condemn it.

        Design: Difficulty/cross_entity_state_dependency/run_approval_blocked_by_low_activity_charge_on_same_train
        """
        site = fx.commissioned_site(
            api,
            rated_ammonia_tpd=600.0,
            design_life_hours=40000.0,
            baseline_operating_hours=30000.0,
            poisoning_index=0.00,
        )
        run = fx.schedule_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )
        validate_error(
            api.approve_production_run(run["id"], _approver_headers()),
            ERR_CATALYST_ACTIVITY_TOO_LOW,
            409,
        )

        charge = validate_success(api.get_catalyst_charge(site["charge"]["id"], ENGINEER))
        assert_pct(charge["activity_pct"], 25.00, "charge.activity_pct")
        assert_pct(charge["calendar_activity_pct"], 25.00, "charge.calendar_activity_pct")
        assert_status(charge, "ACTIVE", label="charge")

        train = validate_success(api.get_reformer_train(site["train"]["id"], ENGINEER))
        assert_status(train, "IDLE", label="train")


class TestSettlementDeratesTheCatalystDownstream:
    def _worn_train_world(self, api):
        site = fx.commissioned_site(
            api,
            spot_gas_index_usd_per_mmbtu=4.2000,
            rated_ammonia_tpd=800.0,
            design_life_hours=40000.0,
            baseline_operating_hours=18000.0,
            poisoning_index=0.00,
        )
        first = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-09-01T00:00:00.000Z",
            window_end="2026-09-11T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )
        fx.set_clock(api, "2026-09-01T00:00:00Z")
        fx.start_run(api, first["id"], actor=ENG_AUTHOR)
        second = fx.approved_run(
            api,
            site["train"]["id"],
            author=ENG_AUTHOR,
            approver=ENG_APPROVER,
            window_start="2026-10-01T00:00:00.000Z",
            window_end="2026-10-10T00:00:00.000Z",
            target_ammonia_tons=100.000,
        )
        site["first"] = first
        site["second"] = second
        return site

    def test_settled_hours_push_both_readings_below_the_floor(self, api):
        """The 240 hours the campaign clocked spend the charge outright.

        Design: Difficulty/transitive_cascade/run_completion_derates_catalyst_and_reverts_unrelated_approved_run
        """
        world = self._worn_train_world(api)
        fx.complete_run(api, world["first"]["id"], 100.000, 240.0, actor=ENG_AUTHOR)

        charge = validate_success(api.get_catalyst_charge(world["charge"]["id"], ENGINEER))
        assert_hours(
            charge["cumulative_operating_hours"],
            18240,
            "charge.cumulative_operating_hours",
        )
        assert_pct(charge["calendar_activity_pct"], 54.40, "charge.calendar_activity_pct")
        assert_pct(charge["activity_pct"], 54.40, "charge.activity_pct")
        assert_status(charge, "SPENT", label="charge")

    def test_the_spent_charge_derates_its_train_and_is_unmounted(self, api):
        """A derated train no longer names an active charge.

        Design: Difficulty/transitive_cascade/run_completion_derates_catalyst_and_reverts_unrelated_approved_run
        """
        world = self._worn_train_world(api)
        settled = fx.complete_run(
            api, world["first"]["id"], 100.000, 240.0, actor=ENG_AUTHOR
        )

        assert_status(settled, "COMPLETED", label="run")
        assert_money(
            settled["final_unit_cost_usd_per_ton"],
            181.10,
            "run.final_unit_cost_usd_per_ton",
        )
        assert_mmbtu(settled["consumed_gas_mmbtu"], 0, "run.consumed_gas_mmbtu")

        train = validate_success(api.get_reformer_train(world["train"]["id"], ENGINEER))
        assert_status(train, "DERATED", label="train")
        assert train["active_charge_id"] is None

    def test_the_unrelated_approved_campaign_falls_back_to_planned(self, api):
        """A second approved campaign on the derated train loses its approval.

        Design: Difficulty/transitive_cascade/run_completion_derates_catalyst_and_reverts_unrelated_approved_run
        """
        world = self._worn_train_world(api)
        fx.complete_run(api, world["first"]["id"], 100.000, 240.0, actor=ENG_AUTHOR)

        collateral = validate_success(
            api.get_production_run(world["second"]["id"], ENGINEER)
        )
        assert_status(collateral, "PLANNED", label="collateral run")
        assert collateral["provisional_unit_cost_usd_per_ton"] is None
