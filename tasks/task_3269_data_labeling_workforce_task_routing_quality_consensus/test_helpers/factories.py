"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_worker_payload(**overrides) -> dict:
    payload = {"handle": "worker-default"}
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_code": TEST_DEFAULTS["PROGRAM_CODE"],
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "language_code": TEST_DEFAULTS["LANGUAGE_CODE"],
        "instruction_model": TEST_DEFAULTS["INSTRUCTION_MODEL"],
        "sensitivity_class": TEST_DEFAULTS["SENSITIVITY_CLASS"],
        "deadline_utc": TEST_DEFAULTS["DEADLINE_UTC"],
        "blackout_start_utc": TEST_DEFAULTS["BLACKOUT_START_UTC"],
        "blackout_end_utc": TEST_DEFAULTS["BLACKOUT_END_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_spec_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": "U-1",
        "max_items": TEST_DEFAULTS["MAX_ITEMS"],
        "instruction_revision": TEST_DEFAULTS["INSTRUCTION_REVISION"],
        "instruction_status": "PUBLISHED",
        "field_schema": list(TEST_DEFAULTS["FIELD_SCHEMA"]),
        "coverage_start_utc": TEST_DEFAULTS["COVERAGE_START_UTC"],
        "coverage_end_utc": TEST_DEFAULTS["COVERAGE_END_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "item_key": "i-0001",
        "payload_uri": "s3://ax/0001",
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(**overrides) -> dict:
    defaults = {"language_code": TEST_DEFAULTS["LANGUAGE_CODE"], "tier": "PROFICIENT"}
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "program_code": TEST_DEFAULTS["PROGRAM_CODE"],
        "category": "PII_EXPOSURE",
        "severity": "MINOR",
        "description_text": "Observed breach.",
        "incident_action": "REPORT",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "grounds": "AMBIGUOUS_INSTRUCTIONS",
        "statement_text": "The instruction document does not cover the null case.",
    }
    defaults.update(overrides)
    return defaults


def commit_label_payload(label="A", **overrides) -> dict:
    defaults = {"payload": {"label": label}, "instructions_ack": True}
    defaults.update(overrides)
    return defaults


def abstain_payload(**overrides) -> dict:
    defaults = {"abstained": True, "instructions_ack": True}
    defaults.update(overrides)
    return defaults


def payout_payload(amount_cents, currency="USD", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "currency": currency}
    defaults.update(overrides)
    return defaults


def grade_payload(gold_outcome, expected_item_version, **overrides) -> dict:
    defaults = {"gold_outcome": gold_outcome, "expected_item_version": expected_item_version}
    defaults.update(overrides)
    return defaults