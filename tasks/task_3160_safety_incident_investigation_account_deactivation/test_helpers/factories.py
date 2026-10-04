"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "REGION": TEST_DEFAULTS["REGION"],
    "TRIP_REQUESTED_AT": TEST_DEFAULTS["TRIP_REQUESTED_AT"],
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "RIDER",
        "home_region_code": DEFAULTS["REGION"],
        "legal_name": "Test Account",
        "contact_email": "test.account@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_device_cluster_payload(**overrides) -> dict:
    defaults = {
        "cluster_key": "dc-test",
        "region_code": DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_account_device_link_payload(account_id, device_cluster_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "device_cluster_id": device_cluster_id,
        "fingerprint_hash": "fp-test",
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(rider_account_id, driver_account_id, **overrides) -> dict:
    defaults = {
        "rider_account_id": rider_account_id,
        "driver_account_id": driver_account_id,
        "region_code": DEFAULTS["REGION"],
        "requested_at": DEFAULTS["TRIP_REQUESTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "reporter_type": "THIRD_PARTY",
        "incident_category": "PHYSICAL_ASSAULT",
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "evidence_type": "TRIP_DATA",
        "evidence_weight": "DISPOSITIVE",
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(decision_category, expected_incident_version, **overrides) -> dict:
    defaults = {
        "decision_category": decision_category,
        "decision_basis": "Decision recorded after the full investigation round trip.",
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_outcome_payload(adjudication, expected_incident_version, **overrides) -> dict:
    defaults = {
        "adjudication": adjudication,
        "review_notes": "Reviewed by the separate appeal team against the frozen evidence record.",
        "commit_early": False,
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_regulator_report_payload(incident_id, **overrides) -> dict:
    defaults = {
        "incident_id": incident_id,
        "report_channel": "REGULATOR_PORTAL",
        "filing_basis": "PENDING",
    }
    defaults.update(overrides)
    return defaults


def create_background_check_adjudication_payload(adjudication, **overrides) -> dict:
    defaults = {"adjudication": adjudication}
    defaults.update(overrides)
    return defaults


def create_platform_policy_payload(**overrides) -> dict:
    defaults = {
        "region_code": DEFAULTS["REGION"],
        "sd_floor_severity": "S4",
    }
    defaults.update(overrides)
    return defaults