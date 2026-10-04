"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "REGION_NAME": "Test Region",
    "COUNTRY_CODE": "US",
    "TIMEZONE": "America/Chicago",
    "GEO_MIN_LAT": 40.0,
    "GEO_MAX_LAT": 41.0,
    "GEO_MIN_LNG": -88.0,
    "GEO_MAX_LNG": -87.0,
    "LISTING_NAME": "Test Listing",
    "LISTING_CATEGORY": "RETAIL",
    "ADDRESS_TEXT": "1 Main St",
    "GEO_LAT": 40.5,
    "GEO_LNG": -87.5,
    "REVIEW_TEXT": "A perfectly ordinary review with enough characters to be safe.",
    "REVIEW_RATING": 4,
    "WINDOW_START": "2026-09-02T00:00:00Z",
    "WINDOW_END": "2026-09-05T00:00:00Z",
    "BLUR_OBLIGATION": "FACES_AND_PLATES",
    "EFFECTIVE_START": "2026-10-01T00:00:00Z",
    "EFFECTIVE_END": "2026-10-02T00:00:00Z",
}


def create_region_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["REGION_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "timezone": DEFAULTS["TIMEZONE"],
        "geo_min_lat": DEFAULTS["GEO_MIN_LAT"],
        "geo_max_lat": DEFAULTS["GEO_MAX_LAT"],
        "geo_min_lng": DEFAULTS["GEO_MIN_LNG"],
        "geo_max_lng": DEFAULTS["GEO_MAX_LNG"],
    }
    defaults.update(overrides)
    return defaults


def create_contributor_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Test Contributor",
        "email": "contributor@example.com",
        "home_region_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_contributor_grant_payload(**overrides) -> dict:
    defaults = {
        "contributor_id": "",
        "source_type": "ADJUSTMENT",
        "source_id": "manual-adjustment",
        "base_points": 10,
        "note": "manual adjustment rationale",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    defaults = {
        "region_id": "",
        "name": DEFAULTS["LISTING_NAME"],
        "category": DEFAULTS["LISTING_CATEGORY"],
        "address_text": DEFAULTS["ADDRESS_TEXT"],
        "geo_lat": DEFAULTS["GEO_LAT"],
        "geo_lng": DEFAULTS["GEO_LNG"],
    }
    defaults.update(overrides)
    return defaults


def create_verification_attempt_payload(**overrides) -> dict:
    defaults = {
        "listing_id": "",
        "method": "POSTCARD",
    }
    defaults.update(overrides)
    return defaults


def create_map_edit_payload(**overrides) -> dict:
    defaults = {
        "listing_id": "",
        "contributor_id": "",
        "edit_type": "ATTRIBUTE",
        "payload": {"attribute": "wifi", "value": True},
        "expected_listing_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_review_ticket_payload(**overrides) -> dict:
    defaults = {
        "queue": "EDIT_REVIEW",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {
        "listing_id": "",
        "contributor_id": "",
        "rating": DEFAULTS["REVIEW_RATING"],
        "text": DEFAULTS["REVIEW_TEXT"],
    }
    defaults.update(overrides)
    return defaults


def create_review_flag_payload(**overrides) -> dict:
    defaults = {
        "reason": "SPAM",
    }
    defaults.update(overrides)
    return defaults


def create_suspension_payload(**overrides) -> dict:
    defaults = {
        "violation_type": "FAKE_ADDRESS",
        "evidence_notes": "evidence gathered by policy team",
    }
    defaults.update(overrides)
    return defaults


def create_hours_observation_payload(**overrides) -> dict:
    defaults = {
        "listing_id": "",
        "source": "WEB_CRAWL",
        "day_mask": "1111100",
        "open_time": "09:00",
        "close_time": "17:00",
    }
    defaults.update(overrides)
    return defaults


def create_imagery_task_payload(**overrides) -> dict:
    defaults = {
        "region_id": "",
        "collection_zone": "zone-A",
        "operator_id": "op-1",
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "blur_obligation": DEFAULTS["BLUR_OBLIGATION"],
    }
    defaults.update(overrides)
    return defaults


def create_routing_update_payload(**overrides) -> dict:
    defaults = {
        "region_id": "",
        "segment_ref": "S1",
        "kind": "CLOSURE",
        "effective_start": DEFAULTS["EFFECTIVE_START"],
        "effective_end": DEFAULTS["EFFECTIVE_END"],
        "expected_region_version": 1,
    }
    defaults.update(overrides)
    return defaults
