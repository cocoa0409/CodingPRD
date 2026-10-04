"""Regulator report bookkeeping: the region rollup check and the filing queue."""

from db import STORE, add_days, now
from middleware import new_id, stamp
from services import common


def run_rollup_for_account(account):
    """A trip completion re-evaluates the rollup for the account's incidents."""
    produced = []
    for incident in list(STORE.incidents.values()):
        if incident.get("account_id") != account.get("id"):
            continue
        produced.extend(run_rollup(incident, account))
    return produced


def run_rollup(incident, account):
    """The region rollup threshold check over the incident's historical window."""
    region = account.get("home_region_code")
    policy = common.policy_for_region(region)
    window_days = int(policy.get("rollup_window_days", 30))
    threshold = int(policy.get("rollup_threshold", 3))

    created_at = incident.get("created_at")
    if created_at is None:
        return []
    window_start = add_days(created_at, -window_days)

    qualifying = 0
    for other in STORE.account_incidents(account.get("id")):
        other_created = other.get("created_at")
        if other_created is None:
            continue
        # The window is closed-open: the lower edge counts, the upper does not.
        if window_start <= other_created < created_at and other.get("severity") in ("S3", "S4"):
            qualifying += 1

    if qualifying < threshold:
        return []
    if account.get("status") not in ("DEACTIVATED", "RESTRICTED", "UNDER_HOLD",
                                     "PENDING_DECISION", "APPEAL_PENDING"):
        return []
    if common.filing_basis_invariant_breached(account.get("id"), region, "ROLLUP_THRESHOLD"):
        return []

    report = {
        "id": new_id(),
        "incident_id": incident.get("id"),
        "region_code": region,
        "report_channel": "REGULATOR_PORTAL",
        "filing_basis": "ROLLUP_THRESHOLD",
        "filed_at": now(),
        "report_status": "FILED",
        "_window_index": 0,
    }
    stamp(report)
    STORE.regulator_reports[report["id"]] = report
    return [report]


def rollup_count(incident, account):
    """The retained scope readings the rollup sweep reports."""
    region = account.get("home_region_code")
    policy = common.policy_for_region(region)
    window_days = int(policy.get("rollup_window_days", 30))
    created_at = incident.get("created_at")
    if created_at is None:
        return 0, 0.0
    window_start = add_days(created_at, -window_days)
    qualifying = 0
    for other in STORE.account_incidents(account.get("id")):
        other_created = other.get("created_at")
        if other_created is None:
            continue
        if window_start <= other_created < created_at and other.get("severity") in ("S3", "S4"):
            qualifying += 1
    return qualifying, qualifying / 5.0