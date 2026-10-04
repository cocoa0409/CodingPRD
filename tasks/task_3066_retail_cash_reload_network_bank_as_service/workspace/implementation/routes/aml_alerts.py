"""AML alert endpoints and the alert adjudication machine."""

from flask import Blueprint, request

import calc
import db
import errors
import middleware
import requests_helpers as rh
import response
import services.core as core
import timeutil

bp = Blueprint("aml_alerts", __name__)

READ_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
    "SettlementOperator",
)
LIST_ROLES = (
    "PlatformAdmin",
    "BankSponsor",
    "ProgramManager",
    "ComplianceAnalyst",
    "ComplianceOfficer",
)


@bp.post("/v1/aml-alerts")
def raise_alert():
    middleware.authenticate(("ComplianceAnalyst",))
    data = rh.body()
    program_id = rh.require_str(data, "program_id")
    account_id = rh.require_str(data, "card_account_id")
    alert_type = rh.require_enum(data, "alert_type", ("VELOCITY", "STRUCTURING"))
    window_start_at = rh.require_datetime(data, "window_start_at")
    window_end_at = rh.require_datetime(data, "window_end_at")
    note = rh.optional(data, "resolution_note")

    program = core.ref_program(program_id)
    account = core.ref_account(account_id)
    if account["program_id"] != program["id"]:
        raise errors.referenced_not_found(
            "card_account_id does not belong to the named program."
        )
    core.guard_not_frozen(program)

    if alert_type == "STRUCTURING":
        _, _, is_structuring = calc.structuring_trip(core.account_loads(account), timeutil.now())
        if not is_structuring:
            raise errors.structuring_suspected(
                "The account does not satisfy the structuring predicate."
            )

    alert = core.build_alert(
        program,
        account,
        alert_type,
        window_start_at,
        window_end_at,
        raised_by_analyst_id=request.headers.get(middleware.USER_ID_HEADER),
        resolution_note=note,
    )
    core.recompute_program(program)
    return response.ok(core.public(core.AML_ALERT, alert), 201)


@bp.get("/v1/aml-alerts/<alert_id>")
def get_alert(alert_id):
    middleware.authenticate(READ_ROLES)
    return response.ok(core.public(core.AML_ALERT, core.get_alert(alert_id)))


@bp.get("/v1/aml-alerts")
def list_alerts():
    middleware.authenticate(LIST_ROLES)
    limit, offset = rh.pagination()
    rows = core.loads_of(
        db.aml_alerts,
        program_id=request.args.get("program_id"),
        card_account_id=request.args.get("card_account_id"),
        alert_status=request.args.get("alert_status"),
    )
    total = len(rows)
    return response.array(
        core.public_list(core.AML_ALERT, rows[offset : offset + limit]), limit, offset, total
    )


def _program_of(alert):
    return core.get_program(alert["program_id"])


@bp.post("/v1/aml-alerts/<alert_id>/review")
def review_alert(alert_id):
    user_id, role = middleware.authenticate(("ComplianceAnalyst",))
    alert = core.get_alert(alert_id)
    data = rh.body()
    if alert["alert_status"] != "OPEN":
        raise errors.invalid_state(
            "An alert in status %s cannot be taken into review." % alert["alert_status"]
        )
    alert["alert_status"] = "UNDER_REVIEW"
    alert["assigned_analyst_id"] = user_id
    if "resolution_note" in data:
        alert["resolution_note"] = rh.optional(data, "resolution_note")
    core.touch(alert)
    return response.ok(core.public(core.AML_ALERT, alert))


@bp.post("/v1/aml-alerts/<alert_id>/return")
def return_alert(alert_id):
    middleware.authenticate(("ComplianceAnalyst",))
    alert = core.get_alert(alert_id)
    if alert["alert_status"] != "UNDER_REVIEW":
        raise errors.invalid_state(
            "An alert in status %s cannot be returned." % alert["alert_status"]
        )
    alert["alert_status"] = "OPEN"
    alert["assigned_analyst_id"] = None
    core.touch(alert)
    return response.ok(core.public(core.AML_ALERT, alert))


@bp.post("/v1/aml-alerts/<alert_id>/confirm")
def confirm_alert(alert_id):
    user_id, role = middleware.authenticate(("ComplianceOfficer",))
    alert = core.get_alert(alert_id)
    rh.body()
    if alert["alert_status"] != "UNDER_REVIEW":
        raise errors.invalid_state(
            "An alert in status %s cannot be confirmed." % alert["alert_status"]
        )
    if user_id == alert["raised_by_analyst_id"] or user_id == alert["assigned_analyst_id"]:
        raise errors.segregation_of_duties(
            "The confirming principal raised or worked this alert."
        )

    program = _program_of(alert)
    account = core.get_account(alert["card_account_id"])

    # hop 1
    alert["alert_status"] = "CONFIRMED"
    alert["confirmed_by_analyst_id"] = user_id
    core.touch(alert)

    # hop 2
    account = core.get_account(alert["card_account_id"])
    account["compliance_hold_status"] = "FROZEN"
    account["frozen_at"] = timeutil.now()
    core.touch(account)

    # hop 3
    reversed_ids = []
    for load in core.account_loads(account):
        if load["load_status"] == "FUNDED":
            core.reverse_load(load, "AML_CONFIRMED", finalize=False)
            reversed_ids.append(load["id"])
    core.dismiss_stale_alerts(account)

    # hop 4
    core.recover_allocations_for(reversed_ids)

    # hop 5
    core.recompute_program(program)
    core.touch(program)
    return response.ok(core.public(core.AML_ALERT, alert))


@bp.post("/v1/aml-alerts/<alert_id>/reopen")
def reopen_alert(alert_id):
    middleware.authenticate(("ComplianceOfficer",))
    alert = core.get_alert(alert_id)
    rh.body()
    if alert["alert_status"] != "CONFIRMED":
        raise errors.invalid_state(
            "An alert in status %s cannot be reopened." % alert["alert_status"]
        )
    program = _program_of(alert)
    alert["alert_status"] = "UNDER_REVIEW"
    alert["confirmed_by_analyst_id"] = None
    core.touch(alert)
    core.recompute_program(program)
    core.touch(program)
    return response.ok(core.public(core.AML_ALERT, alert))


@bp.post("/v1/aml-alerts/<alert_id>/dismiss")
def dismiss_alert(alert_id):
    middleware.authenticate(("ComplianceOfficer",))
    alert = core.get_alert(alert_id)
    rh.body()
    if alert["alert_status"] != "UNDER_REVIEW":
        raise errors.invalid_state(
            "An alert in status %s cannot be dismissed." % alert["alert_status"]
        )
    program = _program_of(alert)
    alert["alert_status"] = "DISMISSED"
    core.touch(alert)
    core.recompute_program(program)
    core.touch(program)
    return response.ok(core.public(core.AML_ALERT, alert))