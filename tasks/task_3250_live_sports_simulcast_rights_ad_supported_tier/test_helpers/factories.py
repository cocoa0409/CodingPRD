"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_property_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "property_code": f"P-{n}",
        "display_name": f"Property {n}",
        "sport": "NFL",
        "rights_fee_cents": TEST_DEFAULTS["RIGHTS_FEE_CENTS"],
        "term_start": TEST_DEFAULTS["TERM_START"],
        "term_end": TEST_DEFAULTS["TERM_END"],
        "amortization_method": "STRAIGHT_LINE",
        "simulcast_windows_count": 5,
        "exclusive_windows_count": 5,
        "minimum_exclusive_ratio_pct": 0,
        "required_local_breaks_per_event": 0,
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(property_id, expected_property_version, **overrides) -> dict:
    n = _seq()
    defaults = {
        "property_id": property_id,
        "event_code": f"E{n}",
        "rights_mode": "SIMULCAST",
        "scheduled_start": "2026-10-01T18:00:00Z",
        "scheduled_end": "2026-10-01T21:00:00Z",
        "territory_scope": [TEST_DEFAULTS["REGION"]],
        "regional_block": False,
        "capacity_required_units": 1,
        "replay_hours": 0,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def create_territory_rule_payload(window_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "window_id": window_id,
        "region_code": TEST_DEFAULTS["REGION"],
        "rule_kind": "BLACKOUT",
        "effective_start": "2026-10-01T17:00:00Z",
        "effective_end": "2026-10-01T20:00:00Z",
        "broadcast_obligation_ref": f"BC-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_viewer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "email": f"viewer{n}@example.com",
        "home_region": TEST_DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_capacity_pool_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "pool_code": f"POOL-{n}",
        "scope_kind": "REGION",
        "region_code": TEST_DEFAULTS["REGION"],
        "total_units": 100,
        "oversubscribe_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(pool_id, window_id, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "window_id": window_id,
        "units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_ad_campaign_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "advertiser_code": f"ADV-{n}",
        "flight_start": "2026-09-01T00:00:00Z",
        "flight_end": "2026-12-01T00:00:00Z",
        "frequency_cap_per_viewer": 5,
        "frequency_window_hours": 24,
        "cpm_cents": 500,
        "region_target": [],
    }
    defaults.update(overrides)
    return defaults


def create_ad_slot_payload(window_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "window_id": window_id,
        "break_index": 1,
        "pod_index": n,
        "duration_seconds": 30,
        "slot_scope": "NATIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "partner_code": f"PT-{n}",
        "display_name": f"Partner {n}",
        "bundled_tier": "PREMIUM",
        "max_promo_codes": 5,
    }
    defaults.update(overrides)
    return defaults
