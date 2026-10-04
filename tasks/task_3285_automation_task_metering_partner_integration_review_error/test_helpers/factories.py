"""Payload factories -- one per entity, client-supplied fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "ACCOUNT_NAME": "Test Account",
    "MEMBER_EMAIL": "member@example.test",
    "MEMBER_FULL_NAME": "Test Member",
    "FOLDER_NAME": "Ops",
    "WORKFLOW_NAME": "Test Workflow",
    "INTEGRATION_NAME": "Slack",
    "PARTNER_NAME": "Partner Inc",
    "ACTION_TYPE": "send_message",
    "ENDPOINT_PATH": "/v1/op1",
}


def create_account_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "plan_code": TEST_DEFAULTS["PLAN_CODE"],
        "task_allowance": TEST_DEFAULTS["TASK_ALLOWANCE"],
        "closer_cost_per_task_cents": TEST_DEFAULTS["CLOSER_COST_PER_TASK_CENTS"],
        "opening_cost_per_task_cents": TEST_DEFAULTS["OPENING_COST_PER_TASK_CENTS"],
        "overage_enabled": TEST_DEFAULTS["OVERAGE_ENABLED"],
    }
    payload.update(overrides)
    return payload


def create_member_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "email": DEFAULTS["MEMBER_EMAIL"],
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "role": "MEMBER",
    }
    payload.update(overrides)
    return payload


def create_folder_payload(account_id: str, **overrides) -> dict:
    payload = {"account_id": account_id, "name": DEFAULTS["FOLDER_NAME"]}
    payload.update(overrides)
    return payload


def create_folder_grant_payload(member_id: str, **overrides) -> dict:
    payload = {"member_id": member_id, "grant_role": "READ"}
    payload.update(overrides)
    return payload


def create_workflow_payload(account_id: str, folder_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "name": DEFAULTS["WORKFLOW_NAME"],
        "folder_id": folder_id,
        "trigger_type": "POLLING",
        "poll_interval_seconds": 900,
    }
    payload.update(overrides)
    return payload


def create_action_payload(integration_id: str, connection_id: str, **overrides) -> dict:
    payload = {
        "position": 1,
        "integration_id": integration_id,
        "connection_id": connection_id,
        "action_type": DEFAULTS["ACTION_TYPE"],
    }
    payload.update(overrides)
    return payload


def dispatch_run_payload(**overrides) -> dict:
    payload = {"charge": "success"}
    payload.update(overrides)
    return payload


def create_integration_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["INTEGRATION_NAME"],
        "partner_name": DEFAULTS["PARTNER_NAME"],
        "auth_method": "OAUTH2",
    }
    payload.update(overrides)
    return payload


def create_endpoint_payload(**overrides) -> dict:
    payload = {"path": DEFAULTS["ENDPOINT_PATH"], "has_response_schema": True}
    payload.update(overrides)
    return payload


def create_connection_payload(account_id: str, integration_id: str, owner_member_id: str,
                              **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "integration_id": integration_id,
        "owner_member_id": owner_member_id,
    }
    payload.update(overrides)
    return payload


def create_workflow_version_payload(workflow_id: str, integration_version_id: str,
                                    connection_id: str, **overrides) -> dict:
    payload = {
        "workflow_id": workflow_id,
        "integration_version_id": integration_version_id,
        "connection_id": connection_id,
    }
    payload.update(overrides)
    return payload


def publish_integration_version_payload(version_number: int, **overrides) -> dict:
    payload = {"version_number": version_number}
    payload.update(overrides)
    return payload


def create_lapse_incident_payload(kind: str, occurred_at: str, target_id: str, **overrides) -> dict:
    payload = {"kind": kind, "occurred_at": occurred_at, "target_id": target_id}
    payload.update(overrides)
    return payload


def action_charge_payload(account_id: str, action_id: str, expected_account_version: int,
                          **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "action_id": action_id,
        "attempt_no": 1,
        "service_latency_ms": 10,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload