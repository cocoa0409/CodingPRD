"""Record constructors.

Each builder mints the raw UUID `id`, stamps `created_at` at the logical
clock, and (for the eleven mutable entities) initialises `updated_at` and the
`version` counter at its creation value (PRD 2.4).  FileVersion is immutable
and carries only `id` and `created_at`.
"""

from util import fmt_ts, DEFAULT_CLOCK_UTC

BASE_RETENTION_DAYS = 30              # PRD 3.4 / SCAFFOLD constants
EXTENDED_RETENTION_DAYS = 365

DEFAULT_CLOCK = DEFAULT_CLOCK_UTC


def _stamp(store, rec, mutable=True):
    rec["created_at"] = fmt_ts(store.now())
    if mutable:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_order"] = store.tick()
    rec["_seq"] = rec["_order"]
    return rec


def account(store, name, account_type, region, encryption_key_id,
            storage_tier="BASIC", usage_gb=0.0):
    """PRD 3.1: status ACTIVE, retention_days seeded, deposit_held_cents 0."""
    # PRD 3.1 / 3.4: an account is born with the tier default window.  A
    # PERSONAL account starts on the standard 30-day window; a BUSINESS or
    # ENTERPRISE account already carries extended history, so its base window
    # is the 365-day extended retention.
    seeded = (BASE_RETENTION_DAYS if account_type == "PERSONAL"
              else EXTENDED_RETENTION_DAYS)
    rec = {
        "id": store.new_id(),
        "name": name,
        "account_type": account_type,
        "region": region,
        "storage_tier": storage_tier,
        "status": "ACTIVE",
        "encryption_key_id": encryption_key_id,
        "usage_gb": float(usage_gb or 0),
        "restore_download_gb": 0.0,
        "transaction_count": 0,
        "peak_usage_gb": float(usage_gb or 0),
        "retention_days": seeded,
        "has_extended_history": seeded > BASE_RETENTION_DAYS,
        "group_count": 0,
        "deposit_held_cents": 0,
        "initial_full_backup_gb": 0.0,
        "first_closed_period_utc": None,
    }
    return _stamp(store, rec)


def backup_group(store, account_id, name, tier, retention_days_override=None,
                 created_seq=0):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "name": name,
        "tier": tier,
        "retention_days_override": retention_days_override,
        "status": "ACTIVE",
        "group_retention_days": BASE_RETENTION_DAYS,
        "agent_count": 0,
        "expected_daily_transactions": 0,
        "member_transaction_share": 0.0,
        "created_seq": created_seq,
    }
    return _stamp(store, rec)


def group_policy(store, group_id, policy_kind, min_retention_days, max_extended_history_days,
                 min_restore_point_age_hours, require_mfa_for_restore, effective_from_utc):
    rec = {
        "id": store.new_id(),
        "group_id": group_id,
        "policy_kind": policy_kind,
        "min_retention_days": min_retention_days,
        "max_extended_history_days": max_extended_history_days,
        "min_restore_point_age_hours": min_restore_point_age_hours,
        "require_mfa_for_restore": require_mfa_for_restore,
        "effective_from_utc": effective_from_utc,
        "status": "ACTIVE",
    }
    return _stamp(store, rec)


def agent(store, account_id, group_id, hostname, os_type, license_type, throttle_month,
          data_stored_gb=0.0):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "group_id": group_id,
        "hostname": hostname,
        "os_type": os_type,
        "license_type": license_type,
        "status": "PENDING_AUTH",
        "throttle_month": throttle_month,
        "data_stored_gb": float(data_stored_gb or 0),
        "last_change_sequence": 0,
        "in_throttle_window": False,
        "data_stored_share": 0.0,
    }
    return _stamp(store, rec)


def backup_set(store, agent_id, account_id, durability_class, created_seq=0):
    rec = {
        "id": store.new_id(),
        "agent_id": agent_id,
        "account_id": account_id,
        "state": "PROVISIONING",
        "durability_class": durability_class,
        "initial_started_at": None,
        "last_backup_at": None,
        "storage_gb": 0.0,
        "version_chain_depth": 0,
        "retention_floor_utc": None,
        "recovery_points": 0,
        "is_initial_flush": False,
        "created_seq": created_seq,
    }
    return _stamp(store, rec)


def file_version(store, backup_set_id, file_path, version_number, operation,
                 size_bytes, content_hash, event_utc):
    rec = {
        "id": store.new_id(),
        "backup_set_id": backup_set_id,
        "file_path": file_path,
        "version_number": version_number,
        "operation": operation,
        "size_bytes": size_bytes,
        "content_hash": content_hash,
        "event_utc": fmt_ts(event_utc),
        "recoverable_until_utc": None,
        "is_deleted": operation == "DELETE",
        "is_expired": False,
    }
    return _stamp(store, rec, mutable=False)   # immutable: no version/updated_at


def restore_request(store, account_id, subject_agent_id, restore_point_in_utc,
                    restore_type, requested_file_count, requested_size_gb,
                    restore_transaction_count, requester_mfa_ticket,
                    drive_capacity_gb, drive_count, deposit_fee_cents):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "subject_agent_id": subject_agent_id,
        "restore_point_in_utc": restore_point_in_utc,
        "restore_type": restore_type,
        "requested_file_count": requested_file_count,
        "requested_size_gb": float(requested_size_gb or 0),
        "requester_mfa_ticket": requester_mfa_ticket,
        "drive_capacity_gb": drive_capacity_gb,
        "drive_count": drive_count,
        "deposit_fee_cents": deposit_fee_cents,
        "restore_transaction_count": restore_transaction_count,
        "state": "REQUESTED",
        "is_ransomware_recovery": False,
        "egress_gb": 0.0,
        "egress_fee_cents": 0,
        "archive_entry_count": 0,
    }
    return _stamp(store, rec)


def drive_shipment(store, restore_request_id, account_id, drive_capacity_gb,
                   drive_count, deposit_fee_cents):
    rec = {
        "id": store.new_id(),
        "restore_request_id": restore_request_id,
        "account_id": account_id,
        "drive_capacity_gb": drive_capacity_gb,
        "drive_count": drive_count,
        "deposit_fee_cents": deposit_fee_cents,
        "state": "PREPARING",
        "shipped_at": None,
        "return_deadline_utc": None,
        "return_credit_cents": 0,
        "was_delinquent": False,
    }
    return _stamp(store, rec)


def billing_period(store, account_id, period_start_utc, period_end_utc, restore_active_days):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "period_start_utc": period_start_utc,
        "period_end_utc": period_end_utc,
        "restore_active_days": restore_active_days,
        "state": "OPEN",
        "usage_gb_avg": 0.0,
        "peak_usage_gb": 0.0,
        "egress_gb": 0.0,
        "transaction_count": 0,
        "storage_fee_cents": 0,
        "initial_upload_credit_cents": 0,
        "storage_credit_applied_cents": 0,
        "egress_fee_cents": 0,
        "transaction_fee_cents": 0,
        "total_cents": 0,
    }
    return _stamp(store, rec)


def storage_pod(store, region, total_shards, data_shards, failed_shards, created_seq):
    rec = {
        "id": store.new_id(),
        "region": region,
        "status": "HEALTHY",
        "total_shards": total_shards,
        "data_shards": data_shards,
        "parity_shards": total_shards - data_shards,
        "failed_shards": failed_shards,
        "reliability_pct": 100.0,
        "is_reconstructable": True,
        "last_repair_utc": None,
        "created_seq": created_seq,
    }
    return _stamp(store, rec)


def retention_change_request(store, account_id, group_id, requested_retention_days,
                             reason_code):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "group_id": group_id,
        "requested_retention_days": requested_retention_days,
        "reason_code": reason_code,
        "state": "SUBMITTED",
        "submitted_at_utc": None,
        "cooling_off_until_utc": None,
        "original_retention_days": None,
    }
    return _stamp(store, rec)


def data_deletion_request(store, account_id, deletion_scope, authorization_ref):
    rec = {
        "id": store.new_id(),
        "account_id": account_id,
        "deletion_scope": deletion_scope,
        "authorization_ref": authorization_ref,
        "state": "SUBMITTED",
        "approved_at_utc": None,
        "executability_utc": None,
        "files_purged": 0,
        "bytes_purged": 0,
    }
    return _stamp(store, rec)


def public(rec):
    """Strip internal bookkeeping keys."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def touch(store, rec):
    """Any mutation refreshes updated_at and advances version (PRD 2.4)."""
    rec["updated_at"] = fmt_ts(store.now())
    rec["version"] = int(rec.get("version", 1)) + 1
    return rec