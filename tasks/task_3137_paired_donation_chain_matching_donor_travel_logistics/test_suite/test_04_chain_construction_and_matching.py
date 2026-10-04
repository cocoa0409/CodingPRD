"""Chain construction, match scoring, and crossmatch review tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_altruistic_donor,
    create_center,
    create_in_pool_pair,
    execute_chain_run,
    find_offer,
    get_success_data,
    list_offers,
    make_center_coordinator_headers,
    reset_clock,
    setup_two_pair_chain,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import _parse
from datetime import timedelta

OPERATOR = TEST_USERS["match_operator_headers"]
ADMIN = TEST_USERS["registry_admin_headers"]


class TestMatchScore:
    def test_match_score_multifactor_weighted_combination(self, api):
        """PRD §3.4: "The composite `match_score_bps` is computed at proposal
        time as follows: the KDRI component is `10000` reduced by `10000` times
        the proportion of the donor's `kdri_score` along the range from
        `KDRI_MIN` 20 to `KDRI_MAX` 250, clamped to the closed range from 0 to
        10000. The HLA penalty is `hla_mismatch_count` multiplied by
        `HLA_PENALTY_PER_LOCUS_BPS` of 500 basis points. The waiting-time bonus
        is the recipient's `waiting_time_days` multiplied by
        `WAIT_BONUS_PER_DAY_BPS` of 5, capped at `WAIT_BONUS_CAP_BPS` of 1500.
        The priority bonus is `PRIORITY_BOOST_BPS` of 2000 if the recipient's
        `priority_boost_active` is true, zero otherwise. The cPRA bonus is the
        recipient's `cpra_percent` multiplied by `CPRA_BONUS_PER_PCT_BPS` of 20
        — high sensitization is rewarded, because matching a highly sensitized
        recipient is valuable. The raw score is the KDRI component, minus the
        HLA penalty, plus the waiting-time bonus, plus the priority bonus, plus
        the cPRA bonus. If the pair is ABO-incompatible, or if
        `unacceptable_antigen_hit` is true, the score is zero outright;
        otherwise the raw score is floored at 0 and capped at 10000 to produce
        `match_score_bps`."
        PRD §3.4: "`hla_mismatch_count` counts, across the three loci, how many
        have zero shared alleles between donor and recipient — a value from 0
        to 3."
        PRD §3.3 Step 3: chains open from ALTRUISTIC starters; the canonical
        pool is seeded with an altruistic donor. kdri=89 chosen so that
        (89-20)*10000/230 = 3000 exactly — integer division is unambiguous.

        Design: Difficulty/combinatorial_formula/match_score_multifactor_weighted_combination
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        # Pair 1: donor A (kdri=89) at A, recipient B (cpra=20) at B.
        p1 = create_in_pool_pair(
            center_a, center_b, donor_abo="A", recipient_abo="B",
            donor_kdri=89, recipient_cpra=20,
            donor_hla={"hla_a": "A02,A24", "hla_b": "B07,B44",
                       "hla_drb1": "DRB1*04,DRB1*07"},
        )
        # Pair 2: donor B (kdri=89) at B, recipient A (cpra=30) at A.
        # Higher cpra on p2's recipient pulls the altruistic starter toward
        # p2.recipient, so position-2 lands on p2.donor -> p1.recipient.
        p2 = create_in_pool_pair(
            center_b, center_a, donor_abo="B", recipient_abo="A",
            donor_kdri=89, recipient_cpra=30,
            donor_hla={"hla_a": "A01,A03", "hla_b": "B08,B15",
                       "hla_drb1": "DRB1*01,DRB1*03"},
        )
        create_altruistic_donor(center_a, abo_type="O")
        execute_chain_run("run-score")
        offers = list_offers()
        assert len(offers) == 2, f"expected 2 offers, got {len(offers)}"
        # Edge donor p2 (B, kdri=89) -> recipient p1 (B, cpra=20):
        #   kdri_component = 10000 - 69*10000/230 = 10000 - 3000 = 7000
        #   hla_penalty = 3*500 = 1500; wait_bonus = 0; cpra_bonus = 400
        #   raw = 7000 - 1500 + 0 + 0 + 400 = 5900
        target = find_offer(p2["donor"]["id"], p1["recipient"]["id"])
        assert target["match_score_bps"] == 5900
        assert target["hla_mismatch_count"] == 3
        assert target["abo_compatible"] is True
        assert target["unacceptable_antigen_hit"] is False

    def test_match_score_other_edge_of_canonical_pool(self, api):
        """PRD §3.4: "The composite `match_score_bps` is computed at proposal
        time as follows: the KDRI component is `10000` reduced by `10000` times
        the proportion of the donor's `kdri_score` along the range from
        `KDRI_MIN` 20 to `KDRI_MAX` 250, clamped to the closed range from 0 to
        10000. The HLA penalty is `hla_mismatch_count` multiplied by
        `HLA_PENALTY_PER_LOCUS_BPS` of 500 basis points."
        PRD §3.4: "If the pair is ABO-incompatible, or if
        `unacceptable_antigen_hit` is true, the score is zero outright;
        otherwise the raw score is floored at 0 and capped at 10000 to produce
        `match_score_bps`."

        Design: Difficulty/combinatorial_formula/match_score_multifactor_weighted_combination
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        # Higher cpra on p1's recipient pulls the altruistic starter toward
        # p1.recipient, so position-2 lands on p1.donor -> p2.recipient.
        p1 = create_in_pool_pair(
            center_a, center_b, donor_abo="A", recipient_abo="B",
            donor_kdri=89, recipient_cpra=30,
            donor_hla={"hla_a": "A02,A24", "hla_b": "B07,B44",
                       "hla_drb1": "DRB1*04,DRB1*07"},
        )
        p2 = create_in_pool_pair(
            center_b, center_a, donor_abo="B", recipient_abo="A",
            donor_kdri=89, recipient_cpra=20,
            donor_hla={"hla_a": "A01,A03", "hla_b": "B08,B15",
                       "hla_drb1": "DRB1*01,DRB1*03"},
        )
        create_altruistic_donor(center_a, abo_type="O")
        execute_chain_run("run-score-2")
        # Edge donor p1 (A, kdri=89) -> recipient p2 (A, cpra=20):
        #   kdri_component = 10000 - 69*10000/230 = 7000
        #   hla_penalty = 1500; wait_bonus = 0; cpra_bonus = 400
        #   raw = 7000 - 1500 + 0 + 0 + 400 = 5900
        target = find_offer(p1["donor"]["id"], p2["recipient"]["id"])
        assert target["match_score_bps"] == 5900
        assert target["hla_mismatch_count"] == 3
        assert target["abo_compatible"] is True

class TestCrossmatchDecision:
    def _setup_pending_offers(self, api):
        ctx = setup_two_pair_chain()
        return ctx

    def test_crossmatch_decision_threshold_variants_negative_1500(self, api):
        """PRD §3.4: "a `NEGATIVE` result with `dsa_mfi_max` strictly below the
        `DSA_PASS_THRESHOLD` of 1000 yields `PASS`; a `NEGATIVE` result with
        `dsa_mfi_max` at or above 1000 yields `FAIL` (a silent DSA); a
        `WEAK_POSITIVE` result with `dsa_mfi_max` strictly below the
        `DSA_WEAK_THRESHOLD` of 3000 yields `PASS`; a `WEAK_POSITIVE` result at
        or above 3000 yields `FAIL`".

        Design: Difficulty/dual_variant_calc/crossmatch_decision_threshold_variants_at_dsa_boundaries
        """
        ctx = self._setup_pending_offers(api)
        offer = ctx["offers"][0]
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": "NEGATIVE", "flow_cytometry_channel_shift": 100,
             "dsa_mfi_max": 1500, "review_notes": "variant check"},
            coord,
        )
        review = validate_success(resp)
        assert review["decision"] == "FAIL"

    def test_crossmatch_decision_threshold_variants_weak_1500(self, api):
        """PRD §3.4: "a `NEGATIVE` result with `dsa_mfi_max` strictly below the
        `DSA_PASS_THRESHOLD` of 1000 yields `PASS`; a `NEGATIVE` result with
        `dsa_mfi_max` at or above 1000 yields `FAIL` (a silent DSA); a
        `WEAK_POSITIVE` result with `dsa_mfi_max` strictly below the
        `DSA_WEAK_THRESHOLD` of 3000 yields `PASS`; a `WEAK_POSITIVE` result at
        or above 3000 yields `FAIL`".

        Design: Difficulty/dual_variant_calc/crossmatch_decision_threshold_variants_at_dsa_boundaries
        """
        ctx = self._setup_pending_offers(api)
        offer = ctx["offers"][0]
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": "WEAK_POSITIVE", "flow_cytometry_channel_shift": 200,
             "dsa_mfi_max": 1500, "review_notes": "variant check"},
            coord,
        )
        review = validate_success(resp)
        assert review["decision"] == "PASS"

    @pytest.mark.parametrize("dsa,expected", [(999, "PASS"), (1000, "FAIL")])
    def test_crossmatch_dsa_threshold_boundary_999_vs_1000(self, api, dsa, expected):
        """PRD §3.4: "a `NEGATIVE` result with `dsa_mfi_max` strictly below the
        `DSA_PASS_THRESHOLD` of 1000 yields `PASS`; a `NEGATIVE` result with
        `dsa_mfi_max` at or above 1000 yields `FAIL` (a silent DSA)".

        Design: Difficulty/boundary_precision_check/crossmatch_dsa_threshold_boundary_999_vs_1000
        """
        ctx = self._setup_pending_offers(api)
        offer = ctx["offers"][0]
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": "NEGATIVE", "flow_cytometry_channel_shift": 100,
             "dsa_mfi_max": dsa, "review_notes": "boundary"},
            coord,
        )
        review = validate_success(resp)
        assert review["decision"] == expected

    @pytest.mark.parametrize("virtual_result", ["INDETERMINATE", "STRONG_POSITIVE"])
    def test_crossmatch_indeterminate_and_strong_positive_fail(self, api, virtual_result):
        """PRD §3.4: "any `STRONG_POSITIVE` yields `FAIL` regardless of MFI; and
        `INDETERMINATE` yields `FAIL` on conservative grounds."

        Design: Difficulty/dual_variant_calc/crossmatch_decision_indeterminate_vs_strong_positive
        """
        ctx = self._setup_pending_offers(api)
        offer = ctx["offers"][0]
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": virtual_result, "flow_cytometry_channel_shift": 50,
             "dsa_mfi_max": 0, "review_notes": "conservative"},
            coord,
        )
        review = validate_success(resp)
        assert review["decision"] == "FAIL"

    def test_crossmatch_negative_zero_mfi_passes(self, api):
        """PRD §3.4: "a `NEGATIVE` result with `dsa_mfi_max` strictly below the
        `DSA_PASS_THRESHOLD` of 1000 yields `PASS`".

        Design: Difficulty/dual_variant_calc/crossmatch_decision_indeterminate_vs_strong_positive
        """
        ctx = self._setup_pending_offers(api)
        offer = ctx["offers"][0]
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": "NEGATIVE", "flow_cytometry_channel_shift": 50,
             "dsa_mfi_max": 0, "review_notes": "clean"},
            coord,
        )
        review = validate_success(resp)
        assert review["decision"] == "PASS"


class TestCrossmatchDeadline:
    def test_review_deadline_passed_error_triggered(self, api):
        """PRD §3.4: "the logical clock must not have reached the offer's
        `crossmatch_deadline_utc` (otherwise `ERR_REVIEW_DEADLINE_PASSED`)".

        Design: Corner/errors/review_deadline_passed_error_triggered
        """
        ctx = setup_two_pair_chain()
        offer = ctx["offers"][0]
        deadline = _parse(offer["crossmatch_deadline_utc"])
        # Move the logical clock strictly past the crossmatch deadline.
        get_success_data(
            api.set_clock((deadline + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"), ADMIN)
        )
        coord = make_center_coordinator_headers(offer["recipient_center_id"])
        resp = api.submit_crossmatch_review(
            offer["id"],
            {"virtual_result": "NEGATIVE", "flow_cytometry_channel_shift": 100,
             "dsa_mfi_max": 0, "review_notes": "late"},
            coord,
        )
        # PRD §2.5 priority: state-machine legality (9) runs before review-
        # deadline temporal checks (11). The clock advance may have auto-failed
        # the offer, in which case the state check fires first; otherwise the
        # deadline check fires. Both are PRD-consistent surfaces.
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_REVIEW_DEADLINE_PASSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )
