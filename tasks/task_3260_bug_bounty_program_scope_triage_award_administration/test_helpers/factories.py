"""Payload factories — one per entity, input fields only."""
import itertools

_handle_counter = itertools.count(1)

DEFAULTS = {
    "PROGRAM_NAME": "Test Program",
    "BOUNTY_POOL_CENTS": 5_000_000,
    "MIN_REPUTATION": 0,
    "RESPONSE_SLA_HOURS": 72,
    "RESOLUTION_SLA_DAYS": 30,
    "DISCLOSURE_WINDOW_DAYS": 30,
    "ASSET_NAME": "Core API",
    "ASSET_IDENTIFIER": "api.example.com",
    "CRITICALITY": "CRITICAL",
    "SCOPE_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "COUNTRY_CODE": "US",
    "REPORT_TITLE": "XSS in search field",
    "REPORT_DESCRIPTION": "Steps to reproduce and impact narrative.",
    "VULNERABILITY_CLASS": "XSS",
    "EXTERNAL_REF": "ENG-1",
    "PROPOSED_PUBLISH_AT": "2026-10-01T00:00:00Z",
}


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "bounty_pool_cents": DEFAULTS["BOUNTY_POOL_CENTS"],
        "min_reputation": DEFAULTS["MIN_REPUTATION"],
        "response_sla_hours": DEFAULTS["RESPONSE_SLA_HOURS"],
        "resolution_sla_days": DEFAULTS["RESOLUTION_SLA_DAYS"],
        "disclosure_window_days": DEFAULTS["DISCLOSURE_WINDOW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": DEFAULTS["ASSET_NAME"],
        "asset_identifier": DEFAULTS["ASSET_IDENTIFIER"],
        "criticality": DEFAULTS["CRITICALITY"],
    }
    defaults.update(overrides)
    return defaults


def create_scope_version_payload(program_id, in_scope_asset_ids, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "effective_from": DEFAULTS["SCOPE_EFFECTIVE_FROM"],
        "in_scope_asset_ids": list(in_scope_asset_ids),
    }
    defaults.update(overrides)
    return defaults


def create_researcher_payload(**overrides) -> dict:
    n = next(_handle_counter)
    defaults = {
        "handle": f"researcher-{n}",
        "email": f"researcher-{n}@example.com",
        "country_code": DEFAULTS["COUNTRY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(program_id, researcher_id, **overrides) -> dict:
    defaults = {"program_id": program_id, "researcher_id": researcher_id}
    defaults.update(overrides)
    return defaults


def create_report_payload(program_id, asset_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "asset_id": asset_id,
        "title": DEFAULTS["REPORT_TITLE"],
        "description": DEFAULTS["REPORT_DESCRIPTION"],
        "vulnerability_class": DEFAULTS["VULNERABILITY_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(report_id, award_type, **overrides) -> dict:
    defaults = {"report_id": report_id, "award_type": award_type}
    defaults.update(overrides)
    return defaults


def create_disclosure_request_payload(report_id, **overrides) -> dict:
    defaults = {
        "report_id": report_id,
        "proposed_publish_at": DEFAULTS["PROPOSED_PUBLISH_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_remediation_ticket_payload(report_id, **overrides) -> dict:
    defaults = {"report_id": report_id, "external_ref": DEFAULTS["EXTERNAL_REF"]}
    defaults.update(overrides)
    return defaults
