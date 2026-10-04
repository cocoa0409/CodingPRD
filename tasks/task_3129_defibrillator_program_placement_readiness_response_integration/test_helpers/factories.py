"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CAMPUS_NAME": "Test Campus",
    "JURISDICTION_CODE": "CA",
    "JURISDICTION_REGISTRATION_NUMBER": "CA-PAD-000",
    "MEDICAL_DIRECTOR_ID": "md-tbd",
    "RESPONSE_TIME_TARGET_SECONDS": 240,
    "ZONE_CODE": "Z-1",
    "FLOOR_AREA_SQM": 1000,
    "AVG_WALK_SPEED_MPS": 1.5,
    "MODEL_CODE": "AED-TEST",
    "MANUFACTURER": "ZOLL",
    "PAD_SHELF_LIFE_MONTHS": 24,
    "BATTERY_SHELF_LIFE_MONTHS": 48,
    "LOCATION_LABEL": "Lobby Cabinet",
    "LOT_CODE": "LOT-1",
    "LOT_MANUFACTURER_EXPIRES_AT": "2030-01-01T00:00:00Z",
    "QUANTITY_RECEIVED": 5,
    "FULL_NAME": "Test Person",
    "SESSION_CAPACITY": 5,
    "CERT_MONTHS_GRANTED": 24,
}


def create_campus_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CAMPUS_NAME"],
        "jurisdiction_code": DEFAULTS["JURISDICTION_CODE"],
        "jurisdiction_registration_number": DEFAULTS["JURISDICTION_REGISTRATION_NUMBER"],
        "medical_director_id": DEFAULTS["MEDICAL_DIRECTOR_ID"],
        "response_time_target_seconds": DEFAULTS["RESPONSE_TIME_TARGET_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(campus_id: str, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "zone_code": DEFAULTS["ZONE_CODE"],
        "floor_area_sqm": DEFAULTS["FLOOR_AREA_SQM"],
        "avg_walk_speed_mps": DEFAULTS["AVG_WALK_SPEED_MPS"],
        "requires_elevator": False,
        "elevator_delay_seconds": 0,
    }
    defaults.update(overrides)
    return defaults


def create_device_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": DEFAULTS["MODEL_CODE"],
        "manufacturer": DEFAULTS["MANUFACTURER"],
        "pad_shelf_life_months": DEFAULTS["PAD_SHELF_LIFE_MONTHS"],
        "battery_shelf_life_months": DEFAULTS["BATTERY_SHELF_LIFE_MONTHS"],
        "prescription_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_cabinet_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "location_label": DEFAULTS["LOCATION_LABEL"],
        "centroid_x_m": 0.0,
        "centroid_y_m": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(campus_id: str, device_model_id: str, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "device_model_id": device_model_id,
        "serial_number": "SN-1",
    }
    defaults.update(overrides)
    return defaults


def create_consumable_lot_payload(campus_id: str, device_model_id: str, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "device_model_id": device_model_id,
        "kind": "PAD",
        "lot_code": DEFAULTS["LOT_CODE"],
        "manufacturer_expires_at": DEFAULTS["LOT_MANUFACTURER_EXPIRES_AT"],
        "quantity_received": DEFAULTS["QUANTITY_RECEIVED"],
    }
    defaults.update(overrides)
    return defaults


def create_install_payload(device_id: str, consumable_lot_id: str,
                           expected_device_version: int, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "consumable_lot_id": consumable_lot_id,
        "expected_device_version": expected_device_version,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(device_id: str, inspector_id: str, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "inspector_id": inspector_id,
        "scheduled_for": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_submit_payload(**overrides) -> dict:
    defaults = {
        "checklist_items": [
            {"item_code": "PADS_OK", "result": "PASS"},
            {"item_code": "BATT_OK", "result": "PASS"},
            {"item_code": "CABINET_OK", "result": "PASS"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_self_test_report_payload(device_id: str, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "reported_at": "2026-09-01T01:00:00Z",
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_responder_payload(campus_id: str, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "full_name": DEFAULTS["FULL_NAME"],
        "badge_number": "B-1",
        "responder_role": "LAY_RESPONDER",
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(campus_id: str, instructor_id: str, **overrides) -> dict:
    defaults = {
        "campus_id": campus_id,
        "instructor_id": instructor_id,
        "starts_at": "2026-10-01T00:00:00Z",
        "ends_at": "2026-10-01T04:00:00Z",
        "capacity": DEFAULTS["SESSION_CAPACITY"],
        "certification_months_granted": DEFAULTS["CERT_MONTHS_GRANTED"],
    }
    defaults.update(overrides)
    return defaults


def create_case_review_payload(emergency_event_id: str, reviewer_id: str, **overrides) -> dict:
    defaults = {
        "emergency_event_id": emergency_event_id,
        "reviewer_id": reviewer_id,
        "hospital_reviewer_name": "Dr Reviewer",
        "device_data_retrieved": True,
        "outcome_code": "SURVIVED_TO_DISCHARGE",
        "notes": "n",
    }
    defaults.update(overrides)
    return defaults


def create_resolve_event_payload(**overrides) -> dict:
    defaults = {
        "hospital_code": "H-1",
        "patient_transported": True,
        "pads_consumed": False,
    }
    defaults.update(overrides)
    return defaults


def create_receive_replenishment_payload(**overrides) -> dict:
    defaults = {
        "lot_code": "LOT-NEW-1",
        "manufacturer_expires_at": "2031-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
