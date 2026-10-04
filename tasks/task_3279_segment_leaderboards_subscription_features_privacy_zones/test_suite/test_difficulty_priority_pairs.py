"""Difficulty queue A: priority-pair validation conflicts.

state_vs_temporal_on_challenge_join: state beats temporal on challenge join.
safety_vs_referential_on_segment_ops: safety beats referential on activation.
"""

from test_helpers import (
    ApiErrorId,
    create_active_challenge,
    create_athlete,
    create_club,
    create_segment,
    join_club,
    make_athlete_headers,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_challenge_payload, create_segment_payload


class TestStateVsTemporalOnChallengeJoin:
    def test_draft_challenge_with_past_window_reports_invalid_state(self, api):
        """PRD 2.5: "then state-permission checks on the target resource, then the club-archived gate on club-scoped writes, then safety rules, then temporal-window rules, then overlap-conflict rules, then uniqueness and membership constraints, then duplicate-upload detection, then capacity checks, then subscription gating, and finally cross-entity referential consistency. When several of these checks could fail on the same request, the earlier check in this ordering wins and its error code is the one returned."
        PRD 3.7: "Joining a challenge that is not `ACTIVE` is rejected with `ERR_INVALID_STATE`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_challenge_join
        """
        owner = create_athlete(api, email="po_pri@x.com", display_name="PO Pri")
        member = create_athlete(api, email="pm_pri@x.com", display_name="PM Pri")
        club = create_club(api, owner["id"], name="Priority Club", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], member["id"])
        resp = api.create_challenge(
            club["id"],
            create_challenge_payload(
                name="August DRAFT", goal_type="DISTANCE_M", goal_target=10000,
                start_date="2026-08-01", end_date="2026-08-31", join_mode="OPEN",
            ),
            make_athlete_headers(owner["id"]),
        )
        challenge = validate_success(resp, 201)
        assert challenge["status"] == "DRAFT"
        set_clock(api, "2026-09-10T00:00:00Z")
        join = api.join_challenge(challenge["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"]))
        validate_error(join, ApiErrorId.ERR_INVALID_STATE)

    def test_active_challenge_with_valid_window_accepts_join(self, api):
        """PRD 3.7: "under `OPEN`, any `ACTIVE` club member may join".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_temporal_on_challenge_join
        """
        owner = create_athlete(api, email="po_ok@x.com", display_name="PO Ok")
        member = create_athlete(api, email="pm_ok@x.com", display_name="PM Ok")
        club = create_club(api, owner["id"], name="Priority Ok Club", sport_type="RUN", join_policy="OPEN")
        join_club(api, club["id"], member["id"])
        challenge = create_active_challenge(
            api, club["id"], owner["id"], name="September OK",
            start_date="2026-09-01", end_date="2026-09-30", join_mode="OPEN",
        )
        resp = api.join_challenge(challenge["id"], {"athlete_id": member["id"]}, make_athlete_headers(member["id"]))
        part = validate_success(resp, 201)
        assert part["status"] == "JOINED"


class TestSafetyVsReferentialOnSegmentOps:
    def test_hazardous_retired_segment_reactivation_reports_safety_violation(self, api):
        """PRD 3.5: "First, safety: a segment with `hazard_index` greater than zero can never be activated; the attempt is rejected with `ERR_SAFETY_VIOLATION`, because hazardous segments must never appear on leaderboards."
        PRD 2.5: "then state-permission checks on the target resource, then the club-archived gate on club-scoped writes, then safety rules, then temporal-window rules, then overlap-conflict rules, then uniqueness and membership constraints, then duplicate-upload detection, then capacity checks, then subscription gating, and finally cross-entity referential consistency. When several of these checks could fail on the same request, the earlier check in this ordering wins and its error code is the one returned."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_segment_ops
        """
        owner = create_athlete(api, email="so_pri@x.com", display_name="SO Pri")
        headers = make_athlete_headers(owner["id"])
        segment = create_segment(
            api, owner["id"], name="Hazard Hill", sport_type="RIDE",
            start_lat=41.00, start_lng=-126.00, end_lat=41.01, end_lng=-126.00,
            distance_m=2000, city="Hazardtown", hazard_index=1,
        )
        validate_success(api.retire_segment(segment["id"], headers), 200)
        resp = api.activate_segment(segment["id"], headers)
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION)
        after = validate_success(api.get_segment(segment["id"], headers), 200)
        assert after["status"] == "RETIRED"

    def test_hazardous_draft_segment_activation_reports_safety_violation(self, api):
        """PRD 3.5: "a segment with `hazard_index` greater than zero can never be activated; the attempt is rejected with `ERR_SAFETY_VIOLATION`".

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_on_segment_ops
        """
        owner = create_athlete(api, email="so_hz@x.com", display_name="SO Hz")
        headers = make_athlete_headers(owner["id"])
        segment = create_segment(api, owner["id"], name="Hazard Draft", sport_type="RIDE", hazard_index=5)
        resp = api.activate_segment(segment["id"], headers)
        validate_error(resp, ApiErrorId.ERR_SAFETY_VIOLATION)
        after = validate_success(api.get_segment(segment["id"], headers), 200)
        assert after["status"] == "DRAFT"
