"""Route handlers: invitations, travel, physicals, games, participations,
spring trails, minor league assignments and operations checkpoints."""

from datetime import timedelta

import rules as K
import state as S
from core import (ApiError, ERR_FARM_ENTITY_EXCLUDED, ERR_INVALID_STATE,
                  bad, business_days, fmt, new_record, optional_int, parse_dt,
                  require_enum, require_int, require_number, require_str,
                  spend_days, touch, truncate_midnight)
from store import db


# ===========================================================================
# CampInvitation
# ===========================================================================

def _rehab_grace_days(player_id):
    profile = S.profile_of(player_id)
    count = profile["active_rehab_assignment_count"] if profile else 0
    return K.FINAL_GRACE_BASE_DAYS + -((-3 * count) // K.REHAB_GRACE_DIVISOR)


def create_camp_invitation(env):
    player_id = env["path"]["player_id"]
    player = db.get("players", player_id)
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    kind = require_enum(body, "invitation_kind",
                        ("NRI_STANDARD", "GUEST_INSTRUCTOR", "CAMP_INVITEE"))
    base = parse_dt(body.get("report_base_date") or K.DEFAULT_REPORT_BASE_DATE,
                    "report_base_date")
    if player["position_code"] in ("P", "C"):
        lead = K.PITCHER_CATCHER_LEAD_DAYS
    else:
        lead = K.POSITION_PLAYER_LEAD_DAYS
    if kind == "GUEST_INSTRUCTOR":
        lead += K.GUEST_INSTRUCTOR_EXTRA_DAYS
    report_current = truncate_midnight(spend_days(base, -lead))
    report_final = spend_days(report_current, _rehab_grace_days(player_id))
    if body.get("report_final_date") is not None:
        supplied = parse_dt(body["report_final_date"], "report_final_date")
        if supplied < report_current:
            raise bad("report_final_date is earlier than report_current_date.")

    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "invitation_kind": kind,
        "report_current_date": fmt(report_current),
        "report_final_date": fmt(report_final),
        "actual_report_date": None,
        "arrival_band": "MISSED_WINDOW",
        "travel_arrangement_status": "NOT_ARRANGED",
        "invitation_status": "ISSUED",
        "invitation_letter_status": "LETTER_PENDING",
        "domestic_travel": player["home_country"] == "United States",
    })
    db.insert("camp_invitations", record)
    return S.plain(record)


def _invitation_or_404(invitation_id):
    record = db.get("camp_invitations", invitation_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such camp invitation.")
    return record


def get_camp_invitation(env):
    return S.plain(_invitation_or_404(env["path"]["invitation_id"]))


def list_camp_invitations(env):
    records = db.all("camp_invitations")
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    status = env["query"].get("invitation_status")
    if status:
        records = [r for r in records if r["invitation_status"] == status]
    return [S.plain(r) for r in records]


def list_player_camp_invitations(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return [S.plain(r) for r in db.find("camp_invitations", player_id=player_id)]


def send_letter(env):
    record = _invitation_or_404(env["path"]["invitation_id"])
    if record["invitation_letter_status"] != "LETTER_PENDING":
        raise ApiError(ERR_INVALID_STATE, "The invitation letter has already been sent.")
    record["invitation_letter_status"] = "LETTER_SENT"
    touch(record, db.clock)
    return S.plain(record)


def acknowledge_invitation(env):
    record = _invitation_or_404(env["path"]["invitation_id"])
    if env["uid"] is None or env["uid"] != record["player_id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only the invited player may acknowledge this invitation.")
    if record["invitation_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "The invitation is not awaiting acknowledgement.")
    record["invitation_status"] = "ACKNOWLEDGED"
    touch(record, db.clock)
    return S.plain(record)


def _arrival_band(actual, current, final):
    if actual < current:
        return "EARLY"
    if actual == current:
        return "MET_CURRENT"
    if current < actual <= final:
        return "MET_FINAL"
    return "MISSED_WINDOW"


def arrive_invitation(env):
    record = _invitation_or_404(env["path"]["invitation_id"])
    _player_or_404(record["player_id"])
    if record["invitation_status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, "The invitation is not acknowledged.")
    if record["invitation_letter_status"] != "LETTER_SENT":
        raise ApiError("ERR_INVITATION_LETTER_MISSING", "The invitation letter is pending.")
    if not (record["domestic_travel"] or
            record["travel_arrangement_status"] == "ARRANGED"):
        raise ApiError(ERR_INVALID_STATE, "The travel arrangement is not yet arranged.")
    report_final = parse_dt(record["report_final_date"])
    if not db.clock <= report_final:
        raise ApiError("ERR_OUTSIDE_WINDOW", "The clock is past the report window.")
    record["invitation_status"] = "ARRIVED"
    record["actual_report_date"] = fmt(db.clock)
    record["arrival_band"] = _arrival_band(db.clock,
                                           parse_dt(record["report_current_date"]),
                                           report_final)
    touch(record, db.clock)
    return S.plain(record)


def _unwind_invitation_travel(record):
    """CASCADE 1: cancel the arrangements and reverse every agreement post."""
    record["travel_arrangement_status"] = "CANCELLED"
    player = db.get("players", record["player_id"])
    agreement = None
    if player is not None:
        agreement = S.funding_agreement_for_complex(player["home_complex_id"])
    for arrangement in db.find("travel_arrangements", camp_invitation_id=record["id"]):
        if arrangement["status"] in ("PLANNED", "CONFIRMED"):
            arrangement["status"] = "CANCELLED"
            if arrangement["funding_source"] == "AGREEMENT_FUND":
                arrangement["funded_reversed"] = True
            arrangement["funding_source"] = "NONE"
            if arrangement["reimbursement_status"] == "LIABLE":
                arrangement["reimbursement_status"] = "VOIDED"
            arrangement["agreement_funded_cents"] = 0
            arrangement["reimbursement_cents"] = 0
            touch(arrangement, db.clock)
    for other_agreement in db.all("community_agreements"):
        S.recompute_record_for_agreement(other_agreement["id"])
        S.recompute_agreement_liability(other_agreement)
    return agreement


def mark_visa_blocked(env):
    record = _invitation_or_404(env["path"]["invitation_id"])
    if record["invitation_status"] != "ARRIVED":
        raise ApiError(ERR_INVALID_STATE, "The invitation has not arrived.")
    if record["domestic_travel"]:
        raise ApiError(ERR_INVALID_STATE, "A domestic arrival cannot be visa blocked.")
    record["invitation_status"] = "VISA_BLOCKED"
    _unwind_invitation_travel(record)
    touch(record, db.clock)
    return S.plain(record)


# ===========================================================================
# TravelArrangement
# ===========================================================================

def _parse_arrangement_body(body):
    mode = require_enum(body, "mode", ("AIR", "BUS", "AUTO"))
    radius = require_number(body, "travel_radius_miles", 0)
    departure = parse_dt(body.get("departure_at"), "departure_at")
    cost = require_int(body, "travel_cost_cents", 0)
    confirm = body.get("confirm", False)
    if not isinstance(confirm, bool):
        raise bad("confirm must be a boolean.")
    if departure is None:
        raise bad("departure_at is required.")
    return mode, radius, departure, cost, confirm


def _travel_band(radius):
    if radius <= 100:
        return 100
    if radius <= 300:
        return 300
    return 1000


def _run_confirmation(record, invitation, player, cost, mode, radius, departure):
    if record["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, "The arrangement is not planned.")
    report_current = parse_dt(invitation["report_current_date"])
    # The departure window sits behind the letter gate: it is a declared window,
    # so it reports ERR_OUTSIDE_WINDOW, while the missing letter reports
    # ERR_INVITATION_LETTER_MISSING.
    if departure > report_current:
        raise ApiError("ERR_OUTSIDE_WINDOW",
                       "The departure is later than the report date.")
    if not invitation["domestic_travel"]:
        if departure > spend_days(report_current, -K.PHYSICAL_LEAD_DAYS):
            raise ApiError("ERR_OUTSIDE_WINDOW",
                           "An international departure needs a longer runway.")
    if invitation["invitation_letter_status"] != "LETTER_SENT":
        raise ApiError("ERR_INVITATION_LETTER_MISSING", "The invitation letter is pending.")

    agreement = S.funding_agreement_for_complex(player["home_complex_id"])
    if agreement is not None:
        draw = (cost * (1000 - K.MODE_RADIUS_DISCOUNT[mode][_travel_band(radius)])) // 1000
        host = S.host_record_for_agreement(agreement["id"])
        if host is not None:
            # `ticketing_revenue_cents` is the declared ticket-sale accumulator
            # and `agreement_funded_cents` the travel draws posted against it.
            # This row still carries NONE/0, so both reads are pre-post.
            S.recompute_host_record(host)
            available = host["ticketing_revenue_cents"] - host["agreement_funded_cents"]
            if draw > available:
                raise ApiError("ERR_AGREEMENT_UNDERFUNDED",
                               "The draw exceeds the available agreement funding.")
        record["funding_source"] = "AGREEMENT_FUND"
        record["agreement_funded_cents"] = draw
        record["reimbursement_cents"] = 0
    elif cost > 0:
        record["funding_source"] = "REIMBURSEMENT"
        record["agreement_funded_cents"] = 0
        record["reimbursement_cents"] = cost * (1000 - K.HOLDBACK_PERMILLE) // 1000
    else:
        record["funding_source"] = "NONE"
        record["agreement_funded_cents"] = 0
        record["reimbursement_cents"] = 0

    record["reimbursement_status"] = "LIABLE" if cost > 0 else "NOT_LIABLE"
    record["status"] = "CONFIRMED"
    invitation["travel_arrangement_status"] = "ARRANGED"
    touch(invitation, db.clock)
    return agreement


def _arrange(env, invitation_id, body, occ_field=None, always_new=False):
    invitation = _invitation_or_404(invitation_id)
    player = db.get("players", invitation["player_id"])
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The invitation's player is missing.")
    mode, radius, departure, cost, confirm = _parse_arrangement_body(body)

    if occ_field is not None:
        if occ_field not in body or body[occ_field] is None:
            raise bad("%s is required." % occ_field)
        expected = body[occ_field]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise bad("%s must be an integer." % occ_field)
        if expected != invitation["version"]:
            raise ApiError("ERR_STALE_VERSION", "The invitation has advanced.")

    candidates = [a for a in db.find("travel_arrangements", camp_invitation_id=invitation["id"])
                  if a["status"] != "CANCELLED"]
    record = None if always_new else (candidates[-1] if candidates else None)
    if record is not None and record["status"] == "CONFIRMED" and confirm:
        raise ApiError(ERR_INVALID_STATE, "The arrangement is already confirmed.")
    if record is None:
        record = new_record(db.new_id(), db.clock)
        record.update({
            "camp_invitation_id": invitation["id"],
            "player_id": invitation["player_id"],
            "status": "PLANNED",
            "funding_source": "NONE",
            "reimbursement_status": "NOT_LIABLE",
            "agreement_funded_cents": 0,
            "reimbursement_cents": 0,
            "funded_agreement_id": None,
        })
        db.insert("travel_arrangements", record)
    else:
        if record["status"] == "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, "The arrangement is already confirmed.")

    record["mode"] = mode
    record["travel_radius_miles"] = radius
    record["departure_at"] = fmt(departure)
    record["travel_cost_cents"] = cost

    settlement_narrow = False
    if confirm:
        agreement = _run_confirmation(record, invitation, player, cost, mode, radius, departure)
        if agreement is not None:
            record["funded_agreement_id"] = agreement["id"]
    else:
        record["status"] = "PLANNED"
        record["funding_source"] = "NONE"
        record["reimbursement_status"] = "NOT_LIABLE"
        record["agreement_funded_cents"] = 0
        record["reimbursement_cents"] = 0
        record["funded_agreement_id"] = None
    touch(record, db.clock)

    for agreement in db.all("community_agreements"):
        S.recompute_record_for_agreement(agreement["id"])
        S.recompute_agreement_liability(agreement, narrow_to_liable=settlement_narrow)
    _refresh_split_squad(record["player_id"])
    return record


def _refresh_split_squad(player_id):
    """`split_squad_eligibility` tracks the player's own confirmed arrangements,
    so a confirmation, revert or cancellation of one is a mutation of that row."""
    record = S.roster_record_of(player_id)
    if record is not None:
        record["split_squad_eligibility"] = S.split_squad_eligibility_for(player_id)
        touch(record, db.clock)
    return record


def arrange_travel(env):
    record = _arrange(env, env["path"]["invitation_id"], env["body"],
                      occ_field="expected_invitation_version")
    return S.plain(record)


def create_travel_arrangement(env):
    body = env["body"]
    invitation_id = require_str(body, "camp_invitation_id")
    if db.get("camp_invitations", invitation_id) is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such camp invitation.")
    record = _arrange(env, invitation_id, body, always_new=True)
    return S.plain(record)


def _arrangement_or_404(arrangement_id):
    record = db.get("travel_arrangements", arrangement_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such travel arrangement.")
    return record


def get_travel_arrangement(env):
    return S.plain(_arrangement_or_404(env["path"]["arrangement_id"]))


def list_travel_arrangements(env):
    records = db.all("travel_arrangements")
    invitation_id = env["query"].get("camp_invitation_id")
    if invitation_id:
        records = [r for r in records if r["camp_invitation_id"] == invitation_id]
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    return [S.plain(r) for r in records]


def list_invitation_travel_arrangements(env):
    invitation = _invitation_or_404(env["path"]["invitation_id"])
    return [S.plain(r) for r in db.find("travel_arrangements",
                                        camp_invitation_id=invitation["id"])]


def _reverse_agreement_post(record):
    """Reverse this arrangement's draw and settle the ledger back."""
    for agreement in db.all("community_agreements"):
        if record.get("funded_agreement_id") and \
                agreement["id"] != record["funded_agreement_id"]:
            continue
        host = S.host_record_for_agreement(agreement["id"])
        if host is None:
            continue
        S.recompute_host_record(host)


def revert_travel_arrangement(env):
    record = _arrangement_or_404(env["path"]["arrangement_id"])
    if record["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "The arrangement is not confirmed.")
    invitation = _invitation_or_404(record["camp_invitation_id"])
    record["status"] = "PLANNED"
    record["funding_source"] = "NONE"
    record["reimbursement_status"] = "NOT_LIABLE"
    record["agreement_funded_cents"] = 0
    record["reimbursement_cents"] = 0
    record["funded_agreement_id"] = None
    if invitation["travel_arrangement_status"] == "ARRANGED":
        invitation["travel_arrangement_status"] = "NOT_ARRANGED"
        touch(invitation, db.clock)
    touch(record, db.clock)
    for agreement in db.all("community_agreements"):
        S.recompute_record_for_agreement(agreement["id"])
        S.recompute_agreement_liability(agreement)
    _refresh_split_squad(record["player_id"])
    return S.plain(record)


def cancel_travel_arrangement(env):
    record = _arrangement_or_404(env["path"]["arrangement_id"])
    if record["status"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "The arrangement cannot be cancelled.")
    invitation = _invitation_or_404(record["camp_invitation_id"])
    was_confirmed = record["status"] == "CONFIRMED"
    record["status"] = "CANCELLED"
    record["agreement_funded_cents"] = 0
    record["reimbursement_cents"] = 0
    record["funding_source"] = "NONE"
    if was_confirmed:
        record["reimbursement_status"] = "VOIDED"
        # The VOID_EXCLUDED variant is persistent: the cancelled row drops out
        # of the window and travel_liability_window_count decreases by one.
        record["liability_excluded"] = True
    still_live = [a for a in db.find("travel_arrangements",
                                     camp_invitation_id=invitation["id"])
                  if a["id"] != record["id"] and a["status"] != "CANCELLED"]
    if not still_live:
        invitation["travel_arrangement_status"] = "NOT_ARRANGED"
        touch(invitation, db.clock)
    touch(record, db.clock)
    for agreement in db.all("community_agreements"):
        S.recompute_record_for_agreement(agreement["id"])
        S.recompute_agreement_liability(agreement, narrow_to_liable=True)
    _refresh_split_squad(record["player_id"])
    return S.plain(record)


# ===========================================================================
# Physical
# ===========================================================================

def create_physical(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    scheduled = parse_dt(body.get("scheduled_visit_date"), "scheduled_visit_date")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "scheduled_visit_date": fmt(scheduled),
        "status": "SCHEDULED",
        "physical_result": None,
        "performed_at": None,
    })
    db.insert("physicals", record)
    return S.plain(record)


def _physical_or_404(physical_id):
    record = db.get("physicals", physical_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such physical.")
    return record


def get_physical(env):
    return S.plain(_physical_or_404(env["path"]["physical_id"]))


def list_player_physicals(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return [S.plain(r) for r in db.find("physicals", player_id=player_id)]


def list_physicals(env):
    records = db.all("physicals")
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    status = env["query"].get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    return [S.plain(r) for r in records]


def perform_physical(env):
    record = _physical_or_404(env["path"]["physical_id"])
    player = db.get("players", record["player_id"])
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The physical's player is missing.")
    if S.is_farm_excluded(player["id"]):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    result = require_enum(env["body"], "physical_result",
                          ("PASSED", "PASSED_WITH_MODIFICATION", "FAILED"))
    if record["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "The physical is not scheduled.")
    scheduled = parse_dt(record["scheduled_visit_date"])
    if db.clock < scheduled:
        raise ApiError("ERR_OUTSIDE_WINDOW",
                       "The clock has not reached the scheduled visit date.")
    invitation = S.invitation_for_player(player["id"])
    if invitation is not None and not invitation["domestic_travel"]:
        report_current = parse_dt(invitation["report_current_date"])
        if scheduled > spend_days(report_current, -K.PHYSICAL_LEAD_DAYS):
            raise ApiError("ERR_PHYSICAL_WINDOW_LEAD",
                           "A non-domestic visit must sit five days before the report date.")
    for other in db.find("physicals", player_id=player["id"]):
        if other["id"] == record["id"] or other["status"] != "PERFORMED":
            continue
        if parse_dt(other["scheduled_visit_date"]) <= parse_dt(record["scheduled_visit_date"]):
            earlier, later = other, record
        else:
            earlier, later = record, other
        earlier_scheduled = parse_dt(earlier["scheduled_visit_date"])
        later_scheduled = parse_dt(later["scheduled_visit_date"])
        earlier_performed = parse_dt(earlier["performed_at"])
        separated = False
        if earlier_performed + timedelta(seconds=K.DURATION_UNITS) <= later_scheduled:
            separated = True
        elif business_days(earlier_scheduled, later_scheduled) >= \
                K.PHYSICAL_CLEARANCE_BUFFER_DAYS:
            separated = True
        if not separated:
            raise ApiError("ERR_PHYSICAL_DOUBLE_BOOKED",
                           "The examination intervals collide.")

    record["status"] = "PERFORMED"
    record["performed_at"] = fmt(db.clock)
    record["physical_result"] = result
    touch(record, db.clock)
    _apply_physical_cascade(player, result)
    return S.plain(record)


def _apply_physical_cascade(player, result):
    profile = S.profile_of(player["id"])
    if profile is not None:
        if result in ("PASSED", "PASSED_WITH_MODIFICATION"):
            profile["eligibility_status"] = "CAMP_ELIGIBLE"
        else:
            profile["eligibility_status"] = "TURNED_AWAY"
        touch(profile, db.clock)
    if result in ("PASSED", "PASSED_WITH_MODIFICATION"):
        player["clearance_status"] = "CAMP_CLEARED"
    else:
        player["clearance_status"] = "TURNED_AWAY"
        for assignment in S.assignments_of_player(player["id"]):
            if assignment["assignment_status"] in ("PROVISIONAL", "ACTIVE"):
                assignment["assignment_status"] = "WITHDRAWN"
                touch(assignment, db.clock)
    touch(player, db.clock)
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
    for group in db.all("workout_groups"):
        S.recompute_workout_group(group)
    if profile is not None:
        S.recompute_profile(profile)


def void_physical(env):
    record = _physical_or_404(env["path"]["physical_id"])
    player = db.get("players", record["player_id"])
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The physical's player is missing.")
    if record["status"] != "PERFORMED":
        raise ApiError(ERR_INVALID_STATE, "The physical is not performed.")
    record["status"] = "VOIDED"
    record["physical_result"] = None
    touch(record, db.clock)
    remaining = [p for p in db.find("physicals", player_id=player["id"])
                 if p["status"] == "PERFORMED" and p["id"] != record["id"]]
    profile = S.profile_of(player["id"])
    if not remaining:
        if profile is not None:
            profile["eligibility_status"] = "MEDICALS_PENDING"
            touch(profile, db.clock)
        player["clearance_status"] = "PENDING"
        touch(player, db.clock)
    for assignment in S.assignments_of_player(player["id"]):
        if assignment["assignment_status"] == "PROVISIONAL":
            assignment["assignment_status"] = "WITHDRAWN"
            touch(assignment, db.clock)
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
    for group in db.all("workout_groups"):
        S.recompute_workout_group(group)
    if profile is not None:
        S.recompute_profile(profile)
    return S.plain(record)


def _player_or_404(player_id):
    record = db.get("players", player_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return record


# ===========================================================================
# GameSchedule
# ===========================================================================

def create_game(env):
    complex_id = env["path"]["complex_id"]
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    body = env["body"]
    if body.get("complex_id") not in (None, complex_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "complex_id does not match the path.")
    home_away = require_enum(body, "home_away", ("HOME", "AWAY"))
    radius = require_number(body, "travel_radius_miles", 0)
    if home_away == "AWAY" and radius > K.TRAVEL_RADIUS_LIMIT_MILES:
        raise ApiError("ERR_TRAVEL_RADIUS_EXCEEDED",
                       "An away game may not exceed the travel radius.")
    game_datetime = parse_dt(body.get("game_datetime"), "game_datetime")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "complex_id": complex_id,
        "opponent_name": require_str(body, "opponent_name"),
        "home_away": home_away,
        "game_datetime": fmt(game_datetime),
        "travel_radius_miles": radius,
        "duration_units": require_int(body, "duration_units", 1),
        "split_squad": bool(body.get("split_squad", False)),
        "game_schedule_status": "DRAFT",
        "gameday_status": "NOT_GAMEDAY",
    })
    db.insert("games", record)
    S.recompute_game(record)
    return S.plain(record)


def _game_or_404(game_id):
    record = db.get("games", game_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such game schedule.")
    return record


def get_game(env):
    record = _game_or_404(env["path"]["game_id"])
    S.recompute_game(record)
    return S.plain(record)


def list_games(env):
    records = db.all("games")
    complex_id = env["query"].get("complex_id")
    if complex_id:
        records = [r for r in records if r["complex_id"] == complex_id]
    status = env["query"].get("game_schedule_status")
    if status:
        records = [r for r in records if r["game_schedule_status"] == status]
    for record in records:
        S.recompute_game(record)
    return [S.plain(r) for r in records]


def list_complex_games(env):
    complex_id = env["path"]["complex_id"]
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    records = db.find("games", complex_id=complex_id)
    for record in records:
        S.recompute_game(record)
    return [S.plain(r) for r in records]


def _recompute_participating_pitchers(game):
    for participation in db.find("game_participations", game_schedule_id=game["id"]):
        S.recompute_programs_of_player(participation["player_id"])


def publish_game(env):
    record = _game_or_404(env["path"]["game_id"])
    body = env["body"]
    if "expected_game_version" in body and body["expected_game_version"] is not None:
        expected = body["expected_game_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise bad("expected_game_version must be an integer.")
        if expected != record["version"]:
            raise ApiError("ERR_STALE_VERSION", "The game has advanced.")
    if record["game_schedule_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "The game is not in draft.")
    if record["home_away"] == "AWAY" and \
            record["travel_radius_miles"] > K.TRAVEL_RADIUS_LIMIT_MILES:
        raise ApiError("ERR_TRAVEL_RADIUS_EXCEEDED",
                       "An away game may not exceed the travel radius.")
    complex_record = db.get("complexes", record["complex_id"])
    if complex_record is not None and complex_record["facility_posture"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "The owning complex is closed.")
    if complex_record is not None and \
            S.sessions_collide_with_game(complex_record["id"], record) is not None:
        raise ApiError("ERR_TEMPORAL_OVERLAP",
                       "A session block collides with the game interval.")
    record["game_schedule_status"] = "PUBLISHED"
    S.recompute_game(record)
    touch(record, db.clock)
    _recompute_participating_pitchers(record)
    return S.plain(record)


def revert_game_to_draft(env):
    record = _game_or_404(env["path"]["game_id"])
    if record["game_schedule_status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "The game is not published.")
    for participation in db.find("game_participations", game_schedule_id=record["id"]):
        if participation["participation_status"] == "LOCKED":
            raise ApiError(ERR_INVALID_STATE, "A locked participation blocks this revert.")
    record["game_schedule_status"] = "DRAFT"
    record["gameday_status"] = "NOT_GAMEDAY"
    touch(record, db.clock)
    _recompute_participating_pitchers(record)
    return S.plain(record)


def record_game_result(env):
    record = _game_or_404(env["path"]["game_id"])
    if record["game_schedule_status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "The game is not published.")
    if db.clock < parse_dt(record["game_datetime"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", "The clock has not reached first pitch.")
    record["game_schedule_status"] = "PLAYED"
    record["gameday_status"] = "NOT_GAMEDAY"
    touch(record, db.clock)
    _recompute_participating_pitchers(record)
    return S.plain(record)


def cancel_game(env):
    record = _game_or_404(env["path"]["game_id"])
    if record["game_schedule_status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_INVALID_STATE, "The game cannot be cancelled.")
    was_published = record["game_schedule_status"] == "PUBLISHED"
    record["game_schedule_status"] = "CANCELLED"
    record["gameday_status"] = "NOT_GAMEDAY"
    if was_published:
        for participation in db.find("game_participations", game_schedule_id=record["id"]):
            if participation["participation_status"] in ("SCHEDULED", "CONFIRMED"):
                participation["participation_status"] = "WITHDRAWN"
                touch(participation, db.clock)
    touch(record, db.clock)
    _recompute_participating_pitchers(record)
    return S.plain(record)


# ===========================================================================
# GameParticipation
# ===========================================================================

def create_game_participation(env):
    game = _game_or_404(env["path"]["game_id"])
    body = env["body"]
    if body.get("game_schedule_id") not in (None, game["id"]):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "game_schedule_id does not match the path.")
    player_id = require_str(body, "player_id")
    if db.get("players", player_id) is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such player.")
    squad_side = require_enum(body, "squad_side", ("HOME_SQUAD", "AWAY_SQUAD"))
    throw_count = optional_int(body, "throw_count", 0, 0)
    record = new_record(db.new_id(), db.clock)
    record.update({
        "game_schedule_id": game["id"],
        "player_id": player_id,
        "squad_side": squad_side,
        "participation_status": "SCHEDULED",
        "throw_count": throw_count,
    })
    db.insert("game_participations", record)
    game["version"] = game["version"] + 1
    game["updated_at"] = fmt(db.clock)
    S.recompute_programs_of_player(player_id)
    return S.plain(record)


def _participation_or_404(participation_id, game=None):
    record = db.get("game_participations", participation_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such game participation.")
    if game is not None and record["game_schedule_id"] != game["id"]:
        raise ApiError("ERR_RESOURCE_NOT_FOUND",
                       "The participation does not belong to that game.")
    return record


def get_game_participation(env):
    return S.plain(_participation_or_404(env["path"]["participation_id"]))


def list_game_participations(env):
    records = db.all("game_participations")
    game_id = env["query"].get("game_schedule_id")
    if game_id:
        records = [r for r in records if r["game_schedule_id"] == game_id]
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    return [S.plain(r) for r in records]


def list_game_participations_of_game(env):
    game = _game_or_404(env["path"]["game_id"])
    return [S.plain(r) for r in db.find("game_participations",
                                        game_schedule_id=game["id"])]


def confirm_participation(env):
    game = _game_or_404(env["path"]["game_id"])
    record = _participation_or_404(env["path"]["participation_id"], game)
    body = env["body"]
    if "expected_game_version" not in body or body["expected_game_version"] is None:
        raise bad("expected_game_version is required.")
    expected = body["expected_game_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise bad("expected_game_version must be an integer.")
    player = db.get("players", record["player_id"])
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "The participation's player is missing.")
    if expected != game["version"]:
        raise ApiError("ERR_STALE_VERSION", "The game has advanced.")
    if game["game_schedule_status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "The game is not published.")
    if record["participation_status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "The participation cannot be confirmed.")
    if player["clearance_status"] != "CAMP_CLEARED":
        raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED", "The player is not camp-cleared.")
    program = S.program_of_player(player["id"])
    requirement = program["requirement_status"] if program else "NOT_REQUIRED"
    if requirement == "UNMET":
        raise ApiError("ERR_THROW_REQUIREMENT_UNMET",
                       "The player's throwing requirement is unmet.")

    eligibility = S.split_squad_eligibility_for(player["id"])
    if eligibility != "HOME_AND_TRAVEL" and record["squad_side"] != "HOME_SQUAD":
        raise ApiError(ERR_INVALID_STATE,
                       "The player is not split-squad eligible for an away squad slot.")

    phase = program["program_phase"] if program else "PHASE_1"
    if game["home_away"] == "AWAY":
        permitted = (eligibility == "HOME_AND_TRAVEL" or
                     game["travel_radius_miles"] <= K.TRAVEL_RADIUS_LIMIT_MILES)
        if not permitted:
            raise ApiError("ERR_INJURY_TRAVEL_UNSAFE",
                           "The away game is outside the permissible travel envelope.")
        if phase in ("PHASE_1", "PHASE_2", "PHASE_3"):
            raise ApiError("ERR_INJURY_TRAVEL_UNSAFE",
                           "A strict-precursor phase is not cleared for away travel.")
    if phase not in ("PHASE_1", "PHASE_2") and player["clearance_status"] != "CAMP_CLEARED":
        raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED", "The player is not camp-cleared.")

    record["participation_status"] = "CONFIRMED"
    touch(record, db.clock)
    game["version"] = game["version"] + 1
    game["updated_at"] = fmt(db.clock)
    S.recompute_programs_of_player(player["id"])
    return S.plain(record)


def withdraw_participation(env):
    game = _game_or_404(env["path"]["game_id"])
    record = _participation_or_404(env["path"]["participation_id"], game)
    if record["participation_status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError(ERR_INVALID_STATE, "The participation is already withdrawn.")
    was_confirmed = record["participation_status"] == "CONFIRMED"
    record["participation_status"] = "WITHDRAWN"
    touch(record, db.clock)
    game["version"] = game["version"] + 1
    game["updated_at"] = fmt(db.clock)
    if was_confirmed:
        S.recompute_programs_of_player(record["player_id"])
    return S.plain(record)


def package_roster(env):
    game = _game_or_404(env["path"]["game_id"])
    if game["game_schedule_status"] != "PUBLISHED":
        raise ApiError(ERR_INVALID_STATE, "The game is not published.")
    first_pitch = parse_dt(game["game_datetime"])
    window_start = spend_days(first_pitch, 0) - timedelta(seconds=6 * K.HOUR)
    if not (window_start <= db.clock <= first_pitch):
        raise ApiError("ERR_OUTSIDE_WINDOW",
                       "The clock is outside the packaging window.")
    S.recompute_game(game)
    locked = 0
    for participation in db.find("game_participations", game_schedule_id=game["id"]):
        if participation["participation_status"] == "CONFIRMED":
            participation["participation_status"] = "LOCKED"
            touch(participation, db.clock)
            locked += 1
    game["version"] = game["version"] + 1
    game["updated_at"] = fmt(db.clock)
    return {
        "locked_count": locked,
        "game_id": game["id"],
        "gameday_status": game["gameday_status"],
    }


# ===========================================================================
# SpringTrail
# ===========================================================================

def create_spring_trail(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "trail_level": require_enum(body, "trail_level", ("AAA", "AA", "A_PLUS", "A")),
        "mapped_at": fmt(db.clock),
        "trail_status": "ACTIVE",
    })
    db.insert("spring_trails", record)
    return S.plain(record)


def get_spring_trail(env):
    record = db.get("spring_trails", env["path"]["trail_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such spring trail mapping.")
    return S.plain(record)


def list_player_spring_trails(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return [S.plain(r) for r in db.find("spring_trails", player_id=player_id)]


def list_spring_trails(env):
    records = db.all("spring_trails")
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    status = env["query"].get("trail_status")
    if status:
        records = [r for r in records if r["trail_status"] == status]
    return [S.plain(r) for r in records]


def end_spring_trail(env):
    record = db.get("spring_trails", env["path"]["trail_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such spring trail mapping.")
    if record["trail_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "The trail mapping is already ended.")
    record["trail_status"] = "ENDED"
    touch(record, db.clock)
    return S.plain(record)


# ===========================================================================
# MinorLeagueAssignment
# ===========================================================================

def create_minor_league_assignment(env):
    player_id = env["path"]["player_id"]
    player = db.get("players", player_id)
    if player is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    roster_record_id = require_str(body, "roster_record_id")
    roster_record = db.get("roster_records", roster_record_id)
    if roster_record is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such roster record.")
    effective = parse_dt(body.get("effective_datetime"), "effective_datetime")
    agreement = S.funding_agreement_for_complex(player["home_complex_id"])
    if agreement is not None:
        lease_end = parse_dt(agreement["lease_end_date"])
        if db.clock < effective - timedelta(days=K.BREAKOUT_BAILOUT_DAYS):
            raise ApiError("ERR_OUTSIDE_WINDOW",
                           "The assignment opens too far before its effective instant.")
        if effective > lease_end:
            raise ApiError("ERR_OUTSIDE_WINDOW", "The effective instant is past the lease end.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "roster_record_id": roster_record_id,
        "assigned_level": require_enum(body, "assigned_level", ("AAA", "AA")),
        "affiliate_name": require_str(body, "affiliate_name"),
        "effective_datetime": fmt(effective),
        "travel_day_count": 0,
        "break_out_liability_cents": 0,
        "assignment_status": "PENDING",
        "settlement_actor_id": None,
    })
    db.insert("minor_league_assignments", record)
    if agreement is not None:
        record["travel_day_count"] = business_days(effective,
                                                   parse_dt(agreement["lease_end_date"]))
    liability = 0
    for arrangement in S.travel_liability_rows_for_player(player_id):
        liability += arrangement["agreement_funded_cents"]
    record["break_out_liability_cents"] = liability
    return S.plain(record)


def _minor_assignment_or_404(assignment_id):
    record = db.get("minor_league_assignments", assignment_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such minor league assignment.")
    return record


def get_minor_league_assignment(env):
    return S.plain(_minor_assignment_or_404(env["path"]["assignment_id"]))


def list_player_minor_league_assignments(env):
    player_id = env["path"]["player_id"]
    if db.get("players", player_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return [S.plain(r) for r in db.find("minor_league_assignments", player_id=player_id)]


def list_minor_league_assignments(env):
    records = db.all("minor_league_assignments")
    for key in ("player_id", "roster_record_id", "assignment_status"):
        value = env["query"].get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return [S.plain(r) for r in records]


def settle_minor_league_assignment(env):
    record = _minor_assignment_or_404(env["path"]["assignment_id"])
    if record["assignment_status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, "The assignment is not pending.")
    record["assignment_status"] = "SETTLED"
    record["settlement_actor_id"] = env["uid"]
    touch(record, db.clock)
    return S.plain(record)


def void_minor_league_assignment(env):
    record = _minor_assignment_or_404(env["path"]["assignment_id"])
    if record["assignment_status"] != "SETTLED":
        raise ApiError(ERR_INVALID_STATE, "The assignment is not settled.")
    if record.get("settlement_actor_id") == env["uid"]:
        raise ApiError("ERR_SOD_VIOLATION",
                       "The settling operator cannot void the same break-out.")
    record["assignment_status"] = "BREAKOUT_VOIDED"
    record["settlement_actor_id"] = None
    record["break_out_liability_cents"] = 0
    touch(record, db.clock)
    return S.plain(record)


# ===========================================================================
# Operations checkpoints
# ===========================================================================

def run_ops_checkpoint(env):
    run_type = require_enum(env["body"], "run_type",
                            ("invitation-report-sweep", "registration-roster-sweep"))
    stale_expired = 0
    if run_type == "invitation-report-sweep":
        for invitation in db.all("camp_invitations"):
            if invitation["invitation_status"] != "ISSUED":
                continue
            if invitation.get("actual_report_date") is not None:
                continue
            report_final = parse_dt(invitation["report_final_date"])
            if not db.clock > report_final:
                continue
            invitation["invitation_status"] = "NO_SHOW"
            _unwind_invitation_travel(invitation)
            touch(invitation, db.clock)
            stale_expired += 1
    else:
        for record in db.all("roster_records"):
            S.recompute_roster_record(record)

    sweeps = 0
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
        sweeps += 1
    db.ops_run_index += 1
    return {
        "run_type": run_type,
        "stale_invitations_expired": stale_expired,
        "posture_sweeps_run": sweeps,
        "ops_run_index": db.ops_run_index,
    }