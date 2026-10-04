"""Integration review pipeline and revision publishing (PRD §3.7/§3.8)."""
from calc import recompute_integration_coverage, review_gate, review_latency_hours
from clock import Clock
from common import actions_of
from db import db
from errors import ApiError
from models import touch


def _endpoints(integration_id):
    return [e for e in db.integration_endpoints.values()
            if e["integration_id"] == integration_id]


def submit(integration):
    if integration["review_status"] == "REJECTED" or integration.get("_cycle_rejected"):
        raise ApiError("ERR_INTEGRATION_ALREADY_REJECTED")
    recompute_integration_coverage(integration)
    # The gate reads auth_method first, then coverage; only once both pass is
    # endpoint completeness examined (PRD §2.9).
    decision, err = review_gate(integration)
    if err:
        raise ApiError(err)
    rows = _endpoints(integration["id"])
    if len(rows) == 0 or any(e["has_response_schema"] is not True for e in rows):
        raise ApiError("ERR_MISSING_ERROR_SEMANTICS")
    if integration["review_status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INTEGRATION_NOT_IN_REVIEW")
    integration["review_status"] = "IN_REVIEW"
    integration["_review_opened_at"] = Clock.now()
    touch(integration)
    return integration


def review_decision(integration, decision_value):
    if integration["review_status"] not in ("SUBMITTED", "IN_REVIEW"):
        raise ApiError("ERR_INTEGRATION_NOT_IN_REVIEW")
    recompute_integration_coverage(integration)
    # Same gate order as submission: auth method, then coverage, then endpoints.
    _, err = review_gate(integration)
    if err:
        raise ApiError(err)
    rows = _endpoints(integration["id"])
    if len(rows) == 0 or any(e["has_response_schema"] is not True for e in rows):
        raise ApiError("ERR_MISSING_ERROR_SEMANTICS")

    latency = review_latency_hours(integration)
    if decision_value == "APPROVE":
        integration["review_status"] = "LISTED"
        integration["reviewed_version"] = integration["version"]
    else:
        integration["review_status"] = "REJECTED"
        integration["review_rejection_count"] += 1
        integration["_cycle_rejected"] = True
    integration["review_latency_hours"] = latency
    touch(integration)
    return integration


def publish_version(integration, version_number):
    existing = [v["version_number"] for v in db.integration_versions.values()
                if v["integration_id"] == integration["id"]]
    maximum = max(existing) if existing else 0
    if int(version_number) <= maximum:
        raise ApiError("ERR_VERSION_NOT_MONOTONIC")

    schema_coverage = _provisional_schema_coverage(integration["id"])
    from models import new_integration_version
    revision = new_integration_version(
        integration["id"], int(version_number), schema_coverage,
        endpoint_revision_ids=sorted(e["id"] for e in _endpoints(integration["id"])))
    db.integration_versions[revision["id"]] = revision

    if integration["review_status"] == "LISTED":
        integration["review_status"] = "SUBMITTED"
        integration["reviewed_version"] = 0
    integration["endpoint_coverage"] = schema_coverage
    touch(integration)

    _propagate_schema_migration(integration, schema_coverage)
    return revision


def _provisional_schema_coverage(integration_id):
    rows = _endpoints(integration_id)
    total = len(rows)
    if total == 0:
        return 0.0
    with_schema = len([e for e in rows if e["has_response_schema"] is True])
    from decimal import Decimal, ROUND_HALF_UP
    q = Decimal("0.01")
    return float((Decimal(with_schema) / Decimal(total)).quantize(q, rounding=ROUND_HALF_UP))


def _newest_revision(integration_id):
    rows = [v for v in db.integration_versions.values()
            if v["integration_id"] == integration_id]
    if not rows:
        return None
    rows.sort(key=lambda v: v["version_number"])
    return rows[-1]


def _propagate_schema_migration(integration, schema_coverage):
    """A release below 1.0 demotes the snapshots that reference the integration."""
    if schema_coverage >= 1.0:
        return
    gaps = len([e for e in _endpoints(integration["id"])
                if e["has_response_schema"] is not True])
    snapshots = [wv for wv in db.workflow_versions.values()
                 if wv["status"] == "CURRENT"]
    for snapshot in snapshots:
        revision = db.integration_versions.get(snapshot["integration_version_id"])
        if revision is None or revision["integration_id"] != integration["id"]:
            continue
        snapshot["status"] = "MIGRATION_REQUIRED"
        snapshot["schema_issue_count"] = gaps
        touch(snapshot)


# ------------------------------------------------------------------ snapshot
def create_snapshot(workflow, body):
    from models import new_workflow_version
    snapshot = new_workflow_version(
        workflow["id"], body, workflow.get("action_count", 0))
    target = body.get("integration_version_id")
    revision = db.integration_versions.get(target)
    if revision is not None and revision["integration_id"] is not None:
        pass
    db.workflow_versions[snapshot["id"]] = snapshot
    return snapshot


def migrate(workflow, body):
    target_id = body.get("target_integration_version_id")
    revision = db.integration_versions.get(target_id)
    if revision is None:
        raise ApiError("ERR_INTEGRATION_VERSION_NOT_FOUND")

    snapshot = _snapshot_for_target(workflow["id"],
                                    body.get("workflow_version_id"),
                                    body.get("snapshot_id"))
    if snapshot is None or snapshot["status"] != "MIGRATION_REQUIRED":
        raise ApiError("ERR_WORKFLOW_VERSION_NOT_MIGRATABLE")
    for action in actions_of(workflow["id"]):
        if action["status"] == "RUNNING":
            raise ApiError("ERR_WORKFLOW_VERSION_NOT_MIGRATABLE")

    expected = body.get("expected_workflow_version")
    if expected is None or int(expected) != workflow["version"]:
        raise ApiError("ERR_STALE_WORKFLOW_VERSION")

    if revision["schema_coverage"] < 0.8:
        attempts = db.migration_attempts.get(snapshot["id"], 0) + 1
        db.migration_attempts[snapshot["id"]] = attempts
        if attempts >= 3:
            snapshot["status"] = "BROKEN"
            touch(snapshot)
            return "BROKEN", snapshot
        raise ApiError("ERR_WORKFLOW_VERSION_NOT_MIGRATABLE")

    snapshot["status"] = "MIGRATED"
    snapshot["integration_version_id"] = target_id
    snapshot["_target_integration_version_id"] = target_id
    touch(snapshot)
    touch(workflow)
    for action in actions_of(workflow["id"]):
        touch(action)
    return "MIGRATED", snapshot


def _snapshot_for_target(workflow_id, explicit_id, snapshot_id=None):
    for candidate_id in (explicit_id, snapshot_id):
        if candidate_id:
            return db.workflow_versions.get(candidate_id)
    candidates = [wv for wv in db.workflow_versions.values()
                  if wv["workflow_id"] == workflow_id]
    if not candidates:
        return None
    # Prefer the snapshot that actually requires migration; a non-migratable
    # snapshot is still returned so the caller reports the state error rather
    # than mistaking the workflow for one with no snapshot at all.
    for snap in candidates:
        if snap["status"] == "MIGRATION_REQUIRED":
            return snap
    candidates.sort(key=lambda wv: wv["created_at"])
    return candidates[0]