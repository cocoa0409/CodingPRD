"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from . import constants

_COUNTER = itertools.count(1)


def _n() -> int:
    return next(_COUNTER)


def create_program_payload(**overrides) -> dict:
    """Required program inputs plus the three defaulted settings (PRD §3.1)."""
    defaults = dict(constants.DEFAULT_PROGRAM)
    defaults["name"] = f"VBS Program {_n()}"
    defaults.update(overrides)
    return defaults


def create_classroom_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "name": f"Classroom {_n()}",
        "age_min": 4,
        "age_max": 6,
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "household_name": f"Household {n}",
        "primary_contact_name": f"Contact {n}",
        "email": f"family{n}@example.com",
        "phone": f"555-{1000 + (n % 9000)}",
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(family_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "family_id": family_id,
        "first_name": f"Child{n}",
        "last_name": "Test",
        "birth_date": constants.DEFAULT_CHILD_BIRTH_DATE,
        "grade_completed": constants.DEFAULT_CHILD_GRADE,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(child_id, classroom_id, **overrides) -> dict:
    defaults = {"child_id": child_id, "classroom_id": classroom_id}
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(program_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "program_id": program_id,
        "full_name": f"Volunteer {n}",
        "email": f"volunteer{n}@example.com",
        "phone": f"555-{2000 + (n % 9000)}",
        "birth_date": constants.ADULT_BIRTH_DATE_1,
    }
    defaults.update(overrides)
    return defaults


def create_screening_check_payload(volunteer_id, check_type, **overrides) -> dict:
    defaults = {"volunteer_id": volunteer_id, "check_type": check_type}
    defaults.update(overrides)
    return defaults


def create_role_assignment_payload(volunteer_id, classroom_id, role, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "classroom_id": classroom_id,
        "role": role,
    }
    defaults.update(overrides)
    return defaults


def create_accommodation_plan_payload(child_id, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "severity": "FOOD_ALLERGY",
        "allergens": ["PEANUT"],
        "instructions": "No peanut snacks; epinephrine kit in the red bag",
    }
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(program_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "program_id": program_id,
        "kit_name": f"Kit {n}",
        "vendor": "Cokesbury",
        "quantity": 4,
        "unit_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_supply_item_payload(program_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "program_id": program_id,
        "name": f"Item {n}",
        "category": "CRAFT",
        "unit": "pack",
        "quantity_on_hand": 5,
    }
    defaults.update(overrides)
    return defaults


def create_supply_distribution_payload(
    supply_item_id, classroom_id, program_day_id, **overrides
) -> dict:
    defaults = {
        "supply_item_id": supply_item_id,
        "classroom_id": classroom_id,
        "program_day_id": program_day_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_program_day_payload(program_id, date, **overrides) -> dict:
    defaults = {"program_id": program_id, "date": date}
    defaults.update(overrides)
    return defaults


def create_message_payload(program_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "program_id": program_id,
        "subject": f"Message {n}",
        "body": "See you on Monday morning.",
        "audience": "ALL_FAMILIES",
    }
    defaults.update(overrides)
    return defaults
