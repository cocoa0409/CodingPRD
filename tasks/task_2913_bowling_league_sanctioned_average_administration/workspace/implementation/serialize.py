"""Explicit response projections: exactly the fields the entities declare."""

from datetime import datetime
from decimal import Decimal

from clock import clock, to_iso

COMMON = ["id", "created_at", "updated_at", "version"]

LEAGUE = [
    "id", "name", "season_year", "center_name", "declared_team_count",
    "organizational_meeting_at", "secretary_member_id", "treasurer_member_id",
    "status", "bylaws_adopted_at", "handicap_base", "handicap_percentage",
    "handicap_percentage_youth", "max_handicap_per_game",
    "handicap_average_basis", "minimum_games_for_average", "carryover_policy",
    "vacancy_average", "vacancy_score", "absentee_deduction",
    "lineup_positions", "legal_lineup_minimum", "max_vacancy_slots_per_lineup",
    "weekly_dues_cents", "weekly_expense_cents", "max_dues_arrears_weeks",
    "prize_place_weights", "total_weeks", "sanctioned_member_count",
    "confirmed_team_count", "certified_week_high_water",
    "created_at", "updated_at", "version",
]

MEMBER = [
    "id", "full_name", "email", "member_class", "national_member_number",
    "sanctioned_membership_count", "created_at", "updated_at", "version",
]

TEAM = [
    "id", "league_id", "name", "status", "sanctioned_roster_count",
    "team_handicap_per_game", "total_points", "total_scratch_pins",
    "created_at", "updated_at", "version",
]

MEMBERSHIP = [
    "id", "league_id", "member_id", "team_id", "roster_role",
    "sanction_status", "remittance_status", "prior_season_average",
    "prior_season_games", "entering_average", "certified_games",
    "certified_pins", "current_average", "average_status",
    "handicap_per_game", "dues_paid_cents", "dues_arrears_weeks",
    "created_at", "updated_at", "version",
]

FEE_REMITTANCE = [
    "id", "league_id", "membership_ids", "declared_amount_cents",
    "computed_amount_cents", "penalty_cents", "member_count", "status",
    "submitted_at", "submitted_by_user_id", "national_receipt_no",
    "rejection_reason", "created_at", "updated_at", "version",
]

LANE_PAIR = [
    "id", "league_id", "pair_number", "certified_through", "revoked_at",
    "certification_status", "last_certified_at",
    "created_at", "updated_at", "version",
]

MATCH = [
    "id", "league_id", "week_number", "home_team_id", "away_team_id",
    "lane_pair_id", "forfeiting_team_id", "starts_at", "ends_at", "status",
    "home_team_handicap_per_game", "away_team_handicap_per_game",
    "home_points", "away_points", "certified_at", "void_reason",
    "created_at", "updated_at", "version",
]

SERIES_ENTRY = [
    "id", "match_id", "team_id", "membership_id", "position", "entry_type",
    "prebowled_at", "game1_pins", "game2_pins", "game3_pins",
    "games_recorded", "scratch_series", "handicap_per_game_applied",
    "counts_toward_average", "certified",
    "created_at", "updated_at", "version",
]

DUES_PAYMENT = [
    "id", "membership_id", "week_number", "amount_cents", "prize_share_cents",
    "expense_share_cents", "created_at",
]

PRIZE_FUND = [
    "id", "league_id", "status", "collected_prize_cents", "basis_variant",
    "place_count", "plan_basis_cents", "reserve_cents", "admin_fee_cents",
    "net_distributable_cents", "paid_award_total_cents",
    "undistributed_balance_cents", "plan_drafted_at",
    "plan_approved_by_user_id", "disbursed_at",
    "created_at", "updated_at", "version",
]

PRIZE_AWARD = [
    "id", "prize_fund_id", "team_id", "place", "weight", "amount_cents",
    "status", "reversal_reason", "created_at", "updated_at", "version",
]

AWARD_APPLICATION = [
    "id", "league_id", "membership_id", "series_entry_id", "award_type",
    "claimed_game_number", "claimed_pins", "status",
    "lane_certification_verified", "sanctioned_at_game_time", "evidence_note",
    "verified_by_user_id", "association_ruling_note", "round_count",
    "created_at", "updated_at", "version",
]

PROTEST = [
    "id", "league_id", "match_id", "filed_by_membership_id", "category",
    "protest_note", "status", "remedy", "review_round", "filed_at",
    "deadline_at", "ruling_note", "association_ruling",
    "created_at", "updated_at", "version",
]


def _value(value):
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_value(v) for v in value]
    return value


def project(row, fields):
    return {field: _value(row.get(field)) for field in fields}


def league(row):
    return project(row, LEAGUE)


def member(row):
    return project(row, MEMBER)


def team(row):
    return project(row, TEAM)


def membership(row):
    return project(row, MEMBERSHIP)


def fee_remittance(row):
    return project(row, FEE_REMITTANCE)


def certification_status(row):
    if row.get("revoked_at") is not None:
        return "REVOKED"
    if row.get("certified_through") is not None and \
            row["certified_through"] >= clock.now():
        return "CERTIFIED"
    return "EXPIRED"


def lane_pair(row):
    body = project(row, LANE_PAIR)
    body["certification_status"] = certification_status(row)
    return body


def match(row):
    return project(row, MATCH)


def series_entry(row):
    return project(row, SERIES_ENTRY)


def dues_payment(row):
    return project(row, DUES_PAYMENT)


def prize_fund(row):
    return project(row, PRIZE_FUND)


def prize_award(row):
    return project(row, PRIZE_AWARD)


def award_application(row):
    return project(row, AWARD_APPLICATION)


def protest(row):
    return project(row, PROTEST)
