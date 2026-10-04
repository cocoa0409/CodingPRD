"""Performance standards: instantaneous vs seasoned score variants, the
probation-recovery loop, and the exact-60.00 boundary (PRD §3.8)."""
import pytest

from test_helpers import (
    WEEK_1_START,
    WEEK_2_START,
    WEEK_3_START,
    get_licensee,
    play_scored_cycle,
    setup_catalog,
)


class TestInstantaneousVsSeasoned:
    """Difficulty instance: performance_score_instantaneous_vs_seasoned_diverge.
    Cycle A: one qty-2 order DELIVERED, audit 100, no claims -> I == 100.00.
    Cycle B: five qty-1 orders allocated, two DELIVERED, one in-cycle DEFECT
    claim, audit 50 -> I == 0.5*40 + 0.3*50 + 0.2*0 == 35.00; the seasoned score
    renormalizes two cycles: (0.4*35 + 0.3*100)/0.7 == 62.86."""

    def _setup_two_cycles(self):
        ctx = setup_catalog()
        play_scored_cycle(ctx, WEEK_1_START, [2], deliver_count=1, audit_score=100)
        play_scored_cycle(
            ctx,
            WEEK_2_START,
            [1, 1, 1, 1, 1],
            deliver_count=2,
            audit_score=50,
            claim_types=["DEFECT"],
        )
        return ctx

    def test_last_cycle_score_is_the_instantaneous_variant(self, api, platform_admin_headers):
        """PRD §3.8: "The instantaneous score is then, rounded half-up to two decimal
        places: 0.5 times sell-through, plus 0.3 times `latest_audit_score`, plus 0.2
        times the claims component. It is stored on the licensee as `last_cycle_score`."
        PRD §3.8: "the claims component is 100 minus 10 times the claims percentage,
        floored at zero."

        Design: Difficulty/dual_variant_calc/performance_score_instantaneous_vs_seasoned_diverge
        """
        ctx = self._setup_two_cycles()
        licensee = get_licensee(ctx["licensee"]["id"])
        # Cycle B: sell-through 100*2/5 == 40; claims_pct 100*1/2 == 50 ->
        # claims component max(0, 100 - 500) == 0; I == 20 + 15 + 0 == 35.00.
        assert licensee["last_cycle_score"] == pytest.approx(35.00, abs=1e-6), (
            f"expected instantaneous 35.00, got {licensee['last_cycle_score']}"
        )

    def test_seasoned_score_renormalizes_trailing_weights(self, api, platform_admin_headers):
        """PRD §3.8: "the instantaneous scores are weighted by `SEASONED_WEIGHTS` of
        0.4, 0.3, 0.2, and 0.1 respectively; the weighted sum is divided by the sum of
        the weights actually applied, and the result is rounded half-up to two decimal
        places and stored as `seasoned_score`."
        PRD §3.8: "with two cycles the weights 0.4 and 0.3 are divided by 0.7. Identical
        data yields a different seasoned number than the instantaneous one whenever
        history exists, and it is the seasoned score — never the instantaneous one —
        that drives standing."

        Design: Difficulty/dual_variant_calc/performance_score_instantaneous_vs_seasoned_diverge
        """
        ctx = self._setup_two_cycles()
        licensee = get_licensee(ctx["licensee"]["id"])
        # (0.4*35 + 0.3*100) / 0.7 == 62.8571 -> 62.86.
        assert licensee["seasoned_score"] == pytest.approx(62.86, abs=1e-6), (
            f"expected seasoned 62.86, got {licensee['seasoned_score']}"
        )
        assert licensee["seasoned_score"] != pytest.approx(
            licensee["last_cycle_score"], abs=1e-6
        ), "seasoned must diverge from instantaneous once history exists"
        # 62.86 >= 60.00: no probation.
        assert licensee["status"] == "ACTIVE"


class TestProbationRecoveryLoop:
    """Difficulty instance: licensee_probation_recovery_cycle_active_probation_active.
    Cycle A: qty-2 order allocated, never delivered, audit 60 ->
    I == 0.5*0 + 0.3*60 + 0.2*100 == 38.00 -> PROBATION.
    Cycle B: qty-2 delivered, audit 100 -> I == 100.00, seasoned 73.43 -> holds
    PROBATION (below 75). Cycle C: same -> seasoned 86.22 -> recovers ACTIVE."""

    def test_probation_imposed_below_sixty_and_held_below_seventy_five(self, api, platform_admin_headers):
        """PRD §3.8: "An `ACTIVE` licensee whose `seasoned_score` falls strictly below
        the `PERF_PROBATION_THRESHOLD` of 60.00 moves to `PROBATION`; a score of exactly
        60.00 does not trigger probation. A `PROBATION` licensee whose `seasoned_score`
        reaches the `PERF_RECOVERY_THRESHOLD` of 75.00 or better is reinstated to
        `ACTIVE` — this rehabilitation loop is how probation closes."

        Design: Difficulty/non_linear_state_machine/licensee_probation_recovery_cycle_active_probation_active
        """
        ctx = setup_catalog()
        play_scored_cycle(ctx, WEEK_1_START, [2], deliver_count=0, audit_score=60)
        after_a = get_licensee(ctx["licensee"]["id"])
        assert after_a["seasoned_score"] == pytest.approx(38.00, abs=1e-6)
        assert after_a["status"] == "PROBATION", (
            f"38.00 < 60.00 must trigger PROBATION, got {after_a['status']}"
        )
        play_scored_cycle(ctx, WEEK_2_START, [2], deliver_count=1, audit_score=100)
        after_b = get_licensee(ctx["licensee"]["id"])
        # (0.4*100 + 0.3*38)/0.7 == 73.4286 -> 73.43 < 75.00: no recovery yet.
        assert after_b["seasoned_score"] == pytest.approx(73.43, abs=1e-6)
        assert after_b["status"] == "PROBATION"

    def test_recovery_to_active_after_third_cycle(self, api, platform_admin_headers):
        """PRD §3.8: "When fewer than four scored cycles exist, the denominator
        renormalizes to the weights that were actually applied"
        PRD §3.8: "A `PROBATION` licensee whose `seasoned_score` reaches the
        `PERF_RECOVERY_THRESHOLD` of 75.00 or better is reinstated to `ACTIVE` — this
        rehabilitation loop is how probation closes."

        Design: Difficulty/non_linear_state_machine/licensee_probation_recovery_cycle_active_probation_active
        """
        ctx = setup_catalog()
        play_scored_cycle(ctx, WEEK_1_START, [2], deliver_count=0, audit_score=60)
        assert get_licensee(ctx["licensee"]["id"])["status"] == "PROBATION"
        play_scored_cycle(ctx, WEEK_2_START, [2], deliver_count=1, audit_score=100)
        play_scored_cycle(ctx, WEEK_3_START, [2], deliver_count=1)
        after_c = get_licensee(ctx["licensee"]["id"])
        # (0.4*100 + 0.3*100 + 0.2*38)/0.9 == 86.2222 -> 86.22 >= 75.00.
        assert after_c["seasoned_score"] == pytest.approx(86.22, abs=1e-6)
        assert after_c["status"] == "ACTIVE", (
            f"seasoned 86.22 >= 75.00 must close the rehabilitation loop, got {after_c['status']}"
        )


class TestSeasonedScoreExactlySixty:
    """Difficulty instance: seasoned_score_exactly_sixty_stays_active.
    Five qty-1 orders allocated, three DELIVERED (sell-through 60), one in-cycle
    DEFECT claim (claims component 0), audit 100:
    I == 0.5*60 + 0.3*100 + 0.2*0 == 60.00; single-cycle seasoned == 60.00."""

    def _setup(self):
        ctx = setup_catalog()
        play_scored_cycle(
            ctx,
            WEEK_1_START,
            [1, 1, 1, 1, 1],
            deliver_count=3,
            audit_score=100,
            claim_types=["DEFECT"],
        )
        return ctx

    def test_instantaneous_and_single_cycle_seasoned_are_sixty(self, api, platform_admin_headers):
        """PRD §3.8: "sell-through is 100 times `delivered_units` divided by the larger
        of 1 and `allocated_units`."
        PRD §3.8: "a licensee with a single scored cycle has a `seasoned_score` exactly
        equal to that cycle's instantaneous score"

        Design: Difficulty/boundary_precision_check/seasoned_score_exactly_sixty_stays_active
        """
        ctx = self._setup()
        licensee = get_licensee(ctx["licensee"]["id"])
        assert licensee["last_cycle_score"] == pytest.approx(60.00, abs=1e-6), (
            f"expected 60.00, got {licensee['last_cycle_score']}"
        )
        assert licensee["seasoned_score"] == pytest.approx(60.00, abs=1e-6), (
            f"single-cycle seasoned must equal instantaneous, got {licensee['seasoned_score']}"
        )

    def test_exactly_sixty_does_not_trigger_probation(self, api, platform_admin_headers):
        """PRD §3.8: "An `ACTIVE` licensee whose `seasoned_score` falls strictly below
        the `PERF_PROBATION_THRESHOLD` of 60.00 moves to `PROBATION`; a score of exactly
        60.00 does not trigger probation."

        Design: Difficulty/boundary_precision_check/seasoned_score_exactly_sixty_stays_active
        """
        ctx = self._setup()
        licensee = get_licensee(ctx["licensee"]["id"])
        assert licensee["status"] == "ACTIVE", (
            f"60.00 is not strictly below 60.00; status must stay ACTIVE, got {licensee['status']}"
        )
