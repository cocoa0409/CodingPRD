"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "USERNAME": "testuser",
    "EMAIL": "testuser@example.com",
    "PAGE_TITLE": "Test Page",
    "TOPIC_AREA": "GENERAL",
    "CONTENT_TEXT": "Some content",
    "SUMMARY": "edit summary",
    "DISPUTE_TYPE": "CONTENT",
    "REQUESTED_LEVEL": "SEMI",
    "REASON": "reason text",
    "REPORT_TYPE": "VANDALISM",
    "CAMPAIGN_NAME": "Test Campaign",
    "START_AT": "2026-09-01T00:00:00Z",
    "END_AT": "2026-12-31T23:59:59Z",
    "TARGET_AMOUNT_CENTS": 100000,
    "MESSAGE_VARIANT": "A",
    "GEO_TARGET": "GLOBAL",
    "FREQUENCY_CAP": 5,
    "PRIORITY_WEIGHT": 1,
    "DONOR_EMAIL_HASH": "hash123",
    "AMOUNT_CENTS": 1000,
    "CURRENCY": "USD",
    "PROGRAM_NAME": "Test Program",
    "FISCAL_YEAR": 2026,
    "BUDGET_CENTS": 1000000,
    "PROJECT_TITLE": "Test Project",
    "REQUESTED_CENTS": 50000,
    "REQUEST_TYPE": "TAKEDOWN",
    "REQUESTING_PARTY": "Party",
    "PERIOD_START": "2026-01-01T00:00:00Z",
    "PERIOD_END": "2026-06-30T23:59:59Z",
    "VIEWER_KEY": "viewer1",
    "COUNTRY_CODE": "US",
    "RESOLUTION_NOTES": "resolved",
    "DISCLOSURE_TEXT": "I have a COI",
    "IMPACT_SCORE": 80,
    "FEASIBILITY_SCORE": 80,
    "BUDGET_REASONABLENESS_SCORE": 80,
    "COMMUNITY_SUPPORT_SCORE": 80,
}


def create_editor_payload(**overrides) -> dict:
    defaults = {
        "username": DEFAULTS["USERNAME"],
        "email": DEFAULTS["EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_page_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["PAGE_TITLE"],
        "topic_area": DEFAULTS["TOPIC_AREA"],
    }
    defaults.update(overrides)
    return defaults


def create_revision_payload(**overrides) -> dict:
    defaults = {
        "content_text": DEFAULTS["CONTENT_TEXT"],
        "summary": DEFAULTS["SUMMARY"],
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "dispute_type": DEFAULTS["DISPUTE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_protection_request_payload(**overrides) -> dict:
    defaults = {
        "requested_level": DEFAULTS["REQUESTED_LEVEL"],
        "reason": DEFAULTS["REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(**overrides) -> dict:
    defaults = {
        "report_type": DEFAULTS["REPORT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "start_at": DEFAULTS["START_AT"],
        "end_at": DEFAULTS["END_AT"],
        "target_amount_cents": DEFAULTS["TARGET_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_banner_payload(**overrides) -> dict:
    defaults = {
        "message_variant": DEFAULTS["MESSAGE_VARIANT"],
        "geo_target": DEFAULTS["GEO_TARGET"],
        "frequency_cap": DEFAULTS["FREQUENCY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_impression_payload(**overrides) -> dict:
    defaults = {
        "viewer_key": DEFAULTS["VIEWER_KEY"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(**overrides) -> dict:
    defaults = {
        "donor_email_hash": DEFAULTS["DONOR_EMAIL_HASH"],
        "amount_cents": DEFAULTS["AMOUNT_CENTS"],
        "currency": DEFAULTS["CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "fiscal_year": DEFAULTS["FISCAL_YEAR"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_grant_application_payload(**overrides) -> dict:
    defaults = {
        "project_title": DEFAULTS["PROJECT_TITLE"],
        "requested_cents": DEFAULTS["REQUESTED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_score_payload(**overrides) -> dict:
    defaults = {
        "impact_score": DEFAULTS["IMPACT_SCORE"],
        "feasibility_score": DEFAULTS["FEASIBILITY_SCORE"],
        "budget_reasonableness_score": DEFAULTS["BUDGET_REASONABLENESS_SCORE"],
        "community_support_score": DEFAULTS["COMMUNITY_SUPPORT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_legal_request_payload(**overrides) -> dict:
    defaults = {
        "request_type": DEFAULTS["REQUEST_TYPE"],
        "requesting_party": DEFAULTS["REQUESTING_PARTY"],
    }
    defaults.update(overrides)
    return defaults


def create_transparency_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(**overrides) -> dict:
    defaults = {
        "resolution_notes": DEFAULTS["RESOLUTION_NOTES"],
    }
    defaults.update(overrides)
    return defaults


def disclose_coi_payload(**overrides) -> dict:
    defaults = {
        "disclosure_text": DEFAULTS["DISCLOSURE_TEXT"],
    }
    defaults.update(overrides)
    return defaults
