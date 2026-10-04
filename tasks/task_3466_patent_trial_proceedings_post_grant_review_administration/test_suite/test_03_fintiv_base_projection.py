"""Fintiv proximity factor is pinned to the BASE projected decision date,
never widened by any extension (PRD §3.4).
"""
from test_helpers import (
    PANEL,
    accord,
    api_client,
    file_petition,
    new_world,
    per_ground_scores,
    validate_success,
)


class TestFintivProximityUsesBaseProjectedFwdDate:
    def _petition_with_far_trial_date(self):
        # Matter: complaint served 2025-12-01 (274 days before the
        # 2026-09-01 filing -> investment +20); trial 2027-10-15 sits beyond
        # the base projection (decision 2026-09-01 + 365 days = 2027-09-01)
        # but inside the would-be extended date (2028-03-02).
        world = new_world(
            total_claims=4, petitioner_name="P5 Corp", owner_name="O5 Corp",
            patent_number="US10000005", title="Ratchet",
            issue_date="2021-02-01T00:00:00Z",
            matters=[{
                "complaint_served_date": "2025-12-01T00:00:00Z",
                "trial_date": "2027-10-15T00:00:00Z",
                "court_name": "W.D. Tex.", "docket_number": "6:25-cv-00100",
            }],
        )
        petition = file_petition(
            world["petitioner"]["id"], world["patent"]["id"],
            challenged_claims=[1, 2],
            grounds=[{"claim_number": 1, "basis": "ANTICIPATION_102"},
                     {"claim_number": 2, "basis": "OBVIOUSNESS_103"}],
        )
        accord(petition["id"])
        return petition

    def test_trial_date_beyond_base_projection_scores_no_proximity(self):
        """PRD §3.4: "40 further points if its `trial_date` is set and falls
        on or before the projected final-decision date".
        PRD §3.4: "The projected final-decision date used for the proximity
        factor is always the base statutory deadline — the decision date plus
        365 days; any extension granted later never retroactively widens that
        comparison date."

        Design: Difficulty/combinatorial_formula/fintiv_proximity_compared_against_base_projected_fwd_never_extended
        """
        petition = self._petition_with_far_trial_date()
        resp = api_client.decide_institution(
            petition["id"],
            {"per_ground_scores": per_ground_scores((1, 90), (2, 85, "OBVIOUSNESS_103")),
             "lead_judge_user_id": "judge-erin"},
            PANEL,
        )
        data = validate_success(resp, 201)
        # base 20 + proximity 0 + investment 20 + stay 0 = 40.
        assert data["fintiv_score"] == 40

    def test_score_below_denial_band_admits_institution(self):
        """PRD §3.4: "Discretionary denial applies exactly when the score is
        at least 70 and the merits were independently met, producing the
        outcome `DENIED_DISCRETIONARY`".

        Design: Difficulty/combinatorial_formula/fintiv_proximity_compared_against_base_projected_fwd_never_extended
        """
        petition = self._petition_with_far_trial_date()
        resp = api_client.decide_institution(
            petition["id"],
            {"per_ground_scores": per_ground_scores((1, 90), (2, 85, "OBVIOUSNESS_103")),
             "lead_judge_user_id": "judge-erin"},
            PANEL,
        )
        data = validate_success(resp, 201)
        # Merits max 90 >= 40 and Fintiv 40 < 70 -> instituted. An
        # implementation widening the comparison by the 183-day extension
        # (to 2028-03-02) would score 80 and deny — the pinned base-date
        # order is what admits institution here.
        assert data["outcome"] == "INSTITUTED"
        assert data["proceeding_id"]
