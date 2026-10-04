"""Seasonal assistance: intake, eligibility and distribution (PRD 3.6)."""
from flask import request

from core import calcs, clock, store, validate
from core.auth import require_role
from core.blueprint import bp
from core.envelope import page, success
from core.errors import ApiError

PROGRAM_TYPES = ("TOY", "FOOD", "COAT", "HYGIENE")
PROGRAM_STATUSES = ("DRAFT", "OPEN", "CLOSED")
ELIGIBILITY_STATUSES = (
    "SUBMITTED",
    "SCREENING",
    "ELIGIBLE",
    "INELIGIBLE",
    "WAITLISTED",
    "APPROVED",
    "DISTRIBUTION_SCHEDULED",
    "DISTRIBUTED",
    "NO_SHOW",
)
ACCEPTED_STATUSES = ("ELIGIBLE", "APPROVED", "DISTRIBUTION_SCHEDULED", "DISTRIBUTED")


def accepted_application_count(program_id):
    count = 0
    for application in store.rows("assistance_applications"):
        if application.get("program_id") != program_id:
            continue
        if application.get("eligibility_status") in ACCEPTED_STATUSES:
            count += 1
    return count


def refresh_accepted_count(program):
    program["accepted_application_count"] = accepted_application_count(program["id"])
    store.touch(program)
    return program


def promote_earliest_waitlisted(program_id, exclude_id=None):
    candidates = [
        application
        for application in store.rows("assistance_applications")
        if application.get("program_id") == program_id
        and application.get("eligibility_status") == "WAITLISTED"
        and application["id"] != exclude_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a.get("created_at") or "", a.get("_seq", 0)))
    promoted = candidates[0]
    promoted["eligibility_status"] = "ELIGIBLE"
    store.touch(promoted)
    return promoted


@bp.route("/assistance-programs", methods=["POST"])
def create_assistance_program():
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("campaign_id", validate.STRING, required=True),
            validate.f("name", validate.STRING, required=True),
            validate.f("program_type", validate.ENUM, required=True, enum=PROGRAM_TYPES),
            validate.f("intake_opens_on", validate.DATETIME, required=True),
            validate.f("intake_closes_on", validate.DATETIME, required=True),
            validate.f("household_cap", validate.INTEGER, required=True),
            validate.f("per_household_limit_cents", validate.INTEGER),
        ]
    )
    validate.reference("campaigns", values["campaign_id"], "campaign")
    program = {
        "campaign_id": values["campaign_id"],
        "name": values["name"],
        "program_type": values["program_type"],
        "intake_opens_on": clock.fmt(values["intake_opens_on"]),
        "intake_closes_on": clock.fmt(values["intake_closes_on"]),
        "household_cap": int(values["household_cap"]),
        "per_household_limit_cents": int(values.get("per_household_limit_cents", 0) or 0),
        "status": "DRAFT",
        "accepted_application_count": 0,
    }
    store.insert("assistance_programs", program)
    return success(store.public(program)), 201


@bp.route("/assistance-programs", methods=["GET"])
def list_assistance_programs():
    require_role(
        [
            "PlatformAdmin",
            "AssistanceCaseworker",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "ProgramDirector",
        ]
    )
    args = request.args
    rows = store.ordered("assistance_programs")
    for field in ("campaign_id", "status", "program_type"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/assistance-programs/<program_id>", methods=["GET"])
def get_assistance_program(program_id):
    require_role(
        [
            "PlatformAdmin",
            "AssistanceCaseworker",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "ProgramDirector",
        ]
    )
    program = validate.path_row("assistance_programs", program_id, "assistance program")
    return success(store.public(program))


@bp.route("/assistance-programs/<program_id>/open", methods=["POST"])
def open_assistance_program(program_id):
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    program = validate.path_row("assistance_programs", program_id, "assistance program")
    if program.get("status") == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if program.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    program["status"] = "OPEN"
    store.touch(program)
    return success(store.public(program))


@bp.route("/assistance-applications", methods=["POST"])
def create_assistance_application():
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("program_id", validate.STRING, required=True),
            validate.f("applicant_name", validate.STRING, required=True),
            validate.f("household_size", validate.INTEGER, required=True),
            validate.f("annual_income_cents", validate.INTEGER, required=True),
            validate.f("distribution_site_unit_id", validate.STRING),
        ]
    )
    program = validate.reference("assistance_programs", values["program_id"], "assistance program")
    unit_id = values.get("distribution_site_unit_id")
    if unit_id:
        validate.reference("units", unit_id, "unit")

    if program.get("status") != "OPEN":
        raise ApiError("ERR_INTAKE_WINDOW_CLOSED")

    household_size = int(values["household_size"])
    if household_size < 1 or household_size > 12:
        raise ApiError("ERR_HOUSEHOLD_SIZE_INVALID")

    opens_on = clock.parse(program.get("intake_opens_on"))
    closes_on = clock.parse(program.get("intake_closes_on"))
    if opens_on is None or closes_on is None or not (opens_on <= clock.now() <= closes_on):
        raise ApiError("ERR_OUTSIDE_INTAKE_WINDOW")

    application = {
        "program_id": program["id"],
        "applicant_name": values["applicant_name"],
        "household_size": household_size,
        "annual_income_cents": int(values["annual_income_cents"]),
        "verified_income_cents": 0,
        "eligibility_status": "SUBMITTED",
        "provisional_score": calcs.provisional_score(values["annual_income_cents"], household_size),
        "eligibility_score": 0,
        "distribution_site_unit_id": unit_id or None,
        "distribution_scheduled_at": None,
        "distribution_slot_minutes": 30,
        "distribution_status": "NOT_SCHEDULED",
        "pickup_code": None,
    }
    store.insert("assistance_applications", application)
    return success(store.public(application)), 201


@bp.route("/assistance-applications", methods=["GET"])
def list_assistance_applications():
    require_role(
        [
            "PlatformAdmin",
            "AssistanceCaseworker",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "ProgramDirector",
        ]
    )
    args = request.args
    rows = store.ordered("assistance_applications")
    for field in ("program_id", "eligibility_status", "distribution_site_unit_id"):
        wanted = args.get(field)
        if wanted:
            rows = [r for r in rows if r.get(field) == wanted]
    return page([store.public(r) for r in rows], args)


@bp.route("/assistance-applications/<application_id>", methods=["GET"])
def get_assistance_application(application_id):
    require_role(
        [
            "PlatformAdmin",
            "AssistanceCaseworker",
            "CorpsOfficer",
            "TerritorialCommander",
            "DivisionalOfficer",
            "ProgramDirector",
        ]
    )
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    return success(store.public(application))


@bp.route("/assistance-applications/<application_id>/screen", methods=["POST"])
def screen_assistance_application(application_id):
    require_role(["AssistanceCaseworker", "PlatformAdmin"])
    values = validate.shape([validate.f("verified_income_cents", validate.INTEGER, required=True)])
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    status = application.get("eligibility_status")
    if status in ("DISTRIBUTED", "INELIGIBLE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    program = store.find("assistance_programs", application.get("program_id"))
    if program is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "The referenced assistance program does not exist.")
    if program.get("status") not in ("OPEN", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    application["verified_income_cents"] = int(values["verified_income_cents"])
    application["eligibility_status"] = "SCREENING"
    score = calcs.eligibility_score(
        application["verified_income_cents"], application.get("household_size")
    )
    application["eligibility_score"] = score
    store.touch(application)

    if score < calcs.ELIGIBILITY_THRESHOLD:
        application["eligibility_status"] = "INELIGIBLE"
        store.touch(application)
        return success(store.public(application))

    cap = int(program.get("household_cap", 0) or 0)
    if accepted_application_count(program["id"]) < cap:
        application["eligibility_status"] = "ELIGIBLE"
        store.touch(application)
        refresh_accepted_count(program)
    else:
        application["eligibility_status"] = "WAITLISTED"
        store.touch(application)
    return success(store.public(application))


@bp.route("/assistance-applications/<application_id>/approve", methods=["POST"])
def approve_assistance_application(application_id):
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape([validate.f("distribution_site_unit_id", validate.STRING, required=True)])
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    status = application.get("eligibility_status")
    if status in ("DISTRIBUTED", "INELIGIBLE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "ELIGIBLE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    unit = validate.reference("units", values["distribution_site_unit_id"], "unit")
    if unit.get("unit_type") != "CORPS":
        raise ApiError("ERR_INVALID_REQUEST", "The distribution site unit must be a CORPS unit.")

    program = store.find("assistance_programs", application.get("program_id"))
    if program is not None:
        limit = int(program.get("per_household_limit_cents", 0) or 0)
        if limit < 0:
            raise ApiError("ERR_HOUSEHOLD_LIMIT_EXCEEDED")

    application["eligibility_status"] = "APPROVED"
    application["distribution_site_unit_id"] = unit["id"]
    store.touch(application)
    return success(store.public(application))


@bp.route("/assistance-applications/<application_id>/schedule-distribution", methods=["POST"])
def schedule_distribution(application_id):
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape(
        [
            validate.f("distribution_scheduled_at", validate.DATETIME, required=True),
            validate.f("distribution_slot_minutes", validate.INTEGER),
            validate.f("expected_assistance_application_version", validate.INTEGER, required=True),
        ]
    )
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    validate.expect_version(
        application,
        values["expected_assistance_application_version"],
        "expected_assistance_application_version",
    )
    status = application.get("eligibility_status")
    if status in ("DISTRIBUTED", "INELIGIBLE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    starts_at = values["distribution_scheduled_at"]
    if starts_at < clock.now():
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The appointment may not start in the past.")
    slot_minutes = int(
        values.get("distribution_slot_minutes", 30)
        if values.get("distribution_slot_minutes") is not None
        else 30
    )
    ends_at = starts_at + clock.timedelta(minutes=slot_minutes)
    unit_id = application.get("distribution_site_unit_id")

    for other in store.rows("assistance_applications"):
        if other["id"] == application["id"]:
            continue
        if other.get("distribution_status") != "SCHEDULED":
            continue
        if other.get("distribution_site_unit_id") != unit_id:
            continue
        o_start = clock.parse(other.get("distribution_scheduled_at"))
        if o_start is None:
            continue
        o_slot = int(other.get("distribution_slot_minutes", 30) or 30)
        o_end = o_start + clock.timedelta(minutes=o_slot)
        if starts_at < o_end and o_start < ends_at:
            raise ApiError("ERR_DISTRIBUTION_SLOT_CONFLICT")

    application["eligibility_status"] = "DISTRIBUTION_SCHEDULED"
    application["distribution_status"] = "SCHEDULED"
    application["distribution_scheduled_at"] = clock.fmt(starts_at)
    application["distribution_slot_minutes"] = slot_minutes
    application["pickup_code"] = clock.new_pickup_code()
    store.touch(application)
    return success(store.public(application))


@bp.route("/assistance-applications/<application_id>/distribution/complete", methods=["POST"])
def complete_distribution(application_id):
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    values = validate.shape([validate.f("pickup_code", validate.STRING, required=True)])
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    status = application.get("eligibility_status")
    if status == "DISTRIBUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "DISTRIBUTION_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if values["pickup_code"] != application.get("pickup_code"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The pickup code does not match.")

    application["eligibility_status"] = "DISTRIBUTED"
    application["distribution_status"] = "COMPLETED"
    store.touch(application)
    return success(store.public(application))


@bp.route("/assistance-applications/<application_id>/distribution/no-show", methods=["POST"])
def distribution_no_show(application_id):
    require_role(["AssistanceCaseworker", "CorpsOfficer", "PlatformAdmin"])
    application = validate.path_row("assistance_applications", application_id, "assistance application")
    status = application.get("eligibility_status")
    if status in ("DISTRIBUTED", "INELIGIBLE"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if status != "DISTRIBUTION_SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    scheduled_at = clock.parse(application.get("distribution_scheduled_at"))
    slot_minutes = int(application.get("distribution_slot_minutes", 30) or 30)
    if scheduled_at is None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    appointment_end = scheduled_at + clock.timedelta(minutes=slot_minutes)
    if not (clock.now() > appointment_end):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "The appointment has not ended yet.")

    application["eligibility_status"] = "WAITLISTED"
    application["distribution_status"] = "NO_SHOW"
    store.touch(application)

    program = store.find("assistance_programs", application.get("program_id"))
    if program is not None:
        promote_earliest_waitlisted(program["id"], exclude_id=application["id"])
        refresh_accepted_count(program)
    return success(store.public(application))
