"""Location performance reallocation (PRD 3.9)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

DECISION_STATUSES = ("PROPOSED", "APPROVED", "APPLIED", "REJECTED")


def _window_ok(campaign, effective_on):
    starts_on = clock.parse(campaign.get("starts_on"))
    ends_on = clock.parse(campaign.get("ends_on"))
    if starts_on is None or ends_on is None:
        return False
    return starts_on <= effective_on <= ends_on


def _location_cents_per_hour(location):
    return int(location.get("cents_per_hour", 0) or 0)


@bp.route("/reallocation-decisions", methods=["POST"])
def create_reallocation_decision():
    require_role(["KettleCoordinator", "CorpsOfficer", "DivisionalOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("campaign_id", validate.STRING, required=True),
            validate.f("from_location_id", validate.STRING, required=True),
            validate.f("to_location_id", validate.STRING, required=True),
            validate.f("moved_hours", validate.NUMBER, required=True),
            validate.f("effective_on", validate.DATETIME, required=True),
            validate.f("rationale", validate.STRING, required=True),
        ]
    )
    campaign = validate.reference("campaigns", values["campaign_id"], "campaign")
    source = validate.reference("kettle_locations", values["from_location_id"], "kettle location")
    target = validate.reference("kettle_locations", values["to_location_id"], "kettle location")
    if source.get("campaign_id") != values["campaign_id"] or target.get("campaign_id") != values["campaign_id"]:
        validate.scope_mismatch("Both kettle locations must belong to the addressed campaign.")

    effective_on = values["effective_on"]
    if not _window_ok(campaign, effective_on):
        raise ApiError("ERR_REALLOCATION_WINDOW_INVALID")

    decision = {
        "campaign_id": values["campaign_id"],
        "from_location_id": source["id"],
        "to_location_id": target["id"],
        "moved_hours": values["moved_hours"],
        "effective_on": clock.fmt(effective_on),
        "rationale": values["rationale"],
        "status": "PROPOSED",
        "expected_lift_cents": calcs.expected_lift(
            values["moved_hours"], _location_cents_per_hour(source), _location_cents_per_hour(target)
        ),
        "applied_at": None,
    }
    store.insert("reallocation_decisions", decision)
    return success(store.public(decision)), 201


@bp.route("/reallocation-decisions", methods=["GET"])
def list_reallocation_decisions():
    require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "CorpsOfficer",
            "DivisionalOfficer",
            "TerritorialCommander",
            "FinanceOfficer",
        ]
    )
    args = request.args
    rows = store.ordered("reallocation_decisions")
    for field in ("campaign_id", "from_location_id", "to_location_id", "status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/reallocation-decisions/<decision_id>", methods=["GET"])
def get_reallocation_decision(decision_id):
    require_role(
        [
            "PlatformAdmin",
            "KettleCoordinator",
            "CorpsOfficer",
            "DivisionalOfficer",
            "TerritorialCommander",
            "FinanceOfficer",
        ]
    )
    decision = validate.path_row("reallocation_decisions", decision_id, "reallocation decision")
    return success(store.public(decision))


@bp.route("/reallocation-decisions/<decision_id>/approve", methods=["POST"])
def approve_reallocation_decision(decision_id):
    require_role(["TerritorialCommander", "DivisionalOfficer", "PlatformAdmin"])
    decision = validate.path_row("reallocation_decisions", decision_id, "reallocation decision")
    status = decision.get("status")
    if status in ("APPLIED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if decision.get("from_location_id") == decision.get("to_location_id"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The source and target must differ.")
    target = store.find("kettle_locations", decision.get("to_location_id"))
    if target is None or target.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")

    campaign = store.find("campaigns", decision.get("campaign_id"))
    effective_on = clock.parse(decision.get("effective_on"))
    if campaign is None or effective_on is None or not _window_ok(campaign, effective_on):
        raise ApiError("ERR_REALLOCATION_WINDOW_INVALID")
    if effective_on < clock.now():
        raise ApiError("ERR_REALLOCATION_WINDOW_INVALID")

    source = store.find("kettle_locations", decision.get("from_location_id"))
    decision["expected_lift_cents"] = calcs.expected_lift(
        decision.get("moved_hours", 0),
        _location_cents_per_hour(source) if source is not None else 0,
        _location_cents_per_hour(target),
    )
    decision["status"] = "APPROVED"
    store.touch(decision)
    return success(store.public(decision))


@bp.route("/reallocation-decisions/<decision_id>/reject", methods=["POST"])
def reject_reallocation_decision(decision_id):
    require_role(["TerritorialCommander", "DivisionalOfficer", "PlatformAdmin"])
    validate.shape([validate.f("reason", validate.STRING)])
    decision = validate.path_row("reallocation_decisions", decision_id, "reallocation decision")
    status = decision.get("status")
    if status in ("APPLIED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    decision["status"] = "REJECTED"
    store.touch(decision)
    return success(store.public(decision))


@bp.route("/reallocation-decisions/<decision_id>/revise", methods=["POST"])
def revise_reallocation_decision(decision_id):
    require_role(["KettleCoordinator", "DivisionalOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("moved_hours", validate.NUMBER, required=True),
            validate.f("effective_on", validate.DATETIME),
        ]
    )
    decision = validate.path_row("reallocation_decisions", decision_id, "reallocation decision")
    status = decision.get("status")
    if status in ("APPLIED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if values["moved_hours"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "moved_hours must be greater than zero.")

    decision["status"] = "PROPOSED"
    decision["moved_hours"] = values["moved_hours"]
    if values.get("effective_on") is not None:
        campaign = store.find("campaigns", decision.get("campaign_id"))
        if campaign is None or not _window_ok(campaign, values["effective_on"]):
            raise ApiError("ERR_REALLOCATION_WINDOW_INVALID")
        decision["effective_on"] = clock.fmt(values["effective_on"])
    store.touch(decision)
    return success(store.public(decision))


@bp.route("/reallocation-decisions/<decision_id>/apply", methods=["POST"])
def apply_reallocation_decision(decision_id):
    require_role(["KettleCoordinator", "DivisionalOfficer", "PlatformAdmin"])
    decision = validate.path_row("reallocation_decisions", decision_id, "reallocation decision")
    status = decision.get("status")
    if status in ("APPLIED", "REJECTED"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    campaign = store.find("campaigns", decision.get("campaign_id"))
    if campaign is None or campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")

    effective_on = clock.parse(decision.get("effective_on"))
    if effective_on is None or not (clock.now() >= effective_on):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The effective instant has not been reached.")

    source = store.find("kettle_locations", decision.get("from_location_id"))
    target = store.find("kettle_locations", decision.get("to_location_id"))
    if source is None or target is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "A referenced kettle location does not exist.")

    moved_hours = float(decision.get("moved_hours", 0) or 0)
    remaining = calcs.location_remaining_scheduled_hours(source["id"])
    if moved_hours > remaining + 1e-9:
        raise ApiError("ERR_REALLOCATION_HOURS_EXCEED_SOURCE")

    moved_minutes = int(round(moved_hours * 60))
    source["daily_required_minutes"] = int(source.get("daily_required_minutes", 0) or 0) - moved_minutes
    target["daily_required_minutes"] = int(target.get("daily_required_minutes", 0) or 0) + moved_minutes
    decision["status"] = "APPLIED"
    decision["applied_at"] = clock.now_iso()
    store.touch(decision)
    calcs.recompute_location(source)
    calcs.recompute_location(target)
    return success(store.public(decision))
