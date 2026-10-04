"""Payload factories — one per creatable resource, input fields only.
System-managed fields (id, version, computed ledgers) are never supplied."""
from .constants import (
    PROGRAM_END_ISO,
    PROGRAM_START_ISO,
    STANDARD_FIXTURE,
)


def create_member_org_payload(**overrides) -> dict:
    # costing_method deliberately omitted by default: the PRD default is STANDARD.
    defaults = {
        "name": "Test Org",
        "reserve_floor_cents": 0,
        "diversion_floor_bps": 7500,
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(member_org_id, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "region_code": "PNW-N",
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_donation_site_payload(member_org_id, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "name": "Test Site",
        "site_type": "ADC",
    }
    defaults.update(overrides)
    return defaults


def create_donation_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "donor_name": "Test Donor",
        "item_count_declared": 1,
    }
    defaults.update(overrides)
    return defaults


def sort_item_descriptor(category="TEXTILES", condition_grade="A",
                         estimated_value_cents=100, weight_lbs=1.0) -> dict:
    """One item descriptor inside a sort payload."""
    return {
        "category": category,
        "condition_grade": condition_grade,
        "estimated_value_cents": estimated_value_cents,
        "weight_lbs": weight_lbs,
    }


def create_sort_payload(items) -> dict:
    return {"items": items}


def create_production_standard_payload(member_org_id, expected_member_org_version,
                                       **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "expected_member_org_version": expected_member_org_version,
    }
    defaults.update(STANDARD_FIXTURE)
    defaults.update(overrides)
    return defaults


def create_processing_run_payload(site_id, production_standard_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "production_standard_id": production_standard_id,
    }
    defaults.update(overrides)
    return defaults


def close_run_payload(item_count_processed=120, unsalable_count=0,
                      labor_minutes=120, labor_cost_cents=3600, **overrides) -> dict:
    defaults = {
        "item_count_processed": item_count_processed,
        "unsalable_count": unsalable_count,
        "labor_minutes": labor_minutes,
        "labor_cost_cents": labor_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_salvage_lot_payload(member_org_id, channel, item_ids, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "channel": channel,
        "item_ids": item_ids,
    }
    defaults.update(overrides)
    return defaults


def add_items_payload(item_ids) -> dict:
    return {"item_ids": item_ids}


def create_mission_program_payload(member_org_id, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "name": "Test Program",
        "program_type": "JOB_TRAINING",
        "start_date": PROGRAM_START_ISO,
        "end_date": PROGRAM_END_ISO,
        "funding_goal_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_funding_allocation_payload(mission_program_id, amount_cents,
                                      expected_member_org_version, **overrides) -> dict:
    defaults = {
        "mission_program_id": mission_program_id,
        "amount_cents": amount_cents,
        "expected_member_org_version": expected_member_org_version,
    }
    defaults.update(overrides)
    return defaults


def milestone_payload(description="M1", target_date="2026-12-01T00:00:00Z",
                      min_headcount=10, payout_cents=10000, **overrides) -> dict:
    defaults = {
        "description": description,
        "target_date": target_date,
        "min_headcount": min_headcount,
        "payout_cents": payout_cents,
    }
    defaults.update(overrides)
    return defaults


def create_workforce_contract_payload(member_org_id, milestones, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "funding_agency": "DOL",
        "start_date": "2026-03-01T00:00:00Z",
        "end_date": "2026-12-31T00:00:00Z",
        "contract_value_cents": 200000,
        "enrolled_headcount": 50,
        "milestones": milestones,
    }
    defaults.update(overrides)
    return defaults


def create_disposal_ticket_payload(member_org_id, material, weight_lbs, **overrides) -> dict:
    defaults = {
        "member_org_id": member_org_id,
        "material": material,
        "weight_lbs": weight_lbs,
    }
    defaults.update(overrides)
    return defaults
