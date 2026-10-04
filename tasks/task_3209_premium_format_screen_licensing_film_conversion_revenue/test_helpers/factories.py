"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MARKET_NAME": "Metro",
    "COUNTRY_CODE": "US",
    "SCREEN_CAPACITY_CAP": 5,
    "FORMAT_MIX": ["PREMIUM_2D"],
    "EXHIBITOR_LEGAL_NAME": "Exh A",
    "COMMITTED_SCREEN_COUNT": 1,
    "TIER1_PCT": 0.12,
    "TIER2_PCT": 0.15,
    "TIER3_PCT": 0.18,
    "TERM_START": "2026-09-01T00:00:00Z",
    "TERM_END": "2027-09-01T00:00:00Z",
    "AUDITORIUM_LABEL": "S1",
    "SEATING_CAPACITY": 200,
    "STUDIO_LEGAL_NAME": "St A",
    "CONTACT_EMAIL": "a@st.com",
    "FILM_TITLE": "Film X",
    "RUNTIME_MINUTES": 100,
    "WORLDWIDE_RELEASE_DATE": "2026-09-05T00:00:00Z",
    "POST_START": "2026-09-01T00:00:00Z",
    "POST_END": "2026-09-03T00:00:00Z",
    "WINDOW_LABEL": "W37",
    "WINDOW_START": "2026-09-07T00:00:00Z",
    "WINDOW_END": "2026-09-14T00:00:00Z",
    "WINDOW_POOL_SECONDS": 10000000,
    "SHOWINGS_PER_DAY": 2,
    "REPORTED_DATE": "2026-09-07T00:00:00Z",
    "VISIT_DATE": "2026-09-05T00:00:00Z",
}

SCREEN_GEOMETRY = {"width_m": 20, "height_m": 11, "curvature_deg": 60}
SOUND_CALIBRATION_PROFILE = {"spl_target_db": 85, "eq_curve_id": "STD", "channel_count": 12}


def create_market_payload(**overrides) -> dict:
    defaults = {
        "market_name": DEFAULTS["MARKET_NAME"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "screen_capacity_cap": DEFAULTS["SCREEN_CAPACITY_CAP"],
        "target_format_mix": list(DEFAULTS["FORMAT_MIX"]),
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "exhibitor_legal_name": DEFAULTS["EXHIBITOR_LEGAL_NAME"],
        "market_id": "",  # must be supplied via overrides
        "agreement_type": "REVENUE_SHARE",
        "committed_screen_count": DEFAULTS["COMMITTED_SCREEN_COUNT"],
        "revenue_share_tier1_pct": DEFAULTS["TIER1_PCT"],
        "revenue_share_tier2_pct": DEFAULTS["TIER2_PCT"],
        "revenue_share_tier3_pct": DEFAULTS["TIER3_PCT"],
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_auditorium_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": "",  # must be supplied via overrides
        "auditorium_label": DEFAULTS["AUDITORIUM_LABEL"],
        "screen_geometry": dict(SCREEN_GEOMETRY),
        "seating_capacity": DEFAULTS["SEATING_CAPACITY"],
        "supported_formats": ["PREMIUM_2D"],
        "sound_calibration_profile": dict(SOUND_CALIBRATION_PROFILE),
    }
    defaults.update(overrides)
    return defaults


def create_studio_payload(**overrides) -> dict:
    defaults = {
        "studio_legal_name": DEFAULTS["STUDIO_LEGAL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_film_payload(**overrides) -> dict:
    defaults = {
        "studio_id": "",  # must be supplied via overrides
        "title": DEFAULTS["FILM_TITLE"],
        "runtime_minutes": DEFAULTS["RUNTIME_MINUTES"],
        "worldwide_release_date": DEFAULTS["WORLDWIDE_RELEASE_DATE"],
        "format_targets": ["PREMIUM_2D"],
    }
    defaults.update(overrides)
    return defaults


def create_conversion_order_payload(**overrides) -> dict:
    defaults = {
        "studio_film_id": "",  # must be supplied via overrides
        "target_format": "PREMIUM_2D",
        "scheduled_post_start_date": DEFAULTS["POST_START"],
        "scheduled_post_end_date": DEFAULTS["POST_END"],
    }
    defaults.update(overrides)
    return defaults


def create_release_window_payload(**overrides) -> dict:
    defaults = {
        "window_label": DEFAULTS["WINDOW_LABEL"],
        "window_start_date": DEFAULTS["WINDOW_START"],
        "window_end_date": DEFAULTS["WINDOW_END"],
        "total_premium_screen_seconds_pool": DEFAULTS["WINDOW_POOL_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_screen_slot_payload(**overrides) -> dict:
    defaults = {
        "window_id": "",  # must be supplied via overrides
        "auditorium_id": "",
        "studio_film_id": "",
        "conversion_order_id": "",
        "slot_start_date": DEFAULTS["WINDOW_START"],
        "slot_end_date": DEFAULTS["WINDOW_END"],
        "showings_per_day": DEFAULTS["SHOWINGS_PER_DAY"],
        "expected_window_version": 1,  # override with the observed window version
    }
    defaults.update(overrides)
    return defaults


def create_box_office_report_payload(**overrides) -> dict:
    defaults = {
        "screen_slot_id": "",  # must be supplied via overrides
        "reported_date": DEFAULTS["REPORTED_DATE"],
        "gross_receipts_cents": 1000000,
        "admissions": 100,
        "submission_channel": "API_INGEST",
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": "",  # must be supplied via overrides
        "window_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_qa_alert_payload(**overrides) -> dict:
    defaults = {
        "auditorium_id": "",  # must be supplied via overrides
        "alert_code": "SOUND_DRIFT",
        "severity": "WARNING",
    }
    defaults.update(overrides)
    return defaults


def create_tech_dispatch_payload(**overrides) -> dict:
    defaults = {
        "qa_alert_id": "",  # must be supplied via overrides
        "auditorium_id": "",
        "scheduled_visit_date": DEFAULTS["VISIT_DATE"],
        "tech_specialty": "PROJECTION",
    }
    defaults.update(overrides)
    return defaults
