"""Load-chart lookup, nested capacity ceilings, lift classification and the two
scheduling constraints evaluated at configure time."""

import pytest

from test_helpers import (
    ApiErrorId,
    DISPATCHER,
    build_critical_world,
    build_standard_world,
    commit_gear,
    configure_body,
    configure_plan,
    new_chart_row,
    new_serviceable_gear,
    new_standard_crane,
    open_plan,
    read_assignment,
    read_crane,
    read_personnel,
    read_plan,
    setup_surveyed_plan_with_gear,
    survey_plan,
    validate_error,
    validate_success,
)


class TestNestedCapacityCeiling:
    """Difficulty rule: combinatorial_formula."""

    @staticmethod
    def _world():
        return build_critical_world(
            chart_rows=[
                {"radius_ft": 40, "gross_capacity_lb": 100_000},
                {"radius_ft": 50, "gross_capacity_lb": 78_000},
            ],
            gear={"rated_wll_lb": 45_000},
            rigger={"rigger_level": "MASTER"},
        )

    def test_chart_lookup_takes_the_smallest_qualifying_radius_row(self, api):
        """PRD 3.4: "The candidate rows are those belonging to the chosen crane,
        charted for the chosen `configuration`, whose `boom_length_ft` matches the
        requested boom length **exactly** — there is no interpolation between charted
        boom lengths — and whose charted `radius_ft` is greater than or equal to the
        requested radius."
        PRD 3.4: "Among those candidates the system takes the one with the
        **smallest** `radius_ft`, which is the next charted radius at or beyond where
        the load actually sits; should two candidates somehow tie on radius, the
        earlier `created_at` wins."

        Design: Difficulty/combinatorial_formula/net_capacity_nested_min_over_chart_ceiling_and_line_pull
        """
        world = self._world()
        ctx = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-7782",
                                   "window_start": "2026-09-12T06:00:00Z",
                                   "window_end": "2026-09-12T14:00:00Z",
                                   "sail_area_sqft": 150.0}
        )
        body = configure_body(world, ctx["plan_version"], radius_ft=38, parts_of_line=4)
        plan = validate_success(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER))

        assert plan["chart_gross_capacity_lb"] == 100_000, (
            "the ceiling lookup must pick the 40 ft row, not the 50 ft row, "
            f"got {plan['chart_gross_capacity_lb']}"
        )

    def test_net_capacity_is_the_nested_minimum_less_the_three_deductions(self, api):
        """PRD 3.4: "The reeving imposes its own limit: the plan's
        `hoist_line_capacity_lb` is the crane's `max_line_pull_lb` multiplied by
        `parts_of_line`. The governing gross figure is the smaller of
        `chart_gross_capacity_lb` and `hoist_line_capacity_lb`. From that smaller
        figure the system subtracts the sum of the three deductions
        `block_weight_lb`, `jib_weight_lb` and `aux_head_weight_lb` to arrive at
        `net_capacity_lb`."
        PRD 3.4: "The plan's `utilization_pct` is `total_load_lb` divided by
        `net_capacity_lb`, multiplied by 100, rounded half up to two decimal places."
        PRD 3.4: "a plan whose `utilization_pct` is at or above 90.00 percent is
        baselined `ENGINEERED_CRITICAL`"

        Design: Difficulty/combinatorial_formula/net_capacity_nested_min_over_chart_ceiling_and_line_pull
        """
        world = self._world()
        ctx = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-7782",
                                   "window_start": "2026-09-12T06:00:00Z",
                                   "window_end": "2026-09-12T14:00:00Z",
                                   "sail_area_sqft": 150.0}
        )
        body = configure_body(world, ctx["plan_version"], radius_ft=38, parts_of_line=4)
        plan = validate_success(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER))

        assert plan["hoist_line_capacity_lb"] == 80_000
        assert plan["net_capacity_lb"] == 78_000
        assert plan["total_load_lb"] == 73_500
        assert plan["utilization_pct"] == pytest.approx(94.23, abs=0.001)
        assert plan["lift_class"] == "ENGINEERED_CRITICAL"
        assert plan["plan_status"] == "PENDING_ENGINEERING"


class TestUtilizationClassificationBoundary:
    """Difficulty rule: boundary_precision_check."""

    def test_utilization_of_exactly_seventy_five_percent_classifies_as_critical(self, api):
        """PRD 3.4: "A baseline is taken from utilization alone: a plan whose
        `utilization_pct` is at or above 90.00 percent is baselined
        `ENGINEERED_CRITICAL`; failing that, one at or above 75.00 percent is
        baselined `CRITICAL`; anything below 75.00 percent is baselined `STANDARD`."
        PRD 3.4: "A configure that resolves to `CRITICAL` or `ENGINEERED_CRITICAL`
        advances the plan `SURVEYED → PENDING_ENGINEERING` instead, and that plan
        cannot reach `APPROVED` until a stamped engineering analysis exists."
        PRD 3.4: "Each commitment's `leg_tension_lb` is the plan's `total_load_lb`
        divided by that commitment's `leg_count`, multiplied by its
        `load_angle_factor`, rounded half up to a whole pound."

        Design: Difficulty/boundary_precision_check/utilization_exactly_seventy_five_pct_classifies_as_critical
        """
        world = build_critical_world()
        ctx = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-7781", "sail_area_sqft": 150.0}
        )
        plan = configure_plan(world, ctx["plan_id"], ctx["plan_version"])

        assert plan["net_capacity_lb"] == 98_000
        assert plan["total_load_lb"] == 73_500
        assert plan["utilization_pct"] == pytest.approx(75.00, abs=0.001)
        assert plan["lift_class"] == "CRITICAL"
        assert plan["plan_status"] == "PENDING_ENGINEERING"
        assert read_assignment(ctx["ga_id"])["leg_tension_lb"] == 21_223

    def test_utilization_just_below_the_boundary_stays_standard(self, api):
        """PRD 3.4: "The comparison uses the already-rounded `utilization_pct`, so a
        raw quotient of 74.996 percent rounds to 75.00 and **is** critical, while
        74.99 percent is standard."
        PRD 3.4: "A configure that resolves to `STANDARD` advances the plan
        `SURVEYED → CONFIGURED`, and that plan will never see an engineer."

        Design: Difficulty/boundary_precision_check/utilization_exactly_seventy_five_pct_classifies_as_critical
        """
        world = build_critical_world()
        ctx = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-7781B",
                                   "load_weight_lb": 72_990, "sail_area_sqft": 150.0}
        )
        plan = configure_plan(world, ctx["plan_id"], ctx["plan_version"])

        assert plan["total_load_lb"] == 73_490
        assert plan["utilization_pct"] == pytest.approx(74.99, abs=0.001)
        assert plan["lift_class"] == "STANDARD"
        assert plan["plan_status"] == "CONFIGURED"


class TestCraneWindowExclusivity:
    """Difficulty rule: resource_temporal_overlap."""

    @staticmethod
    def _two_plans_on_one_crane(world):
        gear_b = new_serviceable_gear(gear_tag="SL-5002")
        ctx_a = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-A",
                                   "window_start": "2026-09-10T06:00:00Z",
                                   "window_end": "2026-09-10T16:00:00Z"}
        )
        configure_plan(world, ctx_a["plan_id"], ctx_a["plan_version"])
        plan_b = open_plan(world, job_reference="JOB-B",
                           window_start="2026-09-11T03:00:00Z",
                           window_end="2026-09-11T08:00:00Z")
        surveyed_b = survey_plan(world, plan_b["id"])
        commit_gear(world, plan_b["id"], gear_b["id"])
        return ctx_a, plan_b["id"], surveyed_b["version"]

    def test_plan_inside_the_trailing_release_buffer_is_refused(self, api):
        """PRD 3.4: "The first is **crane effective-window exclusivity**: the new
        plan's window, treated as a half-open interval that includes its
        `window_start` and excludes its `window_end`, may not intersect any other
        plan's window on the same crane extended by a trailing release buffer of
        twelve hours — that is, the other plan's interval runs from its
        `window_start` up to but not including twelve hours after its `window_end`."
        PRD 3.4: "An intersection is refused with `ERR_CRANE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/crane_window_conflict_spans_the_trailing_release_buffer
        """
        world = build_standard_world()
        _, plan_b_id, plan_b_version = self._two_plans_on_one_crane(world)

        assert read_crane(world["crane_id"])["reserved_hours_total"] == pytest.approx(10.0)

        body = configure_body(world, plan_b_version)
        resp = api.configure_lift_plan(plan_b_id, body, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_CRANE_WINDOW_CONFLICT.value, 409)

    def test_window_conflict_leaves_the_second_plan_and_the_crane_ledger_untouched(self, api):
        """PRD 3.4: "An intersection is refused with `ERR_CRANE_WINDOW_CONFLICT`."
        PRD 3.4: "A crane's `reserved_hours_total` is the sum, over every plan on
        that crane whose readiness dimension is `CONFIGURED`, `PENDING_ENGINEERING`,
        `APPROVED` or `RELEASED`, of the plan's window length — `window_end` minus
        `window_start`, expressed in hours — rounded half up to two decimal places,
        and its `active_plan_count` is the number of plans in that same set."

        Design: Difficulty/resource_temporal_overlap/crane_window_conflict_spans_the_trailing_release_buffer
        """
        world = build_standard_world()
        _, plan_b_id, plan_b_version = self._two_plans_on_one_crane(world)

        body = configure_body(world, plan_b_version)
        validate_error(api.configure_lift_plan(plan_b_id, body, DISPATCHER),
                       ApiErrorId.ERR_CRANE_WINDOW_CONFLICT.value, 409)

        plan_b = read_plan(plan_b_id)
        assert plan_b["plan_status"] == "SURVEYED"
        assert plan_b["crane_id"] is None

        crane = read_crane(world["crane_id"])
        assert crane["reserved_hours_total"] == pytest.approx(10.0)
        assert crane["active_plan_count"] == 1


class TestOperatorDailyHourCap:
    """Difficulty rule: resource_temporal_overlap."""

    @staticmethod
    def _two_plans_two_cranes(world):
        crane_b = new_standard_crane(model_code="RT-150-B")
        new_chart_row(crane_b["id"])
        gear_b = new_serviceable_gear(gear_tag="SL-5002")
        ctx_a = setup_surveyed_plan_with_gear(
            world, plan_overrides={"job_reference": "JOB-A",
                                   "window_start": "2026-09-10T06:00:00Z",
                                   "window_end": "2026-09-10T16:00:00Z"}
        )
        configure_plan(world, ctx_a["plan_id"], ctx_a["plan_version"])
        plan_b = open_plan(world, job_reference="JOB-B",
                           window_start="2026-09-10T18:00:00Z",
                           window_end="2026-09-10T21:00:00Z")
        surveyed_b = survey_plan(world, plan_b["id"])
        commit_gear(world, plan_b["id"], gear_b["id"])
        return crane_b, plan_b["id"], surveyed_b["version"]

    def test_same_day_windows_aggregate_past_the_twelve_hour_cap(self, api):
        """PRD 3.4: "The person's `peak_daily_assigned_hours` is the largest of those
        per-day sums across every day they touch, rounded half up to two decimal
        places, and is 0 when they hold no reserving plans."
        PRD 3.4: "If any single day's sum would come out **strictly greater** than
        12.0 hours, the configure is refused with `ERR_OPERATOR_HOURS_EXCEEDED`;
        exactly 12.0 hours is allowed."

        Design: Difficulty/resource_temporal_overlap/operator_daily_cap_rejects_two_non_overlapping_same_day_windows
        """
        world = build_standard_world()
        crane_b, plan_b_id, plan_b_version = self._two_plans_two_cranes(world)

        assert read_personnel(world["op_id"])["peak_daily_assigned_hours"] == pytest.approx(10.0)

        body = configure_body(world, plan_b_version, crane_id=crane_b["id"])
        validate_error(api.configure_lift_plan(plan_b_id, body, DISPATCHER),
                       ApiErrorId.ERR_OPERATOR_HOURS_EXCEEDED.value, 409)

    def test_hour_cap_rejection_is_independent_of_crane_exclusivity(self, api):
        """PRD 3.4: "Two plans that never overlap each other in time can still be
        rejected together by this rule, because it aggregates capacity per day rather
        than testing for collisions."
        PRD 3.4: "Two scheduling constraints are evaluated at configure time, and
        they are independent of each other."

        Design: Difficulty/resource_temporal_overlap/operator_daily_cap_rejects_two_non_overlapping_same_day_windows
        """
        world = build_standard_world()
        crane_b, plan_b_id, plan_b_version = self._two_plans_two_cranes(world)

        body = configure_body(world, plan_b_version, crane_id=crane_b["id"])
        error = validate_error(api.configure_lift_plan(plan_b_id, body, DISPATCHER),
                               ApiErrorId.ERR_OPERATOR_HOURS_EXCEEDED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_CRANE_WINDOW_CONFLICT.value

        assert read_plan(plan_b_id)["plan_status"] == "SURVEYED"
        assert read_personnel(world["op_id"])["peak_daily_assigned_hours"] == pytest.approx(10.0)

        crane_b_after = read_crane(crane_b["id"])
        assert crane_b_after["reserved_hours_total"] == pytest.approx(0.0)
        assert crane_b_after["status"] == "AVAILABLE"
