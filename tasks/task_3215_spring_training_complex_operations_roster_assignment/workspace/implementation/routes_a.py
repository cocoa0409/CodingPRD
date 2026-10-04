"""Route handlers: clock, complexes, agreements, players, roster, profiles,
host community ledgers and sponsorships."""

from datetime import timedelta

import rules as K
import state as S
from core import (ApiError, ERR_AGREEMENT_NOT_ACTIVE,
                  ERR_FARM_ENTITY_EXCLUDED, ERR_INVALID_STATE, ERR_SOD_VIOLATION,
                  ERR_SPONSORSHIP_NOT_FULLY_FUNDED, ERR_UNAUTHENTICATED,
                  bad, enum_or_default, fmt, new_record,
                  optional_int, parse_dt, reject_server_minted, require_enum,
                  require_int, require_str, spend_days, touch, upper_snake)
from store import db


# ---------------------------------------------------------------------------
def set_clock(env):
    body = env["body"]
    current = parse_dt(body.get("current_utc"), "current_utc")
    db.clock = current
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
    return {"current_utc": fmt(db.clock)}


# ---------------------------------------------------------------------------
def create_complex(env):
    body = env["body"]
    reject_server_minted(body)
    record = new_record(db.new_id(), db.clock)
    record.update({
        "name": require_str(body, "name"),
        "host_city": require_str(body, "host_city"),
        "season_split_track": enum_or_default(body, "season_split_track", "SHARED",
                                              ("SHARED", "DEDICATED")),
        "timezone": body.get("timezone") or "America/Phoenix",
        "facility_capacity_units": require_int(body, "facility_capacity_units", 1),
        "posted_occupancy_units": 0,
        "reserved_major_units": 0,
        "reserved_minor_units": 0,
        "maintenance_block_units": 0,
        "field_maintenance_status": "OPEN",
        "facility_posture": "NORMAL",
        "contention_flagged": False,
        "posture_sweep_index": 0,
    })
    db.insert("complexes", record)
    return S.complex_view(record)


def _complex_or_404(complex_id):
    record = db.get("complexes", complex_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    return record


def get_complex(env):
    return S.complex_view(_complex_or_404(env["path"]["complex_id"]))


def list_complexes(env):
    records = db.all("complexes")
    return [S.complex_view(r) for r in records]


def field_maintenance(env):
    record = _complex_or_404(env["path"]["complex_id"])
    action = require_enum(env["body"], "maintenance_action",
                          ("OPEN", "FIELD_RESTRICTED", "CLOSED"))
    capacity = record["facility_capacity_units"]

    if action == "OPEN":
        if record["field_maintenance_status"] != "HALF_FIELD":
            raise ApiError(ERR_INVALID_STATE,
                           "Field maintenance is not in a reopenable state.")
        record["maintenance_block_units"] = 0
        record["field_maintenance_status"] = "OPEN"
        record["facility_posture"] = "NORMAL"
        S.recompute_complex(record)
        touch(record, db.clock)
        return S.complex_view(record)

    if action == "FIELD_RESTRICTED":
        if record["field_maintenance_status"] != "OPEN" or \
                record["facility_posture"] != "NORMAL":
            raise ApiError(ERR_INVALID_STATE,
                           "Field maintenance is not in a restrictable state.")
        if record["posted_occupancy_units"] > (capacity * K.RESTRICTED_PCT_OF_RAW) // 100:
            raise ApiError(ERR_INVALID_STATE,
                           "Occupancy is above the restriction threshold.")
        record["field_maintenance_status"] = "HALF_FIELD"
        record["maintenance_block_units"] = -((-capacity) // 2)
        S.recompute_complex(record)
        touch(record, db.clock)
        return S.complex_view(record)

    # action == CLOSED
    if record["field_maintenance_status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "The complex is already closed.")
    # The provisional assignment that sits on the complex must be withdrawn
    # before the field may close: the conflict check names PROVISIONAL, while
    # the withdrawal cascade below drives exactly that state away.
    for assignment in S.assignments_of_complex(record["id"]):
        if assignment["assignment_status"] == "PROVISIONAL":
            raise ApiError("ERR_MAINTENANCE_CONFLICT",
                           "A provisional group assignment still occupies a seat.")
    record["maintenance_block_units"] = capacity
    record["field_maintenance_status"] = "CLOSED"
    record["facility_posture"] = "CLOSED"
    _cascade_complex_closed(record)
    touch(record, db.clock)
    return S.complex_view(record)


def _cascade_complex_closed(record):
    """The closure cascade, exercised only after the provisional-seat gate has
    cleared. It is guarded on the members of a DISBANDED group — a group that
    lost its last provisional-or-active assignment — rather than on every group
    that merely happens to sit at zero."""
    complex_id = record["id"]

    for group in S.groups_of_complex(complex_id):
        S.recompute_workout_group(group)
        if group["group_status"] not in ("FORMING", "PUBLISHED"):
            continue
        if any(a["assignment_status"] in ("PROVISIONAL", "ACTIVE")
               for a in S.assignments_of_group(group["id"])):
            continue
        group["group_status"] = "DISBANDED"
        touch(group, db.clock)
        for session in S.db.find("workout_group_sessions", workout_group_id=group["id"]):
            if session["session_status"] != "CANCELLED":
                session["session_status"] = "CANCELLED"
                touch(session, db.clock)
        for assignment in S.assignments_of_group(group["id"]):
            profile = S.profile_of(assignment["player_id"])
            if profile is not None:
                if profile["rehab_program_phase"] in ("PHASE_1", "PHASE_2"):
                    profile["rehab_program_phase"] = "PHASE_1"
                profile["active_group_assignment_id"] = None
                touch(profile, db.clock)
                S.recompute_profile(profile)

    for player in db.all("players"):
        profile = S.profile_of(player["id"])
        if profile is not None:
            S.recompute_profile(profile)
        S.detach_roster_from_camp(player["id"])

    for game in S.db.find("games", complex_id=complex_id):
        S.recompute_game(game)
        if game["home_away"] == "AWAY" and game["game_schedule_status"] == "DRAFT":
            game["game_schedule_status"] = "CANCELLED"
            touch(game, db.clock)

    S.recompute_complex(record, run_sweep=False)
    record["facility_posture"] = "CLOSED"


def posture_sweep(env):
    record = _complex_or_404(env["path"]["complex_id"])
    S.recompute_complex(record)
    touch(record, db.clock)
    return S.complex_view(record)


# ---------------------------------------------------------------------------
def create_community_agreement(env):
    body = env["body"]
    complex_id = require_str(body, "complex_id")
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such complex.")
    start = parse_dt(body.get("lease_start_date"), "lease_start_date")
    end = parse_dt(body.get("lease_end_date"), "lease_end_date")
    if end <= start:
        raise bad("lease_end_date must be strictly after lease_start_date.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "complex_id": complex_id,
        "stadium_name": require_str(body, "stadium_name"),
        "lease_start_date": fmt(start),
        "lease_end_date": fmt(end),
        "annual_rent_cents": require_int(body, "annual_rent_cents", 0),
        "sponsorship_minor_league_base_cents":
            require_int(body, "sponsorship_minor_league_base_cents", 0),
        "sponsorship_major_league_base_cents":
            require_int(body, "sponsorship_major_league_base_cents", 0),
        "ticket_price_cents": require_int(body, "ticket_price_cents", 0),
        "ticket_sellout_capacity": require_int(body, "ticket_sellout_capacity", 0),
        "agreement_status": "DRAFT",
        "travel_liability_window_count": 0,
        "travel_liability_days": 0,
        "settlement_release_lag_days": 0,
    })
    db.insert("community_agreements", record)
    return S.agreement_view(record)


def _agreement_or_404(agreement_id):
    record = db.get("community_agreements", agreement_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such community agreement.")
    return record


def get_community_agreement(env):
    return S.agreement_view(_agreement_or_404(env["path"]["agreement_id"]))


def list_community_agreements(env):
    complex_id = env["query"].get("complex_id")
    records = db.all("community_agreements")
    if complex_id:
        records = [r for r in records if r["complex_id"] == complex_id]
    return [S.agreement_view(r) for r in records]


def list_complex_community_agreements(env):
    complex_id = env["path"]["complex_id"]
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    return [S.agreement_view(r) for r in db.find("community_agreements", complex_id=complex_id)]


def activate_agreement(env):
    record = _agreement_or_404(env["path"]["agreement_id"])
    if record["agreement_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "The agreement is not in DRAFT.")
    start = parse_dt(record["lease_start_date"])
    end = parse_dt(record["lease_end_date"])
    if not (end > start):
        raise bad("The lease window is inverted.")
    complex_record = db.get("complexes", record["complex_id"])
    if complex_record is not None and complex_record["facility_posture"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, "The owning complex is closed for field work.")
    record["agreement_status"] = "ACTIVE"
    touch(record, db.clock)
    return S.agreement_view(record)


def revert_agreement_to_draft(env):
    record = _agreement_or_404(env["path"]["agreement_id"])
    if record["agreement_status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "The agreement is not ACTIVE.")
    for host in db.find("host_community_records", agreement_id=record["id"]):
        if host["ticketing_status"] == "ON_SALE":
            raise ApiError(ERR_INVALID_STATE, "Ticketing is live on this agreement.")
    record["agreement_status"] = "DRAFT"
    touch(record, db.clock)
    return S.agreement_view(record)


def terminate_agreement(env):
    record = _agreement_or_404(env["path"]["agreement_id"])
    if record["agreement_status"] not in ("ACTIVE", "DRAFT"):
        raise ApiError(ERR_INVALID_STATE, "The agreement cannot be terminated.")
    was_active = record["agreement_status"] == "ACTIVE"
    record["agreement_status"] = "TERMINATED"
    if was_active:
        for host in db.find("host_community_records", agreement_id=record["id"]):
            if host["ticketing_status"] in ("ON_SALE", "SOLD_OUT"):
                host["ticketing_status"] = "SUSPENDED"
                touch(host, db.clock)
    touch(record, db.clock)
    return S.agreement_view(record)


def _revert_agreement_for_fiscal(agreement):
    """CASCADE: an agreement slides back to DRAFT when nothing is on sale."""
    if agreement is None or agreement["agreement_status"] != "ACTIVE":
        return
    for host in db.find("host_community_records", agreement_id=agreement["id"]):
        if host["ticketing_status"] == "ON_SALE":
            return
    agreement["agreement_status"] = "DRAFT"
    touch(agreement, db.clock)


# ---------------------------------------------------------------------------
def create_player(env):
    body = env["body"]
    reject_server_minted(body)
    idp_number = require_str(body, "idp_number")
    for existing in db.all("players"):
        if existing["idp_number"] == idp_number:
            raise ApiError("ERR_DUPLICATE_IDP_NUMBER",
                           "That idp_number is already registered.")
    complex_id = require_str(body, "home_complex_id")
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "No such complex.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "full_name": require_str(body, "full_name"),
        "idp_number": idp_number,
        "position_code": require_enum(body, "position_code", ("P", "C", "INF", "OF", "DH")),
        "acquisition_channel": require_enum(
            body, "acquisition_channel",
            ("DRAFT_PICK", "NRI_ASSIGNMENT", "FREE_AGENT", "INTERNATIONAL_SIGNING", "TRADE")),
        "mlb_service_days": optional_int(body, "mlb_service_days", 0, 0, 9999),
        "minor_league_option_years_used":
            optional_int(body, "minor_league_option_years_used", 0, 0, 3),
        "home_country": require_str(body, "home_country"),
        "home_complex_id": complex_id,
        "clearance_status": "PENDING",
    })
    db.insert("players", record)
    return S.player_view(record)


def _player_or_404(player_id):
    record = db.get("players", player_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such player.")
    return record


def get_player(env):
    return S.player_view(_player_or_404(env["path"]["player_id"]))


def list_players(env):
    query = env["query"]
    records = db.all("players")
    for key in ("home_complex_id", "clearance_status", "position_code"):
        value = query.get(key)
        if value:
            records = [r for r in records if r.get(key) == value]
    return [S.player_view(r) for r in records]


def list_complex_players(env):
    complex_id = env["path"]["complex_id"]
    if db.get("complexes", complex_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such complex.")
    return [S.player_view(r) for r in db.find("players", home_complex_id=complex_id)]


def pend_clearance(env):
    record = _player_or_404(env["path"]["player_id"])
    if record["clearance_status"] != "TURNED_AWAY":
        raise ApiError("ERR_INVALID_STATE", "The player is not turned away.")
    has_pass = any(p["status"] == "PERFORMED" and
                   p["physical_result"] in ("PASSED", "PASSED_WITH_MODIFICATION")
                   for p in db.find("physicals", player_id=record["id"]))
    if not has_pass:
        raise ApiError("ERR_INVALID_STATE", "No passing physical stands for this player.")
    record["clearance_status"] = "PENDING"
    touch(record, db.clock)
    profile = S.profile_of(record["id"])
    if profile is not None:
        _sync_profile_eligibility(profile, record["id"])
        touch(profile, db.clock)
    return S.player_view(record)


# ---------------------------------------------------------------------------
def _sync_profile_eligibility(profile, player_id):
    physicals = db.find("physicals", player_id=player_id)
    latest = None
    for physical in physicals:
        if physical["status"] != "PERFORMED":
            continue
        stamp = physical.get("performed_at") or physical["updated_at"]
        if latest is None or stamp > latest[0]:
            latest = (stamp, physical)
    if latest is None:
        profile["eligibility_status"] = "MEDICALS_PENDING"
    elif latest[1]["physical_result"] in ("PASSED", "PASSED_WITH_MODIFICATION"):
        profile["eligibility_status"] = "CAMP_ELIGIBLE"
    else:
        profile["eligibility_status"] = "TURNED_AWAY"
    return profile


def create_roster_record(env):
    player_id = env["path"]["player_id"]
    player = _player_or_404(player_id)
    if S.is_farm_excluded(player_id):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "current_roster_status": "NRI",
        "roster_decision_status": "DECISION_PENDING",
        "option_eligibility": "OPTION_AVAILABLE",
        "option_decisions_used": 0,
        "waivers_required": False,
        "option_credit_source": "BASE_ALLOWANCE",
        "last_decision_actor_id": None,
        "waiver_claim_window_days": 0,
        "waiver_claim_requested_at": None,
        "split_squad_eligibility": "HOME_ONLY",
        "decision_sequence": 0,
        "decision_finalized_at": None,
        "finalized_roster_status": None,
    })
    db.insert("roster_records", record)
    S.recompute_roster_record(record)
    return S.plain(record)


def _roster_record_of_player(player_id):
    player = _player_or_404(player_id)
    record = S.roster_record_of(player_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No roster record for that player.")
    return player, record


def get_roster_record(env):
    record = db.get("roster_records", env["path"]["record_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such roster record.")
    return S.plain(record)


def list_roster_records(env):
    records = db.all("roster_records")
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    status = env["query"].get("current_roster_status")
    if status:
        records = [r for r in records if r["current_roster_status"] == status]
    return [S.plain(r) for r in records]


def list_player_roster_records(env):
    player_id = env["path"]["player_id"]
    _player_or_404(player_id)
    return [S.plain(r) for r in db.find("roster_records", player_id=player_id)]


def _assert_roster_transition(record, from_states, error="ERR_ROSTER_STATUS_INVALID_TRANSITION"):
    if record["current_roster_status"] not in from_states:
        raise ApiError(error, "The roster record is not in a valid source state.")


TERMINAL_ROSTER = ("RELEASED", "NRI_RELEASED", "ASSIGNED_AAA", "ASSIGNED_AA")


def select_active_roster(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    if player["clearance_status"] != "CAMP_CLEARED":
        raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED", "The player is not camp-cleared.")
    if record["roster_decision_status"] != "DECISION_PENDING":
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "The decision is not pending.")
    _assert_roster_transition(record, ("NRI",))
    profile = S.profile_of(player["id"])
    if profile is None or profile["eligibility_status"] != "CAMP_ELIGIBLE":
        raise ApiError("ERR_MEDICAL_CLEARANCE_REQUIRED", "The player is not camp eligible.")
    record["current_roster_status"] = "ACTIVE_ROSTER"
    record["last_decision_actor_id"] = env["uid"]
    touch(record, db.clock)
    S.recompute_roster_record(record)
    return S.plain(record)


def roster_decide(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    if S.is_farm_excluded(player["id"]):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    decision = require_enum(env["body"], "decision_type",
                            ("OPTION_ASSIGN", "NONROSTER_RELEASE", "OUTRIGHT_ASSIGN", "RESCIND_RELEASE"))
    if record["current_roster_status"] in TERMINAL_ROSTER and \
            record["roster_decision_status"] != "DECISION_VOIDED":
        raise ApiError("ERR_ROSTER_ALREADY_FINAL", "The roster record is terminal.")

    if decision == "OPTION_ASSIGN":
        if record["roster_decision_status"] == "DECISION_VOIDED":
            if record["option_decisions_used"] > 3:
                raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                               "The voided decision cannot be re-issued.")
            record["current_roster_status"] = "OPTIONED_MINORS"
            record["roster_decision_status"] = "DECISION_PENDING"
        else:
            if record["roster_decision_status"] != "DECISION_PENDING":
                raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                               "The decision is not pending.")
            _assert_roster_transition(record, ("NRI",))
            if record["option_eligibility"] != "OPTION_AVAILABLE":
                raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                               "No option year remains for this player.")
            record["current_roster_status"] = "OPTIONED_MINORS"
            # the applied option decision is a charge on the option allowance
            record["option_decisions_used"] = record["option_decisions_used"] + 1
    elif decision == "NONROSTER_RELEASE":
        if record["roster_decision_status"] != "DECISION_PENDING":
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "The decision is not pending.")
        _assert_roster_transition(record, ("NRI",))
        record["current_roster_status"] = "NRI_RELEASED"
    elif decision == "OUTRIGHT_ASSIGN":
        if record["roster_decision_status"] != "DECISION_PENDING":
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "The decision is not pending.")
        _assert_roster_transition(record, ("OPTIONED_MINORS",))
        if record["option_eligibility"] != "NO_OPTION_REMAINING":
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "Options remain, so an outright assignment is not available.")
        record["current_roster_status"] = "DESIGNATED_FOR_ASSIGNMENT"
    else:  # RESCIND_RELEASE
        if record["roster_decision_status"] not in ("DECISION_PENDING", "DECISION_VOIDED"):
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "The decision is already final.")
        _assert_roster_transition(record, ("RELEASED",))
        if not record["waivers_required"]:
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "No release is bound by waivers.")
        record["current_roster_status"] = "DESIGNATED_FOR_ASSIGNMENT"
        record["roster_decision_status"] = "DECISION_PENDING"

    record["decision_sequence"] = record["decision_sequence"] + 1
    record["last_decision_actor_id"] = env["uid"]
    touch(record, db.clock)
    S.recompute_roster_record(record)
    return S.plain(record)


def request_waivers(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    _assert_roster_transition(record, ("DESIGNATED_FOR_ASSIGNMENT",))
    if not record["waivers_required"]:
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "Waivers are not required.")
    record["current_roster_status"] = "WAIVER_PENDING"
    _, days = S.waiver_claim_days(record)
    record["waiver_claim_window_days"] = days
    record["waiver_claim_requested_at"] = fmt(db.clock)
    touch(record, db.clock)
    S.recompute_roster_record(record)
    return S.plain(record)


def record_waiver_outcome(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    outcome = require_enum(env["body"], "outcome",
                           ("CLAIMED", "PENDING", "RETURNED", "CLEARED"))
    if outcome == "CLAIMED":
        if record["current_roster_status"] not in ("WAIVER_PENDING", "WAIVER_CLAIMED"):
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "Waivers are not pending for this record.")
        if not record["waivers_required"]:
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "Waivers are not required.")
        record["current_roster_status"] = "WAIVER_CLAIMED"
    elif outcome == "PENDING":
        _assert_roster_transition(record, ("WAIVER_CLAIMED",))
        record["current_roster_status"] = "WAIVER_PENDING"
    elif outcome == "RETURNED":
        _assert_roster_transition(record, ("WAIVER_PENDING",))
        record["current_roster_status"] = "DESIGNATED_FOR_ASSIGNMENT"
    else:  # CLEARED
        _assert_roster_transition(record, ("WAIVER_PENDING",))
        if not record["waivers_required"]:
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION", "Waivers are not required.")
        record["current_roster_status"] = "RELEASED"
    touch(record, db.clock)
    S.recompute_roster_record(record)
    return S.plain(record)


def finalize_decision(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    if S.is_farm_excluded(player["id"]):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    if record["roster_decision_status"] != "DECISION_PENDING":
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                       "The roster decision is not pending.")
    if record["current_roster_status"] not in ("OPTIONED_MINORS", "NRI_RELEASED", "RELEASED",
                                               "WAIVER_PENDING", "WAIVER_CLAIMED"):
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                       "The roster record is not in a finalizable state.")
    record["split_squad_eligibility"] = S.split_squad_eligibility_for(player["id"])
    if record.get("last_decision_actor_id") == env["uid"]:
        raise ApiError(ERR_SOD_VIOLATION,
                       "The actor that advanced the record cannot finalize it.")
    if record["current_roster_status"] == "WAIVER_CLAIMED":
        if record["waiver_claim_window_days"] <= 0 or S.waiver_window_expired(record):
            raise ApiError("ERR_WAIVER_WINDOW_EXPIRED", "The waiver claim window has elapsed.")

    finalizing_status = record["current_roster_status"]
    if finalizing_status == "WAIVER_CLAIMED":
        record["option_decisions_used"] = record["option_decisions_used"] + 1
    record["roster_decision_status"] = "DECISION_FINALIZED"
    record["decision_finalized_at"] = fmt(db.clock)
    record["finalized_roster_status"] = finalizing_status
    record["decision_sequence"] = record["decision_sequence"] + 1
    touch(record, db.clock)
    S.recompute_option_reads(record)
    S.refresh_waivers_required(record)
    return S.plain(record)


def void_decision(env):
    player, record = _roster_record_of_player(env["path"]["player_id"])
    if S.is_farm_excluded(player["id"]):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    if record["roster_decision_status"] != "DECISION_FINALIZED":
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                       "The roster decision is not finalized.")
    _assert_roster_transition(record, ("OPTIONED_MINORS", "NRI_RELEASED"))
    invitation = S.invitation_for_player(player["id"])
    if invitation is not None:
        report_current = parse_dt(invitation["report_current_date"])
        if not db.clock < report_current:
            raise ApiError("ERR_OUTSIDE_WINDOW",
                           "The clock is at or past the report date.")
    record["roster_decision_status"] = "DECISION_VOIDED"
    record["current_roster_status"] = "NRI"
    record["option_decisions_used"] = max(0, record["option_decisions_used"] - 1)
    record["decision_sequence"] = record["decision_sequence"] + 1
    touch(record, db.clock)
    S.recompute_option_reads(record, relief=True)
    S.refresh_waivers_required(record)
    return S.plain(record)


def break_out_camp(env):
    record = db.get("roster_records", env["path"]["record_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such roster record.")
    _player_or_404(record["player_id"])
    level = require_enum(env["body"], "level", ("AAA", "AA"))
    if record["roster_decision_status"] != "DECISION_FINALIZED":
        raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                       "The roster decision is not finalized.")

    if level == "AAA":
        valid_sources = ("NRI", "OPTIONED_MINORS")
        if record["current_roster_status"] not in valid_sources:
            # the transition-legality check precedes the terminal-status guard,
            # so a terminal source with no declared edge reports the transition error
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "The record cannot break out to AAA from here.")
        if record["current_roster_status"] in TERMINAL_ROSTER:
            raise ApiError("ERR_ROSTER_ALREADY_FINAL", "The roster record is terminal.")
        record["current_roster_status"] = "ASSIGNED_AAA"
    else:
        if record["current_roster_status"] not in ("DESIGNATED_FOR_ASSIGNMENT", "ASSIGNED_AAA"):
            raise ApiError("ERR_ROSTER_STATUS_INVALID_TRANSITION",
                           "The record cannot break out to AA from here.")
        if record["current_roster_status"] == "ASSIGNED_AA":
            raise ApiError("ERR_ROSTER_ALREADY_FINAL", "The roster record is terminal.")
        demotion = record["current_roster_status"] == "ASSIGNED_AAA"
        record["current_roster_status"] = "ASSIGNED_AA"
        if demotion:
            touch(record, db.clock)
            S.recompute_roster_record(record)
            return S.plain(record)

    player_id = record["player_id"]
    for assignment in S.assignments_of_player(player_id):
        if assignment["assignment_status"] in ("PROVISIONAL", "ACTIVE"):
            assignment["assignment_status"] = "WITHDRAWN"
            touch(assignment, db.clock)
    for group in db.all("workout_groups"):
        S.recompute_workout_group(group)
    touched = set()
    for complex_record in db.all("complexes"):
        S.recompute_complex(complex_record)
    for assignment in db.find("group_assignments", player_id=player_id):
        touched.add(assignment["player_id"])
    for pid in touched:
        profile = S.profile_of(pid)
        if profile is not None:
            S.recompute_profile(profile)
    touch(record, db.clock)
    S.recompute_roster_record(record)
    return S.plain(record)


# ---------------------------------------------------------------------------
def create_program_profile(env):
    player_id = env["path"]["player_id"]
    _player_or_404(player_id)
    body = env["body"]
    if body.get("player_id") not in (None, player_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "player_id does not match the path.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "player_id": player_id,
        "eligibility_status": "MEDICALS_PENDING",
        "rehab_program_phase": "PHASE_1",
        "active_group_assignment_id": None,
        "active_group_session_date": None,
        "active_rehab_assignment_count": 0,
        "major_group_count": 0,
        "minor_group_count": 0,
    })
    db.insert("program_profiles", record)
    S.recompute_profile(record)
    return S.plain(record)


def get_program_profile(env):
    record = db.get("program_profiles", env["path"]["profile_id"])
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such program profile.")
    return S.plain(record)


def list_program_profiles(env):
    records = db.all("program_profiles")
    player_id = env["query"].get("player_id")
    if player_id:
        records = [r for r in records if r["player_id"] == player_id]
    return [S.plain(r) for r in records]


def list_player_program_profiles(env):
    player_id = env["path"]["player_id"]
    _player_or_404(player_id)
    return [S.plain(r) for r in db.find("program_profiles", player_id=player_id)]


def reinstate_profile(env):
    player_id = env["path"]["player_id"]
    player = _player_or_404(player_id)
    if S.is_farm_excluded(player_id):
        raise ApiError(ERR_FARM_ENTITY_EXCLUDED,
                       "The player is mapped onto an active spring trail.")
    profile = S.profile_of(player_id)
    if profile is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No program profile for that player.")
    if profile["eligibility_status"] != "TURNED_AWAY":
        raise ApiError("ERR_INVALID_STATE", "The profile is not turned away.")
    has_pass = any(p["status"] == "PERFORMED" and
                   p["physical_result"] in ("PASSED", "PASSED_WITH_MODIFICATION")
                   for p in db.find("physicals", player_id=player_id))
    if not has_pass:
        raise ApiError("ERR_INVALID_STATE", "No passing physical stands for this player.")
    profile["eligibility_status"] = "MEDICALS_PENDING"
    S.recompute_profile(profile)
    touch(profile, db.clock)
    return S.plain(profile)


# ---------------------------------------------------------------------------
def create_host_community_record(env):
    agreement_id = env["path"]["agreement_id"]
    agreement = _agreement_or_404(agreement_id)
    body = env["body"]
    if body.get("agreement_id") not in (None, agreement_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND", "agreement_id does not match the path.")
    record = new_record(db.new_id(), db.clock)
    record.update({
        "agreement_id": agreement_id,
        "ticketing_status": "NOT_OPEN",
        "tickets_sold": 0,
        "ticketing_revenue_cents": 0,
        "sponsorship_recorded_cents": 0,
        "sponsorship_revenue_cents": 0,
        "community_ledger_cents": 0,
        "agreement_funded_cents": 0,
        "recognition_funded_cents": 0,
        "ledger_gap_cents": 0,
    })
    db.insert("host_community_records", record)
    S.recompute_host_record(record)
    return S.plain(record)


def _host_record_or_404(record_id):
    record = db.get("host_community_records", record_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such host community record.")
    return record


def get_host_community_record(env):
    record = _host_record_or_404(env["path"]["record_id"])
    S.recompute_host_record(record)
    return S.plain(record)


def list_agreement_host_records(env):
    agreement_id = env["path"]["agreement_id"]
    _agreement_or_404(agreement_id)
    return [S.plain(r) for r in db.find("host_community_records", agreement_id=agreement_id)]


def list_host_community_records(env):
    records = db.all("host_community_records")
    agreement_id = env["query"].get("agreement_id")
    if agreement_id:
        records = [r for r in records if r["agreement_id"] == agreement_id]
    status = env["query"].get("ticketing_status")
    if status:
        records = [r for r in records if r["ticketing_status"] == status]
    return [S.plain(r) for r in records]


def open_ticketing(env):
    record = _host_record_or_404(env["path"]["record_id"])
    agreement = _agreement_or_404(record["agreement_id"])
    if record["ticketing_status"] != "NOT_OPEN":
        raise ApiError(ERR_INVALID_STATE, "Ticketing is not closed.")
    if agreement["agreement_status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "The agreement is not active.")
    if db.clock < parse_dt(agreement["lease_start_date"]) or \
            not db.clock < parse_dt(agreement["lease_end_date"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", "The clock is outside the lease window.")
    record["ticketing_status"] = "ON_SALE"
    touch(record, db.clock)
    S.recompute_host_record(record)
    return S.plain(record)


def close_ticketing(env):
    record = _host_record_or_404(env["path"]["record_id"])
    if record["ticketing_status"] != "ON_SALE":
        raise ApiError(ERR_INVALID_STATE, "Ticketing is not on sale.")
    if record["tickets_sold"] != 0:
        raise ApiError(ERR_INVALID_STATE, "Tickets have already sold.")
    record["ticketing_status"] = "NOT_OPEN"
    touch(record, db.clock)
    S.recompute_host_record(record)
    return S.plain(record)


def sell_tickets(env):
    record = _host_record_or_404(env["path"]["record_id"])
    agreement = _agreement_or_404(record["agreement_id"])
    quantity = require_int(env["body"], "quantity", 1)
    if record["ticketing_status"] != "ON_SALE":
        raise ApiError(ERR_INVALID_STATE, "Ticketing is not on sale.")
    if agreement["agreement_status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "The agreement is not active.")
    if not db.clock < parse_dt(agreement["lease_end_date"]):
        raise ApiError("ERR_OUTSIDE_WINDOW", "The lease window has closed.")
    record["tickets_sold"] = record["tickets_sold"] + quantity
    record["ticketing_revenue_cents"] = record["ticketing_revenue_cents"] + \
        quantity * agreement["ticket_price_cents"]
    if record["tickets_sold"] >= agreement["ticket_sellout_capacity"]:
        record["ticketing_status"] = "SOLD_OUT"
    touch(record, db.clock)
    S.recompute_host_record(record)
    return S.plain(record)


def get_ledger(env):
    return S.ledger_view(_host_record_or_404(env["path"]["record_id"]))


# ---------------------------------------------------------------------------
def create_sponsorship(env):
    record_id = env["path"]["record_id"]
    host = _host_record_or_404(record_id)
    body = env["body"]
    if body.get("host_community_record_id") not in (None, record_id):
        raise ApiError("ERR_FOREIGN_KEY_NOT_FOUND",
                       "host_community_record_id does not match the path.")
    sponsorship = new_record(db.new_id(), db.clock)
    sponsorship.update({
        "host_community_record_id": record_id,
        "sponsor_name": require_str(body, "sponsor_name"),
        "sponsor_tier": require_enum(body, "sponsor_tier", ("LOCAL", "REGIONAL", "NATIONAL")),
        "committed_amount_cents": require_int(body, "committed_amount_cents", 0),
        "received_amount_cents": 0,
        "fulfillment_completed": False,
        "reconciliation_status": "UNSETTLED",
        "last_action_at": None,
    })
    db.insert("sponsorships", sponsorship)
    S.recompute_host_record(host)
    return S.plain(sponsorship)


def _sponsorship_or_404(sponsorship_id):
    record = db.get("sponsorships", sponsorship_id)
    if record is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "No such sponsorship.")
    return record


def get_sponsorship(env):
    return S.plain(_sponsorship_or_404(env["path"]["sponsorship_id"]))


def list_record_sponsorships(env):
    record_id = env["path"]["record_id"]
    _host_record_or_404(record_id)
    return [S.plain(r) for r in db.find("sponsorships", host_community_record_id=record_id)]


def list_sponsorships(env):
    records = db.all("sponsorships")
    record_id = env["query"].get("host_community_record_id")
    if record_id:
        records = [r for r in records if r["host_community_record_id"] == record_id]
    status = env["query"].get("reconciliation_status")
    if status:
        records = [r for r in records if r["reconciliation_status"] == status]
    return [S.plain(r) for r in records]


def contribute_sponsorship(env):
    sponsorship = _sponsorship_or_404(env["path"]["sponsorship_id"])
    body = env["body"]
    amount = require_int(body, "amount_cents", 1)
    direction = require_enum(body, "direction",
                            ("CONTRIBUTE", "WITHDRAW", "CONTRIBUTION", "WITHDRAWAL"))
    if direction in ("CONTRIBUTE", "CONTRIBUTION"):
        sponsorship["received_amount_cents"] = sponsorship["received_amount_cents"] + amount
    else:
        sponsorship["received_amount_cents"] = max(
            0, sponsorship["received_amount_cents"] - amount)
    touch(sponsorship, db.clock)
    host = _host_record_or_404(sponsorship["host_community_record_id"])
    S.recompute_host_record(host)
    return S.plain(sponsorship)


def settle_sponsorship(env):
    sponsorship = _sponsorship_or_404(env["path"]["sponsorship_id"])
    if sponsorship["reconciliation_status"] != "UNSETTLED":
        raise ApiError(ERR_INVALID_STATE, "The sponsorship is not unsettled.")
    if sponsorship["received_amount_cents"] < sponsorship["committed_amount_cents"]:
        raise ApiError(ERR_SPONSORSHIP_NOT_FULLY_FUNDED, "The sponsorship is under-funded.")
    sponsorship["reconciliation_status"] = "SETTLED"
    sponsorship["fulfillment_completed"] = True
    sponsorship["last_action_at"] = fmt(db.clock)
    touch(sponsorship, db.clock)
    host = _host_record_or_404(sponsorship["host_community_record_id"])
    S.recompute_host_record(host)
    agreement = _agreement_or_404(host["agreement_id"])
    S.recompute_agreement_liability(agreement)
    return S.plain(sponsorship)


def recognize_sponsorship(env):
    sponsorship = _sponsorship_or_404(env["path"]["sponsorship_id"])
    if sponsorship["reconciliation_status"] != "SETTLED":
        raise ApiError(ERR_INVALID_STATE, "The sponsorship is not settled.")
    sponsorship["reconciliation_status"] = "RECOGNIZED"
    sponsorship["last_action_at"] = fmt(db.clock)
    touch(sponsorship, db.clock)
    host = _host_record_or_404(sponsorship["host_community_record_id"])
    S.recompute_host_record(host)
    agreement = _agreement_or_404(host["agreement_id"])
    S.recompute_agreement_liability(agreement)
    return S.plain(sponsorship)


def void_settlement(env):
    sponsorship = _sponsorship_or_404(env["path"]["sponsorship_id"])
    if sponsorship["reconciliation_status"] not in ("SETTLED", "RECOGNIZED"):
        raise ApiError(ERR_INVALID_STATE, "The sponsorship is not settled.")
    host = _host_record_or_404(sponsorship["host_community_record_id"])
    agreement = _agreement_or_404(host["agreement_id"])
    complex_record = db.get("complexes", agreement["complex_id"])
    if complex_record is not None and complex_record["facility_posture"] != "NORMAL":
        raise ApiError("ERR_POSTURE_BLOCKS_FISCAL",
                       "Fiscal operations are locked while the complex is restricted.")
    sponsorship["reconciliation_status"] = "SETTLEMENT_VOIDED"
    sponsorship["fulfillment_completed"] = False
    sponsorship["last_action_at"] = fmt(db.clock)
    touch(sponsorship, db.clock)
    S.recompute_host_record(host)
    _revert_agreement_for_fiscal(agreement)
    S.recompute_agreement_liability(agreement)
    return S.plain(sponsorship)