"""Derived counters, posture, ledgers, composition and cascade helpers."""
from decimal import Decimal

import db
from core import (ADVANCEMENT_TARGET, CREDENTIAL_DENOMINATOR_STATUSES,
                  DIVISION_MIN_ENTRIES, MAXING_RATIO_THRESHOLD,
                  POSTURE_FROZEN_EXPIRED_RATIO, POSTURE_RESTRICTED_EXPIRED_RATIO,
                  TIME_SCORED_SPORTS, UNIFIED_AGE_SPAN_MAX_YEARS,
                  UNIFIED_MIN_ATHLETES, clock_date, clock_now, clock_str, dec,
                  fail, parse_date, parse_dt, round4, sort_key, whole_years)

# --------------------------------------------------------------- existence ---

NOT_FOUND = {
    "programs": "ERR_PROGRAM_NOT_FOUND",
    "athletes": "ERR_ATHLETE_NOT_FOUND",
    "medical_forms": "ERR_MEDICAL_FORM_NOT_FOUND",
    "volunteers": "ERR_VOLUNTEER_NOT_FOUND",
    "credentials": "ERR_CREDENTIAL_NOT_FOUND",
    "seasons": "ERR_SEASON_NOT_FOUND",
    "sessions": "ERR_SESSION_NOT_FOUND",
    "divisions": "ERR_DIVISION_NOT_FOUND",
    "entries": "ERR_ENTRY_NOT_FOUND",
    "teams": "ERR_TEAM_NOT_FOUND",
    "screenings": "ERR_SCREENING_NOT_FOUND",
    "contributions": "ERR_CONTRIBUTION_NOT_FOUND",
}


def require(collection, row_id, error_id=None):
    row = db.COLLECTIONS[collection].get(row_id)
    if row is None:
        fail(error_id or NOT_FOUND[collection], 404,
             "No such resource: %s." % row_id)
    return row

# ------------------------------------------------------------- navigation ---


def program_of_athlete(athlete):
    return db.programs[athlete["program_id"]]


def program_of_volunteer(volunteer):
    return db.programs[volunteer["program_id"]]


def program_of_credential(credential):
    return program_of_volunteer(db.volunteers[credential["volunteer_id"]])


def program_of_season(season):
    return db.programs[season["program_id"]]


def program_of_session(session):
    return program_of_season(db.seasons[session["season_id"]])


def program_of_team(team):
    return program_of_season(db.seasons[team["season_id"]])


def program_of_form(form):
    return program_of_athlete(db.athletes[form["athlete_id"]])


def program_of_screening(screening):
    return program_of_athlete(db.athletes[screening["athlete_id"]])


def program_volunteers(program_id):
    return [v for v in db.volunteers.values() if v["program_id"] == program_id]


def program_credentials(program_id):
    vol_ids = {v["id"] for v in db.volunteers.values()
               if v["program_id"] == program_id}
    return [c for c in db.credentials.values() if c["volunteer_id"] in vol_ids]


def program_athletes(program_id):
    return [a for a in db.athletes.values() if a["program_id"] == program_id]


def program_screenings(program_id):
    ath_ids = {a["id"] for a in db.athletes.values()
               if a["program_id"] == program_id}
    return [s for s in db.screenings.values() if s["athlete_id"] in ath_ids]


def program_contributions(program_id):
    return [c for c in db.contributions.values()
            if c["program_id"] == program_id]


def program_seasons(program_id):
    return [s for s in db.seasons.values() if s["program_id"] == program_id]


def credential_is_live(credential, role_class):
    if credential is None:
        return False
    if credential["role_class"] != role_class:
        return False
    if credential["status"] != "CERTIFIED":
        return False
    expires = parse_date(credential.get("expires_on"))
    return expires is not None and expires >= clock_date()


def volunteer_has_live_partner_credential(volunteer):
    return any(credential_is_live(c, "UNIFIED_PARTNER")
               for c in db.credentials.values()
               if c["volunteer_id"] == volunteer["id"])

# --------------------------------------------------------------- ledgers ---


def recompute_athlete_ledger(athlete):
    rows = [r for r in db.attendance.values()
            if r["athlete_id"] == athlete["id"] and r["status"] == "COUNTED"]
    db.apply_changes(athlete, {
        "cumulative_practice_minutes": sum(r["counted_minutes"] for r in rows),
        "counted_session_count": len(rows),
    })


def compute_program_counters(program):
    program_id = program["id"]
    today = clock_date()
    creds = program_credentials(program_id)
    certified_coach_count = 0
    denominator = 0
    expired = 0
    for cred in creds:
        if cred["status"] in CREDENTIAL_DENOMINATOR_STATUSES:
            denominator += 1
            if cred["status"] in ("EXPIRED", "RENEWAL_IN_PROGRESS"):
                expired += 1
            if cred["role_class"] == "COACH" and cred["status"] == "CERTIFIED":
                expires = parse_date(cred.get("expires_on"))
                if expires is not None and expires >= today:
                    certified_coach_count += 1
    if denominator > 0:
        ratio = round4(dec(expired) / dec(denominator))
    else:
        ratio = Decimal("0.0000")

    urgent = len([s for s in program_screenings(program_id)
                  if s["finding_severity"] == "URGENT"
                  and s["referral_status"] in ("REFERRED", "FOLLOW_UP_LOGGED",
                                               "ESCALATED")])
    athletes = program_athletes(program_id)
    active = len([a for a in athletes if a["registration_status"] == "ACTIVE"])
    practice_minutes = sum(a["cumulative_practice_minutes"] for a in athletes)

    contribs = program_contributions(program_id)
    recognized = sum(c["recognized_value_cents"] for c in contribs
                     if c["status"] == "RECEIVED")
    pledged = sum(c["recognized_value_cents"] for c in contribs
                  if c["status"] == "PLEDGED")
    family = sum(c["match_credit_cents"] for c in contribs
                 if c["status"] == "RECEIVED")

    if certified_coach_count == 0 or ratio >= POSTURE_FROZEN_EXPIRED_RATIO:
        posture = "FROZEN"
    elif ratio >= POSTURE_RESTRICTED_EXPIRED_RATIO or urgent >= 1:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"

    return {
        "certified_coach_count": certified_coach_count,
        "credential_denominator_count": denominator,
        "expired_credential_count": expired,
        "expired_credential_ratio": float(ratio),
        "unresolved_urgent_referral_count": urgent,
        "active_athlete_count": active,
        "program_practice_minutes": practice_minutes,
        "recognized_support_cents": recognized,
        "pledged_support_cents": pledged,
        "family_engagement_credit_cents": family,
        "compliance_posture": posture,
    }


def recompute_program(program):
    db.apply_changes(program, compute_program_counters(program))
    return program

# ---------------------------------------------------------------- posture ---

RESTRICTED_BLOCKED_OPS = {"divisioning", "redivision", "lock_entries",
                          "entry_create"}
FROZEN_BLOCKED_OPS = RESTRICTED_BLOCKED_OPS | {
    "open_practice", "session_create", "attendance_create", "team_create",
    "team_member_add"}


def posture_gate(program, operation):
    posture = program["compliance_posture"]
    if posture == "FROZEN" and operation in FROZEN_BLOCKED_OPS:
        fail("ERR_PROGRAM_POSTURE_FROZEN", 409,
             "The program's compliance posture is FROZEN.")
    if posture == "RESTRICTED" and operation in RESTRICTED_BLOCKED_OPS:
        fail("ERR_PROGRAM_POSTURE_RESTRICTED", 409,
             "The program's compliance posture is RESTRICTED.")

# ------------------------------------------------------------- divisions ---


def division_live_entries(division):
    return [e for e in db.entries.values()
            if e["division_id"] == division["id"] and e["status"] != "VOIDED"]


def recompute_division(division):
    live = division_live_entries(division)
    changes = {"entry_count": len(live)}
    if live:
        high = max(e["skill_score"] for e in live)
        low = min(e["skill_score"] for e in live)
        changes["ability_band_high"] = high
        changes["ability_band_low"] = low
        changes["ability_spread_ratio"] = float(round4(dec(high) / dec(low)))
    if division["status"] != "VOIDED":
        changes["status"] = ("VALID" if len(live) >= DIVISION_MIN_ENTRIES
                             else "UNDERSIZED")
    db.apply_changes(division, changes)


def recompute_season_counts(season):
    rows = [e for e in db.entries.values() if e["season_id"] == season["id"]]
    entry_count = len([e for e in rows if e["status"] != "VOIDED"])
    divisioned = len([e for e in rows
                      if e["status"] in ("DIVISIONED", "LOCKED", "RESULTED",
                                         "ADVANCED", "DISQUALIFIED")
                      and e["division_id"] is not None])
    db.apply_changes(season, {"entry_count": entry_count,
                              "divisioned_entry_count": divisioned})

# ----------------------------------------------------------- unified teams ---


def member_age(team, season, member_row, is_athlete):
    comp = parse_date(season["competition_date"])
    born = parse_date(member_row["birth_date"] if is_athlete
                      else member_row["date_of_birth"])
    return whole_years(born, comp)


def team_ages(team, season):
    ages = []
    for aid in team["athlete_ids"]:
        athlete = db.athletes.get(aid)
        if athlete is not None:
            ages.append(member_age(team, season, athlete, True))
    for vid in team["partner_volunteer_ids"]:
        volunteer = db.volunteers.get(vid)
        if volunteer is not None:
            ages.append(member_age(team, season, volunteer, False))
    return ages


def recompute_team(team):
    season = db.seasons[team["season_id"]]
    ages = team_ages(team, season)
    span = (max(ages) - min(ages)) if len(ages) >= 2 else 0
    athlete_count = len(team["athlete_ids"])
    partner_count = len(team["partner_volunteer_ids"])
    athletes = [db.athletes[a] for a in team["athlete_ids"] if a in db.athletes]
    partners = [db.volunteers[v] for v in team["partner_volunteer_ids"]
                if v in db.volunteers]
    if athlete_count == 0 or partner_count == 0:
        status = "FORMING"
    elif (athlete_count == partner_count
          and athlete_count >= UNIFIED_MIN_ATHLETES
          and span <= UNIFIED_AGE_SPAN_MAX_YEARS
          and all(a["registration_status"] == "ACTIVE"
                  and a["medical_status"] in ("CLEARED", "RESTRICTED")
                  for a in athletes)
          and all(volunteer_has_live_partner_credential(v) for v in partners)):
        status = "COMPLIANT"
    else:
        status = "NON_COMPLIANT"
    db.apply_changes(team, {
        "athlete_count": athlete_count,
        "partner_count": partner_count,
        "age_span_years": span,
        "roster_status": status,
    })


def recompute_teams_for_athlete(athlete):
    for team in list(db.teams.values()):
        if athlete["id"] in team["athlete_ids"]:
            recompute_team(team)


def recompute_teams_for_volunteer(volunteer):
    for team in list(db.teams.values()):
        if volunteer["id"] in team["partner_volunteer_ids"]:
            recompute_team(team)

# --------------------------------------------------------------- cascades ---


def void_attendance_of_session(session):
    affected = set()
    for row in list(db.attendance.values()):
        if row["session_id"] != session["id"]:
            continue
        if row["status"] not in ("COUNTED", "NOT_COUNTED"):
            continue
        row["status"] = "VOIDED"
        row["counted_minutes"] = 0
        db.touch(row)
        affected.add(row["athlete_id"])
    return affected


def void_session(session, reason):
    session["status"] = "VOIDED"
    session["void_reason_code"] = reason
    session["counts_toward_minimum"] = False
    db.touch(session)
    return void_attendance_of_session(session)


def void_sessions_for_credential(credential, reason,
                                 future_scheduled_only=False):
    affected = set()
    for session in list(db.sessions.values()):
        if session["coach_credential_id"] != credential["id"]:
            continue
        if future_scheduled_only:
            if session["status"] != "SCHEDULED":
                continue
            start = parse_dt(session["scheduled_start"])
            if start is None or not start > clock_now():
                continue
        elif session["status"] not in ("SCHEDULED", "HELD"):
            continue
        affected |= void_session(session, reason)
    for athlete_id in affected:
        athlete = db.athletes.get(athlete_id)
        if athlete is not None:
            recompute_athlete_ledger(athlete)
    return affected


def void_entries_for_athlete(athlete, reason):
    division_ids = set()
    season_ids = set()
    for entry in list(db.entries.values()):
        if entry["participant_type"] != "ATHLETE":
            continue
        if entry["participant_id"] != athlete["id"]:
            continue
        if entry["status"] not in ("SUBMITTED", "DIVISIONED", "LOCKED"):
            continue
        entry["status"] = "VOIDED"
        entry["void_reason_code"] = reason
        db.touch(entry)
        if entry["division_id"] is not None:
            division_ids.add(entry["division_id"])
        season_ids.add(entry["season_id"])
    for division_id in division_ids:
        division = db.divisions.get(division_id)
        if division is not None:
            recompute_division(division)
    for season_id in season_ids:
        season = db.seasons.get(season_id)
        if season is not None:
            recompute_season_counts(season)

# ---------------------------------------------------- practice eligibility ---


def practice_totals(athlete, season):
    count = 0
    minutes = 0
    now = clock_now()
    for row in db.attendance.values():
        if row["athlete_id"] != athlete["id"] or row["status"] != "COUNTED":
            continue
        if row["season_id"] != season["id"]:
            continue
        session = db.sessions.get(row["session_id"])
        if session is None or session["status"] != "HELD":
            continue
        start = parse_dt(session["scheduled_start"])
        if start is None or start > now:
            continue
        count += 1
        minutes += row["counted_minutes"]
    return count, minutes


def practice_minimums_met(athlete, season):
    count, minutes = practice_totals(athlete, season)
    return (count >= season["practice_minimum_sessions"]
            and minutes >= season["practice_minimum_minutes"])

# --------------------------------------------------- advancement waterfall ---


def run_waterfall(division):
    season = db.seasons[division["season_id"]]
    time_scored = season["sport"] in TIME_SCORED_SPORTS
    pool = [e for e in db.entries.values()
            if e["division_id"] == division["id"]
            and e["status"] in ("RESULTED", "ADVANCED")]
    pool.sort(key=lambda e: (dec(e["result_value"]) if time_scored
                             else -dec(e["result_value"]),) + sort_key(e))
    plan = []
    for index, entry in enumerate(pool):
        placement = index + 1
        ratio = entry.get("performance_ratio")
        maxing = (ratio is not None
                  and round4(ratio) > MAXING_RATIO_THRESHOLD)
        plan.append([entry, placement,
                     "INELIGIBLE_MAXING" if maxing else "NOT_ADVANCED", False])

    target = ADVANCEMENT_TARGET[season["games_level"]]
    if target != "NOT_ADVANCED":
        slots = season["advancement_slots_per_division"]
        for item in plan:
            if slots <= 0:
                break
            if item[2] == "INELIGIBLE_MAXING":
                continue
            item[2] = target
            item[3] = True
            slots -= 1

    for entry, placement, advancement, advanced in plan:
        changes = {"placement": placement, "advancement_status": advancement}
        changes["status"] = "ADVANCED" if advanced else "RESULTED"
        db.apply_changes(entry, changes)
