"""Shifts: scheduling, staffing gates and the shift lifecycle (PRD 3.3)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import owner_guard, require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

SHIFT_KINDS = ("REGULAR", "RELIEF", "DOUBLE")
SHIFT_STATUSES = ("SCHEDULED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
LIVE_STATUSES = ("SCHEDULED", "CONFIRMED", "CHECKED_IN")
REST_BUFFER_MINUTES = calcs.REST_BUFFER_MINUTES
CHECK_IN_LEAD_MINUTES = 15


def age_at(date_of_birth, instant):
    dob = clock.parse(date_of_birth)
    if dob is None:
        return 999
    years = instant.year - dob.year
    if (instant.month, instant.day) < (dob.month, dob.day):
        years -= 1
    return years


def curfew_violation(ringer, starts_at, ends_at):
    if age_at(ringer.get("date_of_birth"), starts_at) >= 18:
        return False
    curfew = starts_at.replace(hour=calcs.MINOR_CURFEW_HOUR_LOCAL, minute=0, second=0, microsecond=0)
    return ends_at > curfew


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def check_schedule_window(ringer, location, starts_at, ends_at, exclude_shift_id=None):
    """Ladder steps 18 (duration), 19 (rest buffer), 20 (curfew), 22 (overlap)."""
    duration = calcs.minutes_between(starts_at, ends_at)
    if duration <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "ends_at must be later than starts_at.")
    if duration > calcs.MAX_SHIFT_MINUTES:
        raise ApiError("ERR_SHIFT_TOO_LONG")

    rest_violation = False
    overlap = False
    for shift in store.rows("shifts"):
        if shift.get("bell_ringer_id") != ringer["id"]:
            continue
        if exclude_shift_id is not None and shift["id"] == exclude_shift_id:
            continue
        if shift.get("status") not in LIVE_STATUSES:
            continue
        s = clock.parse(shift.get("starts_at"))
        e = clock.parse(shift.get("ends_at"))
        if s is None or e is None:
            continue
        if _overlaps(starts_at, ends_at, s, e):
            overlap = True
            continue
        if s >= ends_at:
            gap = (s - ends_at).total_seconds() / 60.0
        else:
            gap = (starts_at - e).total_seconds() / 60.0
        if gap < REST_BUFFER_MINUTES:
            rest_violation = True

    if rest_violation:
        raise ApiError("ERR_RINGER_REST_BUFFER_VIOLATION")
    if overlap:
        raise ApiError("ERR_SHIFT_OVERLAP")
    if curfew_violation(ringer, starts_at, ends_at):
        raise ApiError("ERR_MINOR_CURFEW_VIOLATION")


def staffing_gates(location, ringer, starts_at):
    """Ladder steps 12-16 for a scheduling decision."""
    campaign = store.find("campaigns", location.get("campaign_id"))
    if campaign is None or campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")
    site = store.find("host_sites", location.get("host_site_id"))
    if site is None or site.get("permission_status") != "APPROVED":
        raise ApiError("ERR_HOST_SITE_NOT_PERMITTED")
    if location.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")
    if not ringer_is_screened(ringer, starts_at):
        raise ApiError("ERR_SCREENING_NOT_CLEARED")
    if ringer.get("engagement_status") != "ACTIVE":
        raise ApiError("ERR_RINGER_INACTIVE")


def ringer_is_screened(ringer, starts_at):
    if ringer.get("screening_status") != "CLEARED":
        return False
    expires = clock.parse(ringer.get("screening_expires_at"))
    if expires is None:
        return False
    return expires > starts_at


def build_shift(location_id, ringer_id, starts_at, ends_at, break_minutes, shift_kind):
    shift = {
        "kettle_location_id": location_id,
        "bell_ringer_id": ringer_id,
        "starts_at": clock.fmt(starts_at),
        "ends_at": clock.fmt(ends_at),
        "break_minutes": int(break_minutes or 0),
        "shift_kind": shift_kind or "REGULAR",
        "status": "SCHEDULED",
        "paid_hours": 0,
        "paid_amount_cents": 0,
        "checked_in_at": None,
    }
    store.insert("shifts", shift)
    ringer = store.find("bell_ringers", ringer_id)
    if ringer is not None:
        calcs.recompute_scheduled_hours(ringer)
    location = store.find("kettle_locations", location_id)
    if location is not None:
        store.touch(location)
    return shift


@bp.route("/shifts", methods=["POST"])
def create_shift():
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    values = validate.shape(
        [
            validate.f("kettle_location_id", validate.STRING, required=True),
            validate.f("bell_ringer_id", validate.STRING, required=True),
            validate.f("starts_at", validate.DATETIME, required=True),
            validate.f("ends_at", validate.DATETIME, required=True),
            validate.f("break_minutes", validate.INTEGER),
            validate.f("shift_kind", validate.ENUM, enum=SHIFT_KINDS),
            validate.f("expected_kettle_location_version", validate.INTEGER, required=True),
        ]
    )
    location = validate.reference("kettle_locations", values["kettle_location_id"], "kettle location")
    ringer = validate.reference("bell_ringers", values["bell_ringer_id"], "bell ringer")
    validate.expect_version(
        location, values["expected_kettle_location_version"], "expected_kettle_location_version"
    )
    staffing_gates(location, ringer, values["starts_at"])
    check_schedule_window(ringer, location, values["starts_at"], values["ends_at"])
    shift = build_shift(
        location["id"],
        ringer["id"],
        values["starts_at"],
        values["ends_at"],
        values.get("break_minutes"),
        values.get("shift_kind"),
    )
    return success(store.public(shift)), 201


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    require_role(
        [
            "PlatformAdmin",
            "VolunteerCoordinator",
            "KettleCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
            "BellRinger",
        ]
    )
    args = request.args
    rows = store.ordered("shifts")
    for field in ("kettle_location_id", "bell_ringer_id", "status"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    starts_at_from = args.get("starts_at_from")
    if starts_at_from:
        bound = clock.parse(starts_at_from)
        if bound is None:
            raise ApiError("ERR_INVALID_REQUEST", "starts_at_from must be an ISO 8601 instant.")
        rows = [r for r in rows if (clock.parse(r.get("starts_at")) or bound) >= bound]
    return page([store.public(r) for r in rows], args)


@bp.route("/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    require_role(
        [
            "PlatformAdmin",
            "VolunteerCoordinator",
            "KettleCoordinator",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "FinanceOfficer",
            "BellRinger",
        ]
    )
    shift = validate.path_row("shifts", shift_id, "shift")
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/confirm", methods=["POST"])
def confirm_shift(shift_id):
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    shift = validate.path_row("shifts", shift_id, "shift")
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
    location = store.find("kettle_locations", shift.get("kettle_location_id"))
    starts_at = clock.parse(shift.get("starts_at"))
    if ringer is None or not ringer_is_screened(ringer, starts_at):
        raise ApiError("ERR_SCREENING_NOT_CLEARED")
    if ringer.get("engagement_status") != "ACTIVE":
        raise ApiError("ERR_RINGER_INACTIVE")
    if location is None or location.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")
    shift["status"] = "CONFIRMED"
    store.touch(shift)
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/check-in", methods=["POST"])
def check_in_shift(shift_id):
    role, user_id = require_role(["BellRinger", "VolunteerCoordinator", "PlatformAdmin"])
    shift = validate.path_row("shifts", shift_id, "shift")
    if role == "BellRinger":
        owner_guard(role, user_id, shift.get("bell_ringer_id"))
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    starts_at = clock.parse(shift.get("starts_at"))
    ends_at = clock.parse(shift.get("ends_at"))
    window_open = starts_at - clock.timedelta(minutes=CHECK_IN_LEAD_MINUTES)
    if not (window_open <= clock.now() <= ends_at):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The check-in window is not open.")
    shift["status"] = "CHECKED_IN"
    shift["checked_in_at"] = clock.now_iso()
    store.touch(shift)
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/complete", methods=["POST"])
def complete_shift(shift_id):
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    shift = validate.path_row("shifts", shift_id, "shift")
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
    location = store.find("kettle_locations", shift.get("kettle_location_id"))
    rate = 0
    if ringer is not None and ringer.get("ringer_type") == "PAID_SEASONAL":
        rate = int(ringer.get("hourly_rate_cents", 0) or 0)
    paid_hours, paid_amount = calcs.shift_paid_amount(shift, rate)

    campaign = None
    if location is not None:
        campaign = store.find("campaigns", location.get("campaign_id"))
    if paid_amount > 0 and campaign is not None:
        committed = 0
        location_ids = {
            loc["id"]
            for loc in store.rows("kettle_locations")
            if loc.get("campaign_id") == campaign["id"]
        }
        for other in store.rows("shifts"):
            if other.get("kettle_location_id") in location_ids and other.get("status") == "COMPLETED":
                committed += int(other.get("paid_amount_cents", 0) or 0)
        budget = int(campaign.get("labor_budget_cents", 0) or 0)
        if committed + paid_amount > budget:
            raise ApiError("ERR_LABOR_BUDGET_EXCEEDED")

    shift["status"] = "COMPLETED"
    shift["paid_hours"] = paid_hours
    shift["paid_amount_cents"] = paid_amount
    store.touch(shift)

    if location is not None:
        calcs.recompute_location(location)
    if ringer is not None:
        calcs.recompute_reliability(ringer)
    if campaign is not None:
        committed = 0
        location_ids = {
            loc["id"]
            for loc in store.rows("kettle_locations")
            if loc.get("campaign_id") == campaign["id"]
        }
        for other in store.rows("shifts"):
            if other.get("kettle_location_id") in location_ids and other.get("status") == "COMPLETED":
                committed += int(other.get("paid_amount_cents", 0) or 0)
        campaign["labor_committed_cents"] = committed
        store.touch(campaign)
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/cancel", methods=["POST"])
def cancel_shift_endpoint(shift_id):
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    validate.shape([validate.f("reason", validate.STRING)])
    shift = validate.path_row("shifts", shift_id, "shift")
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    previous = status
    shift["_prev_status"] = previous
    shift["status"] = "CANCELLED"
    store.touch(shift)
    ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
    if ringer is not None:
        calcs.recompute_scheduled_hours(ringer)
        if previous == "CONFIRMED":
            calcs.recompute_reliability(ringer)
    location = store.find("kettle_locations", shift.get("kettle_location_id"))
    if location is not None:
        calcs.recompute_location(location)
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/no-show", methods=["POST"])
def no_show_shift(shift_id):
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    shift = validate.path_row("shifts", shift_id, "shift")
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    ends_at = clock.parse(shift.get("ends_at"))
    if ends_at is None or not (clock.now() > ends_at):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The shift has not ended yet.")

    shift["status"] = "NO_SHOW"
    store.touch(shift)
    ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
    if ringer is None:
        return success(store.public(shift))
    calcs.recompute_scheduled_hours(ringer)
    score = calcs.recompute_reliability(ringer)
    if score < calcs.SUSPENSION_THRESHOLD and ringer.get("engagement_status") == "ACTIVE":
        ringer["engagement_status"] = "SUSPENDED"
        store.touch(ringer)
        touched_locations = set()
        for other in store.rows("shifts"):
            if other.get("bell_ringer_id") != ringer["id"]:
                continue
            if other.get("status") != "SCHEDULED":
                continue
            start = clock.parse(other.get("starts_at"))
            if start is None or not (start > clock.now()):
                continue
            other["_prev_status"] = "SCHEDULED"
            other["status"] = "CANCELLED"
            store.touch(other)
            touched_locations.add(other.get("kettle_location_id"))
        calcs.recompute_scheduled_hours(ringer)
        for location_id in touched_locations:
            location = store.find("kettle_locations", location_id)
            if location is not None:
                calcs.recompute_location(location)
    return success(store.public(shift))


@bp.route("/shifts/<shift_id>/rebook", methods=["POST"])
def rebook_shift(shift_id):
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    values = validate.shape(
        [
            validate.f("starts_at", validate.DATETIME, required=True),
            validate.f("ends_at", validate.DATETIME, required=True),
        ]
    )
    shift = validate.path_row("shifts", shift_id, "shift")
    status = shift.get("status")
    if status == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status not in ("CANCELLED", "NO_SHOW"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    ringer = store.find("bell_ringers", shift.get("bell_ringer_id"))
    location = store.find("kettle_locations", shift.get("kettle_location_id"))
    if ringer is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "The referenced bell ringer does not exist.")
    if status == "CANCELLED":
        if location is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "The referenced kettle location does not exist.")
        staffing_gates(location, ringer, values["starts_at"])
    else:
        if ringer.get("engagement_status") != "ACTIVE":
            raise ApiError("ERR_RINGER_INACTIVE")
    check_schedule_window(ringer, location, values["starts_at"], values["ends_at"], exclude_shift_id=shift["id"])

    shift["starts_at"] = clock.fmt(values["starts_at"])
    shift["ends_at"] = clock.fmt(values["ends_at"])
    shift["status"] = "SCHEDULED"
    store.touch(shift)
    calcs.recompute_scheduled_hours(ringer)
    return success(store.public(shift))


@bp.route("/shifts/auto-assign", methods=["POST"])
def auto_assign_shift():
    require_role(["VolunteerCoordinator", "KettleCoordinator", "CorpsOfficer"])
    values = validate.shape(
        [
            validate.f("kettle_location_id", validate.STRING, required=True),
            validate.f("starts_at", validate.DATETIME, required=True),
            validate.f("ends_at", validate.DATETIME, required=True),
            validate.f("break_minutes", validate.INTEGER),
        ]
    )
    location = validate.reference("kettle_locations", values["kettle_location_id"], "kettle location")
    starts_at = values["starts_at"]
    ends_at = values["ends_at"]
    duration = calcs.minutes_between(starts_at, ends_at)
    if duration <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "ends_at must be later than starts_at.")
    if duration > calcs.MAX_SHIFT_MINUTES:
        raise ApiError("ERR_SHIFT_TOO_LONG")

    campaign = store.find("campaigns", location.get("campaign_id"))
    if campaign is None or campaign.get("status") != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_NOT_ACTIVE")
    site = store.find("host_sites", location.get("host_site_id"))
    if site is None or site.get("permission_status") != "APPROVED":
        raise ApiError("ERR_HOST_SITE_NOT_PERMITTED")
    if location.get("status") != "ACTIVE":
        raise ApiError("ERR_LOCATION_NOT_ACTIVE")

    ringer = calcs.select_auto_assign_ringer(starts_at, ends_at)
    if ringer is None:
        raise ApiError("ERR_NO_ELIGIBLE_RINGER")
    shift = build_shift(
        location["id"],
        ringer["id"],
        starts_at,
        ends_at,
        values.get("break_minutes"),
        "REGULAR",
    )
    return success(store.public(shift)), 201
