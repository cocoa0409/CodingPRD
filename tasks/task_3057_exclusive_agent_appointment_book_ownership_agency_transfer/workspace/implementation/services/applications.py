"""The appointment application pipeline (PRD §3.1, §3.2)."""

import middleware
from errors import ApiError, ERR_INVALID_STATE, ERR_MARKET_NEED_EXISTS
from services import calculations as calc
from services import factories, recompute

TERMINAL = ("REJECTED", "CONSUMED")


def submit(payload):
    application = factories.create_application(payload)
    return application


def list_applications(request):
    rows = list(db_application_rows())
    rows = middleware.filter_by(rows, {
        "status": request.args.get("status"),
        "agent_id": request.args.get("agent_id"),
    })
    rows.sort(key=lambda a: a["created_at"])
    return rows


def db_application_rows():
    import db
    return list(db.application_rows().values())


def assess(application):
    if application["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if application["status"] not in ("SUBMITTED", "SCORED"):
        raise ApiError(ERR_INVALID_STATE)

    if application["market_need_score"] is not None \
            and int(application["market_need_score"]) <= 40 \
            and _is_support(application):
        raise ApiError(ERR_MARKET_NEED_EXISTS)

    priority = calc.appointment_priority(application)
    application["appointment_priority"] = priority
    application["required_action"] = calc.required_action(application)
    application["application_value_tier"] = calc.application_value_tier(priority)
    application["status"] = "SCORED"
    recompute.touch(application)
    return application


def _is_support(application):
    """A territory of the support subtype; carried on the payload when supplied."""
    subtype = str(application.get("territory_subtype") or "").upper()
    return subtype == "SUPPORT"


def approve(application):
    if application["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if application["status"] != "SCORED":
        raise ApiError(ERR_INVALID_STATE)
    if application["required_action"] != "PROCEED":
        raise ApiError(ERR_INVALID_STATE)
    application["status"] = "APPROVED"
    recompute.touch(application)
    return application


def reject(application, payload):
    if application["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if application["status"] != "SCORED":
        raise ApiError(ERR_INVALID_STATE)
    application["status"] = "REJECTED"
    if payload.get("closure_note") is not None:
        application["closure_note"] = payload.get("closure_note")
    recompute.touch(application)
    return application


def appoint(application):
    if application["status"] in TERMINAL:
        if application["status"] == "CONSUMED":
            raise ApiError("ERR_ALREADY_TERMINAL")
        raise ApiError("ERR_ALREADY_TERMINAL")
    if application["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE)
    if application["required_action"] != "PROCEED":
        raise ApiError(ERR_INVALID_STATE)

    agent = factories.mint_agent_from_application(application)
    application["agent_id"] = agent["id"]
    application["status"] = "CONSUMED"
    recompute.touch(application)
    return agent