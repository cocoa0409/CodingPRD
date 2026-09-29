"""Endpoint behaviour: create-read-list agreement, action side effects, computed reads.

There is no update and no delete endpoint anywhere in this API, so the write
surface is a create, a set of named action sub-resources and one purely derived
progress read; each of those shapes is exercised end to end here.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import fixtures as X
from test_helpers.api_errors import ERR_HOLD_PERIOD_NOT_ELAPSED
from test_helpers.assertions import (
    assert_instant,
    assert_list_total,
    assert_money,
    assert_object_envelope,
    assert_plan_costs,
    assert_source_ledger,
    assert_steel_conservation,
    assert_summary_keys,
    assert_weight,
)
from test_helpers.constants import (
    ACTION_RENEW,
    ALLOCATION_ALLOCATED,
    BASE_EXAMINATION_PCT,
    CLOCK_BASE,
    COURSE_FITTED,
    PHASE_ERECTION_IN_PROGRESS,
    PHASE_HYDROTEST_PASSED,
    PLAN_FILL_HOLD,
    PLAN_PASSED,
    POSTURE_OPEN,
    PASS_DECISION,
    SOURCE_MUNICIPAL,
    SOURCE_RIVER,
    WELDER_LAPSED,
    WELDER_QUALIFIED,
    WITHDRAWAL_CONSUMED,
)
from test_helpers.factories import (
    allocation_payload,
    plan_completion_payload,
    qualification_action_payload,
    water_source_payload,
)
from test_helpers.test_users import AI1, AI2, CC1, ES1, PE1


class TestWaterSourceCreateReadList:
    def test_the_three_water_source_endpoints_agree_on_the_same_two_rows(self, api):
        """Create, read-one and read-many, with the collection narrowed by source_type.

        PRD: "A `ProjectEngineer` registers each permitted source under a `source_name` unique
        across every source in the system (a repeat being rejected with
        `ERR_DUPLICATE_IDENTIFIER`) and a `source_type` of `MUNICIPAL`, `RIVER`, `WELL` or
        `RECLAIMED`."

        PRD: "A new source starts with `reserved_volume_gal` and `consumed_volume_gal` at 0.0
        and `available_volume_gal` equal to `permitted_volume_gal`."

        PRD: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`)
        are included for list endpoints."

        Design: Corner/endpoints/water_source_create_then_read_then_list
        """
        first = assert_object_envelope(
            api.create_water_source(
                water_source_payload("Riverside Intake", source_type=SOURCE_RIVER), PE1
            ),
            201,
        )
        second = assert_object_envelope(
            api.create_water_source(
                water_source_payload(
                    "Municipal Hydrant 12",
                    source_type=SOURCE_MUNICIPAL,
                    permitted_volume_gal=500000.0,
                    max_concurrent_rate_gpm=250.0,
                    water_cost_usd_per_kgal=4.10,
                    disposal_cost_usd_per_kgal=2.55,
                    permit_expiry_utc="2027-01-31T00:00:00Z",
                ),
                PE1,
            ),
            201,
        )

        for source in (first, second):
            assert source["version"] == 1
            assert_money(
                source["available_volume_gal"],
                source["permitted_volume_gal"],
                "available equals permitted on create",
            )
            assert_money(source["reserved_volume_gal"], 0.00, "reserved volume")
            assert_money(source["consumed_volume_gal"], 0.00, "consumed volume")

        fetched = assert_object_envelope(api.get_water_source(second["id"], AI1), 200)
        assert fetched["id"] == second["id"]
        assert fetched["source_name"] == "Municipal Hydrant 12"
        assert fetched["source_type"] == SOURCE_MUNICIPAL
        assert_money(fetched["max_concurrent_rate_gpm"], 250.0, "max concurrent rate")
        assert_money(fetched["available_volume_gal"], 500000.00, "available volume")

        response = api.list_water_sources(AI1, {"source_type": SOURCE_RIVER})
        assert response.json()["response_type"] == "array"
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["source_type"] == SOURCE_RIVER

        assert_list_total(api.list_water_sources(AI1), 2)


class TestWelderQualificationAction:
    def test_a_renewal_restarts_the_window_and_leaves_the_test_date_alone(self, api):
        """The only path back from LAPSED, and its asymmetric side effects.

        PRD: "A welder who has been revoked stays `REVOKED`; otherwise, a welder whose
        `continuity_expires_at_utc` is strictly before the logical clock moves `QUALIFIED
        → LAPSED`, and a welder whose expiry has not yet been passed remains `QUALIFIED`."

        PRD: "`RENEW` is available only from `LAPSED`: the welder returns to `QUALIFIED`,
        `last_weld_date_utc` is reset to `effective_date_utc` when that field is supplied
        and otherwise to the logical clock, `continuity_expires_at_utc` is recomputed from
        the new base date plus `continuity_limit_days`, and `qualification_date_utc` is
        deliberately **not** changed — the original performance-test date is part of the
        permanent record."

        Design: Corner/endpoints/welder_renew_action_restarts_the_continuity_window
        """
        X.set_clock(api, CLOCK_BASE)
        welder = X.create_welder(api)
        assert welder["qualification_status"] == WELDER_QUALIFIED
        assert_instant(
            welder["continuity_expires_at_utc"], "2026-11-28T00:00:00Z", "continuity expiry"
        )

        X.set_clock(api, "2026-12-01T00:00:00Z")
        lapsed = X.read_welder(api, welder["id"])
        assert lapsed["qualification_status"] == WELDER_LAPSED

        renewed = assert_object_envelope(
            api.welder_qualification_action(
                welder["id"],
                qualification_action_payload(
                    ACTION_RENEW,
                    effective_date_utc="2026-12-01T00:00:00Z",
                    remarks="renewal test coupon passed",
                ),
                AI1,
            ),
            200,
        )

        assert renewed["qualification_status"] == WELDER_QUALIFIED
        assert_instant(renewed["last_weld_date_utc"], "2026-12-01T00:00:00Z", "last weld date")
        assert_instant(
            renewed["continuity_expires_at_utc"], "2027-05-30T00:00:00Z", "renewed expiry"
        )
        assert_instant(
            renewed["qualification_date_utc"], "2026-06-01T00:00:00Z", "performance test date"
        )
        assert renewed["revoked_at_utc"] is None

        assert_list_total(api.list_welders(AI1, {"qualification_status": WELDER_QUALIFIED}), 1)


class TestPlateLotAllocation:
    def test_one_allocation_writes_the_course_the_lot_and_the_tank_ledger(self, api):
        """The endpoint answers with the shell course, and the link reads from both sides.

        PRD: "On success the course records `allocated_plate_lot_id` and `allocated_weight_lb`
        and moves its `allocation_status` to `ALLOCATED`."

        PRD: "The tank's `steel_allocated_lb` is the sum of `allocated_weight_lb` over every lot
        of the tank."

        Design: Corner/endpoints/plate_lot_allocation_links_lot_and_course
        """
        X.set_clock(api, CLOCK_BASE)
        tank = X.create_tank(api)
        course = X.create_course(api, tank["id"], 1)
        lot = X.receive_plate_lot(api, tank["id"], mtr_number="MTR-4471-A")
        assert_weight(lot["received_weight_lb"], 12505.00, "received weight")

        allocated_course = assert_object_envelope(
            api.plate_lot_allocation(
                lot["id"], allocation_payload(course["id"], 8000.0), ES1
            ),
            200,
        )

        assert allocated_course["id"] == course["id"]
        assert allocated_course["allocated_plate_lot_id"] == lot["id"]
        assert_weight(allocated_course["allocated_weight_lb"], 8000.00, "course allocation")
        assert allocated_course["allocation_status"] == ALLOCATION_ALLOCATED

        lot = X.read_plate_lot(api, lot["id"])
        assert_weight(lot["allocated_weight_lb"], 8000.00, "lot allocated weight")
        assert_weight(lot["remaining_weight_lb"], 4505.00, "lot remaining weight")

        tank = X.read_tank(api, tank["id"])
        assert_weight(tank["steel_received_lb"], 12505.00, "tank steel received")
        assert_weight(tank["steel_allocated_lb"], 8000.00, "tank steel allocated")
        assert_steel_conservation(tank, [lot])

        rows, _ = assert_list_total(
            api.list_shell_courses(ES1, {"allocated_plate_lot_id": lot["id"]}), 1
        )
        assert rows[0]["id"] == course["id"]
        lots, _ = assert_list_total(api.list_plate_lots(ES1, {"tank_id": tank["id"]}), 1)
        assert lots[0]["id"] == lot["id"]


class TestTankProgressSummary:
    def test_the_progress_read_recomputes_all_eighteen_keys_from_other_rows(self, api):
        """Two courses' worth of tallies, the steel triple and the appurtenance split.

        PRD: "It reports `tank_id`, `construction_phase`, `quality_posture` and
        `open_nonconformance_count`; the course tallies `course_count` and
        `rt_accepted_course_count`; the seam tallies `seam_count`, `welded_seam_count` and
        `rt_accepted_seam_count`; the examination figures `weld_reject_rate` and
        `required_examination_pct`; the steel figures `steel_received_lb`,
        `steel_allocated_lb` and `steel_remaining_lb`; the pointer
        `active_hydrotest_plan_id` alongside `total_hydrotest_cost_usd`; and the
        appurtenance tallies `installed_appurtenance_count` and
        `designed_appurtenance_count`."

        PRD: "`weld_reject_rate` is 0.0 when that population is empty, and otherwise the count
        of rejected reports divided by the count of examined reports, rounded half up to 4
        decimal places."

        Design: Corner/endpoints/tank_summary_computed_read_matches_the_underlying_rows
        """
        ctx = X.foundation_accepted_tank(api)
        course = X.create_course(api, ctx.tank_id, 1)
        lot = X.receive_plate_lot(api, ctx.tank_id, mtr_number="MTR-4471-A")
        X.allocate(api, lot["id"], course["id"], 8000.0)
        X.fitup(api, course["id"])
        welder = X.create_welder(api)
        first_seam = X.create_seam(api, course["id"], "V1", 1)
        X.create_seam(api, course["id"], "V2", 2)
        X.weld(api, first_seam["id"], welder["id"])
        X.create_appurtenance(api, ctx.tank_id, course["id"])

        assert X.read_course(api, course["id"])["status"] == COURSE_FITTED

        summary = assert_object_envelope(api.get_tank_summary(ctx.tank_id, CC1), 200)
        assert_summary_keys(summary)

        assert summary["tank_id"] == ctx.tank_id
        assert summary["construction_phase"] == PHASE_ERECTION_IN_PROGRESS
        assert summary["quality_posture"] == POSTURE_OPEN
        assert summary["open_nonconformance_count"] == 0

        assert summary["course_count"] == 1
        assert summary["rt_accepted_course_count"] == 0
        assert summary["seam_count"] == 2
        assert summary["welded_seam_count"] == 1
        assert summary["rt_accepted_seam_count"] == 0

        assert summary["weld_reject_rate"] == pytest.approx(0.0)
        assert summary["required_examination_pct"] == pytest.approx(BASE_EXAMINATION_PCT)

        assert_weight(summary["steel_received_lb"], 12505.00, "steel received")
        assert_weight(summary["steel_allocated_lb"], 8000.00, "steel allocated")
        assert_weight(summary["steel_remaining_lb"], 4505.00, "steel remaining")

        assert summary["active_hydrotest_plan_id"] is None
        assert_money(summary["total_hydrotest_cost_usd"], 0.00, "hydrotest cost")

        assert summary["installed_appurtenance_count"] == 0
        assert summary["designed_appurtenance_count"] == 1

        before = X.read_tank(api, ctx.tank_id)["version"]
        again = assert_object_envelope(api.get_tank_summary(ctx.tank_id, CC1), 200)
        assert again == summary
        assert X.read_tank(api, ctx.tank_id)["version"] == before


class TestHydrotestCompletionGate:
    def test_the_same_pass_flips_from_conflict_to_success_on_the_clock_alone(self, api):
        """Refused twelve hours in, accepted at exactly hold_started_at_utc plus 24 hours.

        PRD: "A `PASS` additionally requires that the hold period has elapsed — the logical
        clock at or after `hold_started_at_utc` advanced by `hold_hours` hours, a breach
        being rejected with `ERR_HOLD_PERIOD_NOT_ELAPSED` — and that
        `settlement_survey_count` has reached at least 4, so that all four mandatory
        hold-point surveys were actually taken; a shortfall is rejected with
        `ERR_SETTLEMENT_HOLD_POINT_MISSING`."

        PRD: "`PASS` moves the plan `FILL_HOLD → PASSED` (terminal), stamps `completed_at_utc`,
        advances the tank `SHELL_COMPLETE → HYDROTEST_PASSED`, and freezes every cost
        field from the calculation above."

        PRD: "Either decision converts the plan's remaining `RESERVED` withdrawals to
        `CONSUMED`, which moves their volume out of the source's `reserved_volume_gal` and
        into its `consumed_volume_gal` while leaving `available_volume_gal` unchanged —
        consumption turns a reservation into a permanent draw against the permit."

        Design: Corner/endpoints/hydrotest_pass_is_allowed_only_after_the_hold_elapses
        """
        ctx = X.plan_at_fill_hold(api)
        assert ctx.plan["status"] == PLAN_FILL_HOLD
        assert ctx.plan["hold_hours"] == 24
        assert_instant(ctx.plan["hold_started_at_utc"], CLOCK_BASE, "hold start")
        assert ctx.plan["settlement_survey_count"] == 4

        X.set_clock(api, "2026-08-10T12:00:00Z")
        validate_error(
            api.plan_completion(
                ctx.plan_id, plan_completion_payload(PASS_DECISION, remarks="hold half done"), AI2
            ),
            ERR_HOLD_PERIOD_NOT_ELAPSED,
            409,
        )
        held = X.read_plan(api, ctx.plan_id)
        assert held["status"] == PLAN_FILL_HOLD
        assert held["completed_at_utc"] is None

        X.set_clock(api, "2026-08-11T00:00:00Z")
        passed = assert_object_envelope(
            api.plan_completion(
                ctx.plan_id, plan_completion_payload(PASS_DECISION, remarks="no leaks"), AI2
            ),
            200,
        )

        assert passed["status"] == PLAN_PASSED
        assert_instant(passed["completed_at_utc"], "2026-08-11T00:00:00Z", "completion stamp")
        assert_plan_costs(passed, 1332.00, 840.00, 2172.00, 0.05, 108.60, 2280.60)

        assert X.read_tank(api, ctx.tank_id)["construction_phase"] == PHASE_HYDROTEST_PASSED
        assert X.read_withdrawal(api, ctx.withdrawal_id)["status"] == WITHDRAWAL_CONSUMED
        assert_source_ledger(X.read_water_source(api, ctx.source_id), 0.00, 400000.00, 1600000.00)
