"""Payload factories — one per entity, input fields only."""

DEFAULT_OFFER_EXPIRY = "2026-12-31T00:00:00Z"
DEFAULT_SCREENING_START = "2027-01-22T20:00:00Z"
DEFAULT_SCREENING_END = "2027-01-22T22:00:00Z"
DEFAULT_EMBARGO_LIFT = "2027-01-23T08:00:00Z"  # 10h delay -> 1.25 multiplier
DEFAULT_OPENING_WEEKEND = "2027-02-05T00:00:00Z"


def create_film_payload(**overrides) -> dict:
    defaults = {
        "title": "Meridian",
        "director_name": "Ana Ruiz",
        "principal_cast": ["Jae Park"],
        "genre": "DRAMA",
        "runtime_minutes": 102,
        "production_budget_cents": 2_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "code": "US",
        "name": "United States",
        "is_home_ent_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_festival_payload(**overrides) -> dict:
    defaults = {
        "code": "SUNDANCE",
        "name": "Sundance Film Festival",
        "start_date": "2027-01-21T00:00:00Z",
        "end_date": "2027-01-31T00:00:00Z",
        "prestige_tier": "A_LIST",
        "default_review_embargo_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_premiere_slot_payload(**overrides) -> dict:
    defaults = {
        "section": "COMPETITION",
        "screening_starts_at": DEFAULT_SCREENING_START,
        "screening_ends_at": DEFAULT_SCREENING_END,
        "review_embargo_lifts_at": DEFAULT_EMBARGO_LIFT,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "buyer_code": "A24",
        "upfront_price_cents": 5_000_000,
        "backend_participation_pct": 0.10,
        "prints_advertising_commit_cents": 8_000_000,
        "requested_territory_codes": ["US"],
        "requested_windows": ["THEATRICAL"],
        "expiry_at": DEFAULT_OFFER_EXPIRY,
    }
    defaults.update(overrides)
    return defaults


def create_release_plan_payload(**overrides) -> dict:
    defaults = {
        "platform_strategy": "LIMITED_4",
        "opening_weekend_date": DEFAULT_OPENING_WEEKEND,
        "target_market_codes": ["NY"],
        "expansion_threshold_psa_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_market_screening_payload(**overrides) -> dict:
    defaults = {
        "market_code": "LA",
        "weekend_index": 2,
        "screen_count": 10,
        "weekend_gross_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_awards_campaign_payload(**overrides) -> dict:
    defaults = {
        "awards_body": "OSCARS",
        "target_categories": ["BEST_PICTURE"],
        "budget_total_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_campaign_spend_payload(**overrides) -> dict:
    defaults = {
        "category": "PUBLICITY",
        "amount_cents": 100_000,
        "incurred_at": "2026-10-01T00:00:00Z",
        "target_category": "BEST_PICTURE",
    }
    defaults.update(overrides)
    return defaults


def create_talent_obligation_payload(**overrides) -> dict:
    defaults = {
        "talent_name": "Jae Park",
        "obligation_kind": "PRESS_JUNKET",
        "window_starts_at": "2026-12-01T10:00:00Z",
        "window_ends_at": "2026-12-01T12:00:00Z",
        "city_code": "NY",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {
        "period_label": "Q1-2027",
        "basis": "GROSS_RECEIPTS",
        "gross_receipts_cents": 20_000_000,
    }
    defaults.update(overrides)
    return defaults
