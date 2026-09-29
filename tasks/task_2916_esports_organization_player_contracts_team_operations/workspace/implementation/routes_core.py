"""The logical clock, leagues, organizations and players (PRD sections 2.5, 3.1, 3.2)."""

from flask import Blueprint

import calc
import db
import response
import serializers as ser
import validation as v
from auth import endpoint, caller, require_org_owner, require_player_owner
from db import store
from errors import fail

bp = Blueprint("core", __name__)

EDUCATION_STATES = ("NOT_ENROLLED", "ENROLLED_PART_TIME", "ENROLLED_FULL_TIME")
PLAYER_STATES = ("PROSPECT", "TRYOUT_INVITED", "TRYOUT_COMPLETED", "SIGNED", "FREE_AGENT")


# ======================================================================================
# the logical clock
# ======================================================================================

@bp.post("/_clock/set_current_utc")
@endpoint(["LeagueAdmin"])
def set_clock():
    payload = v.body()
    instant = v.req_instant(payload, "current_utc")
    db.set_clock(instant)
    return response.object_response({"current_utc": db.iso(db.now())})


# ======================================================================================
# leagues
# ======================================================================================

def _league_window_shape(record):
    if not record["season_end_at"] > record["season_start_at"]:
        fail("ERR_INVALID_REQUEST", "Field 'season_end_at' must be after 'season_start_at'.")
    if not record["transfer_window_close_at"] > record["transfer_window_open_at"]:
        fail("ERR_INVALID_REQUEST",
             "Field 'transfer_window_close_at' must be after 'transfer_window_open_at'.")
    if record["max_roster_size"] < record["min_roster_size"]:
        fail("ERR_INVALID_REQUEST",
             "Field 'max_roster_size' must be >= 'min_roster_size'.")


@bp.post("/leagues")
@endpoint(["LeagueAdmin"])
def create_league():
    payload = v.body()
    record = {
        "name": v.req_str(payload, "name", 1, 120),
        "season_start_at": v.req_instant(payload, "season_start_at"),
        "season_end_at": v.req_instant(payload, "season_end_at"),
        "roster_lock_at": v.req_instant(payload, "roster_lock_at"),
        "transfer_window_open_at": v.req_instant(payload, "transfer_window_open_at"),
        "transfer_window_close_at": v.req_instant(payload, "transfer_window_close_at"),
        "minimum_salary_cents": v.opt_int(payload, "minimum_salary_cents", 3600000, 0),
        "min_roster_size": v.opt_int(payload, "min_roster_size", 1, 0),
        "max_roster_size": v.opt_int(payload, "max_roster_size", 7, 0),
        "offer_response_window_hours": v.opt_int(payload, "offer_response_window_hours", 72, 1),
        "max_negotiation_rounds": v.opt_int(payload, "max_negotiation_rounds", 3, 1),
        "player_association_levy_bp": v.opt_bp(payload, "player_association_levy_bp", 250),
        "association_min_prize_split_bp":
            v.opt_bp(payload, "association_min_prize_split_bp", 4000),
        "association_max_streaming_hours_per_week":
            v.opt_int(payload, "association_max_streaming_hours_per_week", 20, 0),
        "minor_max_weekly_minutes": v.opt_int(payload, "minor_max_weekly_minutes", 1200, 0),
        "adult_max_weekly_minutes": v.opt_int(payload, "adult_max_weekly_minutes", 2700, 0),
        "education_reserved_minutes": v.opt_int(payload, "education_reserved_minutes", 600, 0),
        "minor_age_threshold_years": v.opt_int(payload, "minor_age_threshold_years", 18, 1, 25),
        "free_agency_cooldown_days": v.opt_int(payload, "free_agency_cooldown_days", 14, 0),
        "tryout_required_before_offer":
            v.opt_bool(payload, "tryout_required_before_offer", False),
    }
    _league_window_shape(record)
    db.insert(store.leagues, record)
    return response.object_response(ser.league(record), 201)


@bp.get("/leagues/<league_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent", "FinanceOfficer"])
def read_league(league_id):
    return response.object_response(ser.league(v.find_league(league_id)))


@bp.get("/leagues")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent", "FinanceOfficer"])
def list_leagues():
    limit, offset = response.pagination()
    records = db.in_creation_order(list(store.leagues.values()))
    return response.paginated(records, ser.league, limit, offset)


@bp.patch("/leagues/<league_id>")
@endpoint(["LeagueAdmin"])
def update_league(league_id):
    record = v.find_league(league_id)
    payload = v.body()
    updates = {}
    for name in ("roster_lock_at", "transfer_window_open_at", "transfer_window_close_at"):
        if v.present(payload, name):
            updates[name] = v.req_instant(payload, name)
    for name, minimum, maximum in (
        ("minimum_salary_cents", 0, None),
        ("min_roster_size", 0, None),
        ("max_roster_size", 0, None),
        ("offer_response_window_hours", 1, None),
        ("max_negotiation_rounds", 1, None),
        ("minor_max_weekly_minutes", 0, None),
        ("adult_max_weekly_minutes", 0, None),
        ("education_reserved_minutes", 0, None),
        ("association_min_prize_split_bp", 0, 10000),
        ("association_max_streaming_hours_per_week", 0, None),
    ):
        if v.present(payload, name):
            updates[name] = v.req_int(payload, name, minimum, maximum)
    if v.present(payload, "tryout_required_before_offer"):
        updates["tryout_required_before_offer"] = v.req_bool(
            payload, "tryout_required_before_offer")
    merged = dict(record)
    merged.update(updates)
    _league_window_shape(merged)
    record.update(updates)
    db.touch(record)
    return response.object_response(ser.league(record))


@bp.get("/leagues/<league_id>/organizations")
@endpoint(["LeagueAdmin", "FinanceOfficer"])
def list_league_organizations(league_id):
    league = v.find_league(league_id)
    limit, offset = response.pagination()
    records = [o for o in store.organizations.values() if o["league_id"] == league["id"]]
    return response.paginated(db.in_creation_order(records), ser.organization, limit, offset)


# ======================================================================================
# organizations
# ======================================================================================

@bp.post("/organizations")
@endpoint(["LeagueAdmin"])
def create_organization():
    payload = v.body()
    league_id = v.req_str(payload, "league_id")
    name = v.req_str(payload, "name", 1, 120)
    jurisdiction = v.req_str(payload, "tax_jurisdiction_code", 2, 8, upper=True)
    budget = v.req_int(payload, "annual_salary_budget_cents", 0)
    share_bp = v.opt_bp(payload, "org_prize_share_bp", 3500)
    v.find_league(league_id)
    record = {
        "league_id": league_id,
        "name": name,
        "tax_jurisdiction_code": jurisdiction,
        "annual_salary_budget_cents": budget,
        "org_prize_share_bp": share_bp,
        "wellness_flag_count": 0,
    }
    db.insert(store.organizations, record)
    return response.object_response(ser.organization(record), 201)


@bp.get("/organizations/<organization_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "FinanceOfficer", "OpsManager",
           "SponsorshipManager"])
def read_organization(organization_id):
    record = v.find_organization(organization_id)
    require_org_owner(record["id"])
    return response.object_response(ser.organization(record))


@bp.get("/organizations")
@endpoint(["LeagueAdmin", "FinanceOfficer"])
def list_organizations():
    limit, offset = response.pagination()
    league_id = v.str_filter("league_id")
    records = list(store.organizations.values())
    if league_id is not None:
        records = [o for o in records if o["league_id"] == league_id]
    return response.paginated(db.in_creation_order(records), ser.organization, limit, offset)


@bp.patch("/organizations/<organization_id>")
@endpoint(["LeagueAdmin"])
def update_organization(organization_id):
    record = v.find_organization(organization_id)
    payload = v.body()
    if v.present(payload, "annual_salary_budget_cents"):
        record["annual_salary_budget_cents"] = v.req_int(
            payload, "annual_salary_budget_cents", 0)
    if v.present(payload, "org_prize_share_bp"):
        record["org_prize_share_bp"] = v.req_bp(payload, "org_prize_share_bp")
    db.touch(record)
    return response.object_response(ser.organization(record))


@bp.get("/organizations/<organization_id>/roster")
@endpoint(["LeagueAdmin", "GeneralManager", "CoachingStaff", "PerformanceSupport", "Scout"])
def list_organization_roster(organization_id):
    record = v.find_organization(organization_id)
    require_org_owner(record["id"])
    limit, offset = response.pagination()
    status = v.enum_filter("player_status", PLAYER_STATES)
    records = [p for p in store.players.values()
               if p["current_organization_id"] == record["id"]
               or p["last_release_organization_id"] == record["id"]]
    if status is not None:
        records = [p for p in records if p["player_status"] == status]
    return response.paginated(db.in_creation_order(records), ser.player, limit, offset)


@bp.get("/organizations/<organization_id>/cap-summary")
@endpoint(["LeagueAdmin", "GeneralManager", "FinanceOfficer"])
def read_cap_summary(organization_id):
    record = v.find_organization(organization_id)
    require_org_owner(record["id"])
    committed = calc.committed_salary_cents(record)
    data = {
        "organization_id": record["id"],
        "annual_salary_budget_cents": record["annual_salary_budget_cents"],
        "committed_salary_cents": committed,
        "uncommitted_salary_cents": record["annual_salary_budget_cents"] - committed,
        "active_roster_count": calc.active_roster_count(record),
        "prize_payable_cents": calc.prize_payable_cents(record),
        "wellness_flag_count": record["wellness_flag_count"],
        "provisional_committed_cents": calc.provisional_committed_cents(record),
        "final_committed_cents": calc.final_committed_cents(record),
    }
    return response.object_response(data)


# ======================================================================================
# players
# ======================================================================================

@bp.post("/players")
@endpoint(["Scout"])
def create_player():
    payload = v.body()
    user_id, _role = caller()
    record = {
        "full_name": v.req_str(payload, "full_name", 1, 120),
        "birth_date": v.req_date(payload, "birth_date"),
        "region_code": v.req_str(payload, "region_code", 2, 8, upper=True),
        "association_member": v.opt_bool(payload, "association_member", False),
        "player_status": "PROSPECT",
        "current_organization_id": None,
        "guardian_name": v.opt_str(payload, "guardian_name", None, 1, 120),
        "guardian_email": v.opt_str(payload, "guardian_email", None, 1, 320),
        "guardian_weekly_cap_minutes":
            v.opt_int(payload, "guardian_weekly_cap_minutes", None, 0),
        "education_enrollment_status":
            v.opt_enum(payload, "education_enrollment_status", EDUCATION_STATES,
                       "NOT_ENROLLED"),
        "free_agency_window_ends_at": None,
        "last_release_organization_id": None,
        "scouted_by_user_id": user_id,
        "guardian_consent_recorded": False,
    }
    db.insert(store.players, record)
    return response.object_response(ser.player(record), 201)


@bp.get("/players/<player_id>")
@endpoint(["LeagueAdmin", "GeneralManager", "PlayerAgent", "Scout", "CoachingStaff",
           "PerformanceSupport", "GuardianRepresentative"])
def read_player(player_id):
    record = v.find_player(player_id)
    require_player_owner(record["id"])
    return response.object_response(ser.player(record))


@bp.get("/players")
@endpoint(["LeagueAdmin", "GeneralManager", "Scout"])
def list_players():
    limit, offset = response.pagination()
    status = v.enum_filter("player_status", PLAYER_STATES)
    region = v.str_filter("region_code")
    current_org = v.str_filter("current_organization_id")
    last_release = v.str_filter("last_release_organization_id")
    records = list(store.players.values())
    if status is not None:
        records = [p for p in records if p["player_status"] == status]
    if region is not None:
        records = [p for p in records if p["region_code"] == region]
    if current_org is not None:
        records = [p for p in records if p["current_organization_id"] == current_org]
    if last_release is not None:
        records = [p for p in records if p["last_release_organization_id"] == last_release]
    return response.paginated(db.in_creation_order(records), ser.player, limit, offset)


@bp.patch("/players/<player_id>")
@endpoint(["Scout", "GuardianRepresentative"])
def update_player(player_id):
    record = v.find_player(player_id)
    require_player_owner(record["id"])
    payload = v.body()
    if v.present(payload, "full_name"):
        record["full_name"] = v.req_str(payload, "full_name", 1, 120)
    if v.present(payload, "region_code"):
        record["region_code"] = v.req_str(payload, "region_code", 2, 8, upper=True)
    if v.present(payload, "education_enrollment_status"):
        record["education_enrollment_status"] = v.req_enum(
            payload, "education_enrollment_status", EDUCATION_STATES)
    if v.present(payload, "guardian_weekly_cap_minutes"):
        record["guardian_weekly_cap_minutes"] = v.req_int(
            payload, "guardian_weekly_cap_minutes", 0)
    db.touch(record)
    return response.object_response(ser.player(record))


@bp.post("/players/<player_id>/guardian-consent")
@endpoint(["GuardianRepresentative"])
def record_guardian_consent(player_id):
    record = v.find_player(player_id)
    require_player_owner(record["id"])
    payload = v.body()
    guardian_name = v.req_str(payload, "guardian_name", 1, 120)
    guardian_email = v.req_str(payload, "guardian_email", 1, 320)
    cap_minutes = v.opt_int(payload, "guardian_weekly_cap_minutes", None, 0)
    record["guardian_name"] = guardian_name
    record["guardian_email"] = guardian_email
    if cap_minutes is not None:
        record["guardian_weekly_cap_minutes"] = cap_minutes
    record["guardian_consent_recorded"] = True
    db.touch(record)
    return response.object_response(ser.player(record))
