"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    CANONICAL_METHODODOLOGY,
    DEFAULT_AVAILABLE_FROM,
    DEFAULT_EVENT_TIME,
    DEFAULT_RELEASE_DATE,
    DEFAULT_WEEK_CLOSES_AT,
    DEFAULT_WEEK_OPENS_AT,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_recurrent_rule_payload(**overrides) -> dict:
    defaults = {
        "rule_code": _uniq("RR"),
        "max_weeks": 20,
        "min_rank": 25,
        "reentry_min_rank": 10,
        "description": "standard recurrent policy",
    }
    defaults.update(overrides)
    return defaults


def create_chart_payload(recurrent_rule_id, **overrides) -> dict:
    defaults = {
        "chart_code": _uniq("CH"),
        "title": "Test Chart",
        "chart_kind": "SINGLES",
        "chart_scope": "MAIN",
        "recurrent_rule_id": recurrent_rule_id,
    }
    defaults.update(overrides)
    return defaults


def create_methodology_version_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_METHODODOLOGY)
    defaults.update(overrides)
    return defaults


def create_chart_week_payload(**overrides) -> dict:
    defaults = {
        "week_index": 1,
        "opens_at": DEFAULT_WEEK_OPENS_AT,
        "closes_at": DEFAULT_WEEK_CLOSES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "provider_code": _uniq("PV"),
        "display_name": "Test Provider",
        "feed_kind": "SALES",
        "territory": "DOMESTIC",
    }
    defaults.update(overrides)
    return defaults


def create_label_payload(**overrides) -> dict:
    defaults = {
        "legal_name": _uniq("Label"),
        "account_code": _uniq("LBL"),
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(label_account_id, **overrides) -> dict:
    defaults = {
        "upc": _uniq("UPC"),
        "title": "Test Title",
        "artist_name": "Test Artist",
        "product_kind": "TRACK",
        "genre_tag": "pop",
        "release_date": DEFAULT_RELEASE_DATE,
        "base_price_cents": 999,
        "label_account_id": label_account_id,
        "availability_policy": {
            "available_from": DEFAULT_AVAILABLE_FROM,
            "available_until": None,
        },
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(title_product_id, chart_week_id, **overrides) -> dict:
    defaults = {
        "title_product_id": title_product_id,
        "chart_week_id": chart_week_id,
        "component_kind": "SALES",
        "quantity": 10,
        "event_time": DEFAULT_EVENT_TIME,
        "file_fingerprint": _uniq("fp"),
    }
    defaults.update(overrides)
    return defaults


def create_sale_batch_payload(chart_week_id, **overrides) -> dict:
    defaults = {
        "channel": "D2C",
        "quantity": 1,
        "buyer_key": _uniq("buyer"),
        "chart_week_id": chart_week_id,
    }
    defaults.update(overrides)
    return defaults


def create_signal_payload(title_product_id, chart_week_id, **overrides) -> dict:
    defaults = {
        "title_product_id": title_product_id,
        "chart_week_id": chart_week_id,
        "signal_kind": "ARTIFICIAL_STREAMING",
        "evidence": "suspicious pattern",
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(title_product_id, chart_id, filed_by_label_id, **overrides) -> dict:
    defaults = {
        "title_product_id": title_product_id,
        "chart_id": chart_id,
        "filed_by_label_id": filed_by_label_id,
        "claimed_genre": "country",
    }
    defaults.update(overrides)
    return defaults
