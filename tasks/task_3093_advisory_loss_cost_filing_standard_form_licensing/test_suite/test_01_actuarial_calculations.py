"""Actuarial calculations: dual-variant trend selection, pinned aggregation
orders, and the recency-decayed quality score (PRD §2.9, §3.2, §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_finding,
    begin_edit,
    create_adoption_payload,
    create_cell_payload,
    create_filing_payload,
    dispose,
    make_active_plan,
    make_agreement,
    make_effective_filing,
    make_insurer,
    make_reviewed_filing,
    make_submission,
    setup_adoption_scenario,
    setup_insurer_with_active_plan,
    validate_error,
    validate_success,
    make_insurer_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ACTUARY = TEST_USERS["actuary_headers"]

_CANONICAL_CELL = dict(
    earned_premium_cents=1000000,
    incurred_loss_cents=550000,
    weight_pct=100,
    current_loss_cost_cents=120000,
)


class TestTrendSelectionDualVariant:
    """Exponential vs linear trend selection on identical cell data."""

    def test_exponential_filing_indicates_1_1102_and_lands_reviewed(self, api):
        """PRD §3.3: "under `EXPONENTIAL_LEAST_SQUARES`, the raw ratio is
        multiplied by one plus the per-period trend rate of 4 percent,
        compounded over two and a half trend periods".
        PRD §3.3: "Successful completion moves the filing from
        `IN_ACTUARIAL_REVIEW` to `REVIEWED` and computes the filing's
        `indicated_change_pct`."

        Design: Difficulty/dual_variant_calc/filing_indication_exponential_vs_linear_diverge_on_identical_cells
        """
        filing = make_reviewed_filing(
            cells=[create_cell_payload(**_CANONICAL_CELL)],
            filing_overrides={"trend_selection": "EXPONENTIAL_LEAST_SQUARES"},
        )
        assert filing["filing_status"] == "REVIEWED"
        assert filing["indicated_change_pct"] == pytest.approx(1.1102, abs=1e-4)

    def test_linear_filing_indicates_strictly_less_0_8333(self, api):
        """PRD §3.3: "under `LINEAR_LEAST_SQUARES`, the raw ratio is multiplied
        by one plus the accumulated trend, that is the 4 percent per-period
        rate times two and a half periods (the linear variant always yields a
        strictly smaller indication than the exponential for identical
        inputs)."

        Design: Difficulty/dual_variant_calc/filing_indication_exponential_vs_linear_diverge_on_identical_cells
        """
        exp_filing = make_reviewed_filing(
            cells=[create_cell_payload(**_CANONICAL_CELL)],
            filing_overrides={"trend_selection": "EXPONENTIAL_LEAST_SQUARES"},
        )
        lin_filing = make_reviewed_filing(
            cells=[create_cell_payload(**_CANONICAL_CELL)],
            filing_overrides={"trend_selection": "LINEAR_LEAST_SQUARES"},
        )
        assert lin_filing["filing_status"] == "REVIEWED"
        assert lin_filing["indicated_change_pct"] == pytest.approx(0.8333, abs=1e-4)
        assert lin_filing["indicated_change_pct"] != pytest.approx(
            exp_filing["indicated_change_pct"], abs=1e-9
        )
        assert lin_filing["indicated_change_pct"] < exp_filing["indicated_change_pct"]


class TestQualityScoreDualVariant:
    """Recency-decayed quality score vs the rejected flat-average variant."""

    def _setup_two_dispositions(self, api):
        insurer, plan = setup_insurer_with_active_plan()
        ins_id, plan_id = insurer["id"], plan["id"]
        # Older disposition: REJECTED with 3 ERROR findings (9400 points).
        sub1 = make_submission(ins_id, plan_id)
        begin_edit(sub1["id"])
        for code in ("E-101", "E-102", "E-103"):
            add_finding(sub1["id"], severity="ERROR", edit_code=code)
        dispose(sub1["id"])
        # Most recent disposition: ACCEPTED_WITH_WARNINGS with 2 WARNING findings (9900 points).
        sub2 = make_submission(
            ins_id, plan_id,
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-09-01T00:00:00Z",
            record_count=50,
            written_premium_cents=2000000,
        )
        begin_edit(sub2["id"])
        add_finding(sub2["id"], severity="WARNING", edit_code="W-201")
        add_finding(sub2["id"], severity="WARNING", edit_code="W-202")
        return insurer, sub2

    def test_quality_score_recency_decay_yields_9733(self, api):
        """PRD §3.2: "Then weight by recency: the most recent submission gets
        weight 1, the next most recent gets weight one half, the next one
        quarter — the k-th most recent submission's weight is one half raised
        to the power of k minus 1."

        Design: Difficulty/dual_variant_calc/insurer_quality_score_recency_decay_vs_flat_average_diverge
        """
        insurer, sub2 = self._setup_two_dispositions(api)
        disposed = dispose(sub2["id"])
        assert disposed["submission_status"] == "ACCEPTED_WITH_WARNINGS"
        refreshed = validate_success(api.get_insurer(insurer["id"], ADMIN))
        assert refreshed["quality_score_bps"] == 9733

    def test_quality_score_differs_from_rejected_flat_average(self, api):
        """PRD §3.2: "The unweighted flat average is expressly not used: the
        geometric decay means the most recent disposition dominates."

        Design: Difficulty/dual_variant_calc/insurer_quality_score_recency_decay_vs_flat_average_diverge
        """
        insurer, sub2 = self._setup_two_dispositions(api)
        disposed = dispose(sub2["id"])
        assert disposed["accepted_record_count"] == 50
        assert disposed["error_finding_count"] == 0
        assert disposed["warning_finding_count"] == 2
        refreshed = validate_success(api.get_insurer(insurer["id"], ADMIN))
        assert refreshed["quality_score_bps"] != 9650


class TestIndicatedChangeWeightNormalization:
    """Mode (a) combinatorial: weights summing above 100 engage the scale-down
    branch of the pinned aggregation."""

    _CELLS = [
        create_cell_payload(class_code="C1", earned_premium_cents=2000000,
                            incurred_loss_cents=1100000, weight_pct=60,
                            current_loss_cost_cents=120000),
        create_cell_payload(class_code="C2", earned_premium_cents=1000000,
                            incurred_loss_cents=700000, weight_pct=60,
                            current_loss_cost_cents=80000),
    ]

    def test_weights_above_100_normalize_down_to_14_8979(self, api):
        """PRD §3.3: "if the weight sum exceeds 100, every weight is scaled
        down by the factor 100 divided by the weight sum so the total
        normalizes to 100; otherwise the weights are used as-is."
        PRD §3.3: "the result is rounded half-up to exactly 4 decimal places —
        the single rounding in the entire computation — and stored as
        `indicated_change_pct`."

        Design: Difficulty/combinatorial_formula/indicated_change_weight_normalization_above_100
        """
        filing = make_reviewed_filing(
            cells=list(self._CELLS),
            filing_overrides={"trend_selection": "EXPONENTIAL_LEAST_SQUARES"},
        )
        assert filing["filing_status"] == "REVIEWED"
        assert filing["indicated_change_pct"] == pytest.approx(14.8979, abs=1e-4)

    def test_normalized_result_differs_from_unscaled_blend(self, api):
        """PRD §3.3: "Cell weights within a filing need not sum to 100 — the
        residual is treated as no-change at aggregation time."
        PRD §3.3: "if the weight sum exceeds 100, every weight is scaled down
        by the factor 100 divided by the weight sum so the total normalizes to
        100; otherwise the weights are used as-is."

        Design: Difficulty/combinatorial_formula/indicated_change_weight_normalization_above_100
        """
        filing = make_reviewed_filing(
            cells=list(self._CELLS),
            filing_overrides={"trend_selection": "EXPONENTIAL_LEAST_SQUARES"},
        )
        # Unscaled blend (no normalization) would be 17.8775; the
        # residual-branch blend (weights as-is, sum 80) would be 9.1608.
        assert filing["indicated_change_pct"] != pytest.approx(17.8775, abs=1e-4)
        assert filing["indicated_change_pct"] != pytest.approx(9.1608, abs=1e-4)


class TestLcmPremiumNestedRounding:
    """Mode (b) combinatorial: per-cell round-then-sum is the pinned order."""

    _CELLS_101 = [
        create_cell_payload(class_code="C1", current_loss_cost_cents=101, weight_pct=40),
        create_cell_payload(class_code="C2", current_loss_cost_cents=101, weight_pct=30),
        create_cell_payload(class_code="C3", current_loss_cost_cents=101, weight_pct=30),
    ]

    def _setup(self, api):
        return setup_adoption_scenario(
            multiplier_pct=150,
            cells=list(self._CELLS_101),
            filing_overrides={"effective_date": "2026-09-02T00:00:00Z"},
            department_overrides={"max_lcm_deviation_pct": 100},
        )

    def test_per_cell_round_then_sum_yields_456(self, api):
        """PRD §3.4: "for each cell, the cell premium is the cell's
        `current_loss_cost_cents` times `multiplier_pct` divided by 100,
        rounded half-up to integer cents, and the adoption's premium is the
        sum of those per-cell rounded amounts."

        Design: Difficulty/combinatorial_formula/lcm_premium_per_cell_round_then_sum_beats_sum_then_round
        """
        scenario = self._setup(api)
        resp = api.authorize_adoption(scenario["adoption"]["id"], ADMIN)
        adoption = validate_success(resp)
        assert adoption["adoption_status"] == "AUTHORIZED"
        assert adoption["authorized_premium_cents"] == 456

    def test_sum_then_round_alternative_455_is_rejected(self, api):
        """PRD §3.4: "The rounding order is pinned — round each cell first,
        then sum. Summing the unrounded products and rounding once would yield
        different cents whenever any cell product has a fractional part of
        half a cent or more, and that alternative is expressly rejected."

        Design: Difficulty/combinatorial_formula/lcm_premium_per_cell_round_then_sum_beats_sum_then_round
        """
        scenario = self._setup(api)
        resp = api.authorize_adoption(scenario["adoption"]["id"], ADMIN)
        adoption = validate_success(resp)
        assert adoption["authorized_premium_cents"] != 455
