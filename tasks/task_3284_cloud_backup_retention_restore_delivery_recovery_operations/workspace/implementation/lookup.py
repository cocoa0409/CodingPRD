"""Id resolution with left-to-right ordering, plus the double-touch helper.

PRD 2.10: identifiers are validated left to right in path order, then in
input-declaration order, and the request is rejected at the first broken link.
PRD 2.4: any recomputation of a derived field is itself a mutation that
refreshes `updated_at` and advances `version`.
"""

from errors import (APIError, ERR_ACCOUNT_NOT_FOUND, ERR_AGENT_NOT_FOUND,
                    ERR_BACKUP_SET_NOT_FOUND, ERR_BILLING_PERIOD_NOT_FOUND,
                    ERR_DELETION_REQUEST_NOT_FOUND, ERR_FILE_VERSION_NOT_FOUND,
                    ERR_GROUP_NOT_FOUND, ERR_POLICY_NOT_FOUND,
                    ERR_RESTORE_REQUEST_NOT_FOUND, ERR_RETENTION_CHANGE_NOT_FOUND,
                    ERR_SHIPMENT_NOT_FOUND, ERR_STORAGE_POD_NOT_FOUND,
                    ERR_INVALID_REQUEST)
from models import touch
from store import store


def ensure_id(value, field):
    if value is None:
        raise APIError(ERR_INVALID_REQUEST, "%s is required" % field)
    if not isinstance(value, str) or not value.strip():
        raise APIError(ERR_INVALID_REQUEST, "%s must be a non-empty id string" % field)
    return value.strip()


def account(account_id):
    rec = store.accounts.get(account_id)
    if rec is None:
        raise APIError(ERR_ACCOUNT_NOT_FOUND, "account %s does not exist" % account_id)
    return rec


def group(group_id):
    rec = store.groups.get(group_id)
    if rec is None:
        raise APIError(ERR_GROUP_NOT_FOUND, "backup group %s does not exist" % group_id)
    return rec


def policy(policy_id):
    rec = store.policies.get(policy_id)
    if rec is None:
        raise APIError(ERR_POLICY_NOT_FOUND, "group policy %s does not exist" % policy_id)
    return rec


def agent(agent_id):
    rec = store.agents.get(agent_id)
    if rec is None:
        raise APIError(ERR_AGENT_NOT_FOUND, "agent %s does not exist" % agent_id)
    return rec


def backup_set(set_id):
    rec = store.sets.get(set_id)
    if rec is None:
        raise APIError(ERR_BACKUP_SET_NOT_FOUND, "backup set %s does not exist" % set_id)
    return rec


def file_version(version_id):
    rec = store.versions.get(version_id)
    if rec is None:
        raise APIError(ERR_FILE_VERSION_NOT_FOUND,
                       "file version %s does not exist" % version_id)
    return rec


def restore_request(restore_id):
    rec = store.restores.get(restore_id)
    if rec is None:
        raise APIError(ERR_RESTORE_REQUEST_NOT_FOUND,
                       "restore request %s does not exist" % restore_id)
    return rec


def shipment(shipment_id):
    rec = store.shipments.get(shipment_id)
    if rec is None:
        raise APIError(ERR_SHIPMENT_NOT_FOUND,
                       "drive shipment %s does not exist" % shipment_id)
    return rec


def billing_period(period_id):
    rec = store.periods.get(period_id)
    if rec is None:
        raise APIError(ERR_BILLING_PERIOD_NOT_FOUND,
                       "billing period %s does not exist" % period_id)
    return rec


def pod(pod_id):
    rec = store.pods.get(pod_id)
    if rec is None:
        raise APIError(ERR_STORAGE_POD_NOT_FOUND,
                       "storage pod %s does not exist" % pod_id)
    return rec


def retention_change(change_id):
    rec = store.retention_changes.get(change_id)
    if rec is None:
        raise APIError(ERR_RETENTION_CHANGE_NOT_FOUND,
                       "retention change request %s does not exist" % change_id)
    return rec


def deletion_request(deletion_id):
    rec = store.deletions.get(deletion_id)
    if rec is None:
        raise APIError(ERR_DELETION_REQUEST_NOT_FOUND,
                       "data deletion request %s does not exist" % deletion_id)
    return rec


def owned_account_of(rec):
    """The account_id a record is scoped to, for AccountOwner ownership."""
    return rec.get("account_id")


def bump(*records):
    """Advance version/updated_at on each record; recompute cascade hops bump
    only the entities they mutate."""
    for rec in records:
        if rec is not None:
            touch(store, rec)


def recompute_touch(rec):
    """Recomputing a derived field on an entity is itself a mutation."""
    if rec is not None:
        touch(store, rec)
    return rec