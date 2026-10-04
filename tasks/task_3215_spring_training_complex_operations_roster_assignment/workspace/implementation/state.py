"""Derived reads, recomputation helpers and the shared calculations.

Every function here is a *recomputation*: it reads the current rows out of the
store and rewrites the derived fields, so cascades and compensating actions need
no special-case bookkeeping.
"""

from core import (business_days, fmt, parse_dt, touch, truncate_minute, upper_snake)
from store import db
import rules as K


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def clock():
    return db.clock


def now_str():
    return fmt(db.clock)


def player_of(player_id):
    return db.get("players", player_id)


def group_of(group_id):
    return db.get("workout_groups", group_id)


def assignment_of(assignment_id):
    return db.get("group_assignments", assignment_id)


def complex_of(complex_id):
    return db.get("complexes", complex_id)


def game_of(game_id):
    return db.get("games", game_id)


def invitation_of(invitation_id):
    return db.get("camp_invitations", invitation_id)


def agreement_of(agreement_id):
    return db.get("community_agreements", agreement_id)


def host_record_of(record_id):
    return db.get("host_community_records", record_id)


def sponsorship_of(sponsorship_id):
    return db.get("sponsorships", sponsorship_id)


def throw_program_of(program_id):
    return db.get("throw_programs", program_id)


def profile_of(player_id):
    profiles = db.find("program_profiles", player_id=player_id)
    return profiles[0] if profiles else None


def roster_record_of(player_id):
    records = db.find("roster_records", player_id=player_id)
    return records[0] if records else None


def invitation_for_player(player_id):
    """The player's live invitation; the newest one when several exist."""
    rows = db.find("camp_invitations", player_id=player_id)
    return rows[-1] if rows else None


def host_record_for_agreement(agreement_id):
    rows = db.find("host_community_records", agreement_id=agreement_id)
    return rows[0] if rows else None


def agreements_of_complex(complex_id):
    return db.find("community_agreements", complex_id=complex_id)


def funding_agreement_for_complex(complex_id):
    """First ACTIVE agreement on the complex, created_at ascending."""
    for agreement in agreements_of_complex(complex_id):
        if agreement["agreement_status"] == "ACTIVE":
            return agreement
    return None


def groups_of_complex(complex_id):
    return db.find("workout_groups", complex_id=complex_id)


def assignments_of_group(group_id):
    return db.find("group_assignments", workout_group_id=group_id)


def assignments_of_player(player_id):
    return db.find("group_assignments", player_id=player_id)


def assignments_of_complex(complex_id):
    out = []
    for group in groups_of_complex(complex_id):
        out.extend(assignments_of_group(group["id"]))
    return out


def programs_of_complex(complex_id):
    out = []
    for assignment in assignments_of_complex(complex_id):
        out.extend(db.find("throw_programs", group_assignment_id=assignment["id"]))
    return out


def packages_for_player(player_id):
    return db.find("throw_programs", player_id=player_id)


def sessions_of_program(program_id):
    rows = db.find("throw_program_sessions", throw_program_id=program_id)
    rows.sort(key=lambda r: (r["logged_at"], r["session_sequence"], r["__seq"]))
    return rows


def program_of_player(player_id):
    """The player's throwing program; the newest one when several exist."""
    rows = packages_for_player(player_id)
    return rows[-1] if rows else None


def program_for_assignment(assignment_id):
    rows = db.find("throw_programs", group_assignment_id=assignment_id)
    return rows[-1] if rows else None


def is_farm_excluded(player_id):
    for trail in db.find("spring_trails", player_id=player_id):
        if trail["trail_status"] == "ACTIVE":
            return True
    return False


def latest_sponsorship_action_instant(agreement_id):
    stamps = []
    record_ids = [r["id"] for r in db.find("host_community_records", agreement_id=agreement_id)]
    for record_id in record_ids:
        for sp in db.find("sponsorships", host_community_record_id=record_id):
            if sp.get("last_action_at"):
                stamps.append(parse_dt(sp["last_action_at"]))
    return max(stamps) if stamps else None


# ---------------------------------------------------------------------------
# Travel liability window
# ---------------------------------------------------------------------------

def liability_rows_for_agreement(agreement, liability_set):
    """Rows posted under this agreement whose reimbursement status is live."""
    rows = []
    eligible_by_complex = {}
    for arrangement in db.all("travel_arrangements"):
        player = player_of(arrangement.get("player_id"))
        if player is None:
            continue
        if player.get("home_complex_id") != agreement["complex_id"]:
            continue
        if arrangement["reimbursement_status"] not in liability_set:
            continue
        if arrangement.get("liability_excluded"):
            # A row cancelled through the explicit cancel action drops out of
            # the window permanently (the VOID_EXCLUDED variant).
            continue
        if arrangement.get("funded_agreement_id") and \
                arrangement["funded_agreement_id"] != agreement["id"]:
            continue
        if not arrangement.get("funded_agreement_id"):
            # Never funded: it still occupies a window only while the player's
            # complex is funded by this agreement.
            if eligible_by_complex.get(agreement["complex_id"]) is None:
                active = funding_agreement_for_complex(agreement["complex_id"])
                eligible_by_complex[agreement["complex_id"]] = active["id"] if active else None
            if eligible_by_complex[agreement["complex_id"]] != agreement["id"]:
                continue
        rows.append(arrangement)
    rows.sort(key=lambda r: (r["created_at"], r["departure_at"] or "", r["__seq"]))
    return rows


def travel_liability_rows_for_player(player_id, liability_set=("LIABLE", "VOIDED")):
    rows = [a for a in db.find("travel_arrangements", player_id=player_id)
            if a["reimbursement_status"] in liability_set]
    rows.sort(key=lambda r: (r["created_at"], r["departure_at"] or "", r["__seq"]))
    return rows


def recompute_agreement_liability(agreement, narrow_to_liable=False):
    liability_set = ["LIABLE"] if narrow_to_liable else ["LIABLE", "VOIDED"]
    rows = liability_rows_for_agreement(agreement, liability_set)
    lease_end = parse_dt(agreement["lease_end_date"])
    total_days = 0
    for row in rows:
        departure = parse_dt(row["departure_at"])
        total_days += business_days(departure, lease_end)
    agreement["travel_liability_window_count"] = len(rows)
    agreement["travel_liability_days"] = total_days
    latest = latest_sponsorship_action_instant(agreement["id"])
    lag = 0
    if latest is not None:
        lag = business_days(lease_end, latest)
    agreement["settlement_release_lag_days"] = lag


# ---------------------------------------------------------------------------
# Host community ledger
# ---------------------------------------------------------------------------

def recognition_amount_cents(record, sponsorship):
    agreement = agreement_of(record["agreement_id"])
    if agreement is None:
        return 0
    corpus = [p for p in db.all("program_profiles")
              if (p["major_group_count"] + p["minor_group_count"]) >= 1]
    if not corpus:
        return 0
    major_equivalents = sum(p["major_group_count"] for p in corpus)
    minor_equivalents = sum(p["minor_group_count"] for p in corpus)
    multiplier = K.TIER_MULTIPLIER_PERMILLE[sponsorship["sponsor_tier"]]
    committed = sponsorship["committed_amount_cents"]
    total = 0
    for member in corpus:
        weight_sum = (K.MAJOR_WEIGHT * member["major_group_count"]) + \
                     (K.MINOR_WEIGHT * member["minor_group_count"])
        match_points = (weight_sum * multiplier) // K.MATCH_POINTS_DIVISOR
        commitment_points = min(committed // K.COMMITMENT_POINTS_DIVISOR,
                                K.COMMITMENT_POINTS_CAP)
        ceiling = K.JV_POINTS_CAP - \
            (K.REHAB_POINTS_DEBIT * member["active_rehab_assignment_count"])
        ceiling = max(0, ceiling)
        contribution = min(match_points + commitment_points, ceiling)
        total += (agreement["sponsorship_major_league_base_cents"] * major_equivalents *
                  contribution +
                  agreement["sponsorship_minor_league_base_cents"] * minor_equivalents *
                  contribution) // K.FINAL_DIVISOR
    return total


def recompute_host_record(record):
    sponsorships = db.find("sponsorships", host_community_record_id=record["id"])
    recorded = 0
    revenue = 0
    recognized_total = 0
    for sp in sponsorships:
        if sp["reconciliation_status"] != "SETTLEMENT_VOIDED":
            recorded += sp["committed_amount_cents"]
        if sp["reconciliation_status"] in ("UNSETTLED", "SETTLED",
                                           "SETTLEMENT_VOIDED"):
            # A voided settlement is a compensating reversal: PRD 2.11 requires
            # recognizing then voiding to leave ledger_gap_cents exactly at its
            # pre-settlement value, so the reversed row posts back to the ledger.
            revenue += sp["received_amount_cents"]
        if sp["reconciliation_status"] == "RECOGNIZED":
            recognized_total += recognition_amount_cents(record, sp)
    record["sponsorship_recorded_cents"] = recorded
    record["sponsorship_revenue_cents"] = revenue
    record["recognition_funded_cents"] = recognized_total
    funded = 0
    for arrangement in db.all("travel_arrangements"):
        invitation = invitation_of(arrangement.get("camp_invitation_id"))
        if invitation is None:
            continue
        player = player_of(invitation["player_id"])
        if player is None or player.get("home_complex_id") is None:
            continue
        active = funding_agreement_for_complex(player["home_complex_id"])
        if active is None or active["id"] != record["agreement_id"]:
            continue
        if arrangement["funding_source"] != "AGREEMENT_FUND":
            continue
        funded += arrangement["agreement_funded_cents"]
    record["agreement_funded_cents"] = funded
    record["community_ledger_cents"] = record["ticketing_revenue_cents"] + \
        record["sponsorship_revenue_cents"]
    record["ledger_gap_cents"] = record["community_ledger_cents"] - \
        record["recognition_funded_cents"]
    return record


def recompute_record_for_agreement(agreement_id):
    record = host_record_for_agreement(agreement_id)
    if record is not None:
        recompute_host_record(record)
    return record


# ---------------------------------------------------------------------------
# Complex aggregates and posture
# ---------------------------------------------------------------------------

def maintenance_block_for(complex_record, status=None):
    status = status or complex_record["field_maintenance_status"]
    capacity = complex_record["facility_capacity_units"]
    if status == "HALF_FIELD":
        return -((-capacity) // 2)
    if status == "CLOSED":
        return capacity
    return 0


def recompute_complex(complex_record, run_sweep=True):
    complex_id = complex_record["id"]
    published = [g for g in groups_of_complex(complex_id) if g["group_status"] == "PUBLISHED"]
    posted = 0
    for group in published:
        posted += group["capacity_units"]
    complex_record["posted_occupancy_units"] = posted
    major = 0
    minor = 0
    room = {g["id"] for g in published}
    for assignment in assignments_of_complex(complex_id):
        if assignment["workout_group_id"] not in room:
            continue
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        if assignment["roster_bucket"] == "MAJOR":
            major += 1
        else:
            minor += 1
    complex_record["reserved_major_units"] = major
    complex_record["reserved_minor_units"] = minor
    complex_record["maintenance_block_units"] = maintenance_block_for(complex_record)
    if run_sweep:
        sweep_posture(complex_record)
    return complex_record


def sweep_posture(complex_record):
    capacity = complex_record["facility_capacity_units"]
    block = maintenance_block_for(complex_record)
    effective = capacity - block
    posted = complex_record["posted_occupancy_units"]

    if complex_record["facility_posture"] == "CLOSED":
        # Sticky: a sweep may never relax a closed posture; only an explicit
        # field-maintenance OPEN from FIELD_RESTRICTED can.
        complex_record["contention_flagged"] = posted > capacity
        complex_record["posture_sweep_index"] = complex_record["posture_sweep_index"] + 1
        return complex_record

    if posted >= effective:
        complex_record["facility_posture"] = "CLOSED"
    elif posted >= (effective * K.RESTRICTED_PCT_OF_EFFECTIVE) // 100:
        complex_record["facility_posture"] = "FIELD_RESTRICTED"
    else:
        complex_record["facility_posture"] = "NORMAL"

    complex_record["contention_flagged"] = posted > capacity
    complex_record["posture_sweep_index"] = complex_record["posture_sweep_index"] + 1
    return complex_record


def contention_posture(complex_record):
    capacity = complex_record["facility_capacity_units"]
    block = maintenance_block_for(complex_record)
    denominator = max(1, capacity - block)
    ratio = (complex_record["posted_occupancy_units"] * 1000) // denominator
    posture = "NORMAL"
    if ratio >= 1000:
        posture = "OVER"
    elif ratio >= 950:
        posture = "TIGHT"
    elif ratio >= 900:
        posture = "WATCH"
    if posture == "NORMAL" and complex_record["season_split_track"] == "SHARED":
        for group in groups_of_complex(complex_record["id"]):
            if group["group_status"] == "PUBLISHED" and \
                    group["assigned_units"] >= group["capacity_units"]:
                posture = "TIGHT"
                break
    return posture


def recompute_groups_of_complex(complex_id):
    for group in groups_of_complex(complex_id):
        recompute_workout_group(group)


def recompute_workout_group(group):
    units = 0
    for assignment in assignments_of_group(group["id"]):
        if assignment["assignment_status"] in ("PROVISIONAL", "ACTIVE"):
            units += 1
    group["assigned_units"] = units
    return group


# ---------------------------------------------------------------------------
# Program profile projections
# ---------------------------------------------------------------------------

def select_active_assignment(player_id):
    """GroupAssignmentSelector: the assignment the profile points at. Only an
    assignment whose workout group is still PUBLISHED is eligible, since a
    DISBANDED group no longer holds a camp seat."""
    best = None
    best_key = None
    for assignment in assignments_of_player(player_id):
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        group = group_of(assignment["workout_group_id"])
        if group is None or group["group_status"] != "PUBLISHED":
            continue
        key = (1 if assignment["assignment_status"] == "ACTIVE" else 0,
               assignment.get("assigned_at") or "",
               assignment["__seq"])
        if best_key is None or key > best_key:
            best_key = key
            best = assignment
    return best


def detach_roster_from_camp(player_id):
    """A player whose last published-group assignment is gone is detached from
    the camp seating: the roster record no longer reports travel eligibility
    derived from a camp seat."""
    live = [a for a in assignments_of_player(player_id)
            if a["assignment_status"] in ("PROVISIONAL", "ACTIVE")
            and (group_of(a["workout_group_id"]) or {}).get("group_status") == "PUBLISHED"]
    if live:
        return None
    record = roster_record_of(player_id)
    if record is not None:
        record["split_squad_eligibility"] = "HOME_ONLY"
        touch(record, db.clock)
    return record


def recompute_profile(profile):
    player_id = profile["player_id"]
    major = 0
    minor = 0
    rehab = 0
    for assignment in assignments_of_player(player_id):
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        if assignment["roster_bucket"] == "MAJOR":
            major += 1
        else:
            minor += 1
        if assignment["assignment_kind"] == "REHAB":
            rehab += 1
    profile["major_group_count"] = major
    profile["minor_group_count"] = minor
    profile["active_rehab_assignment_count"] = rehab
    selected = select_active_assignment(player_id)
    profile["active_group_assignment_id"] = selected["id"] if selected else None
    if selected is not None:
        sessions = db.find("workout_group_sessions", workout_group_id=selected["workout_group_id"])
        profile["active_group_session_date"] = max(
            (s["session_date"] for s in sessions), default=None) if sessions else None
    else:
        profile["active_group_session_date"] = None
    return profile


def recompute_profiles_for_assignments(assignments):
    seen = set()
    for assignment in assignments:
        player_id = assignment["player_id"]
        if player_id in seen:
            continue
        seen.add(player_id)
        profile = profile_of(player_id)
        if profile is not None:
            recompute_profile(profile)
    return seen


# ---------------------------------------------------------------------------
# Throw program arithmetic
# ---------------------------------------------------------------------------

def gameday_game_for_complex(complex_id):
    for game in db.find("games", complex_id=complex_id):
        if game["gameday_status"] == "GAMEDAY":
            return game
    return None


def recompute_throw_program(program):
    sessions = [s for s in sessions_of_program(program["id"])
                if s["session_status"] == "LOGGED"]
    throws = 0
    bullpen = 0
    for session in sessions:
        if session["session_kind"] == "CATCH_PLAY":
            throws += session["play_catch_throws"]
        elif session["session_kind"] == "BULLPEN":
            bullpen += 1
    program["cumulative_throws"] = throws
    program["cumulative_bullpen_sessions"] = bullpen

    last = None
    for session in sessions:
        stamp = session["logged_at"]
        if last is None or stamp > last:
            last = stamp
    program["last_session_date"] = last

    assignment = assignment_of(program["group_assignment_id"])
    scheduled = None
    if assignment is not None:
        for participation in db.find("game_participations", player_id=assignment["player_id"]):
            game = game_of(participation["game_schedule_id"])
            if game is None:
                continue
            if game["game_schedule_status"] not in ("PUBLISHED", "PLAYED"):
                continue
            if participation["participation_status"] not in ("SCHEDULED", "CONFIRMED", "LOCKED"):
                continue
            stamp = game["game_datetime"]
            if scheduled is None or stamp > scheduled:
                scheduled = stamp
    program["last_game_scheduled_date"] = scheduled

    age_factor = min(K.AGE_CAP_DAYS,
                     business_days(parse_dt(program["created_at"]), db.clock))
    bump = 0
    if assignment is not None:
        group = group_of(assignment["workout_group_id"])
        complex_record = complex_of(group["complex_id"]) if group else None
        if complex_record is not None:
            game = gameday_game_for_complex(complex_record["id"])
            if game is not None:
                given = False
                for participation in db.find("game_participations",
                                             game_schedule_id=game["id"],
                                             player_id=assignment["player_id"]):
                    if participation["throw_count"] > 0:
                        given = True
                if not given:
                    bump = K.DAY_OF_GAME_REQUIRED_THROWS
    program["schedule_requirement_throws"] = throws + age_factor + bump

    phase = program["program_phase"]
    if phase == "SHUTDOWN":
        program["requirement_status"] = "NOT_REQUIRED"
    else:
        allowance = K.PHASE_CATCH_ALLOWANCE_PERMILLE[phase]
        programmed_max = (program["target_catch_play_throws"] * allowance) // 100
        tolerance = (program["target_catch_play_throws"] // 10) * K.STEP_TOLERANCE_PER_UNIT
        score = program["schedule_requirement_throws"]
        if programmed_max <= score <= programmed_max + tolerance:
            program["requirement_status"] = "MET"
        else:
            program["requirement_status"] = "UNMET"
    return program


def recompute_programs_of_player(player_id):
    for program in packages_for_player(player_id):
        recompute_throw_program(program)


def assignment_pool_of_group(group):
    """The group the throwing-program cascade seats a pitcher into."""
    return group


# ---------------------------------------------------------------------------
# Roster record derived reads
# ---------------------------------------------------------------------------

def option_charges(player, record, relief=False):
    base = K.OPTION_EQUIVALENT_YEARS_OFFSET + player["minor_league_option_years_used"]
    burden = min(record["option_decisions_used"], K.OPTION_DECISION_BURDEN_CAP)
    charges = base + burden
    if relief:
        charges = max(0, charges - 1)
    return charges


def recompute_option_reads(record, relief=False):
    player = player_of(record["player_id"])
    charges = option_charges(player, record, relief=relief)
    if charges < K.OPTION_ELIGIBILITY_THRESHOLD:
        record["option_eligibility"] = "OPTION_AVAILABLE"
    else:
        record["option_eligibility"] = "NO_OPTION_REMAINING"
    record["option_credit_source"] = \
        "VOIDED_OPTION_RESTORES_CHARGE" if relief else "BASE_ALLOWANCE"
    record["waivers_required"] = (record["option_eligibility"] == "NO_OPTION_REMAINING")
    return record


def bucket_credit_totals(player_id):
    """3 credits per MINOR trigger row, 5 per MAJOR trigger row."""
    minor_count = 0
    major_count = 0
    for assignment in assignments_of_player(player_id):
        if assignment["assignment_status"] not in ("PROVISIONAL", "ACTIVE"):
            continue
        if assignment["roster_bucket"] == "MAJOR":
            major_count += 1
        else:
            minor_count += 1
    return minor_count, major_count


def refresh_waivers_required(record):
    player = player_of(record["player_id"])
    charges = option_charges(player, record)
    option_flag = charges >= K.OPTION_ELIGIBILITY_THRESHOLD
    minor_count, major_count = bucket_credit_totals(record["player_id"])
    credit = (K.MINOR_BUCKET_CREDIT * minor_count) + (K.MAJOR_BUCKET_CREDIT * major_count)
    record["waivers_required"] = option_flag or (credit >= K.WAIVERS_REQUIRED_CREDIT_THRESHOLD)
    return record


def split_squad_eligibility_for(player_id):
    rows = [a for a in db.find("travel_arrangements", player_id=player_id)
            if a["status"] == "CONFIRMED"]
    if not rows:
        return "HOME_ONLY"
    rows.sort(key=lambda r: (r["created_at"], r["__seq"]))
    latest = rows[-1]
    if latest["travel_radius_miles"] <= K.TRAVEL_RADIUS_LIMIT_MILES:
        return "HOME_AND_TRAVEL"
    return "HOME_ONLY"


def recompute_roster_record(record):
    record["split_squad_eligibility"] = split_squad_eligibility_for(record["player_id"])
    recompute_option_reads(record)
    refresh_waivers_required(record)
    return record


def finalized_claim_window_count(player_id):
    count = 0
    for record in db.find("roster_records", player_id=player_id):
        if record.get("decision_finalized_at") and \
                record.get("finalized_roster_status") == "WAIVER_CLAIMED":
            count += 1
    return count


def waiver_claim_days(record):
    if not record["waivers_required"]:
        return None, 0
    player = player_of(record["player_id"])
    if player["minor_league_option_years_used"] >= 4:
        rule_days = K.WAIVER_RULE_DAYS_LONG
    else:
        rule_days = K.WAIVER_RULE_DAYS_SHORT
    liability_sum = 0
    for arrangement in travel_liability_rows_for_player(record["player_id"]):
        liability_sum += arrangement["agreement_funded_cents"]
    bump = -((-liability_sum) // K.WAIVER_BUMP_DIVISOR_CENTS)
    prior = finalized_claim_window_count(record["player_id"])
    effective = max(0, min(rule_days + bump, K.WAIVER_CLAIM_CAP_DAYS) - prior)
    return "NOT_REQUIRED" if False else "EFFECTIVE_CLAIM_WINDOW", effective


def waiver_window_expired(record):
    """True once the recorded claim window has elapsed on the logical clock."""
    if record.get("waiver_claim_requested_at") is None:
        return False
    days = record.get("waiver_claim_window_days") or 0
    requested = parse_dt(record["waiver_claim_requested_at"])
    elapsed = business_days(requested, db.clock)
    return elapsed >= days


# ---------------------------------------------------------------------------
# Game derived reads
# ---------------------------------------------------------------------------

def recompute_game(game):
    first_pitch = parse_dt(game["game_datetime"])
    duration = game["duration_units"]
    start = first_pitch - __import__("datetime").timedelta(hours=duration)
    end = first_pitch + __import__("datetime").timedelta(hours=duration)
    game["game_interval_start"] = fmt(start)
    game["game_interval_end"] = fmt(end)
    if game["game_schedule_status"] == "PUBLISHED":
        box_start = first_pitch - __import__("datetime").timedelta(days=1)
        box_end = first_pitch + __import__("datetime").timedelta(days=1)
        if box_start <= db.clock <= box_end:
            game["gameday_status"] = "GAMEDAY"
        else:
            game["gameday_status"] = "NOT_GAMEDAY"
    else:
        game["gameday_status"] = "NOT_GAMEDAY"
    return game


def game_interval(game):
    first_pitch = parse_dt(game["game_datetime"])
    from datetime import timedelta
    duration = game["duration_units"]
    return (truncate_minute(first_pitch - timedelta(hours=duration)),
            truncate_minute(first_pitch + timedelta(hours=duration)))


def sessions_collide_with_game(complex_id, game):
    start, end = game_interval(game)
    for session in db.all("workout_group_sessions"):
        group = group_of(session["workout_group_id"])
        if group is None or group["complex_id"] != complex_id:
            continue
        if session["session_status"] == "CANCELLED":
            continue
        s_start = truncate_minute(parse_dt(session["session_date"]))
        s_end = truncate_minute(parse_dt(session["session_end_datetime"]))
        # touching at a single shared minute boundary still conflicts, so the
        # comparison is closed at both ends
        if s_start <= end and start <= s_end:
            return session
    return None


# ---------------------------------------------------------------------------
# Response projections
# ---------------------------------------------------------------------------

def complex_view(record):
    for group in groups_of_complex(record["id"]):
        recompute_workout_group(group)
    recompute_complex(record, run_sweep=False)
    data = {k: v for k, v in record.items() if not k.startswith("__")}
    data["contention_posture"] = contention_posture(record)
    return data


def group_view(record):
    recompute_workout_group(record)
    return {k: v for k, v in record.items() if not k.startswith("__")}


def plain(record, extra=None):
    if record is None:
        return None
    data = {k: v for k, v in record.items() if not k.startswith("__")}
    if extra:
        data.update(extra)
    return data


def player_view(record):
    return plain(record)


def agreement_view(agreement):
    recompute_agreement_liability(agreement)
    return plain(agreement)


def ledger_view(record):
    recompute_host_record(record)
    sponsorships = db.find("sponsorships", host_community_record_id=record["id"])
    settled = sum(1 for s in sponsorships if s["reconciliation_status"] in ("SETTLED", "RECOGNIZED"))
    recognized = sum(1 for s in sponsorships if s["reconciliation_status"] == "RECOGNIZED")
    agreement = agreement_of(record["agreement_id"])
    liability = {}
    if agreement is not None:
        recompute_agreement_liability(agreement)
        liability = {
            "travel_liability_window_count": agreement["travel_liability_window_count"],
            "travel_liability_days": agreement["travel_liability_days"],
            "settlement_release_lag_days": agreement["settlement_release_lag_days"],
        }
    data = {
        "community_ledger_cents": record["community_ledger_cents"],
        "ticketing_revenue_cents": record["ticketing_revenue_cents"],
        "sponsorship_recorded_cents": record["sponsorship_recorded_cents"],
        "sponsorship_revenue_cents": record["sponsorship_revenue_cents"],
        "agreement_funded_cents": record["agreement_funded_cents"],
        "recognition_funded_cents": record["recognition_funded_cents"],
        "ledger_gap_cents": record["ledger_gap_cents"],
        "settled_sponsorship_count": settled,
        "recognized_sponsorship_count": recognized,
    }
    data.update(liability)
    return data