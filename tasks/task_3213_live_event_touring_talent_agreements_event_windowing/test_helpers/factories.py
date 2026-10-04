"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "RING_NAME": "Test Talent",
    "LEGAL_NAME": "Test Legal",
    "CONTRACTOR_STATUS": "INDEPENDENT_CONTRACTOR",
    "START_DATE": "2026-01-01",
    "END_DATE": "2027-01-01",
    "DOWNSIDE_GUARANTEE_CENTS": 100000,
    "ROYALTY_RATE_BP": 2000,
    "ARENA_NAME": "Test Arena",
    "ARENA_CITY": "Orlando",
    "COUNTRY_CODE": "US",
    "CAPACITY": 1000,
    "MERCH_BOOTHS": 1,
    "TIMEZONE": "America/New_York",
    "EVENT_DATE": "2026-09-05",
    "START_TIME": "19:00",
    "END_TIME": "21:00",
    "SEGMENT_LABEL": "MATCH_1",
    "STORYLINE_TITLE": "Test Feud",
    "PARTNER_NAME": "TestCo",
    "PARTNER_CODE": "TC",
    "TERRITORY_CODE": "US",
    "PERIOD_START": "2026-09-01",
    "PERIOD_END": "2026-10-01",
}


def create_talent_payload(**overrides) -> dict:
    defaults = {
        "ring_name": DEFAULTS["RING_NAME"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "contractor_status": DEFAULTS["CONTRACTOR_STATUS"],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(talent_id, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "downside_guarantee_cents": DEFAULTS["DOWNSIDE_GUARANTEE_CENTS"],
        "royalty_rate_bp": DEFAULTS["ROYALTY_RATE_BP"],
        "likeness_rights_granted": False,
        "min_appearances_per_quarter": 0,
    }
    defaults.update(overrides)
    return defaults


def create_arena_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ARENA_NAME"],
        "city": DEFAULTS["ARENA_CITY"],
        "country_code": DEFAULTS["COUNTRY_CODE"],
        "capacity": DEFAULTS["CAPACITY"],
        "merch_booths": DEFAULTS["MERCH_BOOTHS"],
        "timezone": DEFAULTS["TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_broadcast_anchor_payload(**overrides) -> dict:
    defaults = {
        "name": "Weekly Show",
        "weekly_day_of_week": 1,
        "territory_code": DEFAULTS["TERRITORY_CODE"],
        "must_have_event_each_week": True,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(arena_id, **overrides) -> dict:
    defaults = {
        "name": "Test Event",
        "event_type": "HOUSE_SHOW",
        "arena_id": arena_id,
        "event_date": DEFAULTS["EVENT_DATE"],
        "start_time": DEFAULTS["START_TIME"],
        "end_time": DEFAULTS["END_TIME"],
        "tour_country_code": DEFAULTS["COUNTRY_CODE"],
        "roster_min_main": 0,
        "roster_min_total": 0,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(event_id, talent_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "talent_id": talent_id,
        "segment_label": DEFAULTS["SEGMENT_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def create_storyline_payload(**overrides) -> dict:
    defaults = {"title": DEFAULTS["STORYLINE_TITLE"]}
    defaults.update(overrides)
    return defaults


def create_chapter_payload(storyline_id, event_id, **overrides) -> dict:
    defaults = {"storyline_id": storyline_id, "event_id": event_id}
    defaults.update(overrides)
    return defaults


def create_streaming_partner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PARTNER_NAME"],
        "partner_code": DEFAULTS["PARTNER_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_territory_right_payload(partner_id, **overrides) -> dict:
    defaults = {
        "partner_id": partner_id,
        "territory_code": DEFAULTS["TERRITORY_CODE"],
        "window_start_date": "2026-01-01",
        "window_end_date": "2027-01-01",
        "exclusive": False,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_window_payload(event_id, partner_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "partner_id": partner_id,
        "territory_code": DEFAULTS["TERRITORY_CODE"],
        "window_type": "LIVE",
        "opens_at": "2026-09-20T23:30:00Z",
        "closes_at": "2026-09-21T04:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_merch_sale_payload(event_id, talent_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "talent_id": talent_id,
        "quantity": 1,
        "unit_price_cents": 2500,
        "sold_at": "2026-09-05T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_royalty_statement_payload(talent_id, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
        "basis_mode": "PROVISIONAL",
    }
    defaults.update(overrides)
    return defaults


def create_medical_case_payload(talent_id, **overrides) -> dict:
    defaults = {"talent_id": talent_id, "severity": "MINOR"}
    defaults.update(overrides)
    return defaults


def create_medical_evaluation_payload(evaluator_id, **overrides) -> dict:
    defaults = {
        "evaluator_id": evaluator_id,
        "findings": "clinical findings",
        "recommends_clearance": True,
    }
    defaults.update(overrides)
    return defaults


def create_medical_clearance_payload(cleared_by, **overrides) -> dict:
    defaults = {"cleared_by": cleared_by}
    defaults.update(overrides)
    return defaults


def create_visa_case_payload(talent_id, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "country_code": "JP",
        "required_by_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults
