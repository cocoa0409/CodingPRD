"""Entity record constructors and serialization helpers (PRD §2.10)."""
from decimal import Decimal, ROUND_HALF_UP

from clock import Clock
from db import new_id

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def public(record):
    """Strip internal (underscore-prefixed) bookkeeping keys."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.10)."""
    record["updated_at"] = Clock.iso_now()
    record["version"] = record.get("version", 0) + 1


def _common():
    now = Clock.iso_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def _immutable():
    return {"id": new_id(), "created_at": Clock.iso_now()}


# ---------------------------------------------------------------- TeamAccount
def new_account(data):
    rec = _common()
    rec.update({
        "name": data.get("name"),
        "plan_code": data.get("plan_code", "TEAM_FREE"),
        "plan_id": new_id(),
        "task_allowance": int(data.get("task_allowance", 0) or 0),
        "closer_cost_per_task_cents": int(data.get("closer_cost_per_task_cents", 1) or 0),
        "opening_cost_per_task_cents": int(data.get("opening_cost_per_task_cents", 1) or 0),
        "overage_enabled": bool(data.get("overage_enabled", True)),
        "tasks_used_current": 0,
        "tasks_used_previous": 0,
        "overage_tasks_used": 0,
        "usage_pct_current": 0,
        "overage_amount_cents": 0,
        "projected_overage_amount_cents": 0,
        "locked_upgrade_code": None,
        "_opening_used_at_epoch": False,
    })
    return rec


# --------------------------------------------------------------------- Member
def new_member(data, account):
    rec = _common()
    rec.update({
        "account_id": data.get("account_id"),
        "email": data.get("email"),
        "full_name": data.get("full_name"),
        "plan_code": account.get("plan_code") if account else None,
        "role": data.get("role", "MEMBER"),
    })
    return rec


# --------------------------------------------------------------------- Folder
def new_folder(account_id, name):
    rec = _common()
    rec.update({"account_id": account_id, "name": name})
    return rec


def new_folder_grant(folder_id, member_id, grant_role):
    rec = _common()
    rec.update({
        "folder_id": folder_id,
        "member_id": member_id,
        "grant_role": grant_role,
    })
    return rec


def new_folder_folder_grant(folder_id, grant_id):
    rec = _immutable()
    rec.update({"folder_id": folder_id, "grant_id": grant_id})
    return rec


# ------------------------------------------------------------------- Workflow
LATENCY_BY_TRIGGER = {"POLLING": 900, "WEBHOOK": 30, "INSTANT_WEBHOOK": 0}


def new_workflow(account_id, data):
    rec = _common()
    trigger_type = data.get("trigger_type")
    rec.update({
        "account_id": account_id,
        "name": data.get("name"),
        "folder_id": data.get("folder_id"),
        "trigger_type": trigger_type,
        "poll_interval_seconds": int(data.get("poll_interval_seconds", 900) or 900),
        "trigger_latency_seconds": LATENCY_BY_TRIGGER.get(trigger_type, 30),
        "status": "DRAFT",
        "pause_reason": None,
        "action_count": 0,
        "attempt_epoch": 0,
    })
    return rec


# ------------------------------------------------------------- WorkflowAction
def new_action(workflow_id, data):
    rec = _common()
    rec.update({
        "workflow_id": workflow_id,
        "position": int(data.get("position")),
        "integration_id": data.get("integration_id"),
        "connection_id": data.get("connection_id"),
        "action_type": data.get("action_type"),
        "filter_expression": data.get("filter_expression"),
        "status": "PENDING",
        "_last_charged_tasks": 0,
        "_last_charged_cents": 0,
        "_attempt_no": 0,
        "_max_retries": 3,
    })
    return rec


# ---------------------------------------------------------------- WorkflowRun
def new_run(workflow_id, data):
    rec = _common()
    rec.update({
        "workflow_id": workflow_id,
        "connection_id": data.get("connection_id"),
        "status": "RUNNING",
        "held_action_id": None,
        "charge": data.get("charge"),
    })
    return rec


# ---------------------------------------------------------------- Integration
def new_integration(data):
    rec = _common()
    rec.update({
        "name": data.get("name"),
        "partner_name": data.get("partner_name"),
        "auth_method": data.get("auth_method"),
        "endpoint_coverage": 0,
        "review_status": "DRAFT",
        "review_rejection_count": 0,
        "review_latency_hours": 0,
        "reviewed_version": 0,
        "version": 1,
        "_review_opened_at": None,
        "_cycle_rejected": False,
        "_pending_schema_issue": 0,
    })
    return rec


def new_integration_endpoint(integration_id, data):
    rec = _common()
    rec.update({
        "integration_id": integration_id,
        "path": data.get("path"),
        "has_response_schema": bool(data.get("has_response_schema", False)),
    })
    return rec


def new_integration_version(integration_id, version_number, schema_coverage, endpoint_revision_ids=None):
    rec = _common()
    rec.update({
        "integration_id": integration_id,
        "version_number": int(version_number),
        "schema_coverage": float(schema_coverage),
        "_endpoint_revision_ids": list(endpoint_revision_ids or []),
    })
    return rec


# ---------------------------------------------------------------- Connection
def new_connection(account_id, data):
    rec = _common()
    rec.update({
        "account_id": account_id,
        "integration_id": data.get("integration_id"),
        "owner_member_id": data.get("owner_member_id"),
        "token_expires_at": None,
        "status": "CONNECTED",
        "refresh_count": 0,
        "reauth_requested_at": None,
    })
    return rec


# ------------------------------------------------------------ WorkflowVersion
def new_workflow_version(workflow_id, data, snapshot_action_count):
    rec = _common()
    rec.update({
        "workflow_id": workflow_id,
        "integration_version_id": data.get("integration_version_id"),
        "connection_id": data.get("connection_id"),
        "status": "CURRENT",
        "snapshot_action_count": snapshot_action_count,
        "schema_issue_count": 0,
        "_target_integration_version_id": data.get("integration_version_id"),
    })
    return rec


# ------------------------------------------------------------------ JobEvent
def new_job_event(action_id, connection_id, attempt_no, outcome, latency_ms):
    rec = _immutable()
    rec.update({
        "action_id": action_id,
        "connection_id": connection_id,
        "attempt_no": attempt_no,
        "outcome": outcome,
        "latency_ms": int(latency_ms or 0),
        "occurred_at": Clock.iso_now(),
    })
    return rec


# --------------------------------------------------------------- RefundGrant
def new_refund_grant(run_id, connection_id, kind, source_job_event_id, integration_id=None):
    rec = _immutable()
    rec.update({
        "run_id": run_id,
        "connection_id": connection_id,
        "kind": kind,
        "source_job_event_id": source_job_event_id,
        "consuming_job_event_id": None,
        "refunded_at": Clock.iso_now(),
        "consumed_at": None,
        "_integration_id": integration_id,
    })
    return rec


# ------------------------------------------------------------- LapseIncident
def new_lapse_incident(event_no, occurred_at, kind, target_id):
    rec = _common()
    rec.update({
        "event_no": event_no,
        "occurred_at": occurred_at,
        "kind": kind,
        "target_id": target_id,
    })
    return rec