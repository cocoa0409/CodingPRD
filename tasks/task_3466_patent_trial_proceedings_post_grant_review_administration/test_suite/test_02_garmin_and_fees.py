"""Combinatorial calculations: Garmin interest-of-justice scoring (PRD §3.6)
and per-brief-then-summed overage fee rounding (PRD §2.8, §3.5).
"""
from test_helpers import (
    api_client,
    assert_discovery_request,
    assert_proceeding,
    create_discovery_request,
    file_brief,
    file_po_response,
    get_proceeding,
    rule_discovery,
    setup_instituted_proceeding,
    validate_success,
    PANEL,
)


class TestGarminEmptyFactorCapAndReplyPhaseBonus:
    def test_uniform_factors_in_instituted_phase_score_below_grant_line(self):
        """PRD §3.6: "The score sums the five factor scores, but if any single
        factor is zero the total is capped at the lesser of the raw sum and 4;
        a request filed while the proceeding stands in `REPLY_WINDOW` earns a
        one-point diligence bonus; and the final score is capped at 10."
        PRD §3.6: "it is granted when its `garmin_score` is at least 6 and
        denied below that line".

        Design: Difficulty/combinatorial_formula/garmin_empty_factor_cap_and_reply_phase_bonus
        """
        world = setup_instituted_proceeding(
            total_claims=5, challenged_claims=(1, 2, 3),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70},
                    {"claim_number": 3, "basis": "ANTICIPATION_102", "score": 60}],
            lead_judge="judge-carol",
        )
        assert world["proceeding"]["phase"] == "INSTITUTED"
        # Filed in INSTITUTED phase: sum [1,1,1,1,1] = 5, no zero cap, no bonus.
        req = create_discovery_request(
            world["proceeding"]["id"], world["petitioner_headers"],
            discovery_type="ADDITIONAL", factor_scores=[1, 1, 1, 1, 1],
        )
        assert_discovery_request(req)
        assert req["garmin_score"] == 5
        assert req["status"] == "PENDING"
        ruled = rule_discovery(req["id"])
        assert ruled["status"] == "DENIED"

    def test_identical_factors_in_reply_window_earn_bonus_and_grant(self):
        """PRD §3.6: "a request filed while the proceeding stands in
        `REPLY_WINDOW` earns a one-point diligence bonus".
        PRD §3.6: "it is granted when its `garmin_score` is at least 6 and
        denied below that line, moving from `PENDING` to `GRANTED` or
        `DENIED`."

        Design: Difficulty/combinatorial_formula/garmin_empty_factor_cap_and_reply_phase_bonus
        """
        world = setup_instituted_proceeding(
            total_claims=5, challenged_claims=(1, 2, 3),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70},
                    {"claim_number": 3, "basis": "ANTICIPATION_102", "score": 60}],
            lead_judge="judge-carol",
        )
        file_po_response(world, 90)  # advances the phase to REPLY_WINDOW
        assert get_proceeding(world["proceeding"]["id"])["phase"] == "REPLY_WINDOW"
        # Identical factor vector as the INSTITUTED-phase filing, +1 bonus.
        req = create_discovery_request(
            world["proceeding"]["id"], world["owner_headers"],
            discovery_type="ADDITIONAL", factor_scores=[1, 1, 1, 1, 1],
        )
        assert req["garmin_score"] == 6
        ruled = rule_discovery(req["id"])
        assert ruled["status"] == "GRANTED"


class TestBriefOverageFeeRoundPerBriefThenSum:
    def _world_with_three_briefs(self):
        world = setup_instituted_proceeding(
            total_claims=5, challenged_claims=(1, 2, 3),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70},
                    {"claim_number": 3, "basis": "ANTICIPATION_102", "score": 60}],
            lead_judge="judge-dana",
        )
        po = file_brief(world["proceeding"]["id"], "PO_RESPONSE", 91,
                        world["owner_headers"])
        reply = file_brief(world["proceeding"]["id"], "PETITIONER_REPLY", 45,
                           world["petitioner_headers"])
        sur = file_brief(world["proceeding"]["id"], "PO_SUR_REPLY", 21,
                         world["owner_headers"])
        return world, po, reply, sur

    def test_each_briefs_overage_fee_is_rounded_individually(self):
        """PRD §3.5: "Beyond the fee-free limit, each additional page is billed
        at 316.25 cents, and the brief's `overage_fee_cents` is that product
        rounded half-up to whole cents — computed per brief first and only
        then accumulated into the proceeding's `total_overage_fee_cents`".

        Design: Difficulty/combinatorial_formula/brief_overage_fee_round_per_brief_then_sum
        """
        _, po, reply, sur = self._world_with_three_briefs()
        # 91-page PO_RESPONSE: 1 overage page -> round_half_up(316.25) = 316.
        assert po["overage_fee_cents"] == 316
        # 45-page PETITIONER_REPLY: exactly at the fee-free limit -> 0.
        assert reply["overage_fee_cents"] == 0
        # 21-page PO_SUR_REPLY: 1 overage page -> 316.
        assert sur["overage_fee_cents"] == 316

    def test_proceeding_total_sums_the_per_brief_rounded_fees(self):
        """PRD §2.8: "two briefs that each run one page over their fee-free
        limit contribute 316 + 316 = 632 cents to the proceeding total under
        the pinned order, whereas summing the raw products first would yield
        632.5, which rounds to 633."

        Design: Difficulty/combinatorial_formula/brief_overage_fee_round_per_brief_then_sum
        """
        world, _, _, _ = self._world_with_three_briefs()
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert_proceeding(proceeding)
        # Pinned order: 316 + 0 + 316 = 632; sum-then-round would give 633.
        assert proceeding["total_overage_fee_cents"] == 632
