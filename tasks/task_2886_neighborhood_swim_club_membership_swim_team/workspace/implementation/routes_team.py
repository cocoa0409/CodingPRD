"""The swim team: registrations, meets and the volunteer credit ledger.

PRD §3.6.
"""
from flask import Blueprint, request

import clock
import constants as C
import engine as E
import validation as V
from auth import guard, require_owner
from envelope import created, ok, ok_list
from errors import fail
from money import allocate_evenly
from store import DB, by_created, serialize, serialize_many

bp = Blueprint("team", __name__)

REG_READ_ROLES = ("SwimTeamCoach", "MembershipChair", "Treasurer", "BoardPresident", "Member")
MEET_READ_ROLES = ("SwimTeamCoach", "BoardPresident", "Treasurer", "Member")
REG_TERMINAL = ("WITHDRAWN", "REVOKED", "COMPLETED")

REGISTRATION_SPECS = [
    V.f("membership_id", "string"),
    V.f("season_id", "string"),
    V.f("swimmer_name", "string"),
    V.f("swimmer_birthdate", "date"),
    V.f("squad", "enum", enum=C.SQUAD),
]


@bp.route("/swim-team-registrations", methods=["POST"])
def create_registration():
    caller = guard(("SwimTeamCoach", "Member"))
    body = V.body_of(request)
    values = V.validate(body, REGISTRATION_SPECS)
    known = DB.get("memberships", values["membership_id"])
    if known is not None:
        require_owner(caller, known["household_id"])
    season = E.need("seasons", values["season_id"])
    membership = E.need("memberships", values["membership_id"])
    household = E.household_of_membership(membership)

    if season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "Registrations open only against an open season.")
    if household is not None and household["standing"] in ("SUSPENDED", "EXPELLED"):
        fail("ERR_HOUSEHOLD_SUSPENDED", "A suspended household may not register a swimmer.")
    if membership["access_status"] not in ("PENDING", "ACTIVE"):
        fail(
            "ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING",
            "A suspended, lapsed or terminated membership may not register a swimmer.",
        )
    if membership["season_id"] != season["id"]:
        fail("ERR_SEASON_MISMATCH", "The membership belongs to a different season.")
    if household is not None and E.household_is_delinquent(household, season["id"]):
        fail("ERR_DUES_DELINQUENT", "The household is behind on its obligations.")

    squad = values["squad"]
    squad_seq = E.squad_seq_for(membership["id"], values["swimmer_birthdate"])
    fee = E.swim_fee_for_seq(squad_seq)
    full = E.squad_count(season["id"], squad) >= C.SQUAD_CAPACITY[squad]

    registration = DB.insert(
        "swim_team_registrations",
        {
            "membership_id": membership["id"],
            "season_id": season["id"],
            "swimmer_name": values["swimmer_name"],
            "swimmer_birthdate": values["swimmer_birthdate"],
            "squad": squad,
            "squad_seq": squad_seq,
            "assessed_fee_cents": fee,
            "status": "WAITLISTED" if full else "PENDING",
        },
    )
    if E.recompute_swim_fee(membership):
        DB.touch(membership)
    return created(serialize(registration))


@bp.route("/swim-team-registrations/<registration_id>/transitions", methods=["POST"])
def transition_registration(registration_id):
    guard(("SwimTeamCoach",))
    body = V.body_of(request)
    values = V.validate(body, [V.f("to_status", "enum", enum=C.REGISTRATION_STATUS)])
    registration = E.need("swim_team_registrations", registration_id)
    target = values["to_status"]
    current = registration["status"]
    season = DB.get("seasons", registration["season_id"])
    membership = E.membership_of_registration(registration)

    if target == "CONFIRMED" and (season is None or season["status"] != "OPEN"):
        fail("ERR_SEASON_NOT_OPEN", "No swimmer is confirmed outside an open season.")
    if current in REG_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This registration is already resolved.")

    allowed = {
        "PENDING": ("CONFIRMED", "WITHDRAWN"),
        "CONFIRMED": ("WITHDRAWN",),
        "WAITLISTED": ("CONFIRMED", "WITHDRAWN"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    if target == "CONFIRMED":
        if membership is None or membership["access_status"] != "ACTIVE" or membership[
            "dues_status"
        ] not in ("INVOICED", "PAID"):
            fail(
                "ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING",
                "Confirmation needs an active, invoiced membership.",
            )
        if current == "WAITLISTED":
            capacity = C.SQUAD_CAPACITY[registration["squad"]]
            if E.squad_count(registration["season_id"], registration["squad"]) >= capacity:
                fail("ERR_SQUAD_FULL", "The squad has no free place.")
        registration["status"] = "CONFIRMED"
        DB.touch(registration)
    else:
        registration["status"] = "WITHDRAWN"
        DB.touch(registration)
        E.release_assignments_of(registration)
        if current in ("PENDING", "CONFIRMED"):
            E.promote_from_waitlist(registration["season_id"], registration["squad"])

    if membership is not None:
        changed = E.recompute_credits_required(membership)
        changed = E.recompute_swim_fee(membership) or changed
        if changed:
            DB.touch(membership)
    return ok(serialize(registration))


@bp.route("/swim-team-registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    caller = guard(REG_READ_ROLES)
    known = DB.get("swim_team_registrations", registration_id)
    if known is not None:
        membership = DB.get("memberships", known["membership_id"])
        if membership is not None:
            require_owner(caller, membership["household_id"])
    return ok(serialize(E.need("swim_team_registrations", registration_id)))


@bp.route("/swim-team-registrations", methods=["GET"])
def list_registrations():
    guard(REG_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("swim_team_registrations"),
        request,
        string_fields=("membership_id", "season_id", "squad", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)

# ------------------------------------------------------------- meets §3.6
MEET_SPECS = [
    V.f("season_id", "string"),
    V.f("name", "string"),
    V.f("start_iso", "instant"),
    V.f("end_iso", "instant"),
    V.f("expected_swimmers", "int", minimum=0),
    V.f("volunteer_slots_required", "int", minimum=0),
]
MEET_TERMINAL = ("HOSTED", "CANCELLED")


@bp.route("/meets", methods=["POST"])
def create_meet():
    guard(("SwimTeamCoach",))
    body = V.body_of(request)
    values = V.validate(body, MEET_SPECS)
    V.require_range(values["start_iso"], values["end_iso"])
    season = E.need("seasons", values["season_id"])

    if season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "Meets are scheduled only against an open season.")
    start_dt = clock.parse_instant(values["start_iso"])
    end_dt = clock.parse_instant(values["end_iso"])
    if start_dt.date() < clock.parse_date(season["open_date"]) or end_dt.date() > clock.parse_date(
        season["close_date"]
    ):
        fail("ERR_OUTSIDE_SEASON_WINDOW", "The meet window falls outside the season window.")

    meet = DB.insert(
        "meets",
        {
            "season_id": season["id"],
            "name": values["name"],
            "start_iso": values["start_iso"],
            "end_iso": values["end_iso"],
            "expected_swimmers": values["expected_swimmers"],
            "volunteer_slots_required": values["volunteer_slots_required"],
            "volunteer_slots_filled": 0,
            "status": "SCHEDULED",
            "roster_closed_at": None,
            "understaffed_penalty_cents": 0,
        },
    )
    return created(serialize(meet))


@bp.route("/meets/<meet_id>/close-roster", methods=["POST"])
def close_roster(meet_id):
    guard(("SwimTeamCoach",))
    meet = E.need("meets", meet_id)

    if meet["status"] in MEET_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This meet is already hosted or cancelled.")
    if meet["roster_closed_at"] is not None:
        fail("ERR_ROSTER_ALREADY_CLOSED", "The volunteer roster is already closed.")
    if meet["status"] != "SCHEDULED":
        fail("ERR_INVALID_TRANSITION", "Only a SCHEDULED meet may close its roster.")

    shortfall = meet["volunteer_slots_required"] - meet["volunteer_slots_filled"]
    if shortfall > 0:
        meet["status"] = "UNDERSTAFFED"
        meet["understaffed_penalty_cents"] = shortfall * C.MEET_UNDERSTAFF_PENALTY_CENTS
    else:
        meet["status"] = "STAFFED"
        meet["understaffed_penalty_cents"] = 0
    meet["roster_closed_at"] = clock.now_iso()
    DB.touch(meet)
    return ok(serialize(meet))


def _complete_assignments_of(meet):
    """Every assignment still ASSIGNED completes, in created_at order, each one
    crediting its owning membership (PRD §3.6)."""
    for assignment in E.assignments_of_meet(meet["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        assignment["status"] = "COMPLETED"
        DB.touch(assignment)
        membership = E.membership_of_assignment(assignment)
        if membership is not None and E.recompute_credits_earned(membership):
            DB.touch(membership)


def _book_understaffed_penalty(meet):
    """The accrued penalty divides evenly across the memberships holding a
    CONFIRMED registration in the meet's season (PRD §3.6)."""
    penalty = meet["understaffed_penalty_cents"]
    if penalty <= 0:
        return
    seen = []
    seen_ids = set()
    for reg in DB.all("swim_team_registrations"):
        if reg["season_id"] != meet["season_id"] or reg["status"] != "CONFIRMED":
            continue
        membership = E.membership_of_registration(reg)
        if membership is not None and membership["id"] not in seen_ids:
            seen_ids.add(membership["id"])
            seen.append(membership)
    seen = by_created(seen)
    for membership, share in zip(seen, allocate_evenly(penalty, len(seen))):
        if share <= 0:
            continue
        membership["balance_due_cents"] += share
        DB.touch(membership)


@bp.route("/meets/<meet_id>/transitions", methods=["POST"])
def transition_meet(meet_id):
    guard(("SwimTeamCoach",))
    body = V.body_of(request)
    values = V.validate(body, [V.f("to_status", "enum", enum=C.MEET_STATUS)])
    meet = E.need("meets", meet_id)
    target = values["to_status"]
    current = meet["status"]
    season = DB.get("seasons", meet["season_id"])

    if target == "HOSTED" and season is not None and season["facility_posture"] != "OPEN":
        fail("ERR_FACILITY_CLOSED", "A meet is hosted only while the facility is open.")
    if current in MEET_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This meet is already hosted or cancelled.")

    allowed = {
        "SCHEDULED": ("CANCELLED",),
        "STAFFED": ("HOSTED", "CANCELLED"),
        "UNDERSTAFFED": ("HOSTED", "CANCELLED"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    if target == "HOSTED":
        if clock.now() < clock.parse_instant(meet["end_iso"]):
            fail("ERR_INVALID_TRANSITION", "The meet has not finished yet.")
        if season is not None and not E.ratio_compliant_over_window(
            season, meet["start_iso"], meet["end_iso"]
        ):
            fail("ERR_GUARD_RATIO_NOT_MET", "The deck is not staffed across the meet window.")
        meet["status"] = "HOSTED"
        DB.touch(meet)
        _complete_assignments_of(meet)
        if current == "UNDERSTAFFED":
            _book_understaffed_penalty(meet)
    else:
        meet["status"] = "CANCELLED"
        meet["understaffed_penalty_cents"] = 0
        DB.touch(meet)
        for assignment in E.assignments_of_meet(meet["id"]):
            if assignment["status"] != "ASSIGNED":
                continue
            assignment["status"] = "RELEASED"
            DB.touch(assignment)
    return ok(serialize(meet))


@bp.route("/meets/<meet_id>", methods=["GET"])
def read_meet(meet_id):
    guard(MEET_READ_ROLES)
    return ok(serialize(E.need("meets", meet_id)))


@bp.route("/meets", methods=["GET"])
def list_meets():
    guard(MEET_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(DB.all("meets"), request, string_fields=("season_id", "status"))
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ---------------------------------------------- volunteer assignments §3.6
ASSIGNMENT_SPECS = [
    V.f("meet_id", "string"),
    V.f("swim_team_registration_id", "string"),
    V.f("job_code", "enum", enum=C.JOB_CODE),
]
ASSIGNMENT_TERMINAL = ("COMPLETED", "NO_SHOW", "RELEASED")


@bp.route("/volunteer-assignments", methods=["POST"])
def create_assignment():
    guard(("SwimTeamCoach",))
    body = V.body_of(request)
    values = V.validate(body, ASSIGNMENT_SPECS)
    registration = E.need("swim_team_registrations", values["swim_team_registration_id"])
    meet = E.need("meets", values["meet_id"])

    if meet["roster_closed_at"] is not None:
        fail("ERR_ROSTER_ALREADY_CLOSED", "A closed roster accepts no further assignment.")

    credit = C.JOB_CREDIT_VALUES[values["job_code"]]
    if meet["volunteer_slots_filled"] + credit > meet["volunteer_slots_required"]:
        fail("ERR_VOLUNTEER_SLOTS_FULL", "The meet's volunteer credits are fully subscribed.")
    for existing in E.assignments_of_meet(meet["id"]):
        if existing["swim_team_registration_id"] != registration["id"]:
            continue
        if existing["status"] in ("ASSIGNED", "COMPLETED"):
            fail(
                "ERR_DUPLICATE_VOLUNTEER_ASSIGNMENT",
                "This registration already works a job at this meet.",
            )
    if meet["season_id"] != registration["season_id"]:
        fail("ERR_SEASON_MISMATCH", "The meet and the registration belong to different seasons.")

    assignment = DB.insert(
        "volunteer_assignments",
        {
            "meet_id": meet["id"],
            "swim_team_registration_id": registration["id"],
            "job_code": values["job_code"],
            "credit_value": credit,
            "status": "ASSIGNED",
        },
    )
    meet["volunteer_slots_filled"] += credit
    DB.touch(meet)
    return created(serialize(assignment))


@bp.route("/volunteer-assignments/<assignment_id>/transitions", methods=["POST"])
def transition_assignment(assignment_id):
    guard(("SwimTeamCoach", "Member"))
    body = V.body_of(request)
    values = V.validate(body, [V.f("to_status", "enum", enum=C.ASSIGNMENT_STATUS)])
    assignment = E.need("volunteer_assignments", assignment_id)
    target = values["to_status"]
    current = assignment["status"]
    meet = DB.get("meets", assignment["meet_id"])

    if current in ASSIGNMENT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This assignment is already resolved.")
    if target not in ("COMPLETED", "NO_SHOW"):
        fail("ERR_INVALID_TRANSITION", "%s is not requestable from %s." % (target, current))
    if target == "NO_SHOW" and (
        meet is None or meet["status"] not in ("STAFFED", "UNDERSTAFFED", "HOSTED")
    ):
        fail(
            "ERR_INVALID_TRANSITION",
            "A no-show is recorded only once the roster is closed.",
        )

    assignment["status"] = target
    DB.touch(assignment)
    membership = E.membership_of_assignment(assignment)
    if target == "COMPLETED":
        if membership is not None and E.recompute_credits_earned(membership):
            DB.touch(membership)
    elif meet is not None:
        E.recompute_meet_filled(meet)
    return ok(serialize(assignment))


@bp.route("/volunteer-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    guard(MEET_READ_ROLES)
    return ok(serialize(E.need("volunteer_assignments", assignment_id)))


@bp.route("/volunteer-assignments", methods=["GET"])
def list_assignments():
    guard(MEET_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("volunteer_assignments"),
        request,
        string_fields=("meet_id", "swim_team_registration_id", "job_code", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)
