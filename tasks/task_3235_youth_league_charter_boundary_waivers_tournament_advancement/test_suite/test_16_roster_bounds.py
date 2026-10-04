"""Roster size bounds and the pinned within-add check ordering."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    ApiErrorId,
    set_clock, charter_league, major_division,
    register_and_verify_player, create_open_roster, add_selection,
    get_roster,
)

LA = TEST_USERS["league_admin_headers"]


def test_submit_below_minimum_rejected(api):
    """PRD §3.6: "Submission requires a `roster_size` of at least 3, enforced
    with `ERR_ROSTER_BELOW_MINIMUM` (HTTP 422)"
    PRD §3.6: "These bounds — a submittable roster window of 3 to 5 active
    players — are the benchmark-scale stand-in for the real
    twelve-to-fourteen-player all-star window."

    Design: Corner/validations/roster_submit_below_minimum_rejected
    """
    ctx = charter_league(league_name="Short Roster LL")
    set_clock("2027-02-01T00:00:00Z")
    p1 = register_and_verify_player(ctx["league"]["id"],
                                    birth_date="2015-03-10", last_name="One")
    p2 = register_and_verify_player(ctx["league"]["id"],
                                    birth_date="2015-04-11", last_name="Two")
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
    add_selection(ctx["league"]["id"], roster["id"], p1["id"])
    add_selection(ctx["league"]["id"], roster["id"], p2["id"])

    err = validate_error(api.submit_roster(ctx["league"]["id"], roster["id"],
                                           LA, {}),
                         ApiErrorId.ERR_ROSTER_BELOW_MINIMUM)
    assert err["error_id"] == "ERR_ROSTER_BELOW_MINIMUM"
    assert get_roster(ctx["league"]["id"], roster["id"])["status"] == "OPEN"


def test_sixth_selection_and_division_mismatch_rejected(api):
    """PRD §3.6: "Within a single add, the checks are evaluated in a pinned
    order — the player's division match is evaluated before roster capacity. The
    candidate player must be `ELIGIBLE`, or the add is rejected with
    `ERR_PLAYER_NOT_ELIGIBLE` (HTTP 409); the player's `division_id` must equal
    the roster's `division_id`, or the add is rejected with
    `ERR_PLAYER_DIVISION_MISMATCH` (HTTP 422); the player's `participation_pct`
    must be at least 60.00 — exactly 60.00 passes — or the add is rejected with
    `ERR_PARTICIPATION_THRESHOLD_NOT_MET` (HTTP 422); and the add must not push
    the roster beyond its capacity of 5 active selections, or it is rejected
    with `ERR_ROSTER_ABOVE_MAXIMUM` (HTTP 422)."

    Design: Corner/validations/roster_above_maximum_and_division_mismatch_rejected
    """
    ctx = charter_league(league_name="Full Roster LL")
    set_clock("2027-02-01T00:00:00Z")
    births = ["2015-03-10", "2015-04-11", "2015-05-12", "2015-06-13",
              "2015-07-14", "2015-08-15"]
    majors = [register_and_verify_player(
        ctx["league"]["id"], birth_date=b, last_name=f"M{i}")
        for i, b in enumerate(births)]
    # A MINOR player (league_age 9 in season 2027: born after the Aug 31
    # cutoff, so 2027 - 2018 = 9).
    minor = register_and_verify_player(
        ctx["league"]["id"], birth_date="2018-01-01", last_name="Minor")
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
    for player in majors[:5]:
        roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
    assert roster["roster_size"] == 5

    # Sixth MAJOR player: the capacity bound fires.
    err_max = validate_error(api.add_roster_selection(
        ctx["league"]["id"], roster["id"], {"player_id": majors[5]["id"]}, LA),
        ApiErrorId.ERR_ROSTER_ABOVE_MAXIMUM)
    assert err_max["error_id"] == "ERR_ROSTER_ABOVE_MAXIMUM"

    # MINOR player on the full MAJOR roster: the pinned order evaluates the
    # division match before capacity, so the mismatch error surfaces.
    err_div = validate_error(api.add_roster_selection(
        ctx["league"]["id"], roster["id"], {"player_id": minor["id"]}, LA),
        ApiErrorId.ERR_PLAYER_DIVISION_MISMATCH)
    assert err_div["error_id"] == "ERR_PLAYER_DIVISION_MISMATCH"
    assert get_roster(ctx["league"]["id"], roster["id"])["roster_size"] == 5
