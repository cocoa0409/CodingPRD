"""Payload factories — one per operation that accepts a body.

Only client-supplied fields appear here; derived and system-managed fields are
never sent (PRD §2.5).
"""
from .constants import TEST_DEFAULTS

_name_counter = {"n": 0}


def unique_name(prefix: str = "Environment") -> str:
    """A name that is unique across the whole organization (PRD §2.4)."""
    _name_counter["n"] += 1
    return f"{prefix} {_name_counter['n']}"


def create_environment_payload(**overrides) -> dict:
    payload = {
        "name": unique_name(),
        "type": "DEVELOPER",
    }
    payload.update(overrides)
    return payload


def create_refresh_job_payload(environment_id: str, **overrides) -> dict:
    payload = {
        "environment_id": environment_id,
        "partition": "ACCOUNT_PARTIAL",
        "masked_field_count": 2,
    }
    payload.update(overrides)
    return payload


def create_package_version_payload(namespace: str, **overrides) -> dict:
    payload = {
        "namespace": namespace,
        "major_version": TEST_DEFAULTS["MAJOR_VERSION"],
        "name": f"{namespace} Core {TEST_DEFAULTS['MAJOR_VERSION']}",
    }
    payload.update(overrides)
    return payload


def create_package_installation_payload(package_version_id: str,
                                        expected_environment_version: int,
                                        **overrides) -> dict:
    payload = {
        "package_version_id": package_version_id,
        "expected_environment_version": expected_environment_version,
    }
    payload.update(overrides)
    return payload


def create_permission_payload(principal_type: str, principal_name: str,
                              user_id: str, **overrides) -> dict:
    payload = {
        "principal_type": principal_type,
        "principal_name": principal_name,
        "user_id": user_id,
    }
    payload.update(overrides)
    return payload


def create_change_set_payload(source_environment_id: str, target_environment_id: str,
                              expected_environment_version: int, **overrides) -> dict:
    payload = {
        "source_environment_id": source_environment_id,
        "target_environment_id": target_environment_id,
        "component_list": [{"component": "acme_controller", "version_tag": 1}],
        "component_dependencies": [],
        "expected_environment_version": expected_environment_version,
    }
    payload.update(overrides)
    return payload


def create_deployment_payload(idempotency_key: str, **overrides) -> dict:
    payload = {"idempotency_key": idempotency_key}
    payload.update(overrides)
    return payload


def create_governor_request_payload(**overrides) -> dict:
    payload = {
        "request_kind": "BATCH",
        "scope_count": TEST_DEFAULTS["SCOPE_COUNT"],
        "callout_graph": [],
        "max_concurrent_jobs": 5,
    }
    payload.update(overrides)
    return payload


def create_storage_ledger_payload(kind: str, bytes: int, rank_index: int, **overrides) -> dict:
    payload = {"kind": kind, "bytes": bytes, "rank_index": rank_index}
    payload.update(overrides)
    return payload


def create_access_audit_payload(environment_id: str, reviewed_assignment_ids=None, **overrides) -> dict:
    payload = {
        "environment_id": environment_id,
        "reviewed_assignment_ids": reviewed_assignment_ids or [],
    }
    payload.update(overrides)
    return payload


def close_audit_payload(finding: str, **overrides) -> dict:
    payload = {"finding": finding}
    payload.update(overrides)
    return payload