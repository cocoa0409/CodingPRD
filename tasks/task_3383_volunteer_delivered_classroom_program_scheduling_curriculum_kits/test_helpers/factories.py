"""Payload factories — one per entity, input fields only (PRD §3).

Factories accept ``**overrides`` so tests control exactly the values a claim
depends on; everything else takes a benign default.
"""
from .constants import ALL_WEEKDAYS, funding_floor_cents


def area_office_payload(**overrides) -> dict:
    defaults = {
        "name": "Metro Area Office",
        "region_code": "METRO",
        "max_districts": 5,
    }
    defaults.update(overrides)
    return defaults


def district_payload(area_office_id, **overrides) -> dict:
    defaults = {
        "area_office_id": area_office_id,
        "name": "Riverview Unified",
    }
    defaults.update(overrides)
    return defaults


def school_payload(district_id, **overrides) -> dict:
    defaults = {
        "district_id": district_id,
        "name": "Riverview Elementary",
        "grade_band_low": 1,
        "grade_band_high": 5,
        "instructional_days": list(ALL_WEEKDAYS),
    }
    defaults.update(overrides)
    return defaults


def corporate_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Corp",
        "industry": "Logistics",
    }
    defaults.update(overrides)
    return defaults


def volunteer_payload(corporate_partner_id, **overrides) -> dict:
    defaults = {
        "corporate_partner_id": corporate_partner_id,
        "full_name": "Vol One",
        "email": "vol1@acme.example",
    }
    defaults.update(overrides)
    return defaults


def program_catalog_payload(**overrides) -> dict:
    defaults = {
        "code": "JA-BIZ",
        "title": "Biz Basics",
        "grade_band_low": 3,
        "grade_band_high": 5,
        "session_count": 4,
        "minutes_per_session": 60,
        "capstone_required": False,
        "capstone_facility": "NONE",
        "min_students": 4,
        "max_students": 30,
    }
    defaults.update(overrides)
    return defaults


def partnership_agreement_payload(school_id, program_catalog_id, sponsor_partner_id, **overrides) -> dict:
    defaults = {
        "school_id": school_id,
        "program_catalog_id": program_catalog_id,
        "sponsor_partner_id": sponsor_partner_id,
        "school_year": "2026-2027",
        "funding_pledged_cents": funding_floor_cents(4),
    }
    defaults.update(overrides)
    return defaults


def delivery_payload(agreement_id, lead_volunteer_id, expected_agreement_version, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "lead_volunteer_id": lead_volunteer_id,
        "classroom_label": "Room 1",
        "teacher_email": "teacher@rv.example",
        "enrolled_count": 10,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def session_payload(delivery_id, volunteer_id, scheduled_date, **overrides) -> dict:
    defaults = {
        "delivery_id": delivery_id,
        "volunteer_id": volunteer_id,
        "scheduled_date": scheduled_date,
        "start_minutes": 540,
        "end_minutes": 600,
    }
    defaults.update(overrides)
    return defaults


def kit_inventory_payload(area_office_id, program_catalog_id, **overrides) -> dict:
    defaults = {
        "area_office_id": area_office_id,
        "program_catalog_id": program_catalog_id,
    }
    defaults.update(overrides)
    return defaults


def capstone_event_payload(delivery_id, **overrides) -> dict:
    defaults = {
        "delivery_id": delivery_id,
        "facility": "SIMULATED_TOWN",
        "event_date": "2026-10-13",
        "start_minutes": 540,
        "end_minutes": 720,
        "rotation_slot_count": 2,
    }
    defaults.update(overrides)
    return defaults


def students_payload(delivery_id, names=("Stu A", "Stu B")) -> dict:
    return {
        "delivery_id": delivery_id,
        "students": [
            {"full_name": n, "external_ref": f"REF-{i + 1}"} for i, n in enumerate(names)
        ],
    }
