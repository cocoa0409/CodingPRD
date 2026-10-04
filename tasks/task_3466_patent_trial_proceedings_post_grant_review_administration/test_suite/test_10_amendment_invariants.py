"""Compensating invariants: the claim ledger conserved through amendment
grants, and the per-cycle amendment slot budget conserved through withdrawal
(PRD §2.9, §3.6).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    api_client,
    create_amendment_motion,
    create_amendment_motion_payload,
    get_patent,
    get_proceeding,
    get_success_data,
    resolve_amendment_motion,
    setup_instituted_proceeding,
    substitute_claim,
    validate_error,
)


class TestAmendmentGrantConservesClaimsAlive:
    def _granted_world(self):
        world = setup_instituted_proceeding(
            total_claims=5, challenged_claims=(1, 2, 3),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 72},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 68},
                    {"claim_number": 3, "basis": "ANTICIPATION_102", "score": 64}],
            lead_judge="judge-paul",
        )
        motion = create_amendment_motion(
            world["proceeding"]["id"], world["owner_headers"], (1,)
        )
        resolve_amendment_motion(
            motion["id"], "GRANTED", PANEL,
            rationale="Substitute claim 1 is responsive to the instituted "
                      "anticipation ground under the PHILLIPS construction.",
        )
        return world, motion

    def test_grant_swaps_claim_and_leaves_claims_alive_unchanged(self):
        """PRD §2.9: "When an amendment motion is granted, each substitute
        claim swaps an original claim out of the patent: `total_claims`
        increases by one, `claims_cancelled_count` increases by one because
        the original is cancelled, and `claims_amended_count` increases by
        one — `claims_alive` is therefore unchanged by the swap."

        Design: Difficulty/compensating_invariant/amendment_grant_conserves_claims_alive
        """
        world, _ = self._granted_world()
        patent = get_patent(world["patent"]["id"])
        assert patent["claims_alive"] == 5  # identical to the pre-grant value
        assert patent["total_claims"] == 6
        assert patent["claims_cancelled_count"] == 1
        assert patent["claims_amended_count"] == 1

    def test_grant_consumes_the_amendment_slot_permanently(self):
        """PRD §3.6: "A denial spends the motion of right: the amendment slot
        stays consumed" — and a grant consumes it likewise, since the
        per-cycle invariant counts motions in `FILED`, `GRANTED`, or `DENIED`
        status: "the slots available plus the cycle's motions in `FILED`,
        `GRANTED`, or `DENIED` status always total exactly one."
        PRD §3.6: "Substitute claims are construed under the `PHILLIPS`
        standard — the same construction standard a district court would
        apply — recorded as the motion's fixed `construction_standard`."

        Design: Difficulty/compensating_invariant/amendment_grant_conserves_claims_alive
        """
        world, motion = self._granted_world()
        motion_after = get_success_data(
            api_client.list_amendment_motions(world["proceeding"]["id"], PANEL)
        )
        granted = [m for m in motion_after if m["id"] == motion["id"]][0]
        assert granted["status"] == "GRANTED"
        assert granted["construction_standard"] == "PHILLIPS"
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert proceeding["amendment_slots_available"] == 0
        # Ledger conservation after the swap: alive + cancelled == total.
        patent = get_patent(world["patent"]["id"])
        assert patent["claims_alive"] + patent["claims_cancelled_count"] == 6


class TestAmendmentSlotWithdrawalConservesCycleBudget:
    def test_second_motion_while_first_filed_is_quota_rejected(self):
        """PRD §3.6: "Filing a motion consumes the slot immediately: the
        motion is created in `FILED` status, stamped with the current
        `cycle`, and the slot count drops by one — maintaining the per-cycle
        invariant that the slots available plus the cycle's motions in
        `FILED`, `GRANTED`, or `DENIED` status always total exactly one.
        Filing with no slot available is rejected with
        `ERR_AMENDMENT_QUOTA_EXCEEDED`".

        Design: Difficulty/compensating_invariant/amendment_slot_withdrawal_conserves_cycle_budget
        """
        world = setup_instituted_proceeding(
            total_claims=4, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 71},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 62}],
            lead_judge="judge-quinn",
        )
        create_amendment_motion(
            world["proceeding"]["id"], world["owner_headers"], (1,)
        )
        assert get_proceeding(world["proceeding"]["id"])[
            "amendment_slots_available"
        ] == 0
        resp = api_client.create_amendment_motion(
            world["proceeding"]["id"],
            create_amendment_motion_payload([substitute_claim(2)]),
            world["owner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_QUOTA_EXCEEDED, 422)

    def test_withdrawal_returns_the_slot_for_reuse(self):
        """PRD §3.6: "A withdrawal is compensating: `amendment_slots_available`
        rises by one, returning the slot for reuse within the cycle."

        Design: Difficulty/compensating_invariant/amendment_slot_withdrawal_conserves_cycle_budget
        """
        world = setup_instituted_proceeding(
            total_claims=4, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 71},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 62}],
            lead_judge="judge-quinn",
        )
        motion = create_amendment_motion(
            world["proceeding"]["id"], world["owner_headers"], (1,)
        )
        resp = api_client.create_amendment_motion(
            world["proceeding"]["id"],
            create_amendment_motion_payload([substitute_claim(2)]),
            world["owner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AMENDMENT_QUOTA_EXCEEDED, 422)
        # WITHDRAWN returns the slot; the previously rejected filing succeeds.
        withdrawn = resolve_amendment_motion(
            motion["id"], "WITHDRAWN", world["owner_headers"]
        )
        assert withdrawn["status"] == "WITHDRAWN"
        motion2 = create_amendment_motion(
            world["proceeding"]["id"], world["owner_headers"], (2,)
        )
        assert motion2["status"] == "FILED"
        # slots 0 + one cycle-0 motion in {FILED, GRANTED, DENIED} == 1;
        # the WITHDRAWN motion is excluded from the count.
        assert get_proceeding(world["proceeding"]["id"])[
            "amendment_slots_available"
        ] == 0
