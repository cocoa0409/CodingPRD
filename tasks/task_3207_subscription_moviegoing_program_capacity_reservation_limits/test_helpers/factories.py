"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}@x.com"


def create_member_payload(**overrides) -> dict:
    defaults = {"email": _uniq("member"), "full_name": "Test Member"}
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "code": f"PLAN-{next(_counter)}",
        "tier": "BASIC",
        "monthly_fee_cents": 1999,
        "weekly_reservation_quota": 3,
        "max_rollover_credits": 2,
        "premium_format_allowed": False,
        "max_future_reservations": 5,
        "loyalty_points_multiplier_pct": 100,
        "concession_discount_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_theater_payload(**overrides) -> dict:
    defaults = {"name": f"Theater {next(_counter)}", "timezone": "America/Chicago"}
    defaults.update(overrides)
    return defaults


def create_auditorium_payload(**overrides) -> dict:
    defaults = {"label": "Auditorium 1", "seat_count": 10, "supported_formats": ["STANDARD"]}
    defaults.update(overrides)
    return defaults


def create_showtime_payload(auditorium_id: str, **overrides) -> dict:
    defaults = {
        "auditorium_id": auditorium_id,
        "film_title": "Test Film",
        "studio_code": "WB",
        "format": "STANDARD",
        "starts_at": "2026-09-06T19:00:00Z",
        "runtime_minutes": 120,
        "base_price_cents": 1200,
        "premium_surcharge_cents": 0,
        "opening_weekend": False,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(subscription_id: str, showtime_id: str,
                               expected_showtime_version: int, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "showtime_id": showtime_id,
        "expected_showtime_version": expected_showtime_version,
    }
    defaults.update(overrides)
    return defaults


def create_concession_purchase_payload(member_id: str, theater_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "theater_id": theater_id,
        "pre_discount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_report_payload(**overrides) -> dict:
    defaults = {
        "studio_code": "WB",
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
