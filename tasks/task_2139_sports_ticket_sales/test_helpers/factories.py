"""Payload factories - one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_season_payload(**overrides):
    payload = {
        "code": TEST_DEFAULTS["SEASON_CODE"],
        "year": TEST_DEFAULTS["SEASON_YEAR"],
        "total_home_games": 1,
        "renewal_deadline_utc": TEST_DEFAULTS["RENEWAL_DEADLINE_UTC"],
        "revenue_goal_cents": TEST_DEFAULTS["REVENUE_GOAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_game_payload(season_id, **overrides):
    payload = {
        "season_id": season_id,
        "opponent_code": "RIV",
        "opponent_tier": "PREMIUM",
        "game_date_utc": TEST_DEFAULTS["GAME_DATE_UTC"],
        "day_bucket": "WEEKEND",
        "demand_index": 85,
    }
    payload.update(overrides)
    return payload


def create_seats_payload(season_id, **overrides):
    payload = {
        "season_id": season_id,
        "section_code": "104",
        "row_label": "A",
        "price_zone": "ZONE_C",
        "seat_number_from": 1,
        "seat_number_to": 2,
    }
    payload.update(overrides)
    return payload


def create_season_plan_payload(season_id, game_ids, **overrides):
    payload = {
        "season_id": season_id,
        "plan_type": "FULL_SEASON",
        "game_ids": list(game_ids),
        "min_seats": 1,
        "max_seats": 4,
    }
    payload.update(overrides)
    return payload


def create_service_rep_payload(**overrides):
    payload = {
        "rep_name": "Rep North",
        "territory_code": TEST_DEFAULTS["TERRITORY_CODE"],
        "book_capacity": 5,
    }
    payload.update(overrides)
    return payload


def create_account_payload(**overrides):
    payload = {
        "account_name": "Acct One",
        "account_type": "INDIVIDUAL",
        "territory_code": TEST_DEFAULTS["TERRITORY_CODE"],
        "tenure_years": 0,
    }
    payload.update(overrides)
    return payload


def create_seat_hold_payload(seat_id, account_id, expected_seat_version, **overrides):
    payload = {
        "seat_id": seat_id,
        "account_id": account_id,
        "hold_type": "GROUP_HOLD",
        "hold_window_start_utc": "2026-08-01T00:00:00Z",
        "hold_window_end_utc": "2026-09-01T00:00:00Z",
        "expected_seat_version": expected_seat_version,
    }
    payload.update(overrides)
    return payload


def create_plan_order_payload(account_id, plan_id, seat_ids, **overrides):
    payload = {
        "account_id": account_id,
        "plan_id": plan_id,
        "seat_ids": list(seat_ids),
    }
    payload.update(overrides)
    return payload


def create_hospitality_package_payload(game_id, account_id, **overrides):
    payload = {
        "game_id": game_id,
        "account_id": account_id,
        "suite_code": "SUITE-1",
        "headcount": 10,
        "service_window_start_utc": "2026-10-10T18:00:00Z",
        "service_window_end_utc": "2026-10-10T21:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_ticket_transfer_payload(order_id, game_id, seat_id, **overrides):
    payload = {
        "order_id": order_id,
        "game_id": game_id,
        "seat_id": seat_id,
        "transfer_type": "RESALE",
        "resale_price_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_touchpoint_payload(**overrides):
    payload = {"touchpoint_type": "CALL", "outcome": "COMMITTED"}
    payload.update(overrides)
    return payload
