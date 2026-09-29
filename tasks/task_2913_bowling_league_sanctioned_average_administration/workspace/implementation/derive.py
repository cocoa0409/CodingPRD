"""Derived fields and cascades (PRD 2.9, 3.3, 3.5, 3.6, 3.7)."""

import calc
from store import store, apply_changes, ordered

SETTLED_MATCH = ("CERTIFIED", "FORFEITED", "VOID")
SCORING_MATCH = ("CERTIFIED", "FORFEITED")
AVERAGE_BEARING = ("REGULAR", "SUBSTITUTE", "PREBOWL")


# --- collections -----------------------------------------------------------

def memberships_of_league(league_id):
    return ordered([m for m in store.memberships.values()
                    if m["league_id"] == league_id])


def teams_of_league(league_id):
    return ordered([t for t in store.teams.values()
                    if t["league_id"] == league_id])


def matches_of_league(league_id):
    return ordered([m for m in store.matches.values()
                    if m["league_id"] == league_id])


def lane_pairs_of_league(league_id):
    return ordered([p for p in store.lane_pairs.values()
                    if p["league_id"] == league_id])


def slots_of_match(match_id):
    return ordered([s for s in store.series_entries.values()
                    if s["match_id"] == match_id])


def side_slots(match_id, team_id):
    return sorted([s for s in store.series_entries.values()
                   if s["match_id"] == match_id and s["team_id"] == team_id],
                  key=lambda s: s["position"])


def slots_of_membership(membership_id):
    return [s for s in store.series_entries.values()
            if s["membership_id"] == membership_id]


def dues_of_membership(membership_id):
    return ordered([d for d in store.dues_payments.values()
                    if d["membership_id"] == membership_id])


def fund_of_league(league_id):
    for f in ordered(list(store.prize_funds.values())):
        if f["league_id"] == league_id:
            return f
    return None


def awards_of_fund(fund_id):
    return sorted([a for a in store.prize_awards.values()
                   if a["prize_fund_id"] == fund_id],
                  key=lambda a: (a["place"], a["_seq"]))


# --- membership ------------------------------------------------------------

def certified_stats(membership_id):
    games = 0
    pins = 0
    for s in store.series_entries.values():
        if (s["membership_id"] == membership_id and s["certified"]
                and s["counts_toward_average"]):
            games += s["games_recorded"]
            pins += s["scratch_series"]
    return games, pins


def recompute_membership(membership, include_entering=False):
    """Recomputes averages and the handicap from scratch (PRD 3.6)."""
    league = store.leagues[membership["league_id"]]
    member = store.members[membership["member_id"]]
    entering = membership["entering_average"]
    changes = {}
    if include_entering:
        entering = calc.entering_average(
            league, membership["prior_season_average"],
            membership["prior_season_games"])
        changes["entering_average"] = entering
    games, pins = certified_stats(membership["id"])
    status, current = calc.bowler_average(
        league, games, pins, entering, membership["prior_season_games"])
    changes["certified_games"] = games
    changes["certified_pins"] = pins
    changes["average_status"] = status
    changes["current_average"] = current
    changes["handicap_per_game"] = calc.bowler_handicap(
        league, membership["sanction_status"], entering, current,
        member["member_class"])
    return apply_changes(membership, changes)


def recompute_dues_figures(membership):
    league = store.leagues[membership["league_id"]]
    payments = dues_of_membership(membership["id"])
    paid = sum(p["amount_cents"] for p in payments)
    high_water = league["certified_week_high_water"]
    weeks = set(p["week_number"] for p in payments
                if p["week_number"] <= high_water)
    arrears = high_water - len(weeks)
    if arrears < 0:
        arrears = 0
    return apply_changes(membership, {"dues_paid_cents": paid,
                                      "dues_arrears_weeks": arrears})


def recompute_member(member):
    count = len([m for m in store.memberships.values()
                 if m["member_id"] == member["id"]
                 and m["sanction_status"] == "SANCTIONED"])
    return apply_changes(member, {"sanctioned_membership_count": count})


# --- team ------------------------------------------------------------------

def roster_handicap(league, team):
    depth = league.get("lineup_positions")
    if depth is None:
        return 0
    candidates = [m for m in store.memberships.values()
                  if m["team_id"] == team["id"]
                  and m["sanction_status"] == "SANCTIONED"]
    ranked = sorted(candidates,
                    key=lambda m: (-m["handicap_per_game"], m["created_at"],
                                   m["_seq"]))
    return sum(m["handicap_per_game"] for m in ranked[:depth])


def recompute_team(team):
    league = store.leagues[team["league_id"]]
    roster_count = len([m for m in store.memberships.values()
                        if m["team_id"] == team["id"]
                        and m["sanction_status"] == "SANCTIONED"])
    changes = {"sanctioned_roster_count": roster_count}
    minimum = league.get("legal_lineup_minimum")
    status = team["status"]
    if status != "CONFIRMED" and minimum is not None and roster_count >= minimum:
        status = "CONFIRMED"
    changes["status"] = status
    changes["team_handicap_per_game"] = roster_handicap(league, team)
    points = 0.0
    pins = 0
    for match in matches_of_league(team["league_id"]):
        if match["status"] not in SCORING_MATCH:
            continue
        if match["home_team_id"] == team["id"]:
            points += match["home_points"]
        elif match["away_team_id"] == team["id"]:
            points += match["away_points"]
        else:
            continue
        for s in slots_of_match(match["id"]):
            if s["team_id"] == team["id"]:
                pins += s["scratch_series"]
    changes["total_points"] = round(points, 1)
    changes["total_scratch_pins"] = pins
    return apply_changes(team, changes)


# --- league ----------------------------------------------------------------

def certified_week_high_water(league_id):
    matches = [m for m in store.matches.values() if m["league_id"] == league_id]
    if not matches:
        return 0
    max_week = max(m["week_number"] for m in matches)
    high_water = 0
    for week in range(1, max_week + 1):
        weekly = [m for m in matches if m["week_number"] == week]
        if all(m["status"] in SETTLED_MATCH for m in weekly):
            high_water = week
        else:
            break
    return high_water


def recompute_league_counters(league):
    sanctioned = len([m for m in store.memberships.values()
                      if m["league_id"] == league["id"]
                      and m["sanction_status"] == "SANCTIONED"])
    confirmed = len([t for t in store.teams.values()
                     if t["league_id"] == league["id"]
                     and t["status"] == "CONFIRMED"])
    return apply_changes(league, {
        "sanctioned_member_count": sanctioned,
        "confirmed_team_count": confirmed,
        "certified_week_high_water": certified_week_high_water(league["id"]),
    })


# --- prize fund ------------------------------------------------------------

def recompute_prize_fund(league):
    fund = fund_of_league(league["id"])
    if fund is None:
        return False
    collected = 0
    for membership in memberships_of_league(league["id"]):
        for payment in dues_of_membership(membership["id"]):
            collected += payment["prize_share_cents"]
    paid = sum(a["amount_cents"] for a in awards_of_fund(fund["id"])
               if a["status"] == "PAID")
    return apply_changes(fund, {
        "collected_prize_cents": collected,
        "paid_award_total_cents": paid,
        "undistributed_balance_cents": collected - paid,
    })


def settled_prize_amount(league):
    """Prize shares of dues paid for weeks at or below the high-water mark."""
    high_water = league["certified_week_high_water"]
    total = 0
    for membership in memberships_of_league(league["id"]):
        for payment in dues_of_membership(membership["id"]):
            if payment["week_number"] <= high_water:
                total += payment["prize_share_cents"]
    return total


# --- cascades --------------------------------------------------------------

def cascade_certification_change(league, membership_ids, team_ids):
    """Hops 2, 3 and 4 shared by certification, voiding and forfeiting."""
    for membership_id in membership_ids:
        membership = store.memberships.get(membership_id)
        if membership is not None:
            recompute_membership(membership)
    for team_id in team_ids:
        team = store.teams.get(team_id)
        if team is not None:
            recompute_team(team)
    recompute_league_counters(league)
    for membership in memberships_of_league(league["id"]):
        recompute_dues_figures(membership)


def recompute_whole_league(league):
    """Bylaw amendment: every membership and every team re-derived."""
    for membership in memberships_of_league(league["id"]):
        recompute_membership(membership, include_entering=True)
    for team in teams_of_league(league["id"]):
        recompute_team(team)


def match_side_of_team(match, team_id):
    if match["home_team_id"] == team_id:
        return "home"
    if match["away_team_id"] == team_id:
        return "away"
    return None


def freeze_side_handicap(match, team_id):
    side = match_side_of_team(match, team_id)
    if side is None:
        return
    total = sum(s["handicap_per_game_applied"]
                for s in side_slots(match["id"], team_id))
    apply_changes(match, {side + "_team_handicap_per_game": total})


def set_and_recompute(membership, changes, include_entering=False):
    """Apply state changes and re-derive, bumping the version exactly once."""
    from store import touch
    changed = False
    for key, value in changes.items():
        if membership.get(key) != value:
            membership[key] = value
            changed = True
    dirty = recompute_membership(membership, include_entering)
    if changed and not dirty:
        touch(membership)
    return changed or dirty
