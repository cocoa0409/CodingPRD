"""Boundaries that sit exactly on a gate (PRD §3.1, §2.6)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_season,
    onboard_partner,
    record_round,
    set_clock,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _clinic(legal_name, state, registry_id, ein, recipients):
    return onboard_partner(
        legal_name=legal_name,
        partner_type="COMMUNITY_HEALTH_CLINIC",
        operating_region="SOUTHEAST",
        operating_state_code=state,
        registry_id=registry_id,
        ein=ein,
        founded_year=1988,
        unduplicated_recipients_per_facility=recipients,
        need_tier="LOW",
    )


class TestNeedScoreAccessBoundaryAtTheGate:
    """Difficulty/boundary_precision_check — the access cap lands one point from the gate."""

    def test_19999_recipients_scores_39_and_the_approval_is_refused(self, api):
        """PRD §3.1: "A separate access component is added: the partner's average unduplicated recipients per facility divided by one thousand in truncating integer division, capped at 20."
        PRD §3.1: "It is assembled from a base value that depends on the partner's declared need band and a regional adjustment, with the band's base drawn from the partner type (a disaster relief organization scores 95, a domestic violence shelter 83, a homeless shelter 70, a veteran outreach organization 61, a youth outreach organization 52, and a community health clinic 20) and the adjustment drawn from the operating region (the midwest adds 6, the northeast 3, the southwest 2, the southeast 0 and the west subtracts 2)."
        PRD §3.1: "Independently, the computed `need_score` must be at least 40; a score below that threshold is rejected with `ERR_NEED_SCORE_BELOW_MINIMUM` (HTTP 409) even when every verification flag is true."
        PRD §3.1: "When the points are 3 or fewer the declared band's base is used unchanged."

        Design: Difficulty/boundary_precision_check/need_score_zero_access_boundary_sits_at_exactly_one_thousand_recipients
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        below = _clinic("Iota Health Access", "FL", "FL-CHR-900009", "999000111", 19999)
        record_round(below["latest_vetting_round_id"], need_verification_points=1)

        refreshed = validate_success(
            api_client.get_giving_partner(below["id"], COORD), 200
        )
        assert refreshed["need_score"] == 39, "19999 // 1000 == 19"

        refused = api_client.approve_vetting_round(below["latest_vetting_round_id"], {}, COORD)
        validate_error(refused, "ERR_NEED_SCORE_BELOW_MINIMUM", expected_status=409)
        assert validate_success(
            api_client.get_giving_partner(below["id"], COORD), 200
        )["status"] == "VETTING"

    def test_20000_recipients_scores_40_and_the_approval_succeeds(self, api):
        """PRD §3.1: "A separate access component is added: the partner's average unduplicated recipients per facility divided by one thousand in truncating integer division, capped at 20."
        PRD §3.1: "It is assembled from a base value that depends on the partner's declared need band and a regional adjustment, with the band's base drawn from the partner type (a disaster relief organization scores 95, a domestic violence shelter 83, a homeless shelter 70, a veteran outreach organization 61, a youth outreach organization 52, and a community health clinic 20) and the adjustment drawn from the operating region (the midwest adds 6, the northeast 3, the southwest 2, the southeast 0 and the west subtracts 2)."
        PRD §3.1: "Independently, the computed `need_score` must be at least 40; a score below that threshold is rejected with `ERR_NEED_SCORE_BELOW_MINIMUM` (HTTP 409) even when every verification flag is true."

        Design: Difficulty/boundary_precision_check/need_score_zero_access_boundary_sits_at_exactly_one_thousand_recipients
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        at_gate = _clinic("Kappa Health Access", "FL", "FL-CHR-910010", "999000222", 20000)
        record_round(at_gate["latest_vetting_round_id"], need_verification_points=1)

        refreshed = validate_success(
            api_client.get_giving_partner(at_gate["id"], COORD), 200
        )
        assert refreshed["need_score"] == 40, "20000 // 1000 == 20"

        validate_success(
            api_client.approve_vetting_round(at_gate["latest_vetting_round_id"], {}, COORD), 200
        )
        assert validate_success(
            api_client.get_giving_partner(at_gate["id"], COORD), 200
        )["status"] == "APPROVED"