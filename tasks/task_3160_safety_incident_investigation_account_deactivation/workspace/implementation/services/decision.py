"""Committing the graduated decision and the appeal lifecycle."""

from db import STORE, add_days, now
from calculations import (appeal_track, proposed_decision, regulator_report_required,
                          severity_level)
from errors import (ApiError, ERR_APPEAL_ALREADY_FILED, ERR_APPEAL_NOT_ELIGIBLE,
                    ERR_APPEAL_WINDOW_CLOSED, ERR_INVALID_STATE,
                    ERR_THROWN_ON_APPEAL)
from middleware import touch
from services import common, enforcement

APPEAL_OUTCOMES = ("UPHELD", "OVERTURNED")


def decision_guards(account, incident):
    """The specialised prohibitions, asserted ahead of the shared state check."""
    # The two specialised prohibitions are asserted ahead of the shared state
    # check: a deactivation cannot be committed while the account carries an
    # action whose appeal is still in flight, and the mandatory-report gate
    # refuses the write while the linked report still sits BLOCKED -- which is
    # also what makes the blocked branch of §3.5 a genuine dead end.
    enforcement.assert_no_in_flight_appeal(account)
    enforcement.assert_report_not_blocked(incident.get("id"))

    # PRD §3.4 declares the decision from `PENDING_DECISION`, and adds the
    # repeat-offender path for an incident at `PENDING_DECISION` whose account is
    # `RESTRICTED` from an earlier matter.
    if incident.get("incident_status") != "PENDING_DECISION":
        raise ApiError(*ERR_INVALID_STATE,
                       message="A decision is not declared from %s."
                               % incident.get("incident_status"))
    if account.get("status") not in ("PENDING_DECISION", "RESTRICTED"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="A decision is not declared from account status %s."
                               % account.get("status"))


def commit_decision(account, incident, payload, user_id):
    decision_guards(account, incident)

    requested_category = payload.get("decision_category")
    if requested_category is None:
        raise ApiError(*ERR_INVALID_STATE, message="decision_category is required.")

    basis = payload.get("decision_basis")
    if basis is not None and 0 < len(str(basis)) < 20:
        raise ApiError(*ERR_INVALID_STATE,
                       message="decision_basis must be at least 20 characters.")

    incident["decision_category"] = requested_category
    incident["decision_basis"] = basis
    incident["decided_at"] = now()
    incident["decision_maker_user_id"] = user_id

    beware_blocked_deactivation = (
        requested_category == "DEACTIVATED"
        and incident.get("incident_category") in ("PHYSICAL_ASSAULT", "SEXUAL_MISCONDUCT")
        and incident.get("severity") in ("S3", "S4")
        and enforcement.blocked_report_for_incident(incident.get("id")) is not None)

    if beware_blocked_deactivation:
        # The deactivating decision does not reach DECIDED at all: the incident
        # is diverted into the blocked mandatory-report branch, the account is
        # deactivated, and the linked action stays in DRAFT until the window opens.
        incident["incident_status"] = "MANDATORY_REPORTED_BLOCKED"
        touch(incident)
        report = enforcement.blocked_report_for_incident(incident.get("id"))
        if report is not None:
            report["report_status"] = "BLOCKED"
            touch(report)
        account["status"] = "DEACTIVATED"
        enforcement.create_enforcement_action(account, incident, incident["decided_at"])
        common.refresh_account(account)
        return incident

    incident["incident_status"] = "DECIDED"
    touch(incident)

    # The account's destination follows the graduated matrix; a deactivation also
    # increments deactivation_count and recomputes the account's risk in full.
    if requested_category == "DEACTIVATED":
        account["status"] = "DEACTIVATED"
    elif requested_category in ("RESTRICTED", "WARNING"):
        account["status"] = "RESTRICTED"
    else:
        account["status"] = "ACTIVE"

    enforcement.create_enforcement_action(account, incident, incident["decided_at"])
    common.refresh_account(account)
    return incident


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

def _action_for(incident):
    action = STORE.action_for_incident(incident.get("id"))
    if action is None:
        raise ApiError(*ERR_INVALID_STATE,
                       message="The incident carries no enforcement action.")
    return action


def file_appeal(incident):
    status = incident.get("incident_status")
    # The filing edges exist for all three graduated outcomes, not only for a
    # deactivating one.
    if incident.get("decision_category") not in ("WARNING", "RESTRICTED", "DEACTIVATED"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="Only a committed graduated outcome may be appealed.")

    if status == "APPEAL_PENDING" or incident.get("_appeal_committed"):
        raise ApiError(*ERR_APPEAL_ALREADY_FILED,
                       message="Exactly one appeal may be in flight per incident.")
    if status != "DECIDED":
        raise ApiError(*ERR_INVALID_STATE,
                       message="An appeal is not declared from %s." % status)

    action = _action_for(incident)
    arrival = now()
    deadline = action.get("appeal_deadline_at")
    if deadline is None or not arrival < deadline:
        raise ApiError(*ERR_APPEAL_WINDOW_CLOSED,
                       message="The appeal window has closed.")
    if action.get("enforcement_status") not in ("ACTIVE", "MANDATORY_REPORTED"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="The linked enforcement action is not appealable.")

    account = STORE.accounts.get(incident.get("account_id"))
    policy = common.policy_for_region((account or {}).get("home_region_code"))

    incident["incident_status"] = "APPEAL_PENDING"
    incident["_appeal_committed_at"] = arrival
    incident["_appeal_file_deadline"] = arrival
    incident["_appeal_file_deadline"] = add_days(arrival, int(policy.get("appeal_window_days", 30)))
    touch(incident)

    action["enforcement_status"] = "APPEAL_PENDING"
    action["last_applied_appeal_deadline"] = add_days(
        arrival, int(policy.get("appeal_window_days", 30)))
    touch(action)

    if account is not None:
        account["status"] = "APPEAL_PENDING"
        common.refresh_account(account)
    return incident


def _review_due_at(incident):
    """appeal_committed_at plus the review interval for the incident's track."""
    arrival = incident.get("_appeal_committed_at")
    if arrival is None:
        return None
    _, review_days = appeal_track(incident)
    return add_days(arrival, review_days)


def review_due_at(incident):
    return _review_due_at(incident)


def commit_appeal_outcome(incident, payload, user_id):
    if incident.get("incident_status") not in ("APPEAL_PENDING",):
        raise ApiError(*ERR_INVALID_STATE,
                       message="An appeal outcome is not declared from %s."
                               % incident.get("incident_status"))

    adjudication = payload.get("adjudication")
    if adjudication not in APPEAL_OUTCOMES:
        raise ApiError(*ERR_INVALID_STATE,
                       message="adjudication must be UPHELD or OVERTURNED.")

    # Segregation of duties: a case can never be reviewed by its decider.
    account = STORE.accounts.get(incident.get("account_id")) or {}
    policy = common.policy_for_region(account.get("home_region_code"))
    floor_armed = bool(policy.get("sd_floor_enabled", True))
    floor_severity = policy.get("sd_floor_severity", "S3")
    if (user_id == incident.get("decision_maker_user_id")
            and floor_armed
            and severity_level(floor_severity) <= severity_level(incident.get("severity"))):
        raise ApiError(*ERR_THROWN_ON_APPEAL,
                       message="The appeal reviewer must differ from the deciding "
                               "investigator.")

    action = _action_for(incident)
    credit = action.get("rehabilitation_credit") or 0

    if adjudication == "OVERTURNED" and credit < 1:
        raise ApiError(*ERR_APPEAL_NOT_ELIGIBLE,
                       message="A reinstatement requires a completed-trip credit.")

    # The review deadline is a floor on when an outcome may be committed.
    due_at = _review_due_at(incident)
    if due_at is not None and payload.get("commit_early") is not True and now() < due_at:
        raise ApiError(*ERR_APPEAL_NOT_ELIGIBLE,
                       message="The appeal review deadline has not yet arrived.")

    incident["appeal_reviewer_user_id"] = user_id
    incident["_appeal_committed"] = True
    incident["_appeal_outcome"] = adjudication

    if adjudication == "OVERTURNED":
        _apply_overturn(account, incident, action)
    else:
        _apply_uphold(account, incident, action)

    common.refresh_account(account)
    return incident


def _apply_overturn(account, incident, action):
    incident["incident_status"] = "APPEAL_OVERTURNED"
    touch(incident)

    account["status"] = "ACTIVE"
    account["prior_reinstatement_count"] = (account.get("prior_reinstatement_count") or 0) + 1

    before = action.get("enforcement_status")
    action["enforcement_status"] = "REVERTED"
    action["reinstatement_generation"] = (action.get("reinstatement_generation") or 0) + 1
    if before in ("MANDATORY_REPORTED", "ACTIVE"):
        action["rehabilitation_credit"] = max(0, (action.get("rehabilitation_credit") or 0) - 1)
    common.recompute_rehabilitation_credit(action)
    touch(action)

    common.drop_from_consumer_report(account.get("id"))
    # The risk score reverts toward its incident-free baseline; recomputing the
    # projection with the reverted ledger produces exactly that baseline.
    common.refresh_account(account)


def _apply_uphold(account, incident, action):
    if action.get("enforcement_status") == "APPEAL_PENDING":
        action["enforcement_status"] = "REVERTED"
    else:
        action["enforcement_status"] = "REVERTED"
    incident["incident_status"] = "APPEAL_UPHELD"
    touch(incident)
    account["status"] = "DEACTIVATED"
    action["rehabilitation_credit"] = max(0, (action.get("rehabilitation_credit") or 0) - 1)
    touch(action)
    common.refresh_account(account)