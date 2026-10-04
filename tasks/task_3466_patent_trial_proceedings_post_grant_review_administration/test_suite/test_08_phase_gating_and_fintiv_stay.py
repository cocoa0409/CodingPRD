"""Cross-entity state dependencies: brief types gated on the proceeding's
phase, and the Fintiv screen flipping on a litigation matter's status
(PRD §3.4, §3.5).
"""
from test_helpers import (
    ApiErrorId,
    accord,
    api_client,
    create_brief_payload,
    create_litigation_matter,
    create_party,
    create_patent,
    decide_institution,
    file_brief,
    file_petition,
    get_proceeding,
    patch_litigation_matter,
    per_ground_scores,
    set_clock,
    setup_instituted_proceeding,
    validate_error,
)


class TestReplyBriefGatedOnProceedingPhase:
    def test_reply_while_instituted_is_rejected_invalid_phase(self):
        """PRD §3.5: "Acceptance of a `PETITIONER_REPLY` requires
        `REPLY_WINDOW` and advances it to `SUR_REPLY_WINDOW`." and "Filings
        against the wrong phase draw `ERR_INVALID_PHASE`."

        Design: Difficulty/cross_entity_state_dependency/reply_brief_gated_on_proceeding_phase
        """
        world = setup_instituted_proceeding(
            total_claims=3, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 66},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 61}],
            lead_judge="judge-lisa",
        )
        assert world["proceeding"]["phase"] == "INSTITUTED"
        resp = api_client.create_brief(
            world["proceeding"]["id"],
            create_brief_payload("PETITIONER_REPLY", 30),
            world["petitioner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PHASE, 409)

    def test_reply_succeeds_once_po_response_advances_the_phase(self):
        """PRD §3.5: "Acceptance of a `PO_RESPONSE` requires the proceeding
        to be in `INSTITUTED` or `REMANDED` phase and advances it to
        `REPLY_WINDOW`."

        Design: Difficulty/cross_entity_state_dependency/reply_brief_gated_on_proceeding_phase
        """
        world = setup_instituted_proceeding(
            total_claims=3, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 66},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 61}],
            lead_judge="judge-lisa",
        )
        # The rejected attempt first (phase INSTITUTED)...
        resp = api_client.create_brief(
            world["proceeding"]["id"],
            create_brief_payload("PETITIONER_REPLY", 30),
            world["petitioner_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PHASE, 409)
        # ...then the PO_RESPONSE opens the reply window and the identical
        # reply call succeeds.
        file_brief(world["proceeding"]["id"], "PO_RESPONSE", 70,
                   world["owner_headers"])
        reply = file_brief(world["proceeding"]["id"], "PETITIONER_REPLY", 30,
                           world["petitioner_headers"])
        assert reply["brief_type"] == "PETITIONER_REPLY"
        assert get_proceeding(world["proceeding"]["id"])["phase"] == "SUR_REPLY_WINDOW"


class TestInstitutionDiscretionFlipsOnMatterStay:
    def _two_petitions(self):
        """Two patents, each with a matter naming the same petitioner
        (served 2025-09-01 — exactly 365 days, not barred; trial 2027-06-01
        within the base projection -> proximity +40). Matter B is STAYED
        before filing; both petitions are accorded."""
        set_clock("2026-09-01T00:00:00Z")
        petitioner = create_party("P15 Corp", "PETITIONER")
        owner = create_party("O15 Corp", "PATENT_OWNER")
        pat_a = create_patent(owner["id"], total_claims=2,
                              patent_number="US10000015A", title="Valve A")
        pat_b = create_patent(owner["id"], total_claims=2,
                              patent_number="US10000015B", title="Valve B")
        create_litigation_matter(
            pat_a["id"], petitioner["id"], "2025-09-01T00:00:00Z",
            trial_date="2027-06-01T00:00:00Z",
            court_name="W.D. Tex.", docket_number="6:25-cv-00501",
        )
        matter_b = create_litigation_matter(
            pat_b["id"], petitioner["id"], "2025-09-01T00:00:00Z",
            trial_date="2027-06-01T00:00:00Z",
            court_name="W.D. Tex.", docket_number="6:25-cv-00502",
        )
        patch_litigation_matter(
            matter_b["id"],
            {"status": "STAYED",
             "expected_litigation_matter_version": matter_b["version"]},
        )
        grounds = [{"claim_number": 1, "basis": "ANTICIPATION_102"},
                   {"claim_number": 2, "basis": "OBVIOUSNESS_103"}]
        pet_a = file_petition(petitioner["id"], pat_a["id"],
                              challenged_claims=[1, 2], grounds=grounds)
        pet_b = file_petition(petitioner["id"], pat_b["id"],
                              challenged_claims=[1, 2], grounds=grounds)
        accord(pet_a["id"])
        accord(pet_b["id"])
        scores = per_ground_scores((1, 80), (2, 75, "OBVIOUSNESS_103"))
        return pet_a, pet_b, scores

    def test_active_parallel_matter_drives_discretionary_denial(self):
        """PRD §3.4: "each qualifying matter contributes a base of 20 points
        for the existence of the parallel case; 40 further points if its
        `trial_date` is set and falls on or before the projected
        final-decision date; 20 further points if strictly more than 180 days
        elapsed between that matter's `complaint_served_date` and the
        petition's `filing_date`; and a 20-point credit if the matter
        currently stands `STAYED`."
        PRD §3.4: "Discretionary denial applies exactly when the score is at
        least 70 and the merits were independently met, producing the outcome
        `DENIED_DISCRETIONARY`".

        Design: Difficulty/cross_entity_state_dependency/institution_discretion_flips_on_litigation_matter_stay
        """
        pet_a, _, scores = self._two_petitions()
        data = decide_institution(pet_a["id"], scores, "judge-liam")
        # ACTIVE matter: base 20 + proximity 40 + investment 20 = 80 >= 70.
        assert data["fintiv_score"] == 80
        assert data["outcome"] == "DENIED_DISCRETIONARY"

    def test_stayed_parallel_matter_drops_score_below_denial_band(self):
        """PRD §3.4: "a 20-point credit if the matter currently stands
        `STAYED`" — the same petition data with the matter stayed scores
        20 + 40 + 20 − 20 = 60, below the 70 denial line, so the petition
        institutes on identical merits.

        Design: Difficulty/cross_entity_state_dependency/institution_discretion_flips_on_litigation_matter_stay
        """
        _, pet_b, scores = self._two_petitions()
        data = decide_institution(pet_b["id"], scores, "judge-liam")
        assert data["fintiv_score"] == 60
        assert data["outcome"] == "INSTITUTED"
