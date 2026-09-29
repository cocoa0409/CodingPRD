"""Unified teams, competition entries, divisioning and results."""
from decimal import Decimal

from flask import Blueprint

import db
import derive
from core import (ABILITY_SPREAD_MAX_RATIO, AGE_GROUP_ORDINAL,
                  DISQUALIFICATION_REASON_CODES, DIVISION_MAX_ENTRIES,
                  DIVISION_MIN_ENTRIES, DIVISION_STATUSES, ENTRY_STATUSES,
                  MEMBER_TYPES, PARTICIPANT_TYPES, RESTRICTION_BARS_SPORT,
                  ROSTER_STATUSES, TIME_SCORED_SPORTS,
                  UNIFIED_AGE_SPAN_MAX_YEARS, auth, bad_request, clock_date,
                  dec, fail, get_body, is_num, ok, opt_bool, opt_enum,
                  paginate, parse_date, query_enum, query_str, req_enum,
                  req_int, req_num, req_str, round4, sort_key, whole_years,
                  age_group_for)
from serialize import ser_division, ser_entry, ser_season, ser_team

bp = Blueprint("competition", __name__)

# ------------------------------------------------------------ unified teams ---


@bp.get("/seasons/<rid>/unified-teams")
def list_season_teams(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    season = derive.require("seasons", rid)
    roster_status = query_enum("roster_status", ROSTER_STATUSES)
    rows = [t for t in db.teams.values() if t["season_id"] == season["id"]]
    if roster_status:
        rows = [t for t in rows if t["roster_status"] == roster_status]
    return paginate(rows, ser_team)


@bp.get("/unified-teams/<rid>")
def get_team(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    team = derive.require("teams", rid)
    return ok(ser_team(team))


@bp.post("/seasons/<rid>/unified-teams")
def create_team(rid):
    auth(["ProgramManager", "CompetitionDirector"])
    season = derive.require("seasons", rid)
    body = get_body()
    team_name = req_str(body, "team_name", 3, 80)
    for other in db.teams.values():
        if other["season_id"] == season["id"] and other["team_name"] == team_name:
            bad_request("team_name is already used within this season.")
    if season["status"] != "PRACTICE_OPEN":
        fail("ERR_SEASON_NOT_PRACTICE_OPEN", 409,
             "The season is not open for practice.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "team_create")
    team = db.new_row("teams", {
        "season_id": season["id"],
        "team_name": team_name,
        "athlete_ids": [],
        "partner_volunteer_ids": [],
        "athlete_count": 0,
        "partner_count": 0,
        "age_span_years": 0,
        "roster_status": "FORMING",
    })
    return ok(ser_team(team), 201)


@bp.post("/unified-teams/<rid>/members")
def add_team_member(rid):
    auth(["ProgramManager", "CompetitionDirector"])
    team = derive.require("teams", rid)
    body = get_body()
    member_type = req_enum(body, "member_type", MEMBER_TYPES)
    member_id = body.get("member_id")
    if not isinstance(member_id, str) or member_id == "":
        bad_request("Field 'member_id' must be a resource id string.")
    if member_type == "ATHLETE":
        member = derive.require("athletes", member_id)
    else:
        member = derive.require("volunteers", member_id)
    expected_version = req_int(body, "expected_team_version")
    if expected_version != team["version"]:
        fail("ERR_STALE_TEAM_VERSION", 412,
             "expected_team_version does not match the team's current version.")
    season = db.seasons[team["season_id"]]
    program = derive.program_of_season(season)
    derive.posture_gate(program, "team_member_add")
    if member_type == "ATHLETE":
        if member["medical_status"] not in ("CLEARED", "RESTRICTED"):
            fail("ERR_ATHLETE_MEDICAL_HOLD", 422,
                 "The athlete's medical dimension does not clear them for a "
                 "field of play.")
        if member["registration_status"] != "ACTIVE":
            fail("ERR_ATHLETE_NOT_ACTIVE", 422,
                 "The athlete's registration is not ACTIVE.")
    else:
        if not derive.volunteer_has_live_partner_credential(member):
            fail("ERR_PARTNER_CREDENTIAL_INVALID", 422,
                 "A unified partner must hold a live CERTIFIED "
                 "UNIFIED_PARTNER credential.")
    if (member_id in team["athlete_ids"]
            or member_id in team["partner_volunteer_ids"]):
        fail("ERR_DUPLICATE_TEAM_MEMBER", 409,
             "This member is already listed on the roster.")
    athlete_count = team["athlete_count"]
    partner_count = team["partner_count"]
    if member_type == "ATHLETE":
        athlete_count += 1
    else:
        partner_count += 1
    if abs(athlete_count - partner_count) > 1:
        fail("ERR_UNIFIED_RATIO_VIOLATION", 422,
             "Neither side of a unified roster may exceed the other by more "
             "than one.")
    ages = derive.team_ages(team, season)
    ages.append(derive.member_age(team, season, member,
                                  member_type == "ATHLETE"))
    span = (max(ages) - min(ages)) if len(ages) >= 2 else 0
    if span > UNIFIED_AGE_SPAN_MAX_YEARS:
        fail("ERR_UNIFIED_AGE_SPAN_EXCEEDED", 422,
             "The roster's age span may not exceed %d years."
             % UNIFIED_AGE_SPAN_MAX_YEARS)
    if member_type == "ATHLETE":
        team["athlete_ids"].append(member_id)
    else:
        team["partner_volunteer_ids"].append(member_id)
    db.touch(team)
    derive.recompute_team(team)
    return ok(ser_team(team))

# -------------------------------------------------------- competition entries ---


@bp.get("/competition-entries")
def list_entries():
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    season_id = query_str("season_id")
    division_id = query_str("division_id")
    participant_id = query_str("participant_id")
    participant_type = query_enum("participant_type", PARTICIPANT_TYPES)
    status = query_enum("status", ENTRY_STATUSES)
    rows = list(db.entries.values())
    if season_id:
        rows = [e for e in rows if e["season_id"] == season_id]
    if division_id:
        rows = [e for e in rows if e["division_id"] == division_id]
    if participant_id:
        rows = [e for e in rows if e["participant_id"] == participant_id]
    if participant_type:
        rows = [e for e in rows if e["participant_type"] == participant_type]
    if status:
        rows = [e for e in rows if e["status"] == status]
    return paginate(rows, ser_entry)


@bp.get("/competition-entries/<rid>")
def get_entry(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    entry = derive.require("entries", rid)
    return ok(ser_entry(entry))


def _entry_restriction_conflict(athlete, season):
    form_id = athlete.get("current_medical_form_id")
    if form_id is None:
        return False
    form = db.medical_forms.get(form_id)
    if form is None:
        return False
    for restriction in (form.get("restrictions") or []):
        if RESTRICTION_BARS_SPORT.get(restriction) == season["sport"]:
            return True
    return False


@bp.post("/competition-entries")
def create_entry():
    auth(["CompetitionDirector"])
    body = get_body()
    season_id = body.get("season_id")
    if not isinstance(season_id, str) or season_id == "":
        bad_request("Field 'season_id' must be a resource id string.")
    season = derive.require("seasons", season_id)
    participant_type = req_enum(body, "participant_type", PARTICIPANT_TYPES)
    participant_id = body.get("participant_id")
    if not isinstance(participant_id, str) or participant_id == "":
        bad_request("Field 'participant_id' must be a resource id string.")
    program = derive.program_of_season(season)
    if participant_type == "ATHLETE":
        participant = db.athletes.get(participant_id)
        if participant is None or participant["program_id"] != program["id"]:
            fail("ERR_PARTICIPANT_NOT_FOUND", 404,
                 "No athlete of this program matches participant_id.")
    else:
        participant = db.teams.get(participant_id)
        if participant is None:
            fail("ERR_PARTICIPANT_NOT_FOUND", 404,
                 "No unified team matches participant_id.")
        team_season = db.seasons.get(participant["season_id"])
        if team_season is None or team_season["program_id"] != program["id"]:
            fail("ERR_PARTICIPANT_NOT_FOUND", 404,
                 "The unified team does not belong to the season's program.")
    event_code = req_str(body, "event_code", 3, 32)
    skill_score = req_num(body, "skill_score")
    if dec(skill_score) <= 0:
        bad_request("skill_score must be strictly greater than zero.")
    if season["status"] != "PRACTICE_OPEN":
        fail("ERR_SEASON_NOT_PRACTICE_OPEN", 409,
             "The season is not open for practice.")
    derive.posture_gate(program, "entry_create")
    if participant_type == "ATHLETE":
        if participant["medical_status"] not in ("CLEARED", "RESTRICTED"):
            fail("ERR_ATHLETE_MEDICAL_HOLD", 422,
                 "The athlete's medical dimension does not clear them for a "
                 "field of play.")
        if participant["registration_status"] != "ACTIVE":
            fail("ERR_ATHLETE_NOT_ACTIVE", 422,
                 "The athlete's registration is not ACTIVE.")
        if _entry_restriction_conflict(participant, season):
            fail("ERR_MEDICAL_RESTRICTION_INCOMPATIBLE", 422,
                 "The athlete's medical restrictions bar this sport.")
    if clock_date() > parse_date(season["registration_deadline"]):
        fail("ERR_REGISTRATION_DEADLINE_PASSED", 409,
             "The season's registration deadline has passed.")
    if participant_type == "ATHLETE":
        if not derive.practice_minimums_met(participant, season):
            fail("ERR_PRACTICE_MINIMUM_NOT_MET", 422,
                 "The athlete has not met both of the season's practice "
                 "minimums.")
    else:
        if participant["roster_status"] != "COMPLIANT":
            fail("ERR_ROSTER_NOT_COMPLIANT", 422,
                 "The unified roster is not COMPLIANT.")
    for other in db.entries.values():
        if (other["season_id"] == season["id"]
                and other["participant_id"] == participant_id
                and other["event_code"] == event_code
                and other["status"] not in ("VOIDED", "DISQUALIFIED")):
            fail("ERR_DUPLICATE_ENTRY", 409,
                 "This participant already holds a live entry for this event.")
    live_entries = len([e for e in db.entries.values()
                        if e["season_id"] == season["id"]
                        and e["status"] != "VOIDED"])
    if live_entries >= season["entry_slot_budget"]:
        fail("ERR_SEASON_ENTRY_BUDGET_EXCEEDED", 409,
             "The season's entry slot budget is exhausted.")

    competition_date = parse_date(season["competition_date"])
    if participant_type == "ATHLETE":
        born = parse_date(participant["birth_date"])
    else:
        births = [parse_date(db.athletes[a]["birth_date"])
                  for a in participant["athlete_ids"] if a in db.athletes]
        born = max(births) if births else None
    age = whole_years(born, competition_date) if born is not None else 0
    entry = db.new_row("entries", {
        "season_id": season["id"],
        "division_id": None,
        "participant_type": participant_type,
        "participant_id": participant_id,
        "event_code": event_code,
        "skill_score": skill_score,
        "age_on_competition_date": age,
        "age_group": age_group_for(age),
        "seed_rank": None,
        "result_value": None,
        "performance_ratio": None,
        "placement": None,
        "advancement_status": "NOT_ADVANCED",
        "status": "SUBMITTED",
        "disqualification_reason_code": None,
        "void_reason_code": None,
    })
    derive.recompute_season_counts(season)
    return ok(ser_entry(entry), 201)


@bp.post("/competition-entries/<rid>/result")
def post_result(rid):
    auth(["CompetitionDirector"])
    entry = derive.require("entries", rid)
    body = get_body()
    result_value = req_num(body, "result_value")
    if dec(result_value) <= 0:
        bad_request("result_value must be strictly greater than zero.")
    disqualified = opt_bool(body, "disqualified", default=False)
    reason_code = opt_enum(body, "disqualification_reason_code",
                           DISQUALIFICATION_REASON_CODES)
    if disqualified and reason_code is None:
        bad_request("disqualification_reason_code is required when disqualified "
                    "is true.")
    season = db.seasons[entry["season_id"]]
    if entry["status"] != "LOCKED":
        fail("ERR_ENTRY_STATE_INVALID", 409,
             "Only a LOCKED entry may have a result posted.")
    if season["status"] != "ENTRIES_LOCKED":
        fail("ERR_SEASON_STATE_INVALID", 409,
             "The season's entries are not locked.")
    if clock_date() < parse_date(season["competition_date"]):
        fail("ERR_COMPETITION_DATE_NOT_REACHED", 409,
             "The season's competition date has not been reached.")

    entry["result_value"] = result_value
    if disqualified:
        entry["status"] = "DISQUALIFIED"
        entry["disqualification_reason_code"] = reason_code
        entry["performance_ratio"] = None
        entry["placement"] = None
    else:
        if season["sport"] in TIME_SCORED_SPORTS:
            ratio = round4(dec(entry["skill_score"]) / dec(result_value))
        else:
            ratio = round4(dec(result_value) / dec(entry["skill_score"]))
        entry["performance_ratio"] = float(ratio)
        entry["status"] = "RESULTED"
    db.touch(entry)
    division = db.divisions.get(entry["division_id"])
    if division is not None:
        derive.run_waterfall(division)
    return ok(ser_entry(entry))

# ----------------------------------------------------------------- divisions ---


@bp.get("/divisions")
def list_divisions():
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    season_id = query_str("season_id")
    merged_into = query_str("merged_into_division_id")
    status = query_enum("status", DIVISION_STATUSES)
    rows = list(db.divisions.values())
    if season_id:
        rows = [d for d in rows if d["season_id"] == season_id]
    if merged_into:
        rows = [d for d in rows if d["merged_into_division_id"] == merged_into]
    if status:
        rows = [d for d in rows if d["status"] == status]
    return paginate(rows, ser_division)


@bp.get("/divisions/<rid>")
def get_division(rid):
    auth(["ProgramManager", "CompetitionDirector", "Coach"], write=False)
    division = derive.require("divisions", rid)
    return ok(ser_division(division))


def _new_division(season, entry):
    return db.new_row("divisions", {
        "season_id": season["id"],
        "merged_into_division_id": None,
        "event_code": entry["event_code"],
        "participant_type": entry["participant_type"],
        "age_group": entry["age_group"],
        "ability_band_high": entry["skill_score"],
        "ability_band_low": entry["skill_score"],
        "ability_spread_ratio": None,
        "entry_count": 0,
        "merged_source_count": 0,
        "status": "DRAFT",
    })


def _close_division(division, members):
    high = max(dec(e["skill_score"]) for e in members)
    low = min(dec(e["skill_score"]) for e in members)
    division["ability_band_high"] = max(
        members, key=lambda e: dec(e["skill_score"]))["skill_score"]
    division["ability_band_low"] = min(
        members, key=lambda e: dec(e["skill_score"]))["skill_score"]
    division["ability_spread_ratio"] = float(round4(high / low))
    division["entry_count"] = len(members)
    division["status"] = ("VALID" if len(members) >= DIVISION_MIN_ENTRIES
                          else "UNDERSIZED")


def _banding_pass(season, candidates):
    partitions = {}
    for entry in candidates:
        key = (entry["participant_type"], entry["event_code"],
               entry["age_group"])
        partitions.setdefault(key, []).append(entry)
    divisions = []
    for key in sorted(partitions.keys()):
        ordered = sorted(partitions[key],
                         key=lambda e: (-dec(e["skill_score"]),) + sort_key(e))
        open_division = None
        members = []
        band_floor = None
        for entry in ordered:
            if open_division is not None:
                fits = (dec(entry["skill_score"]) >= band_floor
                        and len(members) < DIVISION_MAX_ENTRIES)
                if not fits:
                    _close_division(open_division, members)
                    open_division = None
            if open_division is None:
                open_division = _new_division(season, entry)
                divisions.append(open_division)
                members = []
                band_floor = round4(dec(entry["skill_score"])
                                    / ABILITY_SPREAD_MAX_RATIO)
            entry["division_id"] = open_division["id"]
            members.append(entry)
        if open_division is not None:
            _close_division(open_division, members)
    return divisions


def _merge_pass(season, divisions):
    snapshot = {}
    for division in divisions:
        snapshot[division["id"]] = {
            "entry_count": division["entry_count"],
            "ability_band_high": division["ability_band_high"],
            "ability_band_low": division["ability_band_low"],
            "status": division["status"],
        }
    sources = [d for d in divisions if snapshot[d["id"]]["status"] == "UNDERSIZED"]
    sources.sort(key=lambda d: (AGE_GROUP_ORDINAL[d["age_group"]],
                               dec(snapshot[d["id"]]["ability_band_low"]))
                 + sort_key(d))
    received = set()
    for source in sources:
        if source["id"] in received:
            continue
        source_snap = snapshot[source["id"]]
        source_high = dec(source_snap["ability_band_high"])
        source_low = dec(source_snap["ability_band_low"])
        source_count = source_snap["entry_count"]
        source_ordinal = AGE_GROUP_ORDINAL[source["age_group"]]
        eligible = []
        for target in db.divisions.values():
            if target["id"] == source["id"]:
                continue
            if target["season_id"] != season["id"]:
                continue
            if target["participant_type"] != source["participant_type"]:
                continue
            if target["event_code"] != source["event_code"]:
                continue
            if target["status"] not in ("VALID", "UNDERSIZED"):
                continue
            target_ordinal = AGE_GROUP_ORDINAL[target["age_group"]]
            if abs(target_ordinal - source_ordinal) > 1:
                continue
            live = len(derive.division_live_entries(target))
            if live + source_count > DIVISION_MAX_ENTRIES:
                continue
            target_high = dec(target["ability_band_high"])
            target_low = dec(target["ability_band_low"])
            combined = round4(max(target_high, source_high)
                              / min(target_low, source_low))
            if combined > ABILITY_SPREAD_MAX_RATIO:
                continue
            eligible.append(target)
        if not eligible:
            continue
        eligible.sort(key=lambda t: (abs(dec(t["ability_band_high"])
                                         - source_high),
                                     abs(AGE_GROUP_ORDINAL[t["age_group"]]
                                         - source_ordinal))
                      + sort_key(t))
        target = eligible[0]
        for entry in derive.division_live_entries(source):
            entry["division_id"] = target["id"]
        source["status"] = "VOIDED"
        source["merged_into_division_id"] = target["id"]
        source["entry_count"] = 0
        db.touch(source)
        target["merged_source_count"] = target["merged_source_count"] + 1
        live_entries = derive.division_live_entries(target)
        if live_entries:
            high = max(live_entries, key=lambda e: dec(e["skill_score"]))
            low = min(live_entries, key=lambda e: dec(e["skill_score"]))
            target["ability_band_high"] = high["skill_score"]
            target["ability_band_low"] = low["skill_score"]
            target["ability_spread_ratio"] = float(
                round4(dec(high["skill_score"]) / dec(low["skill_score"])))
        target["entry_count"] = len(live_entries)
        target["status"] = ("VALID"
                           if len(live_entries) >= DIVISION_MIN_ENTRIES
                           else "UNDERSIZED")
        db.touch(target)
        received.add(target["id"])


def _seed_divisions(season):
    for division in db.divisions.values():
        if division["season_id"] != season["id"]:
            continue
        if division["status"] == "VOIDED":
            continue
        live = derive.division_live_entries(division)
        live.sort(key=lambda e: (-dec(e["skill_score"]),) + sort_key(e))
        for index, entry in enumerate(live):
            entry["seed_rank"] = index + 1


@bp.post("/seasons/<rid>/divisioning")
def run_divisioning(rid):
    auth(["CompetitionDirector"])
    season = derive.require("seasons", rid)
    if season["status"] != "PRACTICE_OPEN":
        fail("ERR_SEASON_STATE_INVALID", 409,
             "Only a PRACTICE_OPEN season may be divisioned.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "divisioning")
    if clock_date() < parse_date(season["registration_deadline"]):
        fail("ERR_REGISTRATION_STILL_OPEN", 409,
             "The season's registration deadline has not been reached.")
    candidates = [e for e in db.entries.values()
                  if e["season_id"] == season["id"]
                  and e["status"] == "SUBMITTED"
                  and e["division_id"] is None]
    if not candidates:
        fail("ERR_NO_ELIGIBLE_ENTRIES", 422,
             "This season has no SUBMITTED entry to division.")
    divisions = _banding_pass(season, candidates)
    _merge_pass(season, divisions)
    _seed_divisions(season)
    for entry in candidates:
        entry["status"] = "DIVISIONED"
        db.touch(entry)
    changes = {
        "status": "DIVISIONED",
        "divisioning_run_count": season["divisioning_run_count"] + 1,
    }
    db.apply_changes(season, changes)
    derive.recompute_season_counts(season)
    return ok(ser_season(season))


@bp.post("/seasons/<rid>/redivision")
def run_redivision(rid):
    auth(["CompetitionDirector"])
    season = derive.require("seasons", rid)
    if season["status"] != "DIVISIONED":
        fail("ERR_SEASON_STATE_INVALID", 409,
             "Only a DIVISIONED season may be reverted for redivision.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "redivision")
    pool = [e for e in db.entries.values()
            if e["season_id"] == season["id"]
            and e["status"] in ("SUBMITTED", "DIVISIONED")]
    if not pool:
        fail("ERR_NO_ELIGIBLE_ENTRIES", 422,
             "This season has no entry to return for a fresh run.")
    for division in db.divisions.values():
        if division["season_id"] != season["id"]:
            continue
        if division["status"] not in ("DRAFT", "VALID", "UNDERSIZED"):
            continue
        division["status"] = "VOIDED"
        db.touch(division)
    for entry in pool:
        if entry["status"] != "DIVISIONED":
            continue
        entry["status"] = "SUBMITTED"
        entry["division_id"] = None
        entry["seed_rank"] = None
        db.touch(entry)
    db.apply_changes(season, {"status": "PRACTICE_OPEN"})
    derive.recompute_season_counts(season)
    return ok(ser_season(season))


@bp.post("/seasons/<rid>/lock-entries")
def lock_entries(rid):
    auth(["CompetitionDirector"])
    season = derive.require("seasons", rid)
    if season["status"] != "DIVISIONED":
        fail("ERR_SEASON_STATE_INVALID", 409,
             "Only a DIVISIONED season may have its entries locked.")
    if clock_date() > parse_date(season["competition_date"]):
        fail("ERR_SEASON_STATE_INVALID", 409,
             "The season's competition date has already passed.")
    program = derive.program_of_season(season)
    derive.posture_gate(program, "lock_entries")
    for division in db.divisions.values():
        if (division["season_id"] == season["id"]
                and division["status"] == "UNDERSIZED"):
            fail("ERR_UNDERSIZED_DIVISION_PRESENT", 409,
                 "An undersized division still stands in this season.")
    for entry in db.entries.values():
        if entry["season_id"] != season["id"] or entry["status"] != "DIVISIONED":
            continue
        division = db.divisions.get(entry["division_id"])
        if division is None or division["status"] != "VALID":
            continue
        entry["status"] = "LOCKED"
        db.touch(entry)
    db.apply_changes(season, {"status": "ENTRIES_LOCKED"})
    derive.recompute_season_counts(season)
    return ok(ser_season(season))
