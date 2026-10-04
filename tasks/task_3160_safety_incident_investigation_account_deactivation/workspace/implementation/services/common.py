"""Cross-service helpers.

Keeping the account-side derived fields, the enforcement ledger bookkeeping and
the announcement registry in one place avoids the drift that creeps in when
several routers each re-derive a counter.
"""

from db import STORE, add_days, now
from calculations import (COUNTED_INCIDENT_STATUSES, ENFORCEMENT_WEIGHT,
                          STANDING_ENFORCEMENT_STATUSES, policy_for_region,
                          propagate_risk, recompute_cluster_aggregate,
                          recompute_linked_clusters)
from middleware import touch

REGULATOR_FILING_BASES = ("ROLLUP_THRESHOLD", "ALWAYS_LAW_ENFORCEMENT",
                          "BLOCKED_WINDOW_TRIGGER")
REPORT_BLOCK_DAYS = 30
REPORT_PUBLICATION_DAYS = 365


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def recompute_account_counters(account):
    account_id = account.get("id")
    standing = 0
    deactivations = 0
    for action in STORE.account_actions(account_id):
        if action.get("enforcement_status") in STANDING_ENFORCEMENT_STATUSES:
            standing += 1
        if action.get("outcome") == "DEACTIVATED":
            deactivations += 1
    account["standing_enforcement_count"] = standing
    account["deactivation_count"] = deactivations
    return account


def compute_safety_posture(account):
    """FROZEN on APPEAL_PENDING; RESTRICTED on RESTRICTED or any standing action."""
    if account.get("status") == "APPEAL_PENDING":
        return "FROZEN"
    if account.get("status") == "RESTRICTED" or (account.get("standing_enforcement_count") or 0) >= 1:
        return "RESTRICTED"
    return "OPEN"


def refresh_account(account, propagate=True, touch_resource=True, exclude_action_id=None):
    """Recompute every derived account field after an incident/enforcement change."""
    recompute_account_counters(account)
    if propagate:
        propagate_risk(account, exclude_action_id=exclude_action_id)
        recompute_linked_clusters(account.get("id"))
    account["safety_posture"] = compute_safety_posture(account)
    if touch_resource:
        touch(account)
    return account


def announcements_suppressed_for(account_id):
    """Derived book of account: an account under hold has its announcements muted."""
    account = STORE.accounts.get(account_id)
    if account is None:
        return False
    return account.get("status") == "UNDER_HOLD"


def standing_actions(account_id, exclude_action_id=None, outcome=None):
    """The account's actions still in flight (ACTIVE / MANDATORY_REPORTED / APPEAL_PENDING).

    ``exclude_action_id`` lets the expiry sweep read the *other* standing actions:
    the action being expired is itself standing at that instant, so counting it
    would make every legitimate sweep refuse. ``outcome`` narrows the reading to
    the deactivating actions.
    """
    return [a for a in STORE.account_actions(account_id)
            if a.get("enforcement_status") in STANDING_ENFORCEMENT_STATUSES
            and a.get("id") != exclude_action_id
            and (outcome is None or a.get("outcome") == outcome)]


# ---------------------------------------------------------------------------
# Consumer safety report queue
# ---------------------------------------------------------------------------

def queue_consumer_report(account):
    """Queue an account for the next publication, honouring the region cap.

    The queue is ordered by account identifier ascending. The cap is consumed by
    accounts whose deactivation_count is at or above 2; when it is already
    exhausted the account is simply not queued -- the request itself succeeds and
    the cap decrements rather than the write failing.
    """
    account_id = account.get("id")
    if account_id in STORE.consumer_report_queue:
        STORE.consumer_report_queue.sort()
        return True
    region = account.get("home_region_code")
    cap = STORE.monthly_report_cap.get(region, 10)
    if cap <= 0:
        return False
    STORE.monthly_report_cap[region] = cap - 1
    STORE.consumer_report_queue.append(account_id)
    STORE.consumer_report_queue.sort()
    return True


def drop_from_consumer_report(account_id):
    if account_id in STORE.consumer_report_queue:
        STORE.consumer_report_queue.remove(account_id)
        return True
    return False


def drop_ineligible_from_report_queue(account_id):
    """Drop an account that no longer clears the two-deactivation bar."""
    account = STORE.accounts.get(account_id)
    if account is None:
        return
    if (account.get("deactivation_count") or 0) < 2:
        drop_from_consumer_report(account_id)


# ---------------------------------------------------------------------------
# Enforcement actions
# ---------------------------------------------------------------------------

def stamp_action_schedule(action, decided_at):
    region = None
    incident = STORE.incidents.get(action.get("incident_id"))
    if incident is not None:
        account = STORE.accounts.get(incident.get("account_id"))
        if account is not None:
            region = account.get("home_region_code")
    policy = policy_for_region(region)
    appeal_window_days = int(policy.get("appeal_window_days", 30))

    action["effective_at"] = decided_at
    action["decision_made_at"] = decided_at
    action["appeal_deadline_at"] = add_days(decided_at, appeal_window_days)
    action["expires_at"] = add_days(decided_at, 365)
    action["review_due_at"] = add_days(decided_at, 180)
    return action


def compute_regulator_report_required(incident):
    return (incident.get("incident_category") in ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT")
            and incident.get("severity") in ("S3", "S4"))


def recompute_rehabilitation_credit(action):
    account_id = action.get("account_id")
    effective_at = action.get("effective_at")
    if effective_at is None:
        action["rehabilitation_credit"] = 0
        return 0
    count = 0
    for trip in STORE.trips.values():
        if trip.get("status") != "COMPLETED":
            continue
        if account_id not in (trip.get("rider_account_id"), trip.get("driver_account_id")):
            continue
        completed_at = trip.get("completed_at")
        if completed_at is not None and completed_at >= effective_at:
            count += 1
    action["rehabilitation_credit"] = count
    return count


def recompute_credits_for_account(account_id):
    for action in STORE.account_actions(account_id):
        recompute_rehabilitation_credit(action)


def action_is_open(action):
    """An action still capable of being credited toward reinstatement."""
    return action.get("enforcement_status") in (
        "ACTIVE", "MANDATORY_REPORTED", "APPEAL_PENDING", "REVERTED")


# ---------------------------------------------------------------------------
# Regulator reports
# ---------------------------------------------------------------------------

def report_publication_window(report):
    """(window_start, window_end) -- 365-day publication windows."""
    start = report.get("created_at")
    if start is None:
        return None, None
    index = max(0, int(report.get("_window_index") or 0))
    window_start = add_days(start, index * REPORT_PUBLICATION_DAYS)
    window_end = add_days(window_start, REPORT_PUBLICATION_DAYS)
    return window_start, window_end


def open_regulator_window(region_code, days=REPORT_BLOCK_DAYS):
    """Declare the region's regulator window block for the next ``days`` days."""
    instant = now()
    STORE.add_report_window(region_code, instant, add_days(instant, days))


def close_regulator_windows(region_code):
    """The region's blocked window closes, letting backlog items file."""
    STORE.close_report_windows(region_code)


def regulator_window_is_blocked(region_code):
    """Is the region inside an active regulator window block right now?"""
    instant = now()
    for region, start, close in STORE.report_windows():
        if region_code is not None and region != region_code:
            continue
        if start <= instant < close:
            return True
    return False


def filing_basis_invariant_breached(account_id, region_code, filing_basis):
    """The issuance invariant: at most one non-PENDING report per account/region."""
    if filing_basis not in REGULATOR_FILING_BASES:
        return False
    for report in STORE.regulator_reports.values():
        if report.get("filing_basis") not in REGULATOR_FILING_BASES:
            continue
        incident = STORE.incidents.get(report.get("incident_id"))
        if incident is None:
            continue
        if incident.get("account_id") != account_id:
            continue
        if report.get("region_code") != region_code:
            continue
        return True
    return False