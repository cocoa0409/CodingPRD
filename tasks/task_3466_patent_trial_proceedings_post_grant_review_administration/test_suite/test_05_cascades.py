"""Depth-3 cascades: full-cancellation stay cascade and the remand estoppel
unwind (PRD §2.9, §2.10, §3.8, §3.9).
"""
from test_helpers import (
    get_litigation_matter,
    get_patent,
    get_proceeding,
    issue_final_decision,
    decide_appeal,
    outcomes_payload,
    patch_litigation_matter,
    set_clock,
    setup_decision_phase,
    setup_decided_with_appeal,
    setup_instituted_proceeding,
)


def _cancellation_world():
    # Matter M: served 2025-12-01 (274 days -> investment +20), trial
    # 2028-06-01 (beyond the base projection -> proximity 0): Fintiv 40,
    # institution allowed. Institution auto-stays M (INSTITUTION_STAY); the
    # setup then lifts the stay so the matter is ACTIVE at decision time.
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1, 2),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 95},
                {"claim_number": 2, "basis": "ANTICIPATION_102", "score": 90}],
        lead_judge="judge-hank",
        petitioner_name="P8 Corp", owner_name="O8 Corp",
        matters=[{
            "complaint_served_date": "2025-12-01T00:00:00Z",
            "trial_date": "2028-06-01T00:00:00Z",
            "court_name": "N.D. Cal.", "docket_number": "3:25-cv-00200",
        }],
    )
    matter = world["matters"][0]
    assert matter["status"] == "ACTIVE"
    stayed = get_litigation_matter(matter["id"])
    assert stayed["status"] == "STAYED" and stayed["stay_reason"] == "INSTITUTION_STAY"
    patch_litigation_matter(
        matter["id"],
        {"status": "ACTIVE",
         "expected_litigation_matter_version": stayed["version"]},
    )
    world = setup_decision_phase(
        world, hearing_outcome="WAIVED", waive_headers=world["owner_headers"],
        po_pages=70, reply_pages=30,
        hearing_start="2027-02-01T09:00:00Z", hearing_end="2027-02-01T10:00:00Z",
    )
    return world, matter


class TestFullCancellationCascade:
    def test_decision_moves_proceeding_and_fully_cancels_the_patent(self):
        """PRD §3.8: "The proceeding moves `DECISION_PHASE → DECIDED` and its
        `estoppel_applied` flag is set true."
        PRD §2.9: "if `claims_alive` is zero the patent becomes
        `FULLY_CANCELLED`".

        Design: Difficulty/transitive_cascade/fwd_full_cancellation_cascades_proceeding_patent_litigation_stay
        """
        world, _ = _cancellation_world()
        issue_final_decision(
            world["proceeding"]["id"],
            outcomes_payload((1, "UNPATENTABLE"), (2, "UNPATENTABLE")),
        )
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert proceeding["phase"] == "DECIDED"
        assert proceeding["estoppel_applied"] is True
        patent = get_patent(world["patent"]["id"])
        assert patent["status"] == "FULLY_CANCELLED"
        assert patent["claims_alive"] == 0
        assert patent["claims_cancelled_count"] == 2
        # Conserved ledger: alive + cancelled == total.
        assert patent["claims_alive"] + patent["claims_cancelled_count"] == 2

    def test_active_matter_auto_stays_with_patent_cancelled_and_estoppel(self):
        """PRD §3.8: "if the reconciliation leaves the patent
        `FULLY_CANCELLED`, every still-`ACTIVE` litigation matter for the
        patent is automatically stayed with `stay_reason` set to
        `PATENT_CANCELLED`; matters already `STAYED` keep their existing
        reason."
        PRD §3.8: "every litigation matter for the patent that names the
        petitioner as defendant — whatever its current status, including the
        terminal ones — receives `estoppel_claims` equal to the petition's
        `challenged_claims`".

        Design: Difficulty/transitive_cascade/fwd_full_cancellation_cascades_proceeding_patent_litigation_stay
        """
        world, matter = _cancellation_world()
        issue_final_decision(
            world["proceeding"]["id"],
            outcomes_payload((1, "UNPATENTABLE"), (2, "UNPATENTABLE")),
        )
        matter_after = get_litigation_matter(matter["id"])
        # The matter was ACTIVE before the decision (the setup lifted the
        # institution stay), so this stay is caused by the patent flip.
        assert matter_after["status"] == "STAYED"
        assert matter_after["stay_reason"] == "PATENT_CANCELLED"
        assert sorted(matter_after["estoppel_claims"]) == [1, 2]


class TestRemandUnwindsEstoppel:
    def _remanded_world(self):
        # FWD: claim 1 UNPATENTABLE, claims 2-3 NOT_UNPATENTABLE ->
        # PARTIALLY_CANCELLED, estoppel [1,2,3]; owner appeals; remand.
        world = setup_decided_with_appeal(
            institute_kw=dict(
                total_claims=3, challenged_claims=(1, 2, 3),
                scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 85},
                        {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 72},
                        {"claim_number": 3, "basis": "ANTICIPATION_102", "score": 55}],
                lead_judge="judge-iris",
                petitioner_name="P9 Corp", owner_name="O9 Corp",
                matters=[{
                    "complaint_served_date": "2025-12-01T00:00:00Z",
                    "trial_date": "2028-06-01T00:00:00Z",
                    "court_name": "D. Del.", "docket_number": "1:25-cv-00300",
                }],
            ),
            appellant="owner",
            outcomes=outcomes_payload(
                (1, "UNPATENTABLE"), (2, "NOT_UNPATENTABLE"),
                (3, "NOT_UNPATENTABLE"),
            ),
            hearing_start="2027-03-15T10:00:00Z", hearing_end="2027-03-15T11:00:00Z",
            hearing_outcome="HELD",
        )
        matter = world["matters"][0]
        mid_fight = get_litigation_matter(matter["id"])
        assert sorted(mid_fight["estoppel_claims"]) == [1, 2, 3]
        assert get_patent(world["patent"]["id"])["status"] == "PARTIALLY_CANCELLED"
        set_clock("2027-10-01T00:00:00Z")
        decide_appeal(world["appeal"]["id"], "VACATED_AND_REMANDED",
                      remand_instructions="RECONSIDER")
        return world, matter

    def test_remand_returns_proceeding_and_patent_to_review(self):
        """PRD §3.9: "In the same stroke the patent returns from
        `PARTIALLY_CANCELLED`, `AMENDED`, or `CONFIRMED` to `IN_REVIEW`".

        Design: Difficulty/transitive_cascade/remand_unwinds_estoppel_through_proceeding_and_patent
        """
        world, _ = self._remanded_world()
        proceeding = get_proceeding(world["proceeding"]["id"])
        assert proceeding["phase"] == "REMANDED"
        assert proceeding["estoppel_applied"] is False
        assert proceeding["briefing_cycle"] == 1
        assert get_patent(world["patent"]["id"])["status"] == "IN_REVIEW"

    def test_remand_clears_estoppel_claims_on_litigation_matters(self):
        """PRD §3.9: "every litigation matter for the patent has its
        `estoppel_claims` cleared to empty."

        Design: Difficulty/transitive_cascade/remand_unwinds_estoppel_through_proceeding_and_patent
        """
        world, matter = self._remanded_world()
        matter_after = get_litigation_matter(matter["id"])
        # Cleared because the patent re-entered review, not because of any
        # direct matter write.
        assert matter_after["estoppel_claims"] == []
