"""Boundary-precision tests: inclusive capacity-guarantee boundary and the
zero-remaining credit pool boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_order,
    create_project,
    get_success_data,
    schedule_performance_test,
    set_clock,
    setup_active_ltsa,
    setup_executed_project,
    validate_error,
    validate_paginated,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


class TestCapacityGuaranteeBoundary:
    def test_exact_guarantee_passes_one_centi_mwh_below_fails(self, api):
        """PRD §3.4: "Either way the evaluated value is rounded half up to 2
        decimal places, and the test `result` is `PASS` when the evaluated
        capacity is greater than or equal to the active agreement's
        `guaranteed_capacity_mwh` — equality passes — and `FAIL` otherwise."

        Design: Difficulty/boundary_precision_check/capacity_test_passes_at_exact_guarantee_boundary
        """
        project, esa = setup_executed_project(
            api=api, esa_overrides={"guaranteed_capacity_mwh": 38.0}
        )
        t1 = schedule_performance_test(
            project["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z", api=api,
        )
        t2 = schedule_performance_test(
            project["id"], "CAPACITY_TEST",
            "2026-09-15T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )
        # Clock at default 2026-09-01 inside T1's window.
        d1 = validate_success(
            api.record_test_results(
                t1["id"], {"measured_capacity_mwh": 39.0, "aux_load_mwh": 1.0}, PERF
            )
        )
        # POI basis: 39.0 - 1.0 = 38.0 == guarantee -> PASS (inclusive)
        assert d1["evaluated_capacity_mwh"] == pytest.approx(38.0, abs=0.001)
        assert d1["result"] == "PASS" and d1["status"] == "PASSED"

        set_clock("2026-09-15T00:00:00Z", api=api)
        d2 = validate_success(
            api.record_test_results(
                t2["id"], {"measured_capacity_mwh": 38.99, "aux_load_mwh": 1.0}, PERF
            )
        )
        # 38.99 - 1.0 = 37.99 < 38.0 -> FAIL
        assert d2["evaluated_capacity_mwh"] == pytest.approx(37.99, abs=0.001)
        assert d2["result"] == "FAIL" and d2["status"] == "FAILED"

    def test_failed_capacity_test_auto_creates_augmentation_event(self, api):
        """PRD §3.4: "A failed `CAPACITY_TEST` has one further consequence: the
        system automatically creates an augmentation event with `origin` `AUTO`
        in `PLANNED` status, sized and scheduled per §3.5, and recomputes the
        project's `projected_capacity_mwh`."
        PRD §3.5: "When a capacity test fails, the shortfall is the active
        agreement's `guaranteed_capacity_mwh` minus the smaller of the current
        projection and the test's evaluated capacity."

        Design: Difficulty/boundary_precision_check/capacity_test_passes_at_exact_guarantee_boundary
        """
        project, esa = setup_executed_project(
            api=api, esa_overrides={"guaranteed_capacity_mwh": 38.0}
        )
        t1 = schedule_performance_test(
            project["id"], "CAPACITY_TEST",
            "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", api=api,
        )
        d1 = validate_success(
            api.record_test_results(
                t1["id"], {"measured_capacity_mwh": 37.0, "aux_load_mwh": 1.0}, PERF
            )
        )
        assert d1["result"] == "FAIL"
        augs, meta = validate_paginated(
            api.list_augmentations(DEV, params={"project_id": project["id"]})
        )
        auto = [a for a in augs if a["origin"] == "AUTO"]
        assert len(auto) == 1, f"exactly one AUTO augmentation, got {len(auto)}"
        assert auto[0]["status"] == "PLANNED"
        assert auto[0]["added_capacity_mwh"] > 0


class TestCreditPoolZeroRemainingBoundary:
    def _setup_pool(self, api):
        project = create_project(api=api)
        ltsa = setup_active_ltsa(
            project["id"], api=api, annual_fee_cents=2_000_000
        )
        return project, ltsa

    def test_exact_remaining_pool_draw_succeeds_then_one_cent_fails(self, api):
        """PRD §3.7: "When the agreement's scope includes spare parts and the
        remaining pool — `credit_pool_cents` minus `credit_drawn_cents` —
        covers the full cost, the order is marked `covered_by_credit` true and
        the cost is added to `credit_drawn_cents`. When the scope includes
        spare parts but the headroom falls short, the order is refused outright
        with `ERR_CREDIT_POOL_EXHAUSTED`; coverage is all-or-nothing, never
        partial."

        Design: Difficulty/boundary_precision_check/credit_pool_exhausted_at_zero_remaining
        """
        _, ltsa = self._setup_pool(api)
        assert ltsa["credit_pool_cents"] == 600000

        order = create_order(
            ltsa["id"], api=api, part_description="Full bank of cells",
            part_cost_cents=600000,
        )
        assert order["covered_by_credit"] is True
        mid = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert mid["credit_drawn_cents"] == 600000

        resp = api.create_spare_part_order(
            {
                "service_agreement_id": ltsa["id"],
                "part_description": "One fuse",
                "part_cost_cents": 1,
                "expected_service_agreement_version": mid["version"],
            },
            SVC_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_POOL_EXHAUSTED)
        after = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert after["credit_pool_cents"] == 600000
        assert after["credit_drawn_cents"] == 600000

    def test_one_cent_over_pool_fails_and_exact_draw_still_succeeds(self, api):
        """PRD §3.7: "When the scope includes spare parts but the headroom
        falls short, the order is refused outright with
        `ERR_CREDIT_POOL_EXHAUSTED`; coverage is all-or-nothing, never
        partial."
        PRD §3.6: "`credit_pool_cents` is 30 percent of `annual_fee_cents`,
        rounded down to a whole cent."

        Design: Difficulty/boundary_precision_check/credit_pool_exhausted_at_zero_remaining
        """
        _, ltsa = self._setup_pool(api)
        # 600001 > pool 600000 -> exhausted even before any draw.
        current = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        resp = api.create_spare_part_order(
            {
                "service_agreement_id": ltsa["id"],
                "part_description": "Over pool",
                "part_cost_cents": 600001,
                "expected_service_agreement_version": current["version"],
            },
            SVC_MGR,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_POOL_EXHAUSTED)

        current = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        ok = validate_success(
            api.create_spare_part_order(
                {
                    "service_agreement_id": ltsa["id"],
                    "part_description": "Exact pool",
                    "part_cost_cents": 600000,
                    "expected_service_agreement_version": current["version"],
                },
                SVC_MGR,
            ),
            expected_status=201,
        )
        assert ok["covered_by_credit"] is True
