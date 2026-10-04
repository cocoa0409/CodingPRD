"""Spoilage expectation: base-only first run, and the changeover branch
flipping the flag on identical inputs (PRD §3.5)."""
import pytest

from test_helpers import (
    publish_index, set_clock, setup_run_env, create_run, start_run,
    complete_run,
)

SPECIALTY_FORMAT = {"is_specialty": True, "shape": "SLEEK",
                    "size_code": "8OZ-SLEEK", "metal_lbs_per_1000_units": 30.0,
                    "tooling_investment_cents": 100000,
                    "min_volume_commitment_units": 1000000}


class TestFirstRunSpoilage:
    def test_spoilage_flag_first_run_on_line_uses_base_only(self, api):
        """PRD §3.5: "The expected spoilage is the line's `base_spoilage_pct`,
        plus a specialty premium of 0.03 when the format is specialty, plus a
        changeover penalty of 0.02 when the run's `graphics_code` differs from
        the previous run's" and "When the effective spoilage ... is strictly
        greater than the expectation, the run's `spoilage_flag` — false by
        default — is set true". With no previous run, only the base applies.

        Design: Corner/calculations/spoilage_flag_first_run_on_line_uses_base_only
        """
        set_clock()
        publish_index("2026-08", 128.0)
        env = setup_run_env()
        run = create_run(env["agreement"]["id"], env["line"]["id"],
                         env["format"]["id"], scheduled_qty=100000,
                         graphics_code="ANYTHING",
                         window_start="2026-09-10T08:00:00Z",
                         window_end="2026-09-10T16:00:00Z")
        start_run(run["id"])
        completed = complete_run(run["id"], 100000, 5000)
        # 5000 / 105000 = 0.0476 (4dp); total cans 105000 x 30.0 / 1000 lbs.
        assert completed["effective_spoilage_pct"] == pytest.approx(0.0476,
                                                                    abs=5e-5)
        assert completed["sheet_lbs_consumed"] == pytest.approx(3150.0)
        assert completed["spoilage_flag"] is True, "0.0476 > base 0.04"


class TestChangeoverBranch:
    def _changeover_env(self, api):
        """Specialty format; PREV graphics SUMMER (09-02, stays SCHEDULED),
        run A graphics OKTOBERFEST (09-03), run B graphics OKTOBERFEST (09-04);
        A and B both IN_PROGRESS. Identical completion payload 100000/8000."""
        set_clock()
        publish_index("2026-08", 128.0)
        publish_index("2026-09", 128.0)
        env = setup_run_env(format_overrides=SPECIALTY_FORMAT,
                            pass_through_pct=1.0)
        agr, line, fmt = (env["agreement"]["id"], env["line"]["id"],
                          env["format"]["id"])
        create_run(agr, line, fmt, scheduled_qty=100000, graphics_code="SUMMER",
                   window_start="2026-09-02T08:00:00Z",
                   window_end="2026-09-02T16:00:00Z")
        run_a = create_run(agr, line, fmt, scheduled_qty=100000,
                           graphics_code="OKTOBERFEST",
                           window_start="2026-09-03T08:00:00Z",
                           window_end="2026-09-03T16:00:00Z")
        start_run(run_a["id"])
        run_b = create_run(agr, line, fmt, scheduled_qty=100000,
                           graphics_code="OKTOBERFEST",
                           window_start="2026-09-04T08:00:00Z",
                           window_end="2026-09-04T16:00:00Z")
        start_run(run_b["id"])
        return run_a["id"], run_b["id"]

    def test_changeover_branch_widens_expectation_flag_false(self, api):
        """PRD §3.5: "plus a changeover penalty of 0.02 when the run's
        `graphics_code` differs from the previous run's — and the whole sum is
        capped at 0.15" — with the changeover, expected = min(0.15,
        0.04 + 0.03 + 0.02) = 0.09 and 0.0741 is not strictly greater.

        Design: Difficulty/combinatorial_formula/spoilage_expected_capped_multifactor_with_changeover_branch
        """
        run_a_id, _run_b_id = self._changeover_env(api)
        completed = complete_run(run_a_id, 100000, 8000)
        assert completed["effective_spoilage_pct"] == pytest.approx(0.0741,
                                                                    abs=5e-5)
        assert completed["spoilage_flag"] is False

    def test_same_graphics_branch_narrows_expectation_flag_true(self, api):
        """PRD §3.5: ""Previous run" means the non-terminal run on the same line
        ... with the latest `window_end` at or before this run's
        `window_start`" — the previous run shares the graphics code, so
        expected = min(0.15, 0.04 + 0.03) = 0.07 and 0.0741 > 0.07 sets the
        flag; identical produced/spoiled inputs flip the flag purely via the
        changeover branch.

        Design: Difficulty/combinatorial_formula/spoilage_expected_capped_multifactor_with_changeover_branch
        """
        run_a_id, run_b_id = self._changeover_env(api)
        complete_run(run_a_id, 100000, 8000)  # becomes run B's previous run
        completed_b = complete_run(run_b_id, 100000, 8000)
        assert completed_b["effective_spoilage_pct"] == pytest.approx(0.0741,
                                                                      abs=5e-5)
        assert completed_b["spoilage_flag"] is True
