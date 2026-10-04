"""Cannibalization studies: transfer math, bands, finalization, supersession."""

import pytest

from test_helpers import (
    ApiErrorId,
    create_active_rollout,
    create_cannibalization_study,
    create_existing_store,
    create_qualified_trade_area,
    create_store,
    create_trade_area,
    finalize_study,
    get_success_data,
    select_format,
    setup_store_with_format,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REAL_ESTATE = TEST_USERS["real_estate_manager_headers"]
FINANCE = TEST_USERS["finance_analyst_headers"]

# A DG_FRESH-feasible trade area: hh 2000, gap 30 -> DG_FRESH revenue
# 2000 * 560 * 1.30 = 145,600,000 cents.
FRESH_AREA = {
    "drive_time_minutes": 18,
    "household_count": 2000,
    "median_household_income_cents": 4500000,
    "grocery_gap_pct": 30,
}


def _setup_study_scenario(api, existing_sales=100000000):
    """ACTIVE program; EXISTING store X; DG_FRESH pipeline store S.

    Returns (rollout, existing_store, store).
    """
    rollout = create_active_rollout(name="P")
    t0 = create_trade_area(
        rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
        median_household_income_cents=4000000, grocery_gap_pct=20,
    )
    existing = create_existing_store(
        rollout["id"], t0["id"], name="X", open_year_sales_cents=existing_sales
    )
    area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
    store = setup_store_with_format(rollout["id"], area["id"], name="S")
    return rollout, existing, store


class TestPerLineRounding:
    def test_cannibalization_per_line_rounding_order(self, api):
        """PRD §3.7: "The study's sales-transfer computation proceeds entry by
        entry, and the rounding order is pinned: round per line, then sum."
        PRD §3.7: "The total transferred is the sum of the per-entry
        transferred amounts (already rounded per line), and `transfer_pct` is
        that total divided by the new store's `projected_revenue_cents`,
        expressed as a percentage and rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/cannibalization_per_line_rounding_order
        """
        rollout = create_active_rollout(name="P")
        t0 = create_trade_area(
            rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=20,
        )
        ex = create_existing_store(
            rollout["id"], t0["id"], name="X", open_year_sales_cents=150000000
        )
        ey = create_existing_store(
            rollout["id"], t0["id"], name="Y", open_year_sales_cents=90000001
        )
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        assert store["projected_revenue_cents"] == 145600000

        resp = api.create_cannibalization_study(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "overlap_entries": [
                    {"existing_store_id": ex["id"], "overlap_weight": 0.15},
                    {"existing_store_id": ey["id"], "overlap_weight": 0.15},
                ],
            },
            FINANCE,
        )
        study = validate_success(resp, 201)
        # Per-line rounding: 9000000 + 5400000 = 14400000; sum-then-round
        # would yield 14400001 and transfer_pct 9.90.
        assert study["transfer_pct"] == pytest.approx(9.89, abs=0.001)
        # 9.89 > 8 but <= 15 -> MITIGATE band.
        assert study["recommendation"] == "MITIGATE"

    def test_per_line_rounding_drives_finalize_eligibility(self, api):
        """PRD §3.7: "Failing that, it is `MITIGATE` when any entry's impact
        percentage exceeds 12 or `transfer_pct` exceeds 8. Otherwise it is
        `PROCEED`."
        PRD §3.7: "Finalizing a study moves it `DRAFT → FINAL` and locks it as
        the reference for capital-project approval gating — but a study whose
        recommendation is `BLOCKED` cannot be finalized and fails with
        `ERR_CANNIBALIZATION_BLOCKED`."

        Design: Difficulty/combinatorial_formula/cannibalization_per_line_rounding_order
        """
        rollout = create_active_rollout(name="P")
        t0 = create_trade_area(
            rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=20,
        )
        ex = create_existing_store(
            rollout["id"], t0["id"], name="X", open_year_sales_cents=150000000
        )
        ey = create_existing_store(
            rollout["id"], t0["id"], name="Y", open_year_sales_cents=90000001
        )
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")
        study = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [
                {"existing_store_id": ex["id"], "overlap_weight": 0.15},
                {"existing_store_id": ey["id"], "overlap_weight": 0.15},
            ],
        )
        # MITIGATE (not BLOCKED): finalization is permitted.
        assert study["recommendation"] == "MITIGATE"
        finalized = finalize_study(rollout["id"], study["id"])
        assert finalized["status"] == "FINAL"


class TestBandBoundaries:
    def test_cannibalization_entry_band_below_block_threshold(self, api):
        """PRD §3.7: "It is `BLOCKED` when any entry's impact percentage
        exceeds 20 or the aggregate `transfer_pct` exceeds 15. Failing that, it
        is `MITIGATE` when any entry's impact percentage exceeds 12 or
        `transfer_pct` exceeds 8. Otherwise it is `PROCEED`."

        Design: Difficulty/boundary_precision_check/cannibalization_entry_band_below_block_threshold
        """
        rollout, existing, store = _setup_study_scenario(api)
        # X@0.45: transferred 100000000*0.45*0.4 = 18000000 -> impact 18.00%
        # (below the >20 block band, above the >12 mitigate band);
        # transfer 18000000/145600000 = 12.36% (>8, <=15) -> MITIGATE.
        resp = api.create_cannibalization_study(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "overlap_entries": [
                    {"existing_store_id": existing["id"], "overlap_weight": 0.45}
                ],
            },
            FINANCE,
        )
        study = validate_success(resp, 201)
        assert study["recommendation"] == "MITIGATE"
        assert study["transfer_pct"] == pytest.approx(12.36, abs=0.001)
        finalized = finalize_study(rollout["id"], study["id"])
        assert finalized["status"] == "FINAL"

    def test_entry_below_mitigate_band_proceeds(self, api):
        """PRD §3.7: "Failing that, it is `MITIGATE` when any entry's impact
        percentage exceeds 12 or `transfer_pct` exceeds 8. Otherwise it is
        `PROCEED`."

        Design: Difficulty/boundary_precision_check/cannibalization_entry_band_below_block_threshold
        """
        rollout, existing, store = _setup_study_scenario(api)
        # X@0.10: impact 4.00%, transfer 4000000/145600000 = 2.75% -> PROCEED.
        study = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [{"existing_store_id": existing["id"], "overlap_weight": 0.10}],
        )
        assert study["recommendation"] == "PROCEED"
        finalized = finalize_study(rollout["id"], study["id"])
        assert finalized["status"] == "FINAL"


class TestStudyLifecycle:
    def test_study_finalize_blocked_on_blocked_recommendation(self, api):
        """PRD §3.7: "Finalizing a study moves it `DRAFT → FINAL` and locks it
        as the reference for capital-project approval gating — but a study
        whose recommendation is `BLOCKED` cannot be finalized and fails with
        `ERR_CANNIBALIZATION_BLOCKED`."

        Design: Corner/state_machines/study_finalize_blocked_on_blocked_recommendation
        """
        rollout = create_active_rollout(name="P")
        t0 = create_trade_area(
            rollout["id"], name="T0", drive_time_minutes=12, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=20,
        )
        ex = create_existing_store(
            rollout["id"], t0["id"], name="X", open_year_sales_cents=200000000
        )
        ey = create_existing_store(
            rollout["id"], t0["id"], name="Y", open_year_sales_cents=60000000
        )
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")

        # X@0.25 -> 20000000 (impact 10.00); Y@0.40 -> 9600000 (impact 16.00);
        # total 29600000 / 145600000 = 20.33% > 15 -> BLOCKED.
        study = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [
                {"existing_store_id": ex["id"], "overlap_weight": 0.25},
                {"existing_store_id": ey["id"], "overlap_weight": 0.40},
            ],
        )
        assert study["transfer_pct"] == pytest.approx(20.33, abs=0.001)
        assert study["recommendation"] == "BLOCKED"

        resp = api.finalize_cannibalization_study(
            study["id"], {"rollout_program_id": rollout["id"]}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_CANNIBALIZATION_BLOCKED)
        after = get_success_data(api.get_cannibalization_study(study["id"], FINANCE))
        assert after["status"] == "DRAFT"

    def test_cascade_opening_plan_supersede_on_new_study(self, api):
        """PRD §3.7: "A store carries one live study at a time: creating a new
        study supersedes the store's prior study whether that prior study was
        `DRAFT` or `FINAL`, and when a `FINAL` study is superseded,
        capital-project approval gating re-targets the newest `FINAL` study."
        PRD §3.8: "A `NEW_BUILD` submission additionally requires the subject
        store to hold a `FINAL` cannibalization study that has not been
        superseded; without one the submit fails with `ERR_STUDY_NOT_FINAL`."

        Design: Corner/cross_cutting_complexity_layers/cascade_opening_plan_supersede_on_new_study
        """
        rollout, existing, store = _setup_study_scenario(api, existing_sales=200000000)
        # X@0.20: transferred 200000000*0.20*0.40 = 16000000 -> impact 8.00%
        # (not >12); transfer 16000000/145600000 = 10.99% (>8, <=15) ->
        # MITIGATE, which is still finalizable.
        study1 = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [{"existing_store_id": existing["id"], "overlap_weight": 0.20}],
        )
        assert study1["recommendation"] == "MITIGATE"
        finalized = finalize_study(rollout["id"], study1["id"])
        assert finalized["status"] == "FINAL"

        # New study supersedes the FINAL one. X@0.30 -> 24000000 / 145600000 =
        # 16.48% > 15 -> BLOCKED.
        study2 = create_cannibalization_study(
            rollout["id"],
            store["id"],
            [{"existing_store_id": existing["id"], "overlap_weight": 0.30}],
        )
        assert study2["status"] == "DRAFT"
        assert study2["transfer_pct"] == pytest.approx(16.48, abs=0.001)
        assert study2["recommendation"] == "BLOCKED"

        first = get_success_data(api.get_cannibalization_study(study1["id"], FINANCE))
        assert first["status"] == "SUPERSEDED"

        # No FINAL study remains: NEW_BUILD submit is blocked.
        project = get_success_data(
            api.create_capital_project(
                {
                    "rollout_program_id": rollout["id"],
                    "kind": "NEW_BUILD",
                    "store_id": store["id"],
                },
                FINANCE,
            )
        )
        assert project.get("id"), f"Setup failed creating capital project: {project}"
        resp = api.submit_capital_project(
            project["id"], {"rollout_program_id": rollout["id"]}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_STUDY_NOT_FINAL)

    def test_cannibalization_coefficient_change_rescores(self, api):
        """PRD §3.1: "While the program is `ACTIVE`, the administrator may
        adjust its settings — `new_build_capital_budget_cents` and
        `cannibalization_coefficient` — and each such adjustment recomputes
        `available_capital_cents`."
        PRD §3.7: "For each entry, the transferred sales are the existing
        store's `open_year_sales_cents` multiplied by the entry's
        `overlap_weight` multiplied by the program's `cannibalization_coefficient`,
        rounded to whole cents."

        Design: Corner/cross_cutting_complexity_layers/cannibalization_coefficient_change_rescores
        """
        rollout, existing, store = _setup_study_scenario(api, existing_sales=200000000)
        entries = [{"existing_store_id": existing["id"], "overlap_weight": 0.30}]
        study1 = create_cannibalization_study(rollout["id"], store["id"], entries)
        # At coefficient 0.40: 24000000 / 145600000 = 16.48%.
        assert study1["transfer_pct"] == pytest.approx(16.48, abs=0.001)
        assert study1["recommendation"] == "BLOCKED"

        updated = validate_success(
            api.update_rollout_settings(
                rollout["id"], {"cannibalization_coefficient": 0.6}, ADMIN
            ),
            200,
        )
        assert updated["cannibalization_coefficient"] == 0.6

        study2 = create_cannibalization_study(rollout["id"], store["id"], entries)
        # At coefficient 0.60: 36000000 / 145600000 = 24.73%.
        assert study2["transfer_pct"] == pytest.approx(24.73, abs=0.001)
        assert study2["recommendation"] == "BLOCKED"
        first = get_success_data(api.get_cannibalization_study(study1["id"], FINANCE))
        assert first["status"] == "SUPERSEDED"

    def test_study_references_cross_program_store_rejected(self, api):
        """PRD §3.7: "Every entry's existing store must belong to the same
        program, must be in `OPEN` or `EXISTING` status, and must have
        `open_year_sales_cents` recorded; a missing, out-of-program,
        out-of-state, or sales-less reference fails with `ERR_BAD_REFERENCE`."

        Design: Corner/validations/study_references_cross_program_store_rejected
        """
        other = create_active_rollout(name="P2", fiscal_year=2026,
                                      new_build_capital_budget_cents=1000000000)
        t0 = create_trade_area(
            other["id"], name="T0", drive_time_minutes=12, household_count=1000,
            median_household_income_cents=4000000, grocery_gap_pct=20,
        )
        outsider = create_existing_store(
            other["id"], t0["id"], name="X", open_year_sales_cents=200000000
        )

        rollout = create_active_rollout(name="P1")
        area = create_qualified_trade_area(rollout["id"], name="F", **FRESH_AREA)
        store = setup_store_with_format(rollout["id"], area["id"], name="S")

        resp = api.create_cannibalization_study(
            {
                "rollout_program_id": rollout["id"],
                "store_id": store["id"],
                "overlap_entries": [
                    {"existing_store_id": outsider["id"], "overlap_weight": 0.20}
                ],
            },
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REFERENCE)
