"""Temporal interval semantics: half-open waiver-window overlap and
screening-window containment of the season."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    get_success_data, ApiErrorId,
    set_clock, charter_league, register_player, get_league, get_waiver,
    get_volunteer, get_screening,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]


def _create_waiver(league_id, player_id, valid_from, valid_until):
    league = get_league(league_id)
    return get_success_data(api_client.create_boundary_waiver(
        league_id,
        {"player_id": player_id, "waiver_type": "RESIDENCY_BOUNDARY",
         "reason": "waiver", "valid_from": valid_from,
         "valid_until": valid_until,
         "expected_league_version": league["version"]}, LA))


class TestWaiverHalfOpenOverlap:
    """Intersections reject; touching endpoints (adjacency) do not."""

    def _setup_three_waivers(self, league_name):
        ctx = charter_league(league_name=league_name)
        set_clock("2027-02-01T00:00:00Z")
        player = register_player(ctx["league"]["id"], last_name="Lap",
                                 residence=False, school=False)
        w1 = _create_waiver(ctx["league"]["id"], player["id"],
                            "2027-01-01", "2027-06-01")
        validate_success(api_client.decide_boundary_waiver(
            ctx["league"]["id"], w1["id"], {"action": "APPROVE"}, DA), 200)
        w2 = _create_waiver(ctx["league"]["id"], player["id"],
                            "2027-06-01", "2027-12-01")
        w3 = _create_waiver(ctx["league"]["id"], player["id"],
                            "2027-05-15", "2027-08-01")
        return ctx, player, w1, w2, w3

    def test_adjacent_waiver_approves_and_overlapping_waiver_rejects(self, api):
        """PRD §3.5: "Approval enforces the overlap rule: for the same player and
        the same `waiver_type`, no other already-`APPROVED` waiver may have a
        half-open validity window — start inclusive, end exclusive — that
        intersects this waiver's window. Adjacency is allowed: one waiver ending
        exactly on the day another begins does not intersect it. A violating
        approval is rejected with `ERR_WAIVER_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/waiver_half_open_overlap_rejected_but_adjacency_allowed
        """
        ctx, player, w1, w2, w3 = self._setup_three_waivers("Overlap LL")
        # W2 [2027-06-01, 2027-12-01) touches W1 [2027-01-01, 2027-06-01).
        decided = validate_success(api.decide_boundary_waiver(
            ctx["league"]["id"], w2["id"], {"action": "APPROVE"}, DA), 200)
        assert decided["status"] == "APPROVED"
        # W3 [2027-05-15, 2027-08-01) intersects W1.
        err = validate_error(api.decide_boundary_waiver(
            ctx["league"]["id"], w3["id"], {"action": "APPROVE"}, DA),
            ApiErrorId.ERR_WAIVER_OVERLAP)
        assert err["error_id"] == "ERR_WAIVER_OVERLAP"

    def test_rejected_overlap_leaves_the_waiver_pending(self, api):
        """PRD §3.5: "Approval or denial requires the waiver to be `PENDING`;
        revocation requires it to be `APPROVED`; any other combination is
        rejected with `ERR_WAIVER_NOT_PENDING` (HTTP 409). Approval enforces the
        overlap rule: for the same player and the same `waiver_type`, no other
        already-`APPROVED` waiver may have a half-open validity window — start
        inclusive, end exclusive — that intersects this waiver's window."

        Design: Difficulty/resource_temporal_overlap/waiver_half_open_overlap_rejected_but_adjacency_allowed
        """
        ctx, player, w1, w2, w3 = self._setup_three_waivers("Overlap LL Two")
        validate_error(api.decide_boundary_waiver(
            ctx["league"]["id"], w3["id"], {"action": "APPROVE"}, DA),
            ApiErrorId.ERR_WAIVER_OVERLAP)
        assert get_waiver(w3["id"])["status"] == "PENDING"


class TestScreeningSeasonContainment:
    """Intersection without containment is insufficient; containment clears."""

    def _setup_two_screenings(self, league_name):
        ctx = charter_league(league_name=league_name)
        v1 = get_success_data(api_client.create_volunteer(
            ctx["league"]["id"],
            {"full_name": "Vic One", "role_title": "COACH"}, LA))
        v2 = get_success_data(api_client.create_volunteer(
            ctx["league"]["id"],
            {"full_name": "Vic Two", "role_title": "MANAGER"}, LA))
        s1 = get_success_data(api_client.create_screening(
            ctx["league"]["id"], v1["id"],
            {"offense_category": "NONE",
             "valid_from": "2027-04-01", "valid_through": "2027-11-30"}, LA))
        s2 = get_success_data(api_client.create_screening(
            ctx["league"]["id"], v2["id"],
            {"offense_category": "NONE",
             "valid_from": "2027-02-01", "valid_through": "2027-11-30"}, LA))
        return ctx, v1, v2, s1, s2

    def test_partially_covering_screening_rejected_containing_screening_clears(
            self, api):
        """PRD §3.8: "Approval carries two gates: the screening's window from
        `valid_from` through `valid_through`, inclusive, must fully contain the
        season window from March 1 through October 31 of the league's
        `season_year`, or the approval is rejected with
        `ERR_SCREENING_WINDOW_INCOMPLETE` (HTTP 422)"

        Design: Difficulty/resource_temporal_overlap/screening_must_contain_season_window_not_just_intersect
        """
        ctx, v1, v2, s1, s2 = self._setup_two_screenings("Containment LL")
        # [2027-04-01, 2027-11-30] intersects but does not contain the season.
        err = validate_error(api.adjudicate_screening(
            ctx["league"]["id"], v1["id"], s1["id"], {"action": "APPROVE"}, DA),
            ApiErrorId.ERR_SCREENING_WINDOW_INCOMPLETE)
        assert err["error_id"] == "ERR_SCREENING_WINDOW_INCOMPLETE"
        assert get_screening(s1["id"])["status"] == "SUBMITTED"
        # [2027-02-01, 2027-11-30] fully contains [2027-03-01, 2027-10-31].
        cleared = validate_success(api.adjudicate_screening(
            ctx["league"]["id"], v2["id"], s2["id"], {"action": "APPROVE"}, DA),
            200)
        assert cleared["status"] == "CLEARED"

    def test_containing_screening_clears_the_volunteer(self, api):
        """PRD §3.8: "An approved screening becomes `CLEARED` and flips the
        volunteer from `REGISTERED` to `CLEARED`."

        Design: Difficulty/resource_temporal_overlap/screening_must_contain_season_window_not_just_intersect
        """
        ctx, v1, v2, s1, s2 = self._setup_two_screenings("Containment LL Two")
        validate_error(api.adjudicate_screening(
            ctx["league"]["id"], v1["id"], s1["id"], {"action": "APPROVE"}, DA),
            ApiErrorId.ERR_SCREENING_WINDOW_INCOMPLETE)
        assert get_volunteer(v1["id"])["status"] == "REGISTERED"

        validate_success(api.adjudicate_screening(
            ctx["league"]["id"], v2["id"], s2["id"], {"action": "APPROVE"}, DA),
            200)
        assert get_volunteer(v2["id"])["status"] == "CLEARED"
