"""Composite setup helpers: multi-step scenarios built from PRD endpoints only.

Every helper builds its preconditions from scratch — the server is restarted
before each individual test, so nothing survives between tests.
"""
from typing import List, Optional

from .api_client import api_client as api
from .api_errors import ApiErrorId
from .constants import TEST_DEFAULTS, GB_10, GB_100
from .factories import (
    create_account_payload,
    create_backup_group_payload,
    create_group_policy_payload,
    create_agent_payload,
    create_backup_set_payload,
    create_file_version_payload,
    create_restore_request_payload,
    create_billing_period_payload,
    create_retention_change_request_payload,
    create_data_deletion_request_payload,
    create_storage_pod_payload,
)
from .test_users import TEST_USERS, make_account_owner_headers

SYS = TEST_USERS["system_operator_headers"]
OWNER_SHARED = TEST_USERS["account_owner_headers"]
BACKUP = TEST_USERS["backup_operator_headers"]
RETENTION = TEST_USERS["retention_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _ok(response, label):
    """Lenient setup validator: setup failures read as 'Setup failed: ...'."""
    assert 200 <= response.status_code < 300, (
        f"Setup failed at '{label}': HTTP {response.status_code} {response.text[:400]}")
    return response.json().get("data")


def set_clock(current_utc=TEST_DEFAULTS["CLOCK"]):
    return _ok(api.set_clock(current_utc, SYS), "set_clock")


def create_account(name="Northwind Personal", account_type="PERSONAL",
                   region="US_WEST", storage_tier=None, encryption_key_id="aes-256-key-0001",
                   usage_gb=0, **extra):
    payload = create_account_payload(
        name=name, account_type=account_type, region=region,
        encryption_key_id=encryption_key_id, usage_gb=usage_gb, **extra)
    if storage_tier is not None:
        payload["storage_tier"] = storage_tier
    return _ok(api.create_account(payload, SYS), "create_account")


def create_group(account_id, name="Personal Laptops", tier="STANDARD",
                 retention_days_override=TEST_DEFAULTS["GROUP_RETENTION_DAYS"], **extra):
    payload = create_backup_group_payload(
        account_id, name=name, tier=tier, retention_days_override=retention_days_override, **extra)
    if retention_days_override is None:
        payload.pop("retention_days_override", None)
    return _ok(api.create_backup_group(payload, SYS), "create_group")


def create_policy(group_id, min_retention_days=TEST_DEFAULTS["MIN_RETENTION_DAYS"],
                  max_extended_history_days=TEST_DEFAULTS["MAX_EXTENDED_HISTORY_DAYS"],
                  min_restore_point_age_hours=0, require_mfa_for_restore=True,
                  policy_kind="RETENTION", effective_from_utc=TEST_DEFAULTS["CLOCK"],
                  headers=None, **extra):
    payload = create_group_policy_payload(
        policy_kind=policy_kind, min_retention_days=min_retention_days,
        max_extended_history_days=max_extended_history_days,
        min_restore_point_age_hours=min_restore_point_age_hours,
        require_mfa_for_restore=require_mfa_for_restore,
        effective_from_utc=effective_from_utc, **extra)
    return _ok(api.create_group_policy(group_id, payload, headers or RETENTION), "create_policy")


def create_agent(account_id, group_id, hostname="nw-laptop-01", os_type="MACOS",
                 license_type="PERSONAL", throttle_month=TEST_DEFAULTS["THROTTLE_MONTH"],
                 **extra):
    payload = create_agent_payload(
        account_id, group_id, hostname=hostname, os_type=os_type,
        license_type=license_type, throttle_month=throttle_month, **extra)
    return _ok(api.create_agent(payload, BACKUP), "create_agent")


def block_agent(agent_id):
    return _ok(api.block_agent(agent_id, SYS), "block_agent")


def activate_agent(agent_id):
    return _ok(api.activate_agent(agent_id, BACKUP), "activate_agent")


def block_agent(agent_id, headers=None):
    """Block an ACTIVE agent (a SystemOperator action, PRD 3.2)."""
    return _ok(api.block_agent(agent_id, headers or SYS), "block_agent")


def unblock_agent(agent_id, headers=None):
    return _ok(api.unblock_agent(agent_id, headers or SYS), "unblock_agent")


def create_set(agent_id, account_id, durability_class="STANDARD", **extra):
    payload = create_backup_set_payload(
        agent_id, account_id, durability_class=durability_class, **extra)
    return _ok(api.create_backup_set(payload, BACKUP), "create_set")


def record_version(set_id, file_path, version_number, operation, size_bytes,
                   content_hash, event_utc, **extra):
    payload = create_file_version_payload(
        file_path, version_number, operation, size_bytes, content_hash, event_utc, **extra)
    return _ok(api.create_file_version(set_id, payload, BACKUP), "record_version")


def complete_initial(set_id):
    return _ok(api.complete_initial_backup(set_id, BACKUP), "complete_initial")


def account_version(account_id):
    return _ok(api.get_account(account_id, SYS), "get_account")["version"]


def group_version(group_id):
    return _ok(api.get_backup_group(group_id, RETENTION), "get_backup_group")["version"]


def owner_headers(account_id):
    """Ownership-gated headers for the account's own AccountOwner."""
    return make_account_owner_headers(account_id)


# ---------------------------------------------------------------------------
# Tier 1/2: the common single-agent scenario
# ---------------------------------------------------------------------------

def setup_personal_scenario(account_type="PERSONAL", storage_tier="PRO", region="US_WEST",
                            account_name="Northwind Personal", group_name="Personal Laptops",
                            retention_days_override=TEST_DEFAULTS["GROUP_RETENTION_DAYS"],
                            min_retention_days=TEST_DEFAULTS["MIN_RETENTION_DAYS"],
                            max_extended_history_days=TEST_DEFAULTS["MAX_EXTENDED_HISTORY_DAYS"],
                            min_restore_point_age_hours=0, require_mfa_for_restore=True,
                            hostname="nw-laptop-01", os_type="MACOS", license_type="PERSONAL",
                            durability_class="STANDARD", activate=True, create_backup_set=True,
                            clock_utc=TEST_DEFAULTS["CLOCK"], usage_gb=0,
                            encryption_key_id="aes-256-key-0001", create_policy_record=True):
    """Account + group + RETENTION policy + agent (+ activated, + provisioned set).

    Returns a dict with the created rows under keys account, group, policy, agent, set.
    """
    set_clock(clock_utc)
    account = create_account(name=account_name, account_type=account_type, region=region,
                             storage_tier=storage_tier, encryption_key_id=encryption_key_id,
                             usage_gb=usage_gb)
    group = create_group(account["id"], name=group_name, retention_days_override=retention_days_override)
    policy = None
    if create_policy_record:
        policy = create_policy(
            group["id"], min_retention_days=min_retention_days,
            max_extended_history_days=max_extended_history_days,
            min_restore_point_age_hours=min_restore_point_age_hours,
            require_mfa_for_restore=require_mfa_for_restore)
    agent = create_agent(account["id"], group["id"], hostname=hostname, os_type=os_type,
                         license_type=license_type)
    if activate:
        agent = activate_agent(agent["id"])
    backup_set = None
    if create_backup_set:
        backup_set = create_set(agent["id"], account["id"], durability_class=durability_class)
    return {"account": account, "group": group, "policy": policy,
            "agent": agent, "set": backup_set}


def setup_active_set(set_overrides=None, **kwargs):
    """The personal scenario walked all the way to an ACTIVE backup set.

    A single 100 GB CREATE is recorded and the initial flush completed, so the
    set is in ACTIVE and the account carries 100.0 GB of live volume.
    """
    scenario = setup_personal_scenario(**kwargs)
    record_version(scenario["set"]["id"], "/home/u/archive.tar", 1, "CREATE", GB_100,
                   "sha256-arc-v1", "2026-09-10T00:00:00Z")
    scenario["set"] = complete_initial(scenario["set"]["id"])
    return scenario


def setup_active_set_with_file(size_bytes=GB_100, file_path="/home/u/archive.tar",
                               event_utc="2026-09-10T00:00:00Z", content_hash="sha256-f-v1",
                               **kwargs):
    """Active-set scenario holding exactly one live file of the given size."""
    scenario = setup_personal_scenario(**kwargs)
    record_version(scenario["set"]["id"], file_path, 1, "CREATE", size_bytes,
                   content_hash, event_utc)
    scenario["set"] = complete_initial(scenario["set"]["id"])
    return scenario


def setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/big.bin",
                                 event_utc="2026-09-02T00:00:00Z",
                                 content_hash="sha256-big-v1", **kwargs):
    """Personal active-set scenario holding one live file of the given size.

    A convenience name for tests that walk a restore and only care that the set
    holds enough live content; it simply forwards to `setup_active_set_with_file`.
    """
    kwargs.setdefault("file_path", file_path)
    kwargs.setdefault("event_utc", event_utc)
    kwargs.setdefault("content_hash", content_hash)
    return setup_active_set_with_file(size_bytes=size_bytes, **kwargs)


def setup_disposable_active_set(size_bytes=GB_10, file_path="/home/u/tmp.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                content_hash="sha256-tmp-v1", **kwargs):
    """Active-set scenario holding exactly one *disposable* live file.

    Unlike `setup_active_set`, every keyword accepted by the underlying file
    recording is honoured, so a test may override the file's `size_bytes`,
    `file_path`, `event_utc` (and `content_hash`) without the double-keyword
    clash that the legacy name produces.
    """
    return setup_active_set_with_file(size_bytes=size_bytes, file_path=file_path,
                                      event_utc=event_utc, content_hash=content_hash,
                                      **kwargs)


def setup_business_active_set(size_bytes=GB_100, file_path="/srv/data/ledger.db",
                              event_utc="2026-09-02T00:00:00Z", content_hash="sha256-ledger-v1",
                              region="US_WEST", storage_tier="BASIC",
                              account_name="Harbor Business", group_name="Office Fleet",
                              retention_days_override=None, min_retention_days=30,
                              require_mfa_for_restore=False, hostname="hq-fileserver",
                              os_type="LINUX", license_type="BUSINESS",
                              durability_class="STANDARD", clock_utc=TEST_DEFAULTS["CLOCK"],
                              **kwargs):
    """BUSINESS account with a group, policy, activated agent and an ACTIVE set."""
    scenario = setup_personal_scenario(
        account_type="BUSINESS", storage_tier=storage_tier, region=region,
        account_name=account_name, group_name=group_name,
        retention_days_override=retention_days_override,
        min_retention_days=min_retention_days,
        require_mfa_for_restore=require_mfa_for_restore,
        hostname=hostname, os_type=os_type, license_type=license_type,
        durability_class=durability_class, clock_utc=clock_utc,
        encryption_key_id="aes-256-key-biz", **kwargs)
    record_version(scenario["set"]["id"], file_path, 1, "CREATE", size_bytes,
                   content_hash, event_utc)
    scenario["set"] = complete_initial(scenario["set"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: restore lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                   restore_type="FILE_DOWNLOAD", requested_file_count=1,
                   requested_size_gb=10.0, restore_transaction_count=0, **overrides):
    """Create a restore request against the scenario's own account."""
    account = scenario["account"]
    payload = create_restore_request_payload(
        account["id"], scenario["agent"]["id"], restore_point_in_utc,
        account_version(account["id"]),
        restore_type=restore_type, requested_file_count=requested_file_count,
        requested_size_gb=requested_size_gb,
        restore_transaction_count=restore_transaction_count, **overrides)
    return _ok(api.create_restore_request(payload, owner_headers(account["id"])),
               "create_restore")


def validate_restore(restore_id, account_id, requester_mfa_ticket=None):
    payload = {}
    if requester_mfa_ticket is not None:
        payload["requester_mfa_ticket"] = requester_mfa_ticket
    return _ok(api.validate_restore_request(restore_id, owner_headers(account_id), payload),
               "validate_restore")


def begin_restore(restore_id, account_id):
    return _ok(api.begin_restore(restore_id, owner_headers(account_id)), "begin_restore")


def prepare_restore(restore_id, account_id):
    return _ok(api.prepare_restore(restore_id, owner_headers(account_id)), "prepare_restore")


def complete_restore(restore_id, account_id):
    return _ok(api.complete_restore(restore_id, owner_headers(account_id)), "complete_restore")


def create_restore_in_state(scenario, target_state="READY", mfa_ticket="mfa-ticket-001",
                            **restore_kwargs):
    """Walk a restore request from REQUESTED to VALIDATING / IN_PROGRESS / READY."""
    account_id = scenario["account"]["id"]
    restore = create_restore(scenario, **restore_kwargs)
    if target_state == "REQUESTED":
        return restore
    restore = validate_restore(restore["id"], account_id, mfa_ticket)
    if target_state == "VALIDATING":
        return restore
    restore = begin_restore(restore["id"], account_id)
    if target_state == "IN_PROGRESS":
        return restore
    restore = prepare_restore(restore["id"], account_id)
    if target_state == "READY":
        return restore
    restore = complete_restore(restore["id"], account_id)
    return restore


def find_shipment_for_restore(restore_id, account_id):
    """A shipment row is discoverable only by listing drive shipments."""
    rows = _ok(api.list_drive_shipments(
        owner_headers(account_id), {"restore_request_id": restore_id}),
        "list_drive_shipments")
    return rows[0] if rows else None


def setup_shipment(scenario=None, drive_capacity_gb=50.0, drive_count=1,
                   deposit_fee_cents=5000, requested_size_gb=10.0, **restore_kwargs):
    """DRIVE_SHIPMENT restore walked to IN_PROGRESS with its shipment in PREPARING."""
    if scenario is None:
        scenario = setup_business_active_set()
    account_id = scenario["account"]["id"]
    restore = create_restore(
        scenario, restore_type="DRIVE_SHIPMENT", requested_size_gb=requested_size_gb,
        drive_capacity_gb=drive_capacity_gb, drive_count=drive_count,
        deposit_fee_cents=deposit_fee_cents, **restore_kwargs)
    restore = validate_restore(restore["id"], account_id)
    restore = begin_restore(restore["id"], account_id)
    shipment = find_shipment_for_restore(restore["id"], account_id)
    assert shipment is not None, "Setup failed: no DriveShipment synthesized by begin"
    return {"scenario": scenario, "restore": restore, "shipment": shipment,
            "account": scenario["account"]}


def setup_shipment_in_state(target_state="AWAITING_RETURN", clock_utc=TEST_DEFAULTS["CLOCK"],
                            shipped_clock_utc=TEST_DEFAULTS["CLOCK"], **shipment_kwargs):
    """Shipment walked from PREPARING to SHIPPED / DELIVERED / AWAITING_RETURN.

    Shipping is stamped at `shipped_clock_utc` so the 14-day return deadline is
    deterministic, then the clock is left at `clock_utc`.
    """
    ctx = setup_shipment(**shipment_kwargs)
    account_id = ctx["account"]["id"]
    shipment_id = ctx["shipment"]["id"]
    set_clock(shipped_clock_utc)
    ctx["shipment"] = _ok(api.ship_drive_shipment(shipment_id, SYS), "ship_shipment")
    if target_state == "SHIPPED":
        return ctx
    ctx["shipment"] = _ok(api.deliver_drive_shipment(shipment_id, SYS), "deliver_shipment")
    if target_state == "DELIVERED":
        return ctx
    ctx["shipment"] = _ok(api.open_return_window(shipment_id, owner_headers(account_id)),
                           "open_return_window")
    if target_state == "AWAITING_RETURN":
        set_clock(clock_utc)
        return ctx
    ctx["shipment"] = _ok(api.receive_return(shipment_id, SYS), "receive_return")
    set_clock(clock_utc)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: billing shortcuts
# ---------------------------------------------------------------------------

def open_billing_period(account_id, period_start_utc="2026-09-01T00:00:00Z",
                        period_end_utc="2026-10-01T00:00:00Z", restore_active_days=0):
    payload = create_billing_period_payload(
        account_id, period_start_utc, period_end_utc, restore_active_days=restore_active_days)
    return _ok(api.create_billing_period(payload, SYS), "open_billing_period")


def close_billing_period(period_id):
    return _ok(api.close_billing_period(period_id, SYS), "close_billing_period")


def open_and_close_period(account_id, period_start_utc="2026-09-01T00:00:00Z",
                          period_end_utc="2026-10-01T00:00:00Z", restore_active_days=0):
    period = open_billing_period(account_id, period_start_utc, period_end_utc,
                                 restore_active_days)
    return close_billing_period(period["id"])


# ---------------------------------------------------------------------------
# Tier 3/4: retention change shortcuts
# ---------------------------------------------------------------------------

def create_retention_request(scenario_or_group, requested_retention_days=120,
                             reason_code="UPGRADE", account_id=None, **overrides):
    if isinstance(scenario_or_group, dict) and "group" in scenario_or_group:
        group = scenario_or_group["group"]
        account = scenario_or_group["account"]
    else:
        group = scenario_or_group
        account = {"id": account_id}
    payload = create_retention_change_request_payload(
        account["id"], group["id"], requested_retention_days,
        group_version(group["id"]), reason_code=reason_code, **overrides)
    return _ok(api.create_retention_change_request(payload, RETENTION),
               "create_retention_request")


def begin_cooling_off(request_id):
    return _ok(api.begin_cooling_off(request_id, RETENTION), "begin_cooling_off")


def setup_retention_request_in_cooling_off(scenario=None, requested_retention_days=120,
                                           reason_code="UPGRADE", **kwargs):
    """A RetentionChangeRequest sitting in COOLING_OFF, ready to be applied."""
    if scenario is None:
        scenario = setup_personal_scenario()
    request = create_retention_request(
        scenario, requested_retention_days=requested_retention_days,
        reason_code=reason_code, **kwargs)
    request = begin_cooling_off(request["id"])
    return {"scenario": scenario, "request": request,
            "account": scenario["account"], "group": scenario["group"]}


# ---------------------------------------------------------------------------
# Tier 3/4/5: deletion and closure shortcuts
# ---------------------------------------------------------------------------

def create_deletion_request(account_id, deletion_scope="DELETED_FILES",
                            authorization_ref="ticket-DSR-0001", **overrides):
    payload = create_data_deletion_request_payload(
        account_id, deletion_scope, authorization_ref, account_version(account_id),
        **overrides)
    return _ok(api.create_data_deletion_request(payload, COMPLIANCE), "create_deletion_request")


def approve_deletion_request(request_id):
    return _ok(api.approve_data_deletion_request(request_id, COMPLIANCE),
               "approve_deletion_request")


def execute_deletion_request(request_id):
    return _ok(api.execute_data_deletion_request(request_id, COMPLIANCE),
               "execute_deletion_request")


def complete_deletion_request(request_id):
    return _ok(api.complete_data_deletion_request(request_id, COMPLIANCE),
               "complete_deletion_request")


def setup_approved_closure_deletion(scenario, approve_clock_utc=TEST_DEFAULTS["CLOCK"]):
    """An ACCOUNT_CLOSURE deletion request approved and past its cooling-off window."""
    set_clock(approve_clock_utc)
    request = create_deletion_request(scenario["account"]["id"],
                                      deletion_scope="ACCOUNT_CLOSURE",
                                      authorization_ref="ticket-DSR-4471")
    request = approve_deletion_request(request["id"])
    return {"scenario": scenario, "request": request, "account": scenario["account"]}


def execute_closure_deletion(scenario, execute_clock_utc="2026-09-05T00:00:00Z",
                             approve_clock_utc="2026-07-01T00:00:00Z"):
    """Submit, approve and execute an ACCOUNT_CLOSURE deletion, then walk the
    logical clock forward past the 30-day deletion cooling-off window so the
    execution is legitimately admissible (PRD 3.8)."""
    ctx = setup_approved_closure_deletion(scenario, approve_clock_utc=approve_clock_utc)
    set_clock(execute_clock_utc)
    ctx["request"] = execute_deletion_request(ctx["request"]["id"])
    return ctx


def setup_completed_closure_deletion(scenario, execute_clock_utc="2026-09-05T00:00:00Z"):
    """A COMPLETED ACCOUNT_CLOSURE deletion: the account is purged and CLOSED."""
    ctx = setup_approved_closure_deletion(scenario)
    set_clock(execute_clock_utc)
    execute_deletion_request(ctx["request"]["id"])
    ctx["request"] = complete_deletion_request(ctx["request"]["id"])
    ctx["account"] = _ok(api.get_account(scenario["account"]["id"], SYS), "get_account")
    return ctx


def setup_delete_all_sets(scenario):
    """Delete every backup set of the scenario's agent, on pain of the retention hold."""
    sets = _ok(api.list_backup_sets(SYS, {"agent_id": scenario["agent"]["id"]}),
               "list_backup_sets")
    for row in sets:
        _ok(api.delete_backup_set(row["id"], BACKUP), "delete_backup_set")
    return sets


# ---------------------------------------------------------------------------
# Tier 4: storage pod shortcuts
# ---------------------------------------------------------------------------

def create_pod(region="US_WEST", total_shards=16, data_shards=12, failed_shards=0):
    payload = create_storage_pod_payload(region, total_shards, data_shards,
                                         failed_shards=failed_shards)
    return _ok(api.create_storage_pod(payload, SYS), "create_pod")


def fail_shards(pod_id, delta):
    return _ok(api.fail_storage_pod_shards(pod_id, {"failed_shards_delta": delta}, SYS),
               "fail_shards")


def restore_shards(pod_id, delta):
    return _ok(api.restore_storage_pod_shards(pod_id, {"failed_shards_delta": delta}, SYS),
               "restore_shards")


def setup_pod_with_failed_shards(failed_shards=1, total_shards=16, data_shards=12,
                                 region="US_WEST"):
    pod = create_pod(region=region, total_shards=total_shards, data_shards=data_shards)
    if failed_shards:
        pod = fail_shards(pod["id"], failed_shards)
    return pod