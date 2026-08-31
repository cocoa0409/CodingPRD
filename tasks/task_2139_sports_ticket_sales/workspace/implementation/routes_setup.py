"""Seasons, games, seats, season plans, service reps and the logical clock."""
from flask import Blueprint

import calc
from core import (ROLE_ADMIN, ROLE_REVENUE, READ_ROLES, apply_filters, bad_request, body, bump,
                  base_fields, db, endpoint, err, find_game, find_plan, find_rep, find_season,
                  find_seat, iso, new_id, now, ok, ok_list, ok_page, opt_enum, opt_int, opt_str,
                  pagination, paginate, parse_iso, req_datetime, req_enum, req_id_list, req_int,
                  req_str, set_clock, sort_created)

bp = Blueprint("setup", __name__)

SEASON_STATUSES = ("PLANNING", "RENEWAL_OPEN", "GENERAL_ONSALE", "IN_SEASON", "ARCHIVED")
OPPONENT_TIERS = ("MARQUEE", "PREMIUM", "STANDARD", "VALUE")
DAY_BUCKETS = ("WEEKEND", "WEEKDAY")
PRICE_ZONES = ("ZONE_A", "ZONE_B", "ZONE_C", "ZONE_D")
PLAN_TYPES = ("FULL_SEASON", "HALF_SEASON", "PARTIAL", "GROUP")
REP_STATUSES = ("ACTIVE", "ON_LEAVE")


# ---------------------------------------------------------------------------
# Shared season-status gates (ladder rung 9)
# ---------------------------------------------------------------------------
def gate_selling(season):
    if season["season_status"] not in calc.SELLING_STATUSES:
        err("ERR_SEASON_NOT_SELLING", 409,
            "Season is %s; selling requires RENEWAL_OPEN or GENERAL_ONSALE." % season["season_status"])


def gate_status(season, allowed):
    if season["season_status"] not in allowed:
        err("ERR_SEASON_STATE_INVALID", 409,
            "Season is %s; this operation requires %s." % (season["season_status"], " or ".join(allowed)))


# ---------------------------------------------------------------------------
# Seasons
# ---------------------------------------------------------------------------
def _new_season(data):
    code = req_str(data, "code", 1, 16)
    year = req_int(data, "year", minimum=2020)
    total_home_games = req_int(data, "total_home_games", minimum=1)
    deadline = req_datetime(data, "renewal_deadline_utc")
    revenue_goal = req_int(data, "revenue_goal_cents", minimum=1)
    if deadline <= now():
        bad_request("Field 'renewal_deadline_utc' must be strictly after the current instant.")
    for existing in db.seasons.values():
        if existing["code"] == code:
            bad_request("Field 'code' must be unique across seasons.")
    row = {"id": new_id(), "code": code, "year": year, "total_home_games": total_home_games,
           "renewal_deadline_utc": deadline, "revenue_goal_cents": revenue_goal,
           "season_status": "PLANNING", "dynamic_pricing_mode": "AGGRESSIVE",
           "revenue_goal_met": False, "contracted_revenue_cents": 0,
           "secondary_market_volume_cents": 0, "total_seat_count": 0,
           "available_seat_count": 0, "held_seat_count": 0, "assigned_seat_count": 0,
           "renewal_opened_at_utc": None, "last_ops_run_at_utc": None}
    row.update(base_fields())
    return row


@bp.route("/ticketing/seasons", methods=["POST"])
@endpoint(ROLE_ADMIN)
def create_season(caller):
    row = _new_season(body())
    db.seasons[row["id"]] = row
    return ok(row, 201)


@bp.route("/ticketing/seasons/<season_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_season(caller, season_id):
    return ok(find_season(season_id))


@bp.route("/ticketing/seasons/<season_id>/open-renewal", methods=["POST"])
@endpoint(ROLE_ADMIN)
def open_renewal(caller, season_id):
    season = find_season(season_id)
    gate_status(season, ("PLANNING",))
    game_count = len([g for g in db.games.values() if g["season_id"] == season["id"]])
    if game_count != season["total_home_games"]:
        err("ERR_SEASON_SETUP_INCOMPLETE", 422,
            "Season has %d games but total_home_games is %d." % (game_count, season["total_home_games"]))
    published = [p for p in db.plans.values()
                 if p["season_id"] == season["id"] and p["plan_status"] == "PUBLISHED"]
    if not published:
        err("ERR_SEASON_SETUP_INCOMPLETE", 422, "Season has no PUBLISHED season plan.")
    if not (now() < season["renewal_deadline_utc"]):
        err("ERR_RENEWAL_DEADLINE_PASSED", 422, "The renewal deadline has already passed.")
    season["season_status"] = "RENEWAL_OPEN"
    season["renewal_opened_at_utc"] = now()
    calc.run_census(season)
    bump(season)
    return ok(season)


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------
@bp.route("/ticketing/games", methods=["POST"])
@endpoint(ROLE_ADMIN)
def create_game(caller):
    data = body()
    season_id = req_str(data, "season_id")
    opponent_code = req_str(data, "opponent_code", 1, 8)
    opponent_tier = req_enum(data, "opponent_tier", OPPONENT_TIERS)
    game_date = req_datetime(data, "game_date_utc")
    day_bucket = req_enum(data, "day_bucket", DAY_BUCKETS)
    demand_index = req_int(data, "demand_index", minimum=0, maximum=100)
    cap = opt_int(data, "hospitality_headcount_cap", default=200, minimum=0)

    season = find_season(season_id)
    gate_status(season, ("PLANNING",))

    row = {"id": new_id(), "season_id": season_id, "opponent_code": opponent_code,
           "opponent_tier": opponent_tier, "game_date_utc": game_date, "day_bucket": day_bucket,
           "demand_index": demand_index, "hospitality_headcount_cap": cap,
           "game_status": "SCHEDULED", "hospitality_booked_headcount": 0, "scanned_count": 0,
           "expected_attendance": 0, "no_show_count": 0, "no_show_rate_pct": 0.0}
    row.update(base_fields())
    db.games[row["id"]] = row
    return ok(row, 201)


@bp.route("/ticketing/games/<game_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_game(caller, game_id):
    return ok(find_game(game_id))


@bp.route("/ticketing/games", methods=["GET"])
@endpoint(*READ_ROLES)
def list_games(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.games.values()), [("season_id", "season_id"), ("game_status", "game_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Seats
# ---------------------------------------------------------------------------
@bp.route("/ticketing/seats", methods=["POST"])
@endpoint(ROLE_ADMIN)
def mint_seats(caller):
    data = body()
    season_id = req_str(data, "season_id")
    section_code = req_str(data, "section_code")
    row_label = req_str(data, "row_label")
    price_zone = req_enum(data, "price_zone", PRICE_ZONES)
    number_from = req_int(data, "seat_number_from", minimum=1)
    number_to = req_int(data, "seat_number_to", minimum=1)
    if number_to < number_from:
        bad_request("Field 'seat_number_to' must be >= 'seat_number_from'.")

    season = find_season(season_id)
    gate_status(season, ("PLANNING", "RENEWAL_OPEN"))

    existing = set()
    for seat in db.seats.values():
        if seat["season_id"] == season_id:
            existing.add((seat["section_code"], seat["row_label"], seat["seat_number"]))
    for number in range(number_from, number_to + 1):
        if (section_code, row_label, number) in existing:
            bad_request("Seat %s-%s-%d already exists in this season." % (section_code, row_label, number))

    created = []
    for number in range(number_from, number_to + 1):
        seat = {"id": new_id(), "season_id": season_id, "section_code": section_code,
                "row_label": row_label, "seat_number": number, "price_zone": price_zone,
                "seat_status": "AVAILABLE", "assigned_account_id": None, "scanned_game_ids": []}
        seat.update(base_fields())
        db.seats[seat["id"]] = seat
        created.append(seat)
    calc.run_census(season)
    bump(season)
    return ok_list(created, 201)


@bp.route("/ticketing/seats/<seat_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_seat(caller, seat_id):
    return ok(find_seat(seat_id))


@bp.route("/ticketing/seats", methods=["GET"])
@endpoint(*READ_ROLES)
def list_seats(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.seats.values()), [
        ("season_id", "season_id"), ("assigned_account_id", "assigned_account_id"),
        ("seat_status", "seat_status"), ("price_zone", "price_zone")])
    rows = sorted(rows, key=lambda r: (r["created_at"], r["section_code"], r["row_label"], r["seat_number"]))
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Season plans
# ---------------------------------------------------------------------------
@bp.route("/ticketing/season-plans", methods=["POST"])
@endpoint(ROLE_REVENUE)
def create_plan(caller):
    data = body()
    season_id = req_str(data, "season_id")
    plan_type = req_enum(data, "plan_type", PLAN_TYPES)
    game_ids = req_id_list(data, "game_ids")
    min_seats = req_int(data, "min_seats", minimum=1)
    max_seats = req_int(data, "max_seats", minimum=1)
    if max_seats < min_seats:
        bad_request("Field 'max_seats' must be >= 'min_seats'.")
    base_plan_id = opt_str(data, "base_plan_id")

    season = find_season(season_id)
    base_plan = find_plan(base_plan_id) if base_plan_id is not None else None
    gate_status(season, ("PLANNING", "RENEWAL_OPEN"))

    # Rung 18: plan construction integrity
    for gid in game_ids:
        game = db.games.get(gid)
        if game is None or game["season_id"] != season_id:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "Every game_id must belong to the plan's own season.")
    if plan_type == "FULL_SEASON":
        if base_plan_id is not None:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "A FULL_SEASON plan must not carry a base_plan_id.")
        if len(game_ids) != season["total_home_games"]:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422,
                "A FULL_SEASON plan must include exactly total_home_games games.")
    else:
        if base_plan is None:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "A derived plan requires a base_plan_id.")
        if base_plan["plan_status"] != "PUBLISHED":
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "The base plan must be PUBLISHED.")
        if base_plan["season_id"] != season_id:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "The base plan must live in the same season.")
        if not set(game_ids).issubset(set(base_plan["game_ids"])):
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "Derived game_ids must be a subset of the base plan's games.")
        if len(game_ids) < calc.MIN_PARTIAL_PLAN_GAMES:
            err("ERR_PLAN_GAMES_NOT_SUBSET", 422, "A derived plan must include at least 2 games.")

    row = {"id": new_id(), "season_id": season_id, "base_plan_id": base_plan_id,
           "plan_type": plan_type, "game_ids": list(game_ids), "min_seats": min_seats,
           "max_seats": max_seats, "plan_status": "DRAFT", "included_game_count": len(game_ids)}
    row.update(base_fields())
    db.plans[row["id"]] = row
    return ok(row, 201)


@bp.route("/ticketing/season-plans/<plan_id>/publish", methods=["POST"])
@endpoint(ROLE_REVENUE)
def publish_plan(caller, plan_id):
    plan = find_plan(plan_id)
    season = find_season(plan["season_id"])
    gate_status(season, ("PLANNING", "RENEWAL_OPEN"))
    if plan["plan_status"] != "DRAFT":
        err("ERR_PLAN_NOT_PUBLISHED", 409, "Only a DRAFT plan may be published.")
    plan["plan_status"] = "PUBLISHED"
    bump(plan)
    return ok(plan)


@bp.route("/ticketing/season-plans/<plan_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_plan(caller, plan_id):
    return ok(find_plan(plan_id))


@bp.route("/ticketing/season-plans", methods=["GET"])
@endpoint(*READ_ROLES)
def list_plans(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.plans.values()), [
        ("season_id", "season_id"), ("base_plan_id", "base_plan_id"), ("plan_status", "plan_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Service reps
# ---------------------------------------------------------------------------
@bp.route("/ticketing/service-reps", methods=["POST"])
@endpoint(ROLE_ADMIN)
def create_rep(caller):
    data = body()
    rep_name = req_str(data, "rep_name")
    territory_code = req_str(data, "territory_code")
    book_capacity = req_int(data, "book_capacity", minimum=1)
    rep_status = opt_enum(data, "rep_status", REP_STATUSES, "ACTIVE")
    row = {"id": new_id(), "rep_name": rep_name, "territory_code": territory_code,
           "book_capacity": book_capacity, "rep_status": rep_status,
           "assigned_account_count": 0, "touchpoints_logged_count": 0}
    row.update(base_fields())
    db.reps[row["id"]] = row
    return ok(row, 201)


@bp.route("/ticketing/service-reps/<rep_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_rep(caller, rep_id):
    return ok(find_rep(rep_id))


@bp.route("/ticketing/service-reps", methods=["GET"])
@endpoint(*READ_ROLES)
def list_reps(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.reps.values()), [
        ("rep_status", "rep_status"), ("territory_code", "territory_code")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ROLE_ADMIN)
def set_current_utc(caller):
    data = body()
    instant = req_datetime(data, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": iso(instant)})
