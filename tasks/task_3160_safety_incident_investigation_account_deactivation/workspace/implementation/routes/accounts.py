"""Account provisioning, retrieval and the account-scoped collections."""

from flask import Blueprint, request

from db import STORE, add_days
from errors import ApiError, ERR_RESOURCE_NOT_FOUND
from middleware import body, new_id, route, stamp, touch
from response import created, read_pagination, success, success_list
from serializers import account as serialize_account
from serializers import background_check as serialize_check
from serializers import enforcement_action as serialize_action
from serializers import incident as serialize_incident
from serializers import trip as serialize_trip
from services import common

RESCREEN_INTERVAL_DAYS = 548

bp = Blueprint("accounts", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead",
               "SafetyAppealReviewer", "RegulatorLiaison", "BackgroundReviewer")


def get_account(account_id):
    account = STORE.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such account: %s" % account_id)
    return account


@bp.route("/safety/accounts", methods=["POST"])
@route("PlatformAdmin")
def create_account(ident):
    payload = body()
    region_code = payload.get("home_region_code")
    policy = common.policy_for_region(region_code)
    generation = int(policy.get("knob_generation_index", 0))

    account = {
        "id": new_id(),
        "account_type": payload.get("account_type"),
        "home_region_code": region_code,
        "legal_name": payload.get("legal_name"),
        "contact_email": payload.get("contact_email"),
        "status": "ACTIVE",
        "safety_posture": "OPEN",
        "risk_score": 0,
        "risk_tier": "TIER_LOW",
        "standing_enforcement_count": 0,
        "deactivation_count": 0,
        "three_year_drift_last_run_index": generation,
        "prior_reinstatement_count": 0,
        "policy_generation_index": generation,
        "_announcements_suppressed": False,
    }
    stamp(account)
    STORE.accounts[account["id"]] = account

    if account.get("account_type") == "DRIVER":
        _synthesize_continuous_monitor(account, generation)

    return created(serialize_account(account))


def _synthesize_continuous_monitor(account, generation):
    check = {
        "id": new_id(),
        "account_id": account.get("id"),
        "check_kind": "CONTINUOUS_MONITOR",
        # PRD §2.8: a RESCREEN record is anchored on the account's created_at
        # plus the per-drift-step interval. The synthesized CONTINUOUS_MONITOR
        # record is stamped the same way so its due date, and therefore the
        # acknowledgement window derived from it, is a well-defined instant.
        "scheduled_due_at": add_days(account.get("created_at"), RESCREEN_INTERVAL_DAYS),
        "trigger_source": "CONTINUOUS",
        "triggered_by_incident_id": None,
        "completed_at": None,
        "adjudication": "PENDING",
        "adverse_reason_code": None,
        "monitor_generation": generation,
        "check_status": "SCHEDULED",
    }
    stamp(check)
    STORE.background_checks[check["id"]] = check
    return check


@bp.route("/safety/accounts", methods=["GET"])
@route(*_READ_ROLES)
def list_accounts(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.accounts.values())

    def keep(account):
        for field in ("status", "account_type", "home_region_code", "risk_tier"):
            wanted = request.args.get(field)
            if wanted is not None and account.get(field) != wanted:
                return False
        return True

    items = [a for a in items if keep(a)]
    items.sort(key=lambda a: (a.get("created_at"), a.get("id") or ""))
    return success_list([serialize_account(a) for a in items], limit, offset)


@bp.route("/safety/accounts/<account_id>", methods=["GET"])
@route(*_READ_ROLES, "Rider", "Driver")
def get_one_account(ident, account_id):
    return success(serialize_account(get_account(account_id)))


@bp.route("/safety/accounts/<account_id>/trips", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator")
def list_account_trips(ident, account_id):
    get_account(account_id)
    limit, offset = read_pagination(request.args)
    items = STORE.account_trips(account_id)
    items.sort(key=lambda t: (t.get("created_at"), t.get("id") or ""))
    return success_list([serialize_trip(t) for t in items], limit, offset)


@bp.route("/safety/accounts/<account_id>/enforcement-actions", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead", "SafetyAppealReviewer")
def list_account_actions(ident, account_id):
    get_account(account_id)
    limit, offset = read_pagination(request.args)
    items = STORE.account_actions(account_id)
    items.sort(key=lambda a: (a.get("created_at"), a.get("id") or ""))
    return success_list([serialize_action(a) for a in items], limit, offset)


@bp.route("/safety/accounts/<account_id>/background-checks", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "BackgroundReviewer")
def list_account_checks(ident, account_id):
    get_account(account_id)
    limit, offset = read_pagination(request.args)
    items = STORE.account_checks(account_id)

    def keep(check):
        for field in ("check_kind", "check_status"):
            wanted = request.args.get(field)
            if wanted is not None and check.get(field) != wanted:
                return False
        return True

    items = [c for c in items if keep(c)]
    items.sort(key=lambda c: (c.get("created_at"), c.get("id") or ""))
    return success_list([serialize_check(c) for c in items], limit, offset)


@bp.route("/safety/accounts/<account_id>/incidents", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead", "SafetyAppealReviewer")
def list_account_incidents(ident, account_id):
    get_account(account_id)
    limit, offset = read_pagination(request.args)
    items = STORE.account_incidents(account_id)
    wanted_severity = request.args.get("severity")
    if wanted_severity is not None:
        items = [i for i in items if i.get("severity") == wanted_severity]
    items.sort(key=lambda i: (i.get("created_at"), i.get("id") or ""))
    return success_list([serialize_incident(i) for i in items], limit, offset)