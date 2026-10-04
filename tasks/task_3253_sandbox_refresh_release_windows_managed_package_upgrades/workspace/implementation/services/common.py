"""Shared lookups, existence checks and cascade plumbing.

Path templates are resolved left to right (PRD §2.12): a missing environment is
reported as ERR_ENVIRONMENT_NOT_FOUND before any attempt is made to resolve a
child resource of that environment, and only then does a missing child produce
ERR_RESOURCE_NOT_FOUND.
"""

import db
from errors import (
    ERR_ACCESS_TRACE_INCOMPLETE,
    ERR_ENVIRONMENT_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    fail,
)


def next_seq():
    return db.next_seq()


def get_environment(env_id):
    row = db.find(db.environments, env_id)
    if row is None:
        fail(ERR_ENVIRONMENT_NOT_FOUND, "Environment '%s' does not exist." % (env_id,))
    return row


def get_row(table, row_id, label):
    row = db.find(table, row_id)
    if row is None:
        fail(ERR_RESOURCE_NOT_FOUND, "%s '%s' does not exist." % (label, row_id))
    return row


def get_refresh_job(job_id):
    return get_row(db.refresh_jobs, job_id, "RefreshJob")


def get_package_version(version_id):
    return get_row(db.package_versions, version_id, "PackageVersion")


def get_installed_package(installed_id):
    return get_row(db.installed_packages, installed_id, "InstalledPackage")


def get_change_set(change_set_id):
    return get_row(db.change_sets, change_set_id, "MetadataChangeSet")


def get_deployment_job(job_id):
    return get_row(db.deployment_jobs, job_id, "DeploymentJob")


def get_governor_request(request_id):
    return get_row(db.governor_requests, request_id, "GovernorLimitRequest")


def get_storage_ledger(ledger_id):
    return get_row(db.storage_ledgers, ledger_id, "StorageLedger")


def get_access_audit(audit_id):
    return get_row(db.access_audits, audit_id, "AccessAudit")


def get_permission_assignment(assignment_id):
    return get_row(db.permission_assignments, assignment_id, "PermissionAssignment")


def bump(env):
    """Advance a parent environment's updated_at and version.

    PRD §2.5: an operation that mutates a parent environment as a side effect
    must bump Environment.version.  Each affected child row advances its own
    version independently, via db.touch on that row.
    """
    if env is not None:
        db.touch(env)


def children(rows, env_id, key="environment_id"):
    return [r for r in rows.values() if r.get(key) == env_id]


def live_installed(env_id):
    return [
        r
        for r in db.installed_packages.values()
        if r["environment_id"] == env_id and r["status"] != "UNINSTALLED"
    ]


def installed_namespaces(env_id):
    return {r["namespace"] for r in live_installed(env_id)}


def change_sets_under(env_id):
    return [r for r in db.change_sets.values() if r["target_environment_id"] == env_id]


def require_assignment_trace(environment_id, assignment_ids):
    """Every reviewed assignment must belong to the audited environment."""
    for assignment_id in assignment_ids:
        row = db.permission_assignments.get(assignment_id)
        if row is None or row["environment_id"] != environment_id:
            fail(
                ERR_ACCESS_TRACE_INCOMPLETE,
                "PermissionAssignment '%s' does not belong to environment '%s'."
                % (assignment_id, environment_id),
            )
        if not row.get("user_id"):
            fail(
                ERR_ACCESS_TRACE_INCOMPLETE,
                "PermissionAssignment '%s' does not resolve to an operator identifier."
                % (assignment_id,),
            )


def release_ordinal(env, field="applied_release_version"):
    import calculations

    return calculations.release_ordinal(env.get(field))