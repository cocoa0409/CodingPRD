"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_association_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "association_code": f"ASC-{n:05d}",
        "name": f"Test Association {n}",
        "membership_dues_cents": 120000,
        "late_fee_tier1_cents": 5000,
        "late_fee_tier2_cents": 15000,
        "sanction_credit_cap_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "member_nr": f"M-{n:05d}",
        "full_name": f"Test Member {n}",
    }
    defaults.update(overrides)
    return defaults


def create_office_payload(broker_member_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "office_code": f"OFF-{n:05d}",
        "broker_member_id": broker_member_id,
    }
    defaults.update(overrides)
    return defaults


def create_dues_period_payload(**overrides) -> dict:
    defaults = {
        "year": 2027,
        "period_start_date": "2026-12-01T00:00:00Z",
        "due_date": "2027-01-31T00:00:00Z",
        "grace_end_date": "2027-03-02T00:00:00Z",
        "amount_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(listing_member_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "listing_member_id": listing_member_id,
        "mls_number": f"MLS-{n:05d}",
        "property_address": f"{n} Test Ave",
        "list_price_cents": 20000000,
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(member_id, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "rule_code": "INACCURACY",
    }
    defaults.update(overrides)
    return defaults


def create_fine_schedule_payload(**overrides) -> dict:
    defaults = {
        "rule_code": "INACCURACY",
        "fine_amount_cents": 30000,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ethics_case_payload(respondent_member_id, **overrides) -> dict:
    defaults = {
        "respondent_member_id": respondent_member_id,
        "article_code": "A16",
    }
    defaults.update(overrides)
    return defaults


def create_arbitration_case_payload(respondent_member_id, listing_id, **overrides) -> dict:
    defaults = {
        "respondent_member_id": respondent_member_id,
        "listing_id": listing_id,
        "claim_amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_data_license_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "licensee_name": f"Portal-{n:05d}",
        "scope": "IDX",
        "display_ruleset_version": 1,
        "listing_field_allowlist": ["property_address"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_revision_payload(expected_association_version, **overrides) -> dict:
    n = _seq()
    defaults = {
        "revision_code": f"REV-{n:05d}",
        "effective_at": "2026-09-01T00:00:00Z",
        "comp_display_mode": "COMP_DISPLAY_ON",
        "expected_association_version": expected_association_version,
    }
    defaults.update(overrides)
    return defaults
