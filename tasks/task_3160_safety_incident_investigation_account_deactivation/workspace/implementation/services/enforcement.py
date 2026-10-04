"""Enforcement ledger, the mandatory-report cascade and the case transitions.

The cascade is where three aggregates move in one request: the report moves
BACKLOG -> FILED, the cluster crosses OPEN -> WATCHLIST on its first crossing
only, and a WATCHLIST cluster may purge to BANNED. Every deactivation, whatever
produced it, mints a real DEACTIVATED enforcement action so the account-level
counters stay derivable from the ledger rather than being nudged in place.
"""

from db import STORE, add_days, now
from calculations import (policy_for_region, recompute_cluster_aggregate,
                          resolve_cluster_for_account)
from errors import (ApiError, ERR_IN_FLIGHT_APPEAL, ERR_MONTHLY_REPORT_CAP_REACHED,
                    ERR_REGULATOR_REPORT_BLOCKED)
from middleware import new_id, stamp, touch
from services import common

STANDING_STATUSES = ("ACTIVE", "MANDATORY_REPORTED", "APPEAL_PENDING")


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def _new_action(account, incident, outcome):
    action = {
        "id": new_id(),
        "account_id": account.get("id"),
        "incident_id": incident.get("id") if incident else None,
        "outcome": outcome,
        "enforcement_status": "DRAFT",
        "effective_at": None,
        "review_due_at": None,
        "expires_at": None,
        "appeal_deadline_at": None,
        "decision_made_at": None,
        "last_applied_appeal_deadline": None,
        "reinstatement_generation": 0,
        "rehabilitation_credit": 0,
        "regulator_report_required": (common.compute_regulator_report_required(incident)
                                      if incident else False),
        "cluster_watchlist_triggered": False,
        "_incident_series": len([a for a in STORE.enforcement_actions.values()
                                 if a.get("incident_id") == (incident or {}).get("id")]),
    }
    stamp(action)
    STORE.enforcement_actions[action["id"]] = action
    return action


def create_enforcement_action(account, incident, decided_at):
    """Synthesise the DRAFT action carrying the incident's committed outcome."""
    outcome = incident.get("decision_category")
    if outcome in (None, "NO_ACTION", "PENDING"):
        # NO_ACTION is not a graduated enforcement outcome, so no action exists.
        return None
    action = _new_action(account, incident, outcome)
    activate_enforcement_action(account, incident, action, decided_at)
    return action


def create_standalone_deactivation(account, decided_at, status="ACTIVE"):
    """The cluster-ban edge mints its own deactivation action."""
    action = _new_action(account, None, "DEACTIVATED")
    action["enforcement_status"] = status
    action["effective_at"] = decided_at
    action["decision_made_at"] = decided_at
    action["expires_at"] = add_days(decided_at, 365)
    action["review_due_at"] = add_days(decided_at, 180)
    policy = policy_for_region(account.get("home_region_code"))
    action["appeal_deadline_at"] = add_days(
        decided_at, int(policy.get("appeal_window_days", 30)))
    touch(action)
    account["status"] = "DEACTIVATED"
    common.refresh_account(account)
    common.recompute_rehabilitation_credit(action)
    _queue_after_deactivation(account, action)
    return action


# ---------------------------------------------------------------------------
# Activation and the mandatory-report cascade
# ---------------------------------------------------------------------------

def cascade_report_for_incident(incident):
    """The report the decision cascade files through, if one is queued."""
    reports = STORE.reports_for_incident((incident or {}).get("id"))
    portal = [r for r in reports if r.get("report_channel") == "REGULATOR_PORTAL"]
    candidates = portal or reports
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.get("created_at"), r.get("id") or ""))
    return candidates[-1]


def activate_enforcement_action(account, incident, action, decided_at):
    """Move the action out of DRAFT and run the mandatory-report cascade."""
    report = cascade_report_for_incident(incident)
    blocked = report is not None and report.get("report_status") == "BLOCKED"

    if action is not None:
        if action.get("regulator_report_required"):
            if blocked:
                # The filing window is closed: the action stays in DRAFT and the
                # incident is diverted to the blocked mandatory-report branch.
                return action
            action["enforcement_status"] = "MANDATORY_REPORTED"
            common.stamp_action_schedule(action, decided_at)
            if report is not None:
                report["report_status"] = "FILED"
                report["filed_at"] = now()
                touch(report)
        else:
            action["enforcement_status"] = "ACTIVE"
            common.stamp_action_schedule(action, decided_at)

        account["standing_enforcement_count"] = (account.get("standing_enforcement_count") or 0) + 1
        # The purge edge reads the linked account's risk_tier, so the account is
        # brought up to date before the cluster cascade is evaluated.
        common.refresh_account(account, touch_resource=False)
        action["cluster_watchlist_triggered"] = _run_cluster_cascade(account, action)
        # The credit is anchored on the action's effective_at, so it is read once
        # the schedule has been stamped.
        common.recompute_rehabilitation_credit(action)
        touch(action)

    common.refresh_account(account)
    _queue_after_deactivation(account, action)
    return action


def _run_cluster_cascade(account, action):
    """Escalate the linked cluster; True only on the flag-setting first crossing."""
    cluster = _linked_cluster(account)
    if cluster is None:
        return False
    recompute_cluster_aggregate(cluster)

    region = account.get("home_region_code")
    policy = policy_for_region(region)
    watchlist_threshold = int(policy.get("cluster_watchlist_threshold", 2))
    purge_threshold = float(policy.get("cluster_purge_threshold", 2400))
    escalation_enabled = bool(policy.get("escalation_enabled", True))

    if (cluster.get("status") == "OPEN"
            and (cluster.get("clustered_actor_incident_count") or 0) >= watchlist_threshold):
        cluster["status"] = "WATCHLIST"
        touch(cluster)
        # Every member link still counting toward attribution is severed.
        for link in STORE.cluster_links(cluster.get("id")):
            if link.get("link_status") in ("LINKED", "DORMANT"):
                link["link_status"] = "SEVERED"
                touch(link)
        return True

    if cluster.get("status") == "WATCHLIST":
        if (cluster.get("aggregate_cluster_risk") or 0) >= purge_threshold \
                and account.get("risk_tier") in ("TIER_HIGH", "TIER_SEVERE") \
                and escalation_enabled:
            cluster["status"] = "BANNED"
            touch(cluster)
            _ban_cluster_members(cluster)
    return False


def _ban_cluster_members(cluster):
    """Every member account still reachable becomes deactivation-eligible."""
    for account_id in STORE.cluster_member_accounts(cluster.get("id")):
        account = STORE.accounts.get(account_id)
        if account is None or account.get("status") != "ACTIVE":
            continue
        create_standalone_deactivation(account, now())


def _linked_cluster(account):
    cluster = resolve_cluster_for_account(account.get("id"))
    if cluster is not None:
        return cluster
    for link in STORE.account_links(account.get("id")):
        candidate = STORE.clusters.get(link.get("device_cluster_id"))
        if candidate is not None:
            return candidate
    return None


def _queue_after_deactivation(account, action):
    if action is not None and action.get("outcome") != "DEACTIVATED":
        return
    if (account.get("deactivation_count") or 0) >= 2:
        common.queue_consumer_report(account)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def standing_actions(account_id):
    return [a for a in STORE.account_actions(account_id)
            if a.get("enforcement_status") in STANDING_STATUSES]


def appeal_is_in_flight(account_id, exclude_action_id=None):
    """Is an enforcement action in flight for this account?

    PRD §3.4 names the statuses verbatim: an action sitting at `ACTIVE`,
    `MANDATORY_REPORTED` or `APPEAL_PENDING` puts an appeal in flight. The
    reading is confined to the deactivating actions, because the same paragraph
    renders the repeat-offender path -- a decision against an incident whose
    account "currently sits at `RESTRICTED` from an earlier matter" -- which is
    only reachable while that earlier, non-deactivating action is still
    standing, and which the prohibition therefore cannot be read to cover.

    PRD §3.4 lists the in-flight statuses as `ACTIVE`, `MANDATORY_REPORTED` and
    `APPEAL_PENDING`, but the same paragraph also renders the repeat-offender
    path — "A decision may also be committed against an incident at
    `PENDING_DECISION` whose account currently sits at `RESTRICTED` from an
    earlier matter" — which is only reachable while that earlier action is still
    standing. The only reading that keeps both sentences true counts the
    deactivating actions; an earlier `WARNING`/`RESTRICTED` matter leaves the
    account `RESTRICTED` and does not put a deactivation in flight.
    """
    for action in STORE.account_actions(account_id):
        if action.get("id") == exclude_action_id:
            continue
        if action.get("enforcement_status") in STANDING_STATUSES \
                and action.get("outcome") == "DEACTIVATED":
            return True
    return False


def assert_no_in_flight_appeal(account, exclude_action_id=None):
    if appeal_is_in_flight(account.get("id"), exclude_action_id=exclude_action_id):
        raise ApiError(*ERR_IN_FLIGHT_APPEAL,
                       message="The account carries an in-flight appeal.")


def reevaluate_cluster_escalation(account):
    """Re-read the purge edge after an account-level risk adjustment.

    An adjustment outside the propagation rule (a `CLEAR`/`INCONCLUSIVE`
    adjudication, PRD §2.4) moves a member's score and tier, so the
    watchlisted-to-banned edge is re-evaluated against the adjusted tier.
    """
    cluster = _linked_cluster(account)
    if cluster is None or cluster.get("status") != "WATCHLIST":
        return None
    policy = policy_for_region(account.get("home_region_code"))
    purge_threshold = float(policy.get("cluster_purge_threshold", 2400))
    escalation_enabled = bool(policy.get("escalation_enabled", True))
    if (cluster.get("aggregate_cluster_risk") or 0) >= purge_threshold \
            and account.get("risk_tier") in ("TIER_HIGH", "TIER_SEVERE") \
            and escalation_enabled:
        cluster["status"] = "BANNED"
        touch(cluster)
        _ban_cluster_members(cluster)
    return cluster


def blocked_report_for_incident(incident_id):
    for report in STORE.reports_for_incident(incident_id):
        if report.get("report_status") == "BLOCKED":
            return report
    return None


def assert_report_not_blocked(incident_id):
    if blocked_report_for_incident(incident_id) is not None:
        raise ApiError(*ERR_REGULATOR_REPORT_BLOCKED,
                       message="The linked regulator report is blocked.")


def assert_monthly_cap_available(account):
    """Only the screening-adjudication path refuses on an exhausted cap."""
    region = account.get("home_region_code")
    if STORE.monthly_report_cap.get(region, 10) <= 0:
        raise ApiError(*ERR_MONTHLY_REPORT_CAP_REACHED,
                       message="The monthly safety-report cap is exhausted.")


def incident_action(incident_id):
    return STORE.action_for_incident(incident_id)