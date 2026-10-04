"""Shared domain services: calculations, sweeps, cascades, lookups."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, new_id, now_ts
from errors import err

# ---------------------------------------------------------------- constants
DIVISION_ORDER = ["TEE_BALL", "MINOR", "MAJOR", "JUNIOR", "SENIOR"]
DIVISION_AGE_RANGES = {
    "TEE_BALL": (4, 6),
    "MINOR": (7, 9),
    "MAJOR": (10, 12),
    "JUNIOR": (13, 14),
    "SENIOR": (15, 16),
}
PITCH_MAX = {
    "TEE_BALL": 50,
    "MINOR": 75,
    "MAJOR": 85,
    "JUNIOR": 95,
    "SENIOR": 95,
}
BASE_FEE_CENTS = 50000
PER_TEAM_FEE_CENTS = 7500
LATE_MULTIPLIER = Decimal("1.175")
PARTICIPATION_THRESHOLD = Decimal("60.00")
MIN_ROSTER_SIZE = 3
MAX_ROSTER_SIZE = 5
SEVERE_OFFENSES = {"VIOLENT_FELONY", "SEXUAL_OFFENSE", "CHILD_ABUSE"}
LEVEL_ORDER = ["DISTRICT", "SECTIONAL", "STATE", "REGIONAL"]
ELIMINATION_LIMIT = {"SINGLE_ELIMINATION": 1, "DOUBLE_ELIMINATION": 2}


# ---------------------------------------------------------------- date utils
def parse_date(s):
    return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- lookups
def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 0) + 1


def get_league(league_id):
    rec = db.leagues.get(league_id)
    if rec is None:
        raise err("ERR_LEAGUE_NOT_FOUND", f"league {league_id} not found")
    return rec


def _child(store, cid, parent_key, parent_id, error_id):
    rec = store.get(cid)
    if rec is None or rec.get(parent_key) != parent_id:
        raise err(error_id, f"{cid} not found")
    return rec


def get_division(league_id, division_id):
    return _child(db.divisions, division_id, "league_id", league_id, "ERR_DIVISION_NOT_FOUND")


def get_player(league_id, player_id):
    return _child(db.players, player_id, "league_id", league_id, "ERR_PLAYER_NOT_FOUND")


def get_renewal(league_id, renewal_id):
    return _child(db.renewals, renewal_id, "league_id", league_id, "ERR_RENEWAL_NOT_FOUND")


def get_waiver(league_id, waiver_id):
    return _child(db.waivers, waiver_id, "league_id", league_id, "ERR_WAIVER_NOT_FOUND")


def get_volunteer(league_id, volunteer_id):
    return _child(db.volunteers, volunteer_id, "league_id", league_id, "ERR_VOLUNTEER_NOT_FOUND")


def get_screening(volunteer_id, screening_id):
    return _child(db.screenings, screening_id, "volunteer_id", volunteer_id, "ERR_SCREENING_NOT_FOUND")


def get_roster(league_id, roster_id):
    return _child(db.rosters, roster_id, "league_id", league_id, "ERR_ROSTER_NOT_FOUND")


def get_entry(entry_id):
    rec = db.entries.get(entry_id)
    if rec is None:
        raise err("ERR_ENTRY_NOT_FOUND", f"entry {entry_id} not found")
    return rec


def get_game(entry_id, game_id):
    return _child(db.games, game_id, "entry_id", entry_id, "ERR_GAME_NOT_FOUND")


def get_appearance(game_id, appearance_id):
    rec = db.appearances.get(appearance_id)
    if rec is None or rec.get("game_id") != game_id:
        raise err("ERR_GAME_NOT_FOUND", f"appearance {appearance_id} not found")
    return rec


def get_protest(game_id, protest_id):
    return _child(db.protests, protest_id, "game_id", game_id, "ERR_PROTEST_NOT_FOUND")


def league_divisions(league_id):
    recs = [d for d in db.divisions.values() if d["league_id"] == league_id]
    recs.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return recs


# ---------------------------------------------------------------- calculations
def compute_league_age(birth_date, season_year):
    bd = parse_date(birth_date)
    age = season_year - bd.year
    if (bd.month, bd.day) > (8, 31):
        age -= 1
    return age


def compute_participation_pct(games_played, games_scheduled):
    if games_scheduled == 0:
        return Decimal("0.00")
    pct = (Decimal(100) * Decimal(games_played) / Decimal(games_scheduled)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return pct


def renewal_window_classification(season_year, clock_date):
    d = parse_date(clock_date)
    on_time_open = date(season_year - 1, 10, 1)
    on_time_close = date(season_year - 1, 12, 31)
    late_close = date(season_year, 3, 31)
    late_open = date(season_year, 1, 1)
    if on_time_open <= d <= on_time_close:
        return "ON_TIME"
    if late_open <= d <= late_close:
        return "LATE"
    raise err("ERR_RENEWAL_WINDOW_CLOSED", "renewal submission outside ON_TIME/LATE windows")


def charter_fee(league_id, window_classification):
    """Line-by-line fee; LATE multiplies each line by 1.175 rounded half up per line, then sums."""
    lines = [BASE_FEE_CENTS]
    for d in league_divisions(league_id):
        lines.append(d["team_count"] * PER_TEAM_FEE_CENTS)
    if window_classification == "ON_TIME":
        return sum(lines)
    total = 0
    for line in lines:
        total += int((Decimal(line) * LATE_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def rest_days_for(pitches):
    if pitches <= 20:
        return 0
    if pitches <= 35:
        return 1
    if pitches <= 50:
        return 2
    if pitches <= 65:
        return 3
    return 4


def compute_eligible_again_on(appearance_date, rest_days):
    return fmt_date(parse_date(appearance_date) + timedelta(days=rest_days))


def recompute_recorded_pitch_total(game):
    total = 0
    for a in db.appearances.values():
        if a["game_id"] == game["id"] and a["status"] == "RECORDED":
            total += a["official_pitches"] if a["official_pitches"] is not None else a["pitches_thrown"]
    game["recorded_pitch_total"] = total


def recompute_roster_size(roster):
    roster["roster_size"] = sum(1 for s in roster["selections"] if s["status"] == "ACTIVE")


def active_insurance(league_id):
    return [c for c in db.certificates.values()
            if c["league_id"] == league_id and c["status"] == "ACTIVE"]


def insurance_covers_dates(league_id, start, end):
    for c in active_insurance(league_id):
        if c["coverage_start"] <= start and c["coverage_end"] >= end:
            return True
    return False


# ---------------------------------------------------------------- cascades
def cancel_scheduled_games(entry_id):
    for g in db.games.values():
        if g["entry_id"] == entry_id and g["play_status"] == "SCHEDULED":
            g["play_status"] = "CANCELLED"
            touch(g)


def withdraw_entry(entry):
    if entry["status"] == "ACTIVE":
        entry["status"] = "WITHDRAWN"
        touch(entry)
        cancel_scheduled_games(entry["id"])


def suspend_league(league):
    """CHARTERED -> SUSPENDED with full cascade (§3.8)."""
    if league["charter_status"] != "CHARTERED":
        return
    league["charter_status"] = "SUSPENDED"
    touch(league)
    for d in league_divisions(league["id"]):
        if d["status"] == "ACTIVE":
            d["status"] = "SUSPENDED"
            touch(d)
    for e in db.entries.values():
        if e["league_id"] == league["id"] and e["status"] == "ACTIVE":
            withdraw_entry(e)


def clock_sweeps(new_clock_date):
    """Charter lapse sweep + insurance expiry sweep (§2.5)."""
    d = parse_date(new_clock_date)
    for league in list(db.leagues.values()):
        if league["charter_status"] != "CHARTERED":
            continue
        approved = [r for r in db.renewals.values()
                    if r["league_id"] == league["id"] and r["status"] == "APPROVED"]
        if not approved:
            continue
        latest_y = max(r["season_year"] for r in approved)
        lapse_after = date(latest_y + 1, 3, 31)
        if d > lapse_after:
            has_next = any(r["season_year"] == latest_y + 1 for r in approved)
            if not has_next:
                suspend_league(league)
    for c in list(db.certificates.values()):
        if c["status"] == "ACTIVE" and d > parse_date(c["coverage_end"]):
            c["status"] = "EXPIRED"
            touch(c)


def revoke_eligibility_cascade(player):
    """Player ELIGIBLE -> INELIGIBLE cascade (§3.4)."""
    player["eligibility_status"] = "INELIGIBLE"
    touch(player)
    affected_entry_ids = set()
    for roster in db.rosters.values():
        if roster["league_id"] != player["league_id"]:
            continue
        hit = False
        for sel in roster["selections"]:
            if sel["player_id"] == player["id"] and sel["status"] == "ACTIVE":
                sel["status"] = "VACATED"
                hit = True
        if not hit:
            continue
        recompute_roster_size(roster)
        if roster["status"] == "SUBMITTED":
            roster["status"] = "RECALLED"
        # LOCKED stays LOCKED (self-loop)
        touch(roster)
        for e in db.entries.values():
            if e["roster_id"] == roster["id"] and e["status"] == "ACTIVE":
                affected_entry_ids.add(e["id"])
    for eid in affected_entry_ids:
        withdraw_entry(db.entries[eid])


def elimination_check(entry):
    """After a LOSS finalize: increment losses and maybe eliminate (§3.7)."""
    limit = ELIMINATION_LIMIT[entry["elimination_format"]]
    if entry["losses_count"] >= limit and entry["status"] == "ACTIVE":
        entry["status"] = "ELIMINATED"
        touch(entry)
        cancel_scheduled_games(entry["id"])
