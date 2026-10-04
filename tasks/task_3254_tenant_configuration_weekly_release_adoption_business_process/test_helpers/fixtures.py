"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so no state
carries over). Setup calls use get_success_data so failures surface as
clear "Setup step failed" errors.

Logical-clock discipline: org units are created with effective_date anchored
at the clock's startup instant and activated by an explicit clock advance
before workers or groups reference them.
"""
from .api_client import api_client
from .constants import CLOCK_START, WORK_DATE, THRESHOLDS
from .factories import (
    create_tenant_payload,
    create_org_unit_payload,
    create_worker_payload,
    create_security_group_payload,
    create_definition_payload,
    create_step_payload,
    initiate_transaction_payload,
    create_release_train_payload,
    create_connector_payload,
    create_run_payload,
    create_refresh_job_payload,
)
from .test_users import (
    make_platform_operator_headers,
    make_integration_developer_headers,
    make_tenant_admin_headers,
    make_implementation_partner_headers,
    make_approver_headers,
)
from prd_bench_local_runner.testing import get_success_data, validate_paginated


# ---------------------------------------------------------------------------
# Role header shortcuts
# ---------------------------------------------------------------------------

def op_headers() -> dict:
    return make_platform_operator_headers()


def dev_headers() -> dict:
    return make_integration_developer_headers()


def admin_of(tenant: dict) -> dict:
    """TenantAdministrator headers for the tenant's bootstrap administrator."""
    return make_tenant_admin_headers(tenant["bootstrap_admin_worker_id"])


def admin_as(tenant: dict, worker_id: str) -> dict:
    return make_tenant_admin_headers(worker_id)


def approver_as(worker_id: str) -> dict:
    return make_approver_headers(worker_id)


def partner_as(worker_id: str) -> dict:
    return make_implementation_partner_headers(worker_id)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, op_headers()))


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

def create_tenant(name: str, kind: str = "PRODUCTION", **overrides) -> dict:
    payload = create_tenant_payload(tenant_name=name, tenant_kind=kind, **overrides)
    return get_success_data(api_client.create_tenant(payload, op_headers()), 201)


def get_tenant(tenant_id: str) -> dict:
    return get_success_data(api_client.get_tenant(tenant_id, op_headers()))


# ---------------------------------------------------------------------------
# Org structure & workforce
# ---------------------------------------------------------------------------

def create_active_unit(tid: str, name: str, admin: dict, unit_type: str = "TEAM",
                       parent_unit_id=None, clock_to: str = WORK_DATE) -> dict:
    """Create a unit whose effective_date is the clock startup instant, then
    advance the clock so the unit is ACTIVE on return."""
    payload = create_org_unit_payload(
        unit_name=name, unit_type=unit_type, effective_date=CLOCK_START,
    )
    if parent_unit_id:
        payload["parent_unit_id"] = parent_unit_id
    created = get_success_data(api_client.create_org_unit(tid, payload, admin), 201)
    set_clock(clock_to)
    unit = get_success_data(api_client.get_org_unit(tid, created["id"], admin))
    assert unit["status"] == "ACTIVE", f"unit {name} should be ACTIVE after clock advance"
    return unit


def create_worker(tid: str, unit_id: str, ref: str, admin: dict,
                  full_name: str = None, manager_worker_id=None) -> dict:
    payload = create_worker_payload(
        worker_ref=ref, full_name=full_name or f"Worker {ref}", org_unit_id=unit_id,
    )
    if manager_worker_id:
        payload["manager_worker_id"] = manager_worker_id
    return get_success_data(api_client.create_worker(tid, payload, admin), 201)


def create_workers(tid: str, unit_id: str, count: int, ref_prefix: str, admin: dict) -> list:
    """Create `count` ACTIVE workers in one unit; returns the worker dicts."""
    return [
        create_worker(tid, unit_id, f"{ref_prefix}{i:02d}", admin)
        for i in range(1, count + 1)
    ]


# ---------------------------------------------------------------------------
# Security groups & memberships
# ---------------------------------------------------------------------------

def create_group(tid: str, name: str, admin: dict, assignment_mode: str = "USER_BASED",
                 org_unit_id=None, min_approvers: int = 1) -> dict:
    payload = create_security_group_payload(
        group_name=name, assignment_mode=assignment_mode, min_approvers=min_approvers,
    )
    if org_unit_id:
        payload["org_unit_id"] = org_unit_id
    return get_success_data(api_client.create_security_group(tid, payload, admin), 201)


def add_membership(tid: str, gid: str, worker_id: str, admin: dict) -> dict:
    return get_success_data(
        api_client.create_membership(tid, gid, {"worker_id": worker_id}, admin), 201
    )


def create_group_with_member(tid: str, name: str, worker_id: str, admin: dict,
                             min_approvers: int = 1) -> dict:
    group = create_group(tid, name, admin, min_approvers=min_approvers)
    add_membership(tid, group["id"], worker_id, admin)
    return group


# ---------------------------------------------------------------------------
# Business process definitions & steps
# ---------------------------------------------------------------------------

def create_definition(tid: str, admin: dict, transaction_type: str = "HIRE",
                      name: str = "Flow", **overrides) -> dict:
    payload = create_definition_payload(
        transaction_type=transaction_type, definition_name=name, **overrides,
    )
    return get_success_data(api_client.create_definition(tid, payload, admin), 201)


def add_step(tid: str, definition_id: str, order: int, admin: dict,
             kind: str = "APPROVAL", group_id=None, condition: str = "ALWAYS",
             return_target=None) -> dict:
    payload = create_step_payload(
        step_order=order, step_kind=kind, inclusion_condition=condition,
    )
    if group_id:
        payload["approver_security_group_id"] = group_id
    if return_target is not None:
        payload["return_target_step_order"] = return_target
    return get_success_data(api_client.create_step(tid, definition_id, payload, admin), 201)


def activate_definition(tid: str, definition_id: str, admin: dict) -> dict:
    """Activate using the definition's current version (happy-path OCC)."""
    current = get_success_data(api_client.get_definition(tid, definition_id, admin))
    return get_success_data(
        api_client.activate_definition(
            tid, definition_id,
            {"expected_definition_version": current["version"]}, admin,
        )
    )


# ---------------------------------------------------------------------------
# Composite: tenant + unit + workers + group (+ definition)
# ---------------------------------------------------------------------------

def setup_tenant_with_group(name: str = "T-FX", min_approvers: int = 1,
                            tenant_kind: str = "PRODUCTION", **tenant_overrides) -> dict:
    """Tenant with one ACTIVE unit, an initiator worker, an approver worker,
    and a USER_BASED group holding the approver. Returns a context dict."""
    tenant = create_tenant(name, kind=tenant_kind, **tenant_overrides)
    admin = admin_of(tenant)
    unit = create_active_unit(tenant["id"], "U1", admin)
    initiator = create_worker(tenant["id"], unit["id"], "INIT", admin)
    approver = create_worker(tenant["id"], unit["id"], "MGR", admin)
    group = create_group_with_member(tenant["id"], "G1", approver["id"], admin,
                                     min_approvers=min_approvers)
    return {
        "tenant": tenant,
        "admin": admin,
        "unit": unit,
        "initiator": initiator,
        "approver": approver,
        "group": group,
    }


def setup_active_definition(name: str = "T-FX", steps=None,
                            transaction_type: str = "HIRE",
                            definition_overrides=None, **tenant_overrides) -> dict:
    """setup_tenant_with_group + an ACTIVE definition. `steps` is a list of
    dicts accepted by add_step (order/kind/condition/return_target); the
    tenant's approver group is attached to APPROVAL/REVIEW steps by default."""
    ctx = setup_tenant_with_group(name, **tenant_overrides)
    tid, admin, gid = ctx["tenant"]["id"], ctx["admin"], ctx["group"]["id"]
    definition = create_definition(tid, admin, transaction_type=transaction_type,
                                   name="Flow", **(definition_overrides or {}))
    for spec in (steps or [{"order": 1}]):
        spec = dict(spec)
        order = spec.pop("order")
        spec.setdefault("group_id", gid)
        add_step(tid, definition["id"], order, admin, **spec)
    definition = activate_definition(tid, definition["id"], admin)
    ctx["definition"] = definition
    return ctx


def initiate(ctx: dict, transaction_type: str = "HIRE", amount=0,
             target_unit_id=None, initiator_id=None) -> dict:
    tid = ctx["tenant"]["id"]
    payload = initiate_transaction_payload(
        transaction_type=transaction_type,
        target_org_unit_id=target_unit_id or ctx["unit"]["id"],
        amount=amount,
    )
    caller = admin_as(ctx["tenant"], initiator_id or ctx["initiator"]["id"])
    return get_success_data(api_client.create_transaction(tid, payload, caller), 201)


# ---------------------------------------------------------------------------
# Release trains & feature adoption
# ---------------------------------------------------------------------------

def create_feature_train(label: str, window_start: str, window_end: str,
                         mandatory: str) -> dict:
    payload = create_release_train_payload(
        release_label=label, release_kind="FEATURE_RELEASE",
        opt_in_window_start=window_start, opt_in_window_end=window_end,
        mandatory_date=mandatory,
    )
    return get_success_data(api_client.create_release_train(payload, op_headers()), 201)


def create_weekly_train(label: str, mandatory: str) -> dict:
    payload = create_release_train_payload(
        release_label=label, release_kind="WEEKLY_SERVICE", mandatory_date=mandatory,
    )
    payload.pop("opt_in_window_start", None)
    payload.pop("opt_in_window_end", None)
    return get_success_data(api_client.create_release_train(payload, op_headers()), 201)


def get_train(train_id: str) -> dict:
    return get_success_data(api_client.get_release_train(train_id, op_headers()))


def enroll(tid: str, train_id: str, feature_key: str, admin: dict,
           deprecates_feature_key=None) -> dict:
    payload = {"release_train_id": train_id, "feature_key": feature_key}
    if deprecates_feature_key:
        payload["deprecates_feature_key"] = deprecates_feature_key
    return get_success_data(api_client.create_feature_adoption(tid, payload, admin), 201)


def get_adoption(tid: str, adoption_id: str, admin: dict) -> dict:
    return get_success_data(api_client.get_feature_adoption(tid, adoption_id, admin))


# ---------------------------------------------------------------------------
# Connectors & runs
# ---------------------------------------------------------------------------

def create_active_connector(tid: str, name: str = "C1", trigger_mode: str = "SCHEDULED",
                            schedule_cron: str = "0 * * * *", subscribed_event=None,
                            blackout=(3, 4)) -> dict:
    payload = create_connector_payload(
        connector_name=name, trigger_mode=trigger_mode,
        blackout_window_start_utc=blackout[0], blackout_window_end_utc=blackout[1],
    )
    if trigger_mode == "SCHEDULED":
        payload["schedule_cron"] = schedule_cron
        payload.pop("subscribed_event", None)
    else:
        payload.pop("schedule_cron", None)
        payload["subscribed_event"] = subscribed_event
    connector = get_success_data(api_client.create_connector(tid, payload, dev_headers()), 201)
    return get_success_data(api_client.activate_connector(tid, connector["id"], dev_headers()))


def create_run(tid: str, cid: str, trigger_source: str = "MANUAL",
               as_operator: bool = False) -> dict:
    headers = op_headers() if as_operator else dev_headers()
    return get_success_data(
        api_client.create_run(tid, cid, create_run_payload(trigger_source=trigger_source), headers),
        201,
    )


# ---------------------------------------------------------------------------
# Tenant refresh
# ---------------------------------------------------------------------------

def create_prod_sandbox_pair(src_name: str = "T-SRC", tgt_name: str = "T-TGT",
                             slot: int = 2) -> tuple:
    """A PRODUCTION source tenant and a SANDBOX target refreshed from it."""
    src = create_tenant(src_name, kind="PRODUCTION", maintenance_slot_utc=slot)
    tgt = create_tenant(
        tgt_name, kind="SANDBOX", maintenance_slot_utc=slot,
        refresh_source_tenant_id=src["id"],
    )
    return src, tgt


def plan_refresh(tgt: dict, source_id: str, scheduled_at: str,
                 migration_mode: str = "FULL_COPY", include_workers=None) -> dict:
    payload = create_refresh_job_payload(
        source_tenant_id=source_id, scheduled_at=scheduled_at,
        migration_mode=migration_mode,
    )
    if include_workers is not None:
        payload["include_workers"] = include_workers
    return get_success_data(
        api_client.create_refresh_job(tgt["id"], payload, admin_of(tgt)), 201
    )


def run_refresh_to(tgt: dict, job_id: str, action: str,
                   advance_clock_to: str = None) -> dict:
    """Move a PLANNED job to RUNNING (via clock advance past scheduled_at),
    then apply `action` ("complete" or "fail")."""
    admin = admin_of(tgt)
    if advance_clock_to:
        set_clock(advance_clock_to)
    job = get_success_data(api_client.get_refresh_job(tgt["id"], job_id, admin))
    if job["status"] == "PLANNED":
        job = get_success_data(api_client.start_refresh_job(tgt["id"], job_id, admin))
    assert job["status"] == "RUNNING", f"refresh job should be RUNNING, got {job['status']}"
    if action == "complete":
        return get_success_data(api_client.complete_refresh_job(tgt["id"], job_id, admin))
    if action == "fail":
        return get_success_data(api_client.fail_refresh_job(tgt["id"], job_id, admin))
    raise ValueError(f"unknown refresh action {action!r}")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def list_notifications(tid: str, headers: dict, **filters) -> list:
    params = {k: v for k, v in filters.items() if v is not None}
    params.setdefault("limit", 100)
    body = api_client.list_notifications(tid, headers, params=params)
    data, _meta = validate_paginated(body)
    return data


def notification_kinds(tid: str, headers: dict, **filters) -> list:
    return [n["notification_kind"] for n in list_notifications(tid, headers, **filters)]
