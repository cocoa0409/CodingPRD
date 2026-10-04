"""Bell ringers: registration, screening and engagement (PRD 3.3)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import owner_guard, require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

RINGER_TYPES = ("VOLUNTEER", "PAID_SEASONAL")
SCREENING_STATUSES = ("NOT_STARTED", "PENDING", "CLEARED", "FAILED", "EXPIRED")
ENGAGEMENT_STATUSES = ("ACTIVE", "SUSPENDED", "SEPARATED")
SCREENING_RESULTS = ("CLEAR", "FAIL")


def screening_valid_for(ringer, starts_at):
    if ringer.get("screening_status") != "CLEARED":
        return False
    expires = clock.parse(ringer.get("screening_expires_at"))
    if expires is None:
        return False
    return expires > starts_at


def expire_screening(ringer):
    """CLEARED -> EXPIRED once the clock passes screening_expires_at."""
    expiry = clock.parse(ringer.get("screening_expires_at"))
    ringer["screening_status"] = "EXPIRED"
    store.touch(ringer)
    for shift in store.rows("shifts"):
        if shift.get("bell_ringer_id") != ringer["id"]:
            continue
        if shift.get("status") not in ("SCHEDULED", "CONFIRMED"):
            continue
        start = clock.parse(shift.get("starts_at"))
        if start is None or not (start > expiry):
            continue
        shift["_prev_status"] = shift.get("status")
        shift["status"] = "CANCELLED"
        store.touch(shift)
        calcs.recompute_scheduled_hours(ringer)
    return ringer


def apply_clock_events(ringer):
    if ringer.get("screening_status") != "CLEARED":
        return ringer
    expiry = clock.parse(ringer.get("screening_expires_at"))
    if expiry is not None and clock.now() > expiry:
        expire_screening(ringer)
    return ringer


def cancel_ringer_shifts(ringer):
    for shift in store.rows("shifts"):
        if shift.get("bell_ringer_id") != ringer["id"]:
            continue
        if shift.get("status") in ("SCHEDULED", "CONFIRMED"):
            shift["_prev_status"] = shift.get("status")
            shift["status"] = "CANCELLED"
            store.touch(shift)
    calcs.recompute_scheduled_hours(ringer)


@bp.route("/bell-ringers", methods=["POST"])
def create_bell_ringer():
    require_role(["VolunteerCoordinator", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("full_name", validate.STRING, required=True),
            validate.f("email", validate.STRING, required=True),
            validate.f("ringer_type", validate.ENUM, required=True, enum=RINGER_TYPES),
            validate.f("corps_id", validate.STRING, required=True),
            validate.f("date_of_birth", validate.DATETIME, required=True),
            validate.f("hourly_rate_cents", validate.INTEGER),
        ]
    )
    validate.reference("units", values["corps_id"], "corps unit")
    ringer = {
        "full_name": values["full_name"],
        "email": values["email"],
        "ringer_type": values["ringer_type"],
        "corps_id": values["corps_id"],
        "date_of_birth": clock.fmt(values["date_of_birth"]),
        "screening_status": "NOT_STARTED",
        "screening_expires_at": None,
        "engagement_status": "ACTIVE",
        "reliability_score": 100,
        "hourly_rate_cents": int(values.get("hourly_rate_cents", 0) or 0),
        "scheduled_hours": 0,
    }
    store.insert("bell_ringers", ringer)
    return success(store.public(ringer)), 201


@bp.route("/bell-ringers", methods=["GET"])
def list_bell_ringers():
    require_role(
        [
            "PlatformAdmin",
            "VolunteerCoordinator",
            "CorpsOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
        ]
    )
    args = request.args
    rows = store.ordered("bell_ringers")
    for field in ("corps_id", "screening_status", "engagement_status", "ringer_type"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/bell-ringers/<ringer_id>", methods=["GET"])
def get_bell_ringer(ringer_id):
    require_role(
        [
            "PlatformAdmin",
            "VolunteerCoordinator",
            "CorpsOfficer",
            "KettleCoordinator",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
            "BellRinger",
        ]
    )
    ringer = validate.path_row("bell_ringers", ringer_id, "bell ringer")
    apply_clock_events(ringer)
    return success(store.public(ringer))


@bp.route("/bell-ringers/<ringer_id>/screenings", methods=["POST"])
def submit_screening(ringer_id):
    role, user_id = require_role(["VolunteerCoordinator", "CorpsOfficer", "PlatformAdmin"])
    validate.shape(
        [
            validate.f("vendor", validate.STRING, required=True),
            validate.f("package_level", validate.STRING, required=True),
        ]
    )
    ringer = validate.path_row("bell_ringers", ringer_id, "bell ringer")
    owner_guard(role, user_id, ringer.get("corps_id"))

    status = ringer.get("screening_status")
    if status == "FAILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if status not in ("NOT_STARTED", "EXPIRED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if ringer.get("engagement_status") == "SEPARATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    ringer["screening_status"] = "PENDING"
    store.touch(ringer)
    return success(store.public(ringer))


@bp.route("/bell-ringers/<ringer_id>/screenings/complete", methods=["POST"])
def complete_screening(ringer_id):
    role, user_id = require_role(["VolunteerCoordinator", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("result", validate.ENUM, required=True, enum=SCREENING_RESULTS),
            validate.f("completed_at", validate.DATETIME, required=True),
        ]
    )
    ringer = validate.path_row("bell_ringers", ringer_id, "bell ringer")
    owner_guard(role, user_id, ringer.get("corps_id"))

    if ringer.get("screening_status") != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if values["result"] == "CLEAR":
        completed_at = values["completed_at"]
        if completed_at > clock.now():
            raise ApiError("ERR_INVALID_STATE_TRANSITION", "completed_at may not lie in the future.")
        ringer["screening_status"] = "CLEARED"
        ringer["screening_expires_at"] = clock.fmt(completed_at + clock.days(365))
        if ringer.get("engagement_status") == "SUSPENDED":
            ringer["engagement_status"] = "ACTIVE"
            ringer["reliability_score"] = calcs.SUSPENSION_THRESHOLD
        store.touch(ringer)
        return success(store.public(ringer))

    # result == FAIL
    ringer["screening_status"] = "FAILED"
    ringer["engagement_status"] = "SUSPENDED"
    store.touch(ringer)
    cancel_ringer_shifts(ringer)
    return success(store.public(ringer))


@bp.route("/bell-ringers/<ringer_id>/separate", methods=["POST"])
def separate_ringer(ringer_id):
    require_role(["VolunteerCoordinator", "PlatformAdmin"])
    ringer = validate.path_row("bell_ringers", ringer_id, "bell ringer")
    status = ringer.get("engagement_status")
    if status == "SEPARATED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    calcs.recompute_scheduled_hours(ringer)
    if float(ringer.get("scheduled_hours", 0) or 0) != 0.0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The ringer still has scheduled hours.")
    ringer["engagement_status"] = "SEPARATED"
    store.touch(ringer)
    return success(store.public(ringer))
