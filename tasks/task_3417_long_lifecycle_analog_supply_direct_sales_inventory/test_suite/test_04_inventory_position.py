"""Inventory position: trailing vs forward targets, posture thresholds, consistency."""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_inventory_position,
    get_inventory_position,
    make_active_design_win,
    make_capacity_pool,
    make_customer,
    make_part,
    record_receipt,
    validate_success,
    create_design_win_payload,
    create_reference_design_payload,
)

PLANNER = TEST_USERS["supply_planner_headers"]
FIELD = TEST_USERS["field_engineer_headers"]


class TestInventoryPosition:
    def test_buffer_target_trailing_vs_forward_pipeline(self, api):
        """PRD §3.1: "The trailing target, `target_trailing_units`, is
        `demand_rate_units_per_week` multiplied by `buffer_multiple` multiplied by 26
        weeks — the buffer horizon — with the result rounded up to the next whole unit."
        PRD §3.1: "`target_forward_units` is then the sum of
        `demand_rate_units_per_week` plus that weekly pipeline, multiplied by
        `buffer_multiple`, multiplied by 26 weeks, rounded up to the next whole unit."
        PRD §3.1: "`SHORTAGE` when coverage is below 0.75."

        Design: Difficulty/dual_variant_calc/buffer_target_trailing_vs_forward_pipeline
        """
        part = make_part(
            part_number="OPA2376AIDGKR",
            description="Precision op amp",
            package_family="VSSOP",
            process_technology="CMOS_180NM",
            demand_rate_units_per_week=40,
            buffer_multiple=1.5,
        )
        cust = make_customer(
            name="AutoMotive Controls GmbH", tier="STRATEGIC", channel="DIRECT_FIELD",
            credit_limit_cents=10_000_000,
        )
        make_active_design_win(part, cust, annual_volume_units=5200,
                               title="1kW motor drive reference")

        pos = validate_success(api.get_inventory_position(part["id"], PLANNER), 200)
        assert_inventory_position(pos)
        assert pos["target_trailing_units"] == 1560  # ceil(40 * 1.5 * 26)
        assert pos["target_forward_units"] == 3510  # ceil((40 + (5200/52)*0.5) * 1.5 * 26)
        assert pos["target_trailing_units"] != pos["target_forward_units"]
        assert pos["coverage_trailing"] == pytest.approx(0.0, abs=1e-9)
        assert pos["posture"] == "SHORTAGE"

    def test_forward_target_excludes_registered_design_wins(self, api):
        """PRD §3.1: "for every design win on this part whose status is `ACTIVE`
        (wins still `REGISTERED` or already `COMPLETED` are excluded), take the win's
        `annual_volume_units` divided by 52 and multiplied by the pipeline weight 0.5,
        and sum those contributions."

        Design: Difficulty/dual_variant_calc/buffer_target_trailing_vs_forward_pipeline
        """
        part = make_part(
            part_number="OPA2377AIDGKR",
            process_technology="CMOS_180NM",
            demand_rate_units_per_week=40,
            buffer_multiple=1.5,
        )
        cust = make_customer(name="Registered Only Co", credit_limit_cents=10_000_000)
        rd = validate_success(
            api.create_reference_design(
                create_reference_design_payload(
                    title="Draft pipeline", featured_part_number=part["part_number"]
                ),
                FIELD,
            ),
            201,
        )
        validate_success(api.publish_reference_design(rd["id"], FIELD), 200)
        win = validate_success(
            api.create_design_win(
                create_design_win_payload(rd["id"], cust["id"], part["id"]),
                FIELD,
            ),
            201,
        )
        assert win["status"] == "REGISTERED"  # never activated -> excluded

        pos = validate_success(api.get_inventory_position(part["id"], PLANNER), 200)
        assert pos["target_trailing_units"] == 1560
        assert pos["target_forward_units"] == 1560, (
            "REGISTERED wins are excluded from the forward pipeline"
        )

    def test_buffer_posture_threshold_boundaries(self, api):
        """PRD §3.1: "Posture follows from coverage with inclusive lower bounds:
        `NORMAL` when coverage is at least 1.0; `WATCH` when coverage is at least 0.75
        and below 1.0 — so a coverage of exactly 0.75 is `WATCH` and exactly 1.0 is
        `NORMAL`; and `SHORTAGE` when coverage is below 0.75."
        PRD §3.1: "`coverage_trailing` is `available_units` divided by
        `target_trailing_units`, carried to four decimal places with round-half-up".

        Design: Corner/calculations/buffer_posture_threshold_boundaries
        """
        part = make_part(
            part_number="LM339N",
            demand_rate_units_per_week=40,
            buffer_multiple=1.5,
        )
        pool = make_capacity_pool(
            site_name="DFAB", process_technology="ANALOG_BIPOLAR", total_units=5000
        )
        record_receipt(part["id"], pool["id"], 1170)

        pos_low = validate_success(api.get_inventory_position(part["id"], PLANNER), 200)
        assert pos_low["target_trailing_units"] == 1560
        assert pos_low["coverage_trailing"] == pytest.approx(0.75, abs=1e-9)
        assert pos_low["posture"] == "WATCH"

        record_receipt(part["id"], pool["id"], 390)
        pos_high = validate_success(api.get_inventory_position(part["id"], PLANNER), 200)
        assert pos_high["coverage_trailing"] == pytest.approx(1.0, abs=1e-9)
        assert pos_high["posture"] == "NORMAL"

    def test_patch_part_immediately_visible_in_inventory_position(self, api):
        """PRD §2.4: "The consistency model is immediate: every mutation — including
        any recomputed derived field and any cascaded side effect on a related
        resource — is visible in the response of the request that performed it and in
        any subsequent read."
        PRD §3.1: "Every such update recomputes the part's `posture` and increments
        the part's `version` by one."

        Design: Corner/endpoints/patch_part_immediately_visible_in_inventory_position
        """
        part = make_part(
            part_number="OPA37GP",
            demand_rate_units_per_week=40,
            buffer_multiple=1.5,
        )
        assert get_inventory_position(part["id"])["target_trailing_units"] == 1560

        patched = validate_success(
            api.patch_part(part["id"], {"demand_rate_units_per_week": 80}, PLANNER), 200
        )
        assert patched["demand_rate_units_per_week"] == 80
        assert patched["version"] == part["version"] + 1

        pos = validate_success(api.get_inventory_position(part["id"], PLANNER), 200)
        assert pos["target_trailing_units"] == 3120  # ceil(80 * 1.5 * 26)
