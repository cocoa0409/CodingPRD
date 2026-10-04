"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch out of public endpoints,
because each individual test starts against an empty database. Setup steps use
``get_success_data()`` so a broken precondition reports itself as a setup
failure rather than as a confusing assertion failure in the test body.

All roles in this system are opaque, so the shared role constants from
``TEST_USERS`` are used directly.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_league_payload, create_player_payload,
    create_insurance_certificate_payload,
)
from .test_users import TEST_USERS

DA = TEST_USERS["district_admin_headers"]
LA = TEST_USERS["league_admin_headers"]
TD = TEST_USERS["tournament_director_headers"]
SCORER = TEST_USERS["official_scorer_headers"]
ANY = TEST_USERS["any_headers"]

ON_TIME_CLOCK = TEST_DEFAULTS["ON_TIME_CLOCK"]
REGISTRATION_CLOCK = TEST_DEFAULTS["REGISTRATION_CLOCK"]
GAME_CLOCK = TEST_DEFAULTS["GAME_CLOCK"]
SEASON_YEAR = TEST_DEFAULTS["SEASON_YEAR"]
FRESH_DOC = TEST_DEFAULTS["FRESH_DOC_ISSUED"]


# ═══════════════════════════════════════════════════════
# Tier 1: Clock + league primitives
# ═══════════════════════════════════════════════════════

def set_clock(to_iso8601):
    """Advance the logical clock (also runs the scheduled sweeps)."""
    res = api_client.set_clock(to_iso8601, DA)
    assert res.status_code == 200, f"set_clock({to_iso8601}) failed: {res.text}"


def create_league_raw(league_name=None, season_year=SEASON_YEAR):
    """Create a PROVISIONAL league; returns (league, divisions) with divisions
    in pinned creation order (index 0 TEE_BALL .. index 4 SENIOR)."""
    payload = create_league_payload(season_year=season_year)
    if league_name:
        payload["league_name"] = league_name
    league = get_success_data(api_client.create_league(payload, DA))
    divisions, _meta = validate_paginated(api_client.list_divisions(league["id"], DA))
    return league, divisions


def add_insurance(league_id, coverage_start=TEST_DEFAULTS["INSURANCE_COVERAGE_START"],
                  coverage_end=TEST_DEFAULTS["INSURANCE_COVERAGE_END"]):
    """Record an ACTIVE insurance certificate on the league."""
    return get_success_data(api_client.create_insurance_certificate(
        league_id,
        create_insurance_certificate_payload(
            coverage_start=coverage_start, coverage_end=coverage_end),
        DA))


def patch_team_count(league_id, division_id, team_count):
    return get_success_data(api_client.patch_division(
        league_id, division_id, {"team_count": team_count}, LA))


def submit_renewal(league_id, season_year=SEASON_YEAR):
    return get_success_data(api_client.create_charter_renewal(
        league_id, {"season_year": season_year}, LA))


def approve_renewal(league_id, renewal_id, late_fee_paid=False):
    return get_success_data(api_client.decide_charter_renewal(
        league_id, renewal_id,
        {"action": "APPROVE", "late_fee_paid": late_fee_paid}, DA))


def get_league(league_id):
    return get_success_data(api_client.get_league(league_id, DA))


# ═══════════════════════════════════════════════════════
# Tier 2: Charter prefix (league -> insurance -> renewal -> APPROVE)
# ═══════════════════════════════════════════════════════

def charter_league(league_name=None, season_year=SEASON_YEAR,
                   submit_clock=ON_TIME_CLOCK, late_fee_paid=False,
                   team_counts=None,
                   coverage_start=TEST_DEFAULTS["INSURANCE_COVERAGE_START"],
                   coverage_end=TEST_DEFAULTS["INSURANCE_COVERAGE_END"]):
    """Full charter prefix: set the clock, create the league, record insurance,
    optionally patch division team counts ({division_code: count}), submit and
    approve the renewal. Returns a context dict with league (re-read after
    approval), divisions (creation order), and renewal."""
    set_clock(submit_clock)
    league, divisions = create_league_raw(league_name=league_name,
                                          season_year=season_year)
    add_insurance(league["id"], coverage_start=coverage_start,
                  coverage_end=coverage_end)
    if team_counts:
        by_code = {d["division_code"]: d for d in divisions}
        for code, count in team_counts.items():
            patch_team_count(league["id"], by_code[code]["id"], count)
    renewal = submit_renewal(league["id"], season_year=season_year)
    renewal = approve_renewal(league["id"], renewal["id"],
                              late_fee_paid=late_fee_paid)
    league = get_league(league["id"])
    return {"league": league, "divisions": divisions, "renewal": renewal,
            "division_by_code": {d["division_code"]: d for d in divisions}}


def major_division(ctx):
    """The MAJOR division from a charter_league context (index 2)."""
    return ctx["division_by_code"]["MAJOR"]


# ═══════════════════════════════════════════════════════
# Tier 3: Player registration + verification
# ═══════════════════════════════════════════════════════

def register_player(league_id, birth_date="2015-03-10", games_played=3,
                    games_scheduled=5, residence=True, school=False,
                    first_name="P", last_name=None):
    """Register a player (league must be CHARTERED). Returns the Player."""
    payload = create_player_payload(
        birth_date=birth_date, games_played=games_played,
        games_scheduled=games_scheduled,
        residence_within_boundary=residence,
        school_within_boundary=school,
        first_name=first_name)
    if last_name:
        payload["last_name"] = last_name
    return get_success_data(api_client.create_player(league_id, payload, LA))


def attach_standard_documents(league_id, player_id, birth_date="2015-03-10",
                              proof_type="RESIDENCE_PROOF",
                              proof_issued=FRESH_DOC):
    """Attach a BIRTH_CERTIFICATE (issued on the birth date; birth certificates
    carry no freshness rule) plus a fresh residency-basis document."""
    get_success_data(api_client.create_eligibility_document(
        league_id, player_id,
        {"doc_type": "BIRTH_CERTIFICATE", "issued_date": birth_date}, LA))
    get_success_data(api_client.create_eligibility_document(
        league_id, player_id,
        {"doc_type": proof_type, "issued_date": proof_issued}, LA))


def verify_player(league_id, player_id):
    return get_success_data(api_client.verify_eligibility(league_id, player_id, LA))


def register_and_verify_player(league_id, birth_date="2015-03-10",
                               games_played=3, games_scheduled=5,
                               residence=True, school=False,
                               first_name="P", last_name=None):
    """Register a player with standard fresh documents and verify them ELIGIBLE.
    Caller must have already moved the clock into the registration window."""
    player = register_player(
        league_id, birth_date=birth_date, games_played=games_played,
        games_scheduled=games_scheduled, residence=residence, school=school,
        first_name=first_name, last_name=last_name)
    attach_standard_documents(league_id, player["id"], birth_date=birth_date)
    return verify_player(league_id, player["id"])


# ═══════════════════════════════════════════════════════
# Tier 4: Chartered league + N eligible MAJOR players
# ═══════════════════════════════════════════════════════

_MAJOR_BIRTHS = TEST_DEFAULTS["MAJOR_BIRTH_DATES"]


def setup_chartered_league_with_players(n=3, league_name=None,
                                        games_played=3, games_scheduled=5):
    """Charter a league for the default season, move the clock into the
    registration window, and register + verify ``n`` ELIGIBLE players in MAJOR.
    Returns a context dict: league, divisions, division_by_code, players."""
    ctx = charter_league(league_name=league_name)
    set_clock(REGISTRATION_CLOCK)
    players = []
    for i in range(n):
        players.append(register_and_verify_player(
            ctx["league"]["id"], birth_date=_MAJOR_BIRTHS[i % len(_MAJOR_BIRTHS)],
            games_played=games_played, games_scheduled=games_scheduled,
            last_name=f"Num{i + 1}"))
    ctx["players"] = players
    return ctx


# ═══════════════════════════════════════════════════════
# Tier 5: Rosters, entries, games
# ═══════════════════════════════════════════════════════

def create_open_roster(league_id, division_id):
    return get_success_data(api_client.create_all_star_roster(
        league_id, {"division_id": division_id}, LA))


def add_selection(league_id, roster_id, player_id):
    return get_success_data(api_client.add_roster_selection(
        league_id, roster_id, {"player_id": player_id}, LA))


def submit_roster(league_id, roster_id):
    return get_success_data(api_client.submit_roster(league_id, roster_id, LA))


def get_roster(league_id, roster_id):
    """Re-read a roster via the cross-league detail read."""
    return get_success_data(
        api_client.get_all_star_roster_detail(roster_id, DA))


def setup_submitted_roster(n=3, league_name=None):
    """Charter prefix + n ELIGIBLE MAJOR players + OPEN roster + n selections
    + submit. Returns ctx with league, players, roster (SUBMITTED), major."""
    ctx = setup_chartered_league_with_players(n=n, league_name=league_name)
    roster = create_open_roster(ctx["league"]["id"], major_division(ctx)["id"])
    for player in ctx["players"]:
        roster = add_selection(ctx["league"]["id"], roster["id"], player["id"])
    roster = submit_roster(ctx["league"]["id"], roster["id"])
    ctx["roster"] = roster
    return ctx


def setup_tournament_entry(n=3, league_name=None, level="DISTRICT"):
    """Submitted roster + tournament entry. Returns ctx with entry (ACTIVE)."""
    ctx = setup_submitted_roster(n=n, league_name=league_name)
    entry = get_success_data(api_client.create_tournament_entry(
        ctx["league"]["id"],
        {"roster_id": ctx["roster"]["id"], "level": level}, TD))
    ctx["entry"] = entry
    return ctx


def create_game(entry_id):
    return get_success_data(api_client.create_game(entry_id, TD))


def record_appearance(entry_id, game_id, player_id, pitches_thrown):
    return get_success_data(api_client.record_pitching_appearance(
        entry_id, game_id,
        {"player_id": player_id, "pitches_thrown": pitches_thrown}, SCORER))


def finalize_game(entry_id, game_id, our_score, opponent_score,
                  expected_game_version, scorebook_corrections=None):
    payload = {"our_score": our_score, "opponent_score": opponent_score,
               "expected_game_version": expected_game_version}
    if scorebook_corrections is not None:
        payload["scorebook_corrections"] = scorebook_corrections
    return get_success_data(api_client.finalize_game(entry_id, game_id, payload, TD))


def setup_game_in_progress(ctx, player_index=0, pitches=10,
                           game_clock=GAME_CLOCK):
    """Move the clock to game day, create a game, record one appearance.
    Returns (game, appearance); the game is IN_PROGRESS."""
    set_clock(game_clock)
    game = create_game(ctx["entry"]["id"])
    appearance = record_appearance(
        ctx["entry"]["id"], game["id"],
        ctx["players"][player_index]["id"], pitches)
    return game, appearance


def setup_final_game(ctx, player_index=0, pitches=10,
                     our_score=5, opponent_score=3, game_clock=GAME_CLOCK):
    """Game in progress + finalize. Returns (game, appearance, finalized)."""
    game, appearance = setup_game_in_progress(
        ctx, player_index=player_index, pitches=pitches, game_clock=game_clock)
    finalized = finalize_game(
        ctx["entry"]["id"], game["id"], our_score, opponent_score,
        expected_game_version=game["version"] + 1)
    return game, appearance, finalized


def get_entry(entry_id):
    return get_success_data(api_client.get_tournament_entry_detail(entry_id, DA))


def get_game(game_id):
    return get_success_data(api_client.get_game_detail(game_id, DA))


def get_player(player_id):
    return get_success_data(api_client.get_player_detail(player_id, DA))


def get_appearance(appearance_id):
    return get_success_data(
        api_client.get_pitching_appearance_detail(appearance_id, DA))


def get_renewal(renewal_id):
    return get_success_data(api_client.get_charter_renewal_detail(renewal_id, DA))


def get_waiver(waiver_id):
    return get_success_data(api_client.get_boundary_waiver_detail(waiver_id, DA))


def get_division(division_id):
    return get_success_data(api_client.get_division_detail(division_id, DA))


def get_volunteer(volunteer_id):
    return get_success_data(api_client.get_volunteer_detail(volunteer_id, DA))


def get_screening(screening_id):
    return get_success_data(api_client.get_screening_detail(screening_id, DA))


def get_certificate(certificate_id):
    return get_success_data(
        api_client.get_insurance_certificate_detail(certificate_id, DA))
