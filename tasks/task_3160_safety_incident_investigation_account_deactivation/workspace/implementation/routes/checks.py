"""Background screening reviews and the rescreen cadence."""

from flask import Blueprint, request

from db import STORE, add_days, now
from errors import ApiError, ERR_ADVERSE_REASON_REQUIRED, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND
from middleware import body, new_id, route, stamp, touch
from response import read_pagination, success, success_list
from serializers import background_check as serialize_check
from calculations import drift_step, projected_rescreen_due_at, rescreen_anchor
from services import common, enforcement

bp = Blueprint("checks", __name__)

_READ_ROLES = ("PlatformAdmin", "BackgroundReviewer", "SafetyOperationsLead")


def get_check(check_id):
    check = STORE.background_checks.get(check_id)
    if check is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such background check: %s" % check_id)
    return check


@bp.route("/safety/background-checks", methods=["GET"])
@route(*_READ_ROLES)
def list_checks(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.background_checks.values())

    def keep(check):
        for field in ("account_id", "check_kind", "check_status", "triggered_by_incident_id"):
            wanted = request.args.get(field)
            if wanted is not None and check.get(field) != wanted:
                return False
        return True

    items = [c for c in items if keep(c)]
    items.sort(key=lambda c: (c.get("created_at"), c.get("id") or ""))
    return success_list([serialize_check(c) for c in items], limit, offset)


@bp.route("/safety/background-checks/<check_id>", methods=["GET"])
@route(*_READ_ROLES)
def get_one_check(ident, check_id):
    return success(serialize_check(get_check(check_id)))


@bp.route("/safety/background-checks/<check_id>/acknowledge", methods=["POST"])
@route("BackgroundReviewer")
def acknowledge(ident, check_id):
    check = get_check(check_id)
    if check.get("check_status") != "SCHEDULED":
        raise ApiError(*ERR_INVALID_STATE,
                       message="A review may only be acknowledged from SCHEDULED.")

    account = STORE.accounts.get(check.get("account_id")) or {}
    policy = common.policy_for_region(account.get("home_region_code"))
    deadline_days = int(policy.get("continuous_monitor_ack_deadline_days", 7))
    due_at = check.get("scheduled_due_at")
    if due_at is not None and now() < add_days(due_at, -deadline_days):
        raise ApiError(*ERR_INVALID_STATE,
                       message="The review is not yet due for acknowledgement.")

    check["check_status"] = "IN_REVIEW"
    touch(check)
    _decrement_unacknowledged(account.get("home_region_code"))
    return success(serialize_check(check))


def _decrement_unacknowledged(region_code):
    """The region's unacknowledged-review count is a server-side aggregate."""
    pending = [c for c in STORE.checks_in_region(region_code)
               if c.get("check_status") == "SCHEDULED"]
    STORE.monthly_report_cap.setdefault(region_code, 10)
    return len(pending)


@bp.route("/safety/background-checks/<check_id>/adjudicate", methods=["POST"])
@route("BackgroundReviewer")
def adjudicate(ident, check_id):
    check = get_check(check_id)
    if check.get("check_status") != "IN_REVIEW":
        raise ApiError(*ERR_INVALID_STATE,
                       message="A review may only be adjudicated from IN_REVIEW.")

    payload = body()
    adjudication = payload.get("adjudication")
    if adjudication not in ("CLEAR", "ADVERSE", "INCONCLUSIVE"):
        raise ApiError(*ERR_INVALID_STATE,
                       message="adjudication must be CLEAR, ADVERSE or INCONCLUSIVE.")
    if adjudication == "ADVERSE" and payload.get("adverse_reason_code") is None:
        raise ApiError(*ERR_ADVERSE_REASON_REQUIRED,
                       message="An ADVERSE verdict requires an adverse_reason_code.")

    account = STORE.accounts.get(check.get("account_id"))
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND, message="No such account.")

    if adjudication == "ADVERSE":
        # The same in-flight-appeal and monthly-cap refusals guard this path.
        enforcement.assert_no_in_flight_appeal(account)
        enforcement.assert_monthly_cap_available(account)

    check["adjudication"] = adjudication
    check["adverse_reason_code"] = payload.get("adverse_reason_code")
    check["completed_at"] = now()
    check["check_status"] = "COMPLETED"
    touch(check)

    if adjudication == "ADVERSE":
        from services import enforcement as enforcement_service
        enforcement_service.create_standalone_deactivation(account, check.get("completed_at"))
    elif adjudication == "INCONCLUSIVE":
        _apply_risk_adjustment(account, 30.0)
    else:
        _apply_risk_adjustment(account, -15.0, floor=0.0)

    return success(serialize_check(check))


def _apply_risk_adjustment(account, delta, floor=None):
    """The ancillary adjudication adjustment of PRD §2.4.

    A `CLEAR` verdict subtracts 15 and an `INCONCLUSIVE` one adds 30; the two sit
    *outside* the propagation rule, so the adjustment is applied on top of the
    account's propagated score and the tier, the linked cluster aggregate and the
    escalation edge are then re-derived from that adjusted figure.
    """
    from calculations import recompute_linked_clusters, tier_with_escape_hatch
    from services import enforcement as enforcement_service

    adjusted = round((account.get("risk_score") or 0) + delta, 2)
    if floor is not None:
        adjusted = max(floor, adjusted)
    adjusted = max(0.0, min(1000.0, adjusted))
    account["risk_score"] = adjusted
    account["risk_tier"] = tier_with_escape_hatch(account.get("id"), adjusted)
    touch(account)
    # The member's new score changes every cluster aggregate it appears in, and
    # the purge edge is re-evaluated against the adjusted tier.
    recompute_linked_clusters(account.get("id"))
    enforcement_service.reevaluate_cluster_escalation(account)
    return account


@bp.route("/safety/background-checks/rescreen-sweep", methods=["POST"])
@route("SafetyOperationsLead")
def rescreen_sweep(ident):
    instant = now()
    raised = []
    for account in list(STORE.accounts.values()):
        if account.get("account_type") != "DRIVER":
            continue
        if account.get("status") not in ("ACTIVE", "RESTRICTED", "UNDER_HOLD"):
            continue
        policy = common.policy_for_region(account.get("home_region_code"))
        generation = int(policy.get("review_generation_index", 1))
        refresh_days = int(policy.get("rescreen_refresh_days", 548))
        anchor = rescreen_anchor(account.get("id"))
        if anchor is None:
            continue
        due_at = add_days(anchor, (drift_step(generation) + 1) * refresh_days)
        if instant < due_at:
            continue

        check = {
            "id": new_id(),
            "account_id": account.get("id"),
            "check_kind": "RESCREEN",
            "scheduled_due_at": due_at,
            "trigger_source": "CADENCE",
            "triggered_by_incident_id": None,
            "completed_at": None,
            "adjudication": "PENDING",
            "adverse_reason_code": None,
            "monitor_generation": generation,
            "check_status": "SCHEDULED",
        }
        stamp(check)
        STORE.background_checks[check["id"]] = check
        raised.append(check)

        account["three_year_drift_last_run_index"] = generation
        touch(account)
        # The account's open continuous-monitor record stays in step.
        for existing in STORE.account_checks(account.get("id")):
            if existing.get("check_kind") == "CONTINUOUS_MONITOR" \
                    and existing.get("check_status") != "COMPLETED":
                existing["monitor_generation"] = generation
                touch(existing)

    raised.sort(key=lambda c: (c.get("created_at"), c.get("id") or ""))
    return success_list([serialize_check(c) for c in raised], 100, 0)