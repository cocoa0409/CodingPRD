"""Payload factories — one per entity, input fields only (PRD §4)."""

# Default two-lane configuration that satisfies both site-approval gates:
# total stacking 6 + 6 = 12 >= 10, ingress gap 45 >= 30 (PRD §3.1).
DEFAULT_LANE_CONFIGS = [
    {"lane_code": "A", "max_stack_cars": 6},
    {"lane_code": "B", "max_stack_cars": 6},
]

DEFAULTS = {
    "REGION_NAME": "Northwest",
    "REGION_CODE": "NW",
    "STAND_NAME": "Stand 42",
    "MIN_INGRESS_GAP_SECONDS": 45,
    "OP_NAME": "Op One",
    "OP_HIRED_ON": "2024-01-01",
    "CREW_HIRED_ON": "2025-06-01",
    "CERT_EXPIRES": "2027-12-31",
    "REVENUE_SHARE_PCT": 0.30,
    "RECIPE_NAME": "Carmelizer",
    "RECIPE_BASE_PRICE_CENTS": 450,
    "RECIPE_BASE_BUILD_SECONDS": 60,
    "RECIPE_TEMPERATURE_CLASS": "ICED",
}


def create_region_payload(**overrides):
    defaults = {
        "name": DEFAULTS["REGION_NAME"],
        "code": DEFAULTS["REGION_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_stand_payload(region_id, **overrides):
    defaults = {
        "region_id": region_id,
        "name": DEFAULTS["STAND_NAME"],
        "min_ingress_gap_seconds": DEFAULTS["MIN_INGRESS_GAP_SECONDS"],
        "lane_configs": [dict(lane) for lane in DEFAULT_LANE_CONFIGS],
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(home_stand_id, **overrides):
    defaults = {
        "full_name": DEFAULTS["OP_NAME"],
        "home_stand_id": home_stand_id,
        "hired_on": DEFAULTS["CREW_HIRED_ON"],
        "food_handler_cert_expires_on": DEFAULTS["CERT_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(stand_id, crew_member_id, **overrides):
    defaults = {
        "stand_id": stand_id,
        "crew_member_id": crew_member_id,
        "revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(**overrides):
    defaults = {
        "name": DEFAULTS["RECIPE_NAME"],
        "channel": "CORE",
        "base_price_cents": DEFAULTS["RECIPE_BASE_PRICE_CENTS"],
        "base_build_seconds": DEFAULTS["RECIPE_BASE_BUILD_SECONDS"],
        "temperature_class": DEFAULTS["RECIPE_TEMPERATURE_CLASS"],
        # The default Carmelizer carries one modifier (PRD §3.6 snapshot math):
        # 450 + 50 = 500 per unit, 60 + 10 = 70s base build.
        "modifiers": [
            {"name": "EXTRA_SHOT", "price_cents": 50, "build_seconds_adder": 10}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(recipe_id, stand_id, **overrides):
    defaults = {"recipe_id": recipe_id, "stand_id": stand_id}
    defaults.update(overrides)
    return defaults


def create_loyalty_account_payload(home_stand_id, **overrides):
    defaults = {"full_name": "Loyal Larry", "home_stand_id": home_stand_id}
    defaults.update(overrides)
    return defaults


def create_shift_payload(stand_id, **overrides):
    defaults = {
        "stand_id": stand_id,
        "starts_at": "2026-09-01T07:00:00Z",
        "ends_at": "2026-09-01T09:00:00Z",
        "is_peak": False,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(crew_member_id, expected_shift_version, **overrides):
    defaults = {
        "crew_member_id": crew_member_id,
        "role": "BAR",
        "starts_at": "2026-09-01T07:00:00Z",
        "ends_at": "2026-09-01T09:00:00Z",
        "expected_shift_version": expected_shift_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_item_payload(recipe_id, **overrides):
    defaults = {"recipe_id": recipe_id, "quantity": 1, "modifier_names": []}
    defaults.update(overrides)
    return defaults


def create_order_payload(stand_id, source, expected_stand_version, items, **overrides):
    defaults = {
        "stand_id": stand_id,
        "source": source,
        "items": items,
        "expected_stand_version": expected_stand_version,
    }
    if source == "WINDOW":
        defaults.setdefault("lane_code", "A")
    defaults.update(overrides)
    return defaults


def create_window_payload(stand_id, **overrides):
    defaults = {
        "stand_id": stand_id,
        "starts_at": "2026-09-01T07:00:00Z",
        "ends_at": "2026-09-01T08:00:00Z",
        "target_cars": 1,
    }
    defaults.update(overrides)
    return defaults


def create_authorize_payload(**overrides):
    defaults = {"card_token": "VISA-OK"}
    defaults.update(overrides)
    return defaults


def create_refund_payload(amount_cents, **overrides):
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_points_adjustment_payload(delta_points, **overrides):
    defaults = {"delta_points": delta_points, "reason": "goodwill"}
    defaults.update(overrides)
    return defaults
