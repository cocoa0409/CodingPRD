"""Roster and tournament state-machine corners: duplicate protests, recall and
resubmit, double-elimination cascade, advancement ladder, protest blocking,
insurance expiry, and reinstatement."""
from test_helpers import (
    TEST_USERS, api_client, validate_success, validate_error,
    validate_paginated, get_success_data, ApiErrorId,
    set_clock, charter_league, major_division,
    register_and_verify_player, create_open_roster, add_selection,
    submit_roster, get_roster, get_entry, get_game, get_league,
    get_division, add_insurance, submit_renewal, approve_renewal,
    get_certificate, create_league_raw,
    setup_submitted_roster, setup_tournament_entry, create_game,
    record_appearance, finalize_game,
)

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]


def test_second_protest_while_one_open_rejected(api):
    """PRD §3.8: "A `TournamentDirector` files a protest against a game that is
    `IN_PROGRESS` or `FINAL`, but only while its `protest_status` is `NONE`;
    filing against a game with a protest already open is rejected with
    `ERR_DUPLICATE_OPEN_PROTEST` (HTTP 409)."

    Design: Corner/state_machines/protest_on_game_with_open_protest_rejected
    """
    ctx = setup_tournament_entry(league_name="Double Protest LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 10)
    finalize_game(ctx["entry"]["id"], game["id"], 5, 3, game["version"] + 1)

    validate_success(api.file_protest(
        ctx["entry"]["id"], game["id"],
        {"protest_type": "RULE_INTERPRETATION", "grounds": "first protest"},
        TD), 201)
    err = validate_error(api.file_protest(
        ctx["entry"]["id"], game["id"],
        {"protest_type": "RULE_INTERPRETATION",
         "grounds": "second protest while one is open"}, TD),
        ApiErrorId.ERR_DUPLICATE_OPEN_PROTEST)
    assert err["error_id"] == "ERR_DUPLICATE_OPEN_PROTEST"

    protests, meta = validate_paginated(api.list_protests(
        ctx["entry"]["id"], game["id"], TD))
    assert len(protests) == 1
    assert meta["total_count"] == 1


def test_recalled_roster_accepts_replacement_and_resubmits(api):
    """PRD §3.6: "Adding a selection is permitted while the roster is `OPEN` or
    `RECALLED`"
    PRD §3.6: "Submitting the roster moves it `OPEN` → `SUBMITTED`, or
    `RECALLED` → `SUBMITTED` when resubmitting after fixing selections"

    Design: Corner/state_machines/roster_recall_resubmit_restores_submitted
    """
    ctx = charter_league(league_name="Resubmit LL")
    set_clock("2027-02-01T00:00:00Z")
    births = ["2015-03-10", "2015-04-11", "2015-05-12", "2015-06-13",
              "2015-07-14"]
    players = [register_and_verify_player(
        ctx["league"]["id"], birth_date=b, last_name=f"R{i}")
        for i, b in enumerate(births)]
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
    for player in players[:4]:
        roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
    roster = submit_roster(ctx["league"]["id"], roster["id"])

    validate_success(api.revoke_eligibility(
        ctx["league"]["id"], players[0]["id"], LA, {"reason": "audit"}), 200)
    recalled = get_roster(ctx["league"]["id"], roster["id"])
    assert recalled["status"] == "RECALLED"
    assert recalled["roster_size"] == 3

    add_selection(ctx["league"]["id"], roster["id"], players[4]["id"])
    resubmitted = validate_success(api.submit_roster(
        ctx["league"]["id"], roster["id"], LA, {}), 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["roster_size"] == 4


def test_second_loss_eliminates_and_cancels_remaining_game(api):
    """PRD §3.7: "The entry's `losses_count` increments by 1, and when it
    reaches the elimination limit — 1 loss for `SINGLE_ELIMINATION`, 2 losses
    for `DOUBLE_ELIMINATION` — the entry cascades from `ACTIVE` to `ELIMINATED`
    and every remaining `SCHEDULED` game of that entry is cancelled (`SCHEDULED`
    → `CANCELLED`)."
    PRD §3.7: "Creating the entry computes its `elimination_format`:
    `DOUBLE_ELIMINATION` for `DISTRICT` and `SECTIONAL`, `SINGLE_ELIMINATION`
    for `STATE` and `REGIONAL`."

    Design: Corner/state_machines/entry_elimination_after_second_double_elimination_loss_cancels_games
    """
    ctx = setup_tournament_entry(league_name="Double Elim LL")
    assert ctx["entry"]["elimination_format"] == "DOUBLE_ELIMINATION"
    set_clock("2027-06-01T00:00:00Z")
    g1 = create_game(ctx["entry"]["id"])
    g2 = create_game(ctx["entry"]["id"])
    g3 = create_game(ctx["entry"]["id"])

    record_appearance(ctx["entry"]["id"], g1["id"], ctx["players"][0]["id"], 10)
    finalize_game(ctx["entry"]["id"], g1["id"], 1, 2, g1["version"] + 1)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["status"] == "ACTIVE"
    assert entry["losses_count"] == 1

    record_appearance(ctx["entry"]["id"], g2["id"], ctx["players"][1]["id"], 10)
    finalize_game(ctx["entry"]["id"], g2["id"], 0, 6, g2["version"] + 1)
    entry = get_entry(ctx["entry"]["id"])
    assert entry["status"] == "ELIMINATED"
    assert entry["losses_count"] == 2
    assert get_game(g3["id"])["play_status"] == "CANCELLED"
    assert get_game(g1["id"])["result"] == "LOSS"
    assert get_game(g2["id"])["result"] == "LOSS"


def test_district_advance_unlocks_sectional_entry(api):
    """PRD §3.7: "Levels form a strict ladder: an entry at any level other than
    `DISTRICT` requires an already-`ADVANCED` entry at the immediately preceding
    level within the same league — `SECTIONAL` follows `DISTRICT`, `STATE`
    follows `SECTIONAL`, `REGIONAL` follows `STATE` — and a request missing that
    prerequisite is rejected with `ERR_ADVANCEMENT_PREREQUISITE_NOT_MET`
    (HTTP 409)."
    PRD §3.7: "A successful advance moves the entry to `ADVANCED`, a terminal
    state, and it is that `ADVANCED` marker at level N that licenses the
    league's entry at level N+1."

    Design: Corner/state_machines/advance_after_district_win_unlocks_sectional_entry
    """
    ctx = setup_tournament_entry(league_name="Ladder LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 15)
    finalize_game(ctx["entry"]["id"], game["id"], 4, 2, game["version"] + 1)

    # STATE without an ADVANCED SECTIONAL prerequisite is rejected.
    err = validate_error(api.create_tournament_entry(
        ctx["league"]["id"],
        {"roster_id": ctx["roster"]["id"], "level": "STATE"}, TD),
        ApiErrorId.ERR_ADVANCEMENT_PREREQUISITE_NOT_MET)
    assert err["error_id"] == "ERR_ADVANCEMENT_PREREQUISITE_NOT_MET"

    advanced = validate_success(api.advance_entry(ctx["entry"]["id"], TD, {}),
                                200)
    assert advanced["status"] == "ADVANCED"

    # The first roster is LOCKED by entry creation; the SECTIONAL entry is
    # created against a fresh SUBMITTED roster over the same players.
    sectional_roster = create_open_roster(ctx["league"]["id"],
                                          major_division(ctx)["id"])
    for player in ctx["players"]:
        sectional_roster = add_selection(ctx["league"]["id"],
                                         sectional_roster["id"], player["id"])
    sectional_roster = submit_roster(ctx["league"]["id"],
                                     sectional_roster["id"])

    sectional = validate_success(api.create_tournament_entry(
        ctx["league"]["id"],
        {"roster_id": sectional_roster["id"], "level": "SECTIONAL"}, TD), 201)
    assert sectional["elimination_format"] == "DOUBLE_ELIMINATION"
    assert sectional["status"] == "ACTIVE"
    assert get_entry(ctx["entry"]["id"])["losses_count"] == 0


def test_open_protest_blocks_advance_until_resolved(api):
    """PRD §3.7: "A `TournamentDirector` advances an `ACTIVE` entry when it has
    at least one `FINAL` game with result `WIN` at its level, its `losses_count`
    is below the elimination limit for its format, and none of its games has a
    protest still `OPEN` — an open protest blocks advancement, surfaced as
    `ERR_PROTEST_NOT_OPEN` (HTTP 409)."
    PRD §3.8: "Overturning a protest lets everything stand — the game result,
    counters, and appearances are unchanged; only the protest moves to
    `OVERTURNED` and the game's `protest_status` to `RESOLVED`."

    Design: Corner/state_machines/advance_blocked_by_open_protest
    """
    ctx = setup_tournament_entry(league_name="Blocked Advance LL")
    set_clock("2027-06-01T00:00:00Z")
    game = create_game(ctx["entry"]["id"])
    record_appearance(ctx["entry"]["id"], game["id"], ctx["players"][0]["id"], 10)
    finalize_game(ctx["entry"]["id"], game["id"], 3, 1, game["version"] + 1)
    protest = get_success_data(api.file_protest(
        ctx["entry"]["id"], game["id"],
        {"protest_type": "RULE_INTERPRETATION", "grounds": "protest pending"},
        TD))

    err = validate_error(api.advance_entry(ctx["entry"]["id"], TD, {}),
                         ApiErrorId.ERR_PROTEST_NOT_OPEN)
    assert err["error_id"] == "ERR_PROTEST_NOT_OPEN"

    validate_success(api.resolve_protest(
        ctx["entry"]["id"], game["id"], protest["id"],
        {"action": "OVERTURN"}, TD), 200)
    game_after = get_game(game["id"])
    assert game_after["protest_status"] == "RESOLVED"
    assert game_after["result"] == "WIN"
    assert game_after["recorded_pitch_total"] == 10

    advanced = validate_success(api.advance_entry(ctx["entry"]["id"], TD, {}),
                                200)
    assert advanced["status"] == "ADVANCED"


def test_expired_insurance_blocks_late_finalize(api):
    """PRD §3.8: "The certificate starts `ACTIVE` and remains so until the
    logical clock's date moves past `coverage_end`, at which point the clock
    sweep flips it to `EXPIRED`, its terminal state."
    PRD §3.7: "The league the entry belongs to must hold an `ACTIVE` insurance
    certificate whose coverage window contains the clock date of finalization,
    or the finalize is rejected with `ERR_INSURANCE_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/insurance_expiry_blocks_finalize_after_coverage_end
    """
    ctx = charter_league(league_name="Expiry LL",
                         coverage_start="2027-03-01",
                         coverage_end="2027-10-31")
    set_clock("2027-02-01T00:00:00Z")
    births = ["2015-03-10", "2015-04-11", "2015-05-12"]
    players = [register_and_verify_player(
        ctx["league"]["id"], birth_date=b, last_name=f"E{i}")
        for i, b in enumerate(births)]
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
    for player in players:
        roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
    roster = submit_roster(ctx["league"]["id"], roster["id"])
    entry = get_success_data(api.create_tournament_entry(
        ctx["league"]["id"],
        {"roster_id": roster["id"], "level": "DISTRICT"}, TD))

    set_clock("2027-06-01T00:00:00Z")
    g1 = create_game(entry["id"])
    record_appearance(entry["id"], g1["id"], players[0]["id"], 10)
    finalized = finalize_game(entry["id"], g1["id"], 4, 1, g1["version"] + 1)
    assert finalized["play_status"] == "FINAL"

    # Move past coverage_end: the sweep expires the certificate.
    set_clock("2027-11-15T00:00:00Z")
    g2 = create_game(entry["id"])
    record_appearance(entry["id"], g2["id"], players[1]["id"], 10)
    err = validate_error(api.finalize_game(
        entry["id"], g2["id"],
        {"our_score": 2, "opponent_score": 1,
         "expected_game_version": g2["version"] + 1}, TD),
        ApiErrorId.ERR_INSURANCE_NOT_ACTIVE)
    assert err["error_id"] == "ERR_INSURANCE_NOT_ACTIVE"
    assert get_game(g2["id"])["play_status"] == "IN_PROGRESS"


def test_reinstatement_restores_divisions_but_not_entries(api):
    """PRD §3.2: "Approval then drives the league's charter transition: a
    `PROVISIONAL` league becomes `CHARTERED`, and a `SUSPENDED` league is
    reinstated to `CHARTERED`, in the latter case flipping every `SUSPENDED`
    division back to `ACTIVE`. Tournament entries withdrawn by the suspension
    are not resurrected — they remain `WITHDRAWN`."

    Design: Corner/state_machines/suspension_reinstatement_restores_divisions_but_not_entries
    """
    # Charter for 2027 plus a certificate covering the 2029 season window.
    set_clock("2026-10-15T00:00:00Z")
    league, divisions = create_league_raw(league_name="Reinstate LL")
    add_insurance(league["id"])
    add_insurance(league["id"], coverage_start="2029-01-01",
                  coverage_end="2029-12-31")
    renewal = submit_renewal(league["id"])
    approve_renewal(league["id"], renewal["id"])

    set_clock("2027-02-01T00:00:00Z")
    by_code = {d["division_code"]: d for d in divisions}
    births = ["2015-03-10", "2015-04-11", "2015-05-12"]
    players = [register_and_verify_player(
        league["id"], birth_date=b, last_name=f"S{i}")
        for i, b in enumerate(births)]
    roster = create_open_roster(league["id"], by_code["MAJOR"]["id"])
    for player in players:
        roster = add_selection(league["id"], roster["id"], player["id"])
    roster = submit_roster(league["id"], roster["id"])
    entry = get_success_data(api.create_tournament_entry(
        league["id"], {"roster_id": roster["id"], "level": "DISTRICT"}, TD))
    game = create_game(entry["id"])

    # Lapse the league by jumping past 2028-03-31 with no 2028 renewal.
    set_clock("2028-04-01T00:00:00Z")
    assert get_league(league["id"])["charter_status"] == "SUSPENDED"
    assert get_division(by_code["MAJOR"]["id"])["status"] == "SUSPENDED"
    assert get_entry(entry["id"])["status"] == "WITHDRAWN"

    # Renew for 2029 inside its ON_TIME window and approve.
    set_clock("2028-11-01T00:00:00Z")
    renewal_2029 = submit_renewal(league["id"], season_year=2029)
    approve_renewal(league["id"], renewal_2029["id"])

    assert get_league(league["id"])["charter_status"] == "CHARTERED"
    assert get_division(by_code["MAJOR"]["id"])["status"] == "ACTIVE"
    # No resurrection: the entry and its cancelled game stay put.
    assert get_entry(entry["id"])["status"] == "WITHDRAWN"
    assert get_game(game["id"])["play_status"] == "CANCELLED"
