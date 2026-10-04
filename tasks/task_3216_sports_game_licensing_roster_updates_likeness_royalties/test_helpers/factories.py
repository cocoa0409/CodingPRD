"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "TERM_START_ON": "2026-01-01",
    "TERM_END_ON": "2026-12-31",
    "SPORT_CATEGORY": "AMFOOT_PRO",
    "ROYALTY_RATE_BPS": 1000,
    "AUDIT_WINDOW_DAYS": 90,
    "SEASON_OPENS_ON": "2026-08-01",
    "SEASON_CLOSES_ON": "2027-02-01",
    "DROP_START": "2026-08-15T00:00:00Z",
    "DROP_END": "2026-12-15T00:00:00Z",
    "REG_OPEN": "2026-08-01T00:00:00Z",
    "REG_CLOSE": "2026-12-01T00:00:00Z",
    "PERIOD_START_ON": "2026-08-01",
    "PERIOD_END_ON": "2026-08-31",
}


def create_agreement_payload(**overrides) -> dict:
    payload = {
        "licensor_type": "LEAGUE",
        "licensor_name": "Test League",
        "exclusivity_scope": "NONE",
        "sport_category": DEFAULTS["SPORT_CATEGORY"],
        "term_start_on": DEFAULTS["TERM_START_ON"],
        "term_end_on": DEFAULTS["TERM_END_ON"],
        "royalty_model": "PERCENT_OF_NET",
        "royalty_rate_bps": DEFAULTS["ROYALTY_RATE_BPS"],
        "minimum_guarantee_cents": 0,
        "mg_recoupable": False,
        "audit_window_days": DEFAULTS["AUDIT_WINDOW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_athlete_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Athlete",
        "sport_category": DEFAULTS["SPORT_CATEGORY"],
        "athlete_class": "ACTIVE_PRO",
        "college_opt_in": False,
    }
    payload.update(overrides)
    return payload


def create_likeness_grant_payload(athlete_id, agreement_id, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "agreement_id": agreement_id,
        "grant_kind": "GROUP_PA",
        "term_start_on": DEFAULTS["TERM_START_ON"],
        "term_end_on": DEFAULTS["TERM_END_ON"],
        "royalty_share_bps": 100,
        "payment_destination": "test-escrow",
    }
    payload.update(overrides)
    return payload


def create_season_payload(agreement_id, **overrides) -> dict:
    payload = {
        "title_code": "PIGSKIN26",
        "sport_category": DEFAULTS["SPORT_CATEGORY"],
        "season_label": "2026-27",
        "agreement_id": agreement_id,
        "season_opens_on": DEFAULTS["SEASON_OPENS_ON"],
        "season_closes_on": DEFAULTS["SEASON_CLOSES_ON"],
    }
    payload.update(overrides)
    return payload


def create_roster_batch_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "batch_label": "WEEK_05_UPDATE",
        "submitted_by": "op-1",
    }
    payload.update(overrides)
    return payload


def create_roster_entry_payload(athlete_id, **overrides) -> dict:
    payload = {
        "athlete_id": athlete_id,
        "entry_kind": "ADD",
        "overall_rating": 80,
    }
    payload.update(overrides)
    return payload


def create_content_drop_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "drop_kind": "VANITY",
        "drop_label": "Test Drop",
        "price_vc": 100,
        "scheduled_start_at": DEFAULTS["DROP_START"],
        "scheduled_end_at": DEFAULTS["DROP_END"],
    }
    payload.update(overrides)
    return payload


def create_wallet_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "owner_tag": "test-player",
    }
    payload.update(overrides)
    return payload


def create_ledger_entry_payload(**overrides) -> dict:
    payload = {
        "direction": "CREDIT",
        "amount_vc": 1000,
        "reason_code": "GRANT",
    }
    payload.update(overrides)
    return payload


def create_tournament_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "program_label": "LEAGUE_CUP_Q3",
        "league_sanctioned": True,
        "entry_fee_vc": 0,
        "registration_opens_at": DEFAULTS["REG_OPEN"],
        "registration_closes_at": DEFAULTS["REG_CLOSE"],
    }
    payload.update(overrides)
    return payload


def create_prize_row_payload(**overrides) -> dict:
    payload = {
        "placement": 1,
        "share_bps": 10000,
    }
    payload.update(overrides)
    return payload


def create_audio_asset_payload(**overrides) -> dict:
    payload = {
        "asset_kind": "MUSIC_TRACK",
        "asset_title": "Test Anthem",
        "rights_holder": "Test Label",
    }
    payload.update(overrides)
    return payload


def create_audio_license_payload(asset_id, **overrides) -> dict:
    payload = {
        "asset_id": asset_id,
        "term_start_on": DEFAULTS["TERM_START_ON"],
        "term_end_on": DEFAULTS["TERM_END_ON"],
        "usage_scope": "ALL",
        "region_scope": "GLOBAL",
    }
    payload.update(overrides)
    return payload


def create_edition_payload(season_id, **overrides) -> dict:
    payload = {
        "season_id": season_id,
        "region_code": "DE",
        "censorship_flags": ["NO_BLOOD_OVERLAYS"],
        "embargo_until_on": "2026-09-01",
    }
    payload.update(overrides)
    return payload


def create_royalty_statement_payload(agreement_id, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "period_start_on": DEFAULTS["PERIOD_START_ON"],
        "period_end_on": DEFAULTS["PERIOD_END_ON"],
        "gross_sales_cents": 500000,
        "returns_cents": 0,
        "pending_sales_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_audit_case_payload(agreement_id, statement_id, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "statement_id": statement_id,
        "opened_by_role": "LEAGUE_AUDITOR",
    }
    payload.update(overrides)
    return payload
