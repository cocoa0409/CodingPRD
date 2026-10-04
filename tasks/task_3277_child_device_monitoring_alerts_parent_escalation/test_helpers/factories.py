"""Payload factories — one per entity, input fields only."""

DEFAULT_BIRTH_YEAR = 2012  # age 14 at the default 2026 logical clock


def create_family_payload(**overrides) -> dict:
    defaults = {
        "family_name": "Test Family",
        "primary_contact_email": "parent@example.com",
        "primary_parent_name": "Pat Parent",
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(**overrides) -> dict:
    defaults = {
        "family_account_id": None,
        "display_name": "Test Child",
        "birth_year": DEFAULT_BIRTH_YEAR,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_connection_payload(**overrides) -> dict:
    defaults = {
        "service_type": "MESSAGING",
        "external_handle": "kid@example",
        "credential_token": "tok-000",
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {"platform": "ANDROID", "nickname": "dev-1"}
    defaults.update(overrides)
    return defaults


def create_window_payload(**overrides) -> dict:
    defaults = {
        "weekday": "MON",
        "start_minute": 480,
        "end_minute": 720,
        "window_kind": "BLOCKED",
    }
    defaults.update(overrides)
    return defaults


def create_filter_rule_payload(**overrides) -> dict:
    defaults = {"rule_kind": "CATEGORY_BLOCK", "target": "gambling"}
    defaults.update(overrides)
    return defaults


def create_bypass_event_payload(**overrides) -> dict:
    defaults = {"bypass_kind": "VPN", "detected_at": "2026-09-01T00:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-09-01T01:00:00Z",
        "end_at": "2026-09-01T02:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_content_item_payload(**overrides) -> dict:
    defaults = {
        "service_connection_id": None,
        "occurred_at": "2026-09-01T00:00:00Z",
        "direction": "INBOUND",
        "thread_depth": 1,
        "signals": [{"category": "BULLYING", "weight": 40}],
        "raw_text": "sample monitored content",
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_district_payload(**overrides) -> dict:
    defaults = {
        "district_name": "Test District",
        "contact_email": "admin@district.edu",
        "jurisdiction": "DISCRETIONARY",
    }
    defaults.update(overrides)
    return defaults


def create_district_link_payload(**overrides) -> dict:
    defaults = {"child_profile_id": None}
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
