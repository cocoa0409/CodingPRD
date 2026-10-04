"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS, CLOCK_STARTUP_DEFAULT


def create_ehr_implementation_payload(**overrides) -> dict:
    """Input fields: program_name, vendor_release, go_live_target_utc."""
    payload = {
        "program_name": TEST_DEFAULTS["PROGRAM_NAME"],
        "vendor_release": TEST_DEFAULTS["VENDOR_RELEASE"],
        "go_live_target_utc": TEST_DEFAULTS["GO_LIVE_TARGET_UTC"],
    }
    payload.update(overrides)
    return payload


def create_facility_payload(**overrides) -> dict:
    """Input fields: name, facility_type, bed_count, rollout_wave, conversion_scope."""
    payload = {
        "name": TEST_DEFAULTS["FACILITY_NAME"],
        "facility_type": TEST_DEFAULTS["FACILITY_TYPE"],
        "bed_count": TEST_DEFAULTS["BED_COUNT"],
        "rollout_wave": TEST_DEFAULTS["ROLLOUT_WAVE"],
        "conversion_scope": TEST_DEFAULTS["CONVERSION_SCOPE"],
    }
    payload.update(overrides)
    return payload


def create_department_payload(**overrides) -> dict:
    """Input fields: department_code, application_scope, required_staff_count."""
    payload = {
        "department_code": TEST_DEFAULTS["DEPARTMENT_CODE"],
        "application_scope": list(TEST_DEFAULTS["APPLICATION_SCOPE"]),
        "required_staff_count": TEST_DEFAULTS["REQUIRED_STAFF_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_build_item_payload(**overrides) -> dict:
    """Input fields: application_code, build_classification, customization_depth,
    local_custom_fields."""
    payload = {
        "application_code": TEST_DEFAULTS["APPLICATION_CODE"],
        "build_classification": TEST_DEFAULTS["BUILD_CLASSIFICATION"],
        "customization_depth": TEST_DEFAULTS["CUSTOMIZATION_DEPTH"],
        "local_custom_fields": list(TEST_DEFAULTS["LOCAL_CUSTOM_FIELDS"]),
    }
    payload.update(overrides)
    return payload


def create_staff_payload(primary_facility_id, department_id, **overrides) -> dict:
    """Input fields: full_name, staff_type, primary_facility_id, department_id,
    preceptor_staff_id (optional), hired_on."""
    payload = {
        "full_name": "Test Staffer",
        "staff_type": "NURSE",
        "primary_facility_id": primary_facility_id,
        "department_id": department_id,
        "hired_on": "2026-01-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_training_assignment_payload(**overrides) -> dict:
    """Input fields: curriculum_code, application_code, required_hours, due_utc."""
    payload = {
        "curriculum_code": "CLN100",
        "application_code": "CLN",
        "required_hours": 40,
        "due_utc": TEST_DEFAULTS["DUE_UTC"],
    }
    payload.update(overrides)
    return payload


def create_credentialed_trainer_payload(expected_staff_version, **overrides) -> dict:
    """Input fields: application_code, certification_level, observation_hours,
    expected_staff_version."""
    payload = {
        "application_code": "CLN",
        "certification_level": "STANDARD",
        "observation_hours": 8,
        "expected_staff_version": expected_staff_version,
    }
    payload.update(overrides)
    return payload


def create_proficiency_exam_payload(proctored_by_trainer_id, **overrides) -> dict:
    """Input fields: application_code, proctored_by_trainer_id."""
    payload = {
        "application_code": "CLN",
        "proctored_by_trainer_id": proctored_by_trainer_id,
    }
    payload.update(overrides)
    return payload


def create_test_scenario_payload(**overrides) -> dict:
    """Input fields: scenario_class, step_count."""
    payload = {
        "scenario_class": TEST_DEFAULTS["SCENARIO_CLASS"],
        "step_count": TEST_DEFAULTS["STEP_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_defect_payload(**overrides) -> dict:
    """Input fields: defect_code, severity."""
    payload = {
        "defect_code": "LBL-9001",
        "severity": "SEV1",
    }
    payload.update(overrides)
    return payload


def create_conversion_batch_payload(expected_facility_version, **overrides) -> dict:
    """Input fields: payload_class, attempt_epoch, source_count, reconciled_count,
    expected_facility_version."""
    payload = {
        "payload_class": "PATIENT_DEMOGRAPHICS",
        "attempt_epoch": 0,
        "source_count": 1000,
        "reconciled_count": 990,
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def create_patient_order_payload(**overrides) -> dict:
    """Input fields: patient_mrn, order_type, encounter_utc, legacy_charge_cents."""
    payload = {
        "patient_mrn": "MRN-4001",
        "order_type": "LAB",
        "encounter_utc": "2026-08-25T00:00:00Z",
        "legacy_charge_cents": 10000,
    }
    payload.update(overrides)
    return payload


def create_interface_channel_payload(**overrides) -> dict:
    """Input fields: channel_type, external_system, message_format,
    throughput_per_hour, max_latency_minutes."""
    payload = {
        "channel_type": "LAB",
        "external_system": "Sysmex",
        "message_format": "HL7_V2",
        "throughput_per_hour": 500,
        "max_latency_minutes": 5,
    }
    payload.update(overrides)
    return payload


def create_interface_message_payload(**overrides) -> dict:
    """Input fields: message_code, direction, sent_utc."""
    payload = {
        "message_code": "ORU_R01",
        "direction": "INBOUND",
        "sent_utc": CLOCK_STARTUP_DEFAULT,
    }
    payload.update(overrides)
    return payload


def create_cutover_task_payload(**overrides) -> dict:
    """Input fields: task_class, sequence_index, planned_start_utc, planned_end_utc."""
    payload = {
        "task_class": "DOWNTIME_PREP",
        "sequence_index": 1,
        "planned_start_utc": "2026-11-30T22:00:00Z",
        "planned_end_utc": "2026-11-30T23:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_ticket_payload(facility_id, **overrides) -> dict:
    """Input fields: facility_id, department_id (optional), target_ref, severity,
    at_the_elbow_zone, linked_test_defect_id (optional)."""
    payload = {
        "facility_id": facility_id,
        "target_ref": facility_id,
        "severity": "SEV3",
        "at_the_elbow_zone": "MED_SURG",
    }
    payload.update(overrides)
    return payload


def create_staffing_shift_payload(staff_id, facility_id, **overrides) -> dict:
    """Input fields: staff_id, facility_id, support_role, start_utc, end_utc."""
    payload = {
        "staff_id": staff_id,
        "facility_id": facility_id,
        "support_role": "AT_THE_ELBOW",
        "start_utc": "2026-09-02T06:00:00Z",
        "end_utc": "2026-09-02T14:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_optimization_item_payload(department_id, expected_ehr_implementation_version, **overrides) -> dict:
    """Input fields: department_id, title, effort_points,
    expected_ehr_implementation_version."""
    payload = {
        "department_id": department_id,
        "title": "Optimization request",
        "effort_points": 5,
        "expected_ehr_implementation_version": expected_ehr_implementation_version,
    }
    payload.update(overrides)
    return payload