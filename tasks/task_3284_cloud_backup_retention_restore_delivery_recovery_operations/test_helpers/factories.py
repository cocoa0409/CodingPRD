"""Payload factories for every create-shaped endpoint, input fields only."""
from typing import Optional


def create_account_payload(**overrides) -> dict:
    payload = {
        "name": "Northwind Personal",
        "account_type": "PERSONAL",
        "region": "US_WEST",
        "encryption_key_id": "aes-256-key-0001",
        "usage_gb": 0,
    }
    payload.update(overrides)
    return payload


def create_backup_group_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "name": "Personal Laptops",
        "tier": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_group_policy_payload(**overrides) -> dict:
    payload = {
        "policy_kind": "RETENTION",
        "min_retention_days": 10,
        "max_extended_history_days": 800,
        "min_restore_point_age_hours": 0,
        "require_mfa_for_restore": True,
        "effective_from_utc": "2026-09-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_agent_payload(account_id: str, group_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "group_id": group_id,
        "hostname": "nw-laptop-01",
        "os_type": "MACOS",
        "license_type": "PERSONAL",
        "throttle_month": 202609,
    }
    payload.update(overrides)
    return payload


def create_backup_set_payload(agent_id: str, account_id: str, **overrides) -> dict:
    payload = {
        "agent_id": agent_id,
        "account_id": account_id,
        "durability_class": "STANDARD",
    }
    payload.update(overrides)
    return payload


def create_file_version_payload(file_path: str, version_number: int, operation: str,
                                size_bytes: int, content_hash: str,
                                event_utc: str, **overrides) -> dict:
    payload = {
        "file_path": file_path,
        "version_number": version_number,
        "operation": operation,
        "size_bytes": size_bytes,
        "content_hash": content_hash,
        "event_utc": event_utc,
    }
    payload.update(overrides)
    return payload


def create_restore_request_payload(account_id: str, subject_agent_id: str,
                                   restore_point_in_utc: str,
                                   expected_account_version: int, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "subject_agent_id": subject_agent_id,
        "restore_point_in_utc": restore_point_in_utc,
        "restore_type": "FILE_DOWNLOAD",
        "requested_file_count": 1,
        "requested_size_gb": 10.0,
        "restore_transaction_count": 0,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def create_billing_period_payload(account_id: str, period_start_utc: str,
                                  period_end_utc: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "restore_active_days": 0,
    }
    payload.update(overrides)
    return payload


def create_retention_change_request_payload(account_id: str, group_id: str,
                                            requested_retention_days: int,
                                            expected_group_version: int,
                                            **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "group_id": group_id,
        "requested_retention_days": requested_retention_days,
        "reason_code": "UPGRADE",
        "expected_group_version": expected_group_version,
    }
    payload.update(overrides)
    return payload


def create_data_deletion_request_payload(account_id: str, deletion_scope: str,
                                         authorization_ref: str,
                                         expected_account_version: int,
                                         **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "deletion_scope": deletion_scope,
        "authorization_ref": authorization_ref,
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def create_storage_pod_payload(region: str, total_shards: int, data_shards: int,
                               **overrides) -> dict:
    payload = {
        "region": region,
        "total_shards": total_shards,
        "data_shards": data_shards,
        "failed_shards": 0,
    }
    payload.update(overrides)
    return payload