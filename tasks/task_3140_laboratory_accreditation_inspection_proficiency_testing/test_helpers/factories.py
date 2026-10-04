"""Payload factories — one per entity, input fields only."""

import itertools

_counter = itertools.count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def create_laboratory_payload(**overrides) -> dict:
    defaults = {
        "name": _next("Test Laboratory"),
        "clia_number": f"45D{9000000 + next(_counter)}",
    }
    defaults.update(overrides)
    return defaults


def create_inspector_profile_payload(**overrides) -> dict:
    affiliated_laboratory_id = overrides.pop("affiliated_laboratory_id", None)
    defaults = {
        "full_name": _next("Inspector"),
        "affiliated_laboratory_id": affiliated_laboratory_id,
        "specialties": ["CHEMISTRY"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    laboratory_id = overrides.pop("laboratory_id", None)
    defaults = {
        "laboratory_id": laboratory_id,
        "discipline": "CHEMISTRY",
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(**overrides) -> dict:
    enrollment_id = overrides.pop("enrollment_id", None)
    defaults = {
        "enrollment_id": enrollment_id,
        "section_name": _next("Bench"),
        "critical_testing": False,
    }
    defaults.update(overrides)
    return defaults


def create_checklist_edition_payload(**overrides) -> dict:
    defaults = {
        "checklist_code": "CHM",
        "checklist_version": _next("2026-v"),
    }
    defaults.update(overrides)
    return defaults


def create_pt_subscription_payload(**overrides) -> dict:
    enrollment_id = overrides.pop("enrollment_id", None)
    defaults = {
        "enrollment_id": enrollment_id,
        "analytes": [{"name": "glucose", "critical": True}],
    }
    defaults.update(overrides)
    return defaults


def create_pt_shipment_payload(**overrides) -> dict:
    subscription_id = overrides.pop("subscription_id", None)
    defaults = {
        "subscription_id": subscription_id,
        "event_code": _next("C-2026-"),
    }
    defaults.update(overrides)
    return defaults


def create_pt_result_payload(**overrides) -> dict:
    shipment_id = overrides.pop("shipment_id", None)
    defaults = {
        "shipment_id": shipment_id,
        "collected_at": "2026-09-02T00:00:00Z",
        "analyte_scores": [{"name": "glucose", "score": 95}],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_cycle_payload(**overrides) -> dict:
    laboratory_id = overrides.pop("laboratory_id", None)
    defaults = {
        "laboratory_id": laboratory_id,
        "scheduled_start": "2026-09-10T00:00:00Z",
        "scheduled_end": "2026-09-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_team_assignment_payload(**overrides) -> dict:
    inspection_cycle_id = overrides.pop("inspection_cycle_id", None)
    inspector_id = overrides.pop("inspector_id", None)
    defaults = {
        "inspection_cycle_id": inspection_cycle_id,
        "inspector_id": inspector_id,
        "role_in_team": "LEAD",
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    inspection_cycle_id = overrides.pop("inspection_cycle_id", None)
    section_id = overrides.pop("section_id", None)
    defaults = {
        "inspection_cycle_id": inspection_cycle_id,
        "section_id": section_id,
        "checklist_item_code": "CHM.10000",
        "deficiency_level": "LEVEL_1",
    }
    defaults.update(overrides)
    return defaults


def create_personnel_record_payload(**overrides) -> dict:
    enrollment_id = overrides.pop("enrollment_id", None)
    defaults = {
        "enrollment_id": enrollment_id,
        "person_name": _next("Personnel"),
        "personnel_role": "TESTING_PERSONNEL",
    }
    defaults.update(overrides)
    return defaults


def create_competency_assessment_payload(**overrides) -> dict:
    personnel_id = overrides.pop("personnel_id", None)
    defaults = {
        "personnel_id": personnel_id,
        "assessed_at": "2026-09-05T00:00:00Z",
        "element_scores": [90, 90, 90, 90, 90, 90],
    }
    defaults.update(overrides)
    return defaults


def create_method_validation_payload(**overrides) -> dict:
    enrollment_id = overrides.pop("enrollment_id", None)
    defaults = {
        "enrollment_id": enrollment_id,
        "method_name": _next("Method"),
        "instrument_name": _next("Analyzer"),
        "correlation_r_squared": 0.99,
        "precision_cv_pct": 2.0,
    }
    defaults.update(overrides)
    return defaults
