"""Parties, inspection findings, conduct cases and the capital reserve.

PRD §3.7, §3.1 (findings), §3.9 and §3.10.
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import engine as E
import validation as V
from auth import guard, require_owner, require_segregation, require_transition_role
from envelope import created, ok, ok_list
from errors import fail
from money import D, round_half_up
from store import DB, serialize, serialize_many

bp = Blueprint("facility", __name__)

PARTY_READ_ROLES = ("PoolManager", "Treasurer", "BoardPresident", "Member")
FINDING_ROLES = ("HealthInspector", "PoolManager", "BoardPresident")
CASE_READ_ROLES = ("BoardPresident", "PoolManager", "Member")
PROJECT_ROLES = ("Treasurer", "BoardPresident")

# =========================================================== parties §3.7
PARTY_SPECS = [
    V.f("membership_id", "string"),
    V.f("zone", "enum", enum=C.ZONE),
    V.f("start_iso", "instant"),
    V.f("end_iso", "instant"),
    V.f("guest_count", "int", minimum=0),
    V.f("host_party_size", "int", minimum=1),
]
PARTY_TERMINAL = (
    "COMPLETED",
    "REJECTED",
    "CANCELLED_BY_HOST",
    "CANCELLED_BY_CLOSURE",
    "CANCELLED_BY_SUSPENSION",
)


@bp.route("/party-reservations", methods=["POST"])
def create_reservation():
    caller = guard(("Member", "PoolManager"))
    body = V.body_of(request)
    values = V.validate(body, PARTY_SPECS)
    V.require_range(values["start_iso"], values["end_iso"])
    known = DB.get("memberships", values["membership_id"])
    if known is not None:
        require_owner(caller, known["household_id"])
    membership = E.need("memberships", values["membership_id"])
    season = E.season_of_membership(membership)
    household = E.household_of_membership(membership)
    category = E.category_of_membership(membership)

    if category is not None and not category["party_privileges"]:
        fail("ERR_VALIDATION", "The membership's category carries no party privileges.")
    if season is None or season["status"] != "OPEN":
        fail("ERR_SEASON_NOT_OPEN", "Parties are booked only against an open season.")
    if season["facility_posture"] == "CLOSED":
        fail("ERR_FACILITY_CLOSED", "The facility is closed.")
    if season["facility_posture"] == "RESTRICTED" and values["zone"] == "WHOLE_FACILITY":
        fail(
            "ERR_FACILITY_RESTRICTED",
            "A restricted facility does not let the whole facility be booked.",
        )
    if household["standing"] in ("SUSPENDED", "EXPELLED"):
        fail("ERR_HOUSEHOLD_SUSPENDED", "A suspended household may not book a party.")
    if membership["access_status"] != "ACTIVE":
        fail(
            "ERR_MEMBERSHIP_NOT_IN_GOOD_STANDING",
            "Only an active membership may book a party.",
        )

    start_dt = clock.parse_instant(values["start_iso"])
    end_dt = clock.parse_instant(values["end_iso"])
    if start_dt.date() < clock.parse_date(season["open_date"]) or end_dt.date() > clock.parse_date(
        season["close_date"]
    ):
        fail("ERR_OUTSIDE_SEASON_WINDOW", "The party falls outside the season window.")

    load = values["guest_count"] + values["host_party_size"]
    aggregate = 0
    for other in E.reservations_of_season(season["id"]):
        if other["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        other_start = clock.parse_instant(other["start_iso"])
        other_end = clock.parse_instant(other["end_iso"])
        if not E.windows_overlap(start_dt, end_dt, other_start, other_end):
            continue
        if E.zones_conflict(values["zone"], other["zone"]):
            fail("ERR_ZONE_DOUBLE_BOOKED", "That zone is already held over an overlapping window.")
        aggregate += other["guest_count"] + other["host_party_size"]
    if aggregate + load > season["bather_load_capacity"]:
        fail(
            "ERR_BATHER_CAPACITY_EXCEEDED",
            "The facility's aggregate bather capacity would be exceeded.",
        )

    if E.household_is_delinquent(household, season["id"]):
        fail("ERR_DUES_DELINQUENT", "The household is behind on its obligations.")
    if not E.bond_is_settled(household, category):
        fail("ERR_BOND_NOT_PAID", "The household's bond is not settled.")

    price = E.price_party(
        values["zone"], values["guest_count"], values["host_party_size"], start_dt, end_dt
    )
    fields = {
        "membership_id": membership["id"],
        "zone": values["zone"],
        "start_iso": values["start_iso"],
        "end_iso": values["end_iso"],
        "guest_count": values["guest_count"],
        "host_party_size": values["host_party_size"],
        "status": "REQUESTED",
        "refunded_cents": 0,
    }
    fields.update(price)
    reservation = DB.insert("party_reservations", fields)
    household["party_charges_owed_cents"] += price["total_charge_cents"]
    DB.touch(household)
    return created(serialize(reservation))


@bp.route("/party-reservations/<reservation_id>/transitions", methods=["POST"])
def transition_reservation(reservation_id):
    caller = guard(("PoolManager", "Member"))
    body = V.body_of(request)
    values = V.validate(body, [V.f("to_status", "enum", enum=C.RESERVATION_STATUS)])
    target = values["to_status"]
    if target == "CANCELLED_BY_HOST":
        require_transition_role(caller, ("PoolManager", "Member"))
    elif target in ("CONFIRMED", "REJECTED", "COMPLETED"):
        require_transition_role(caller, ("PoolManager",))
    known = DB.get("party_reservations", reservation_id)
    if known is not None:
        household = E.household_of_reservation(known)
        if household is not None:
            require_owner(caller, household["id"])
    reservation = E.need("party_reservations", reservation_id)
    current = reservation["status"]

    membership = DB.get("memberships", reservation["membership_id"])
    season = E.season_of_membership(membership) if membership is not None else None

    if target == "CONFIRMED" and season is not None and season["facility_posture"] != "OPEN":
        fail("ERR_FACILITY_CLOSED", "A party is confirmed only while the facility is open.")
    if current in PARTY_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This reservation is already resolved.")

    allowed = {
        "REQUESTED": ("CONFIRMED", "REJECTED"),
        "CONFIRMED": ("COMPLETED", "CANCELLED_BY_HOST"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    now = clock.now()
    if target == "CONFIRMED":
        if season is not None and not E.ratio_compliant_over_window(
            season, reservation["start_iso"], reservation["end_iso"]
        ):
            fail("ERR_GUARD_RATIO_NOT_MET", "The deck is not staffed across the party window.")
        reservation["status"] = "CONFIRMED"
        DB.touch(reservation)
    elif target == "REJECTED":
        reservation["status"] = "REJECTED"
        DB.touch(reservation)
        E.refund_reservation(reservation, reservation["total_charge_cents"], auto_apply=False)
    elif target == "COMPLETED":
        if now < clock.parse_instant(reservation["end_iso"]):
            fail("ERR_INVALID_TRANSITION", "The party has not finished yet.")
        reservation["status"] = "COMPLETED"
        DB.touch(reservation)
    else:
        start_dt = clock.parse_instant(reservation["start_iso"])
        if now >= start_dt:
            fail("ERR_INVALID_TRANSITION", "A party under way or past may not be host-cancelled.")
        if start_dt - now >= timedelta(days=C.CANCEL_FULL_REFUND_DAYS):
            refund = reservation["total_charge_cents"]
        else:
            refund = round_half_up(
                D(reservation["total_charge_cents"]) * C.PARTY_HALF_REFUND_RATE
            )
        reservation["status"] = "CANCELLED_BY_HOST"
        DB.touch(reservation)
        E.refund_reservation(reservation, refund, auto_apply=True)
    return ok(serialize(reservation))


@bp.route("/party-reservations/<reservation_id>", methods=["GET"])
def read_reservation(reservation_id):
    caller = guard(PARTY_READ_ROLES)
    known = DB.get("party_reservations", reservation_id)
    if known is not None:
        household = E.household_of_reservation(known)
        if household is not None:
            require_owner(caller, household["id"])
    return ok(serialize(E.need("party_reservations", reservation_id)))


@bp.route("/party-reservations", methods=["GET"])
def list_reservations():
    guard(PARTY_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("party_reservations"),
        request,
        string_fields=("membership_id", "zone", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ============================================== inspection findings §3.1
FINDING_SPECS = [
    V.f("season_id", "string"),
    V.f("inspected_on", "date"),
    V.f("inspector_name", "string"),
    V.f("finding_code", "string"),
    V.f("severity", "enum", enum=C.FINDING_SEVERITY),
    V.f("narrative", "string"),
]


@bp.route("/inspection-findings", methods=["POST"])
def create_finding():
    caller = guard(("HealthInspector",))
    body = V.body_of(request)
    values = V.validate(body, FINDING_SPECS)
    season = E.need("seasons", values["season_id"])

    finding = DB.insert(
        "inspection_findings",
        {
            "season_id": season["id"],
            "inspected_on": values["inspected_on"],
            "inspector_name": values["inspector_name"],
            "finding_code": values["finding_code"],
            "severity": values["severity"],
            "narrative": values["narrative"],
            "status": "OPEN",
            "recorded_by_user_id": caller.user_id,
            "remediation_note": None,
            "remediation_submitted_at": None,
            "verified_by_user_id": None,
            "reopen_count": 0,
        },
    )
    if E.derive_posture(season):
        DB.touch(season)
    return created(serialize(finding))


@bp.route("/inspection-findings/<finding_id>/transitions", methods=["POST"])
def transition_finding(finding_id):
    caller = guard(("HealthInspector", "PoolManager"))
    body = V.body_of(request)
    values = V.validate(
        body,
        [
            V.f("to_status", "enum", enum=C.FINDING_STATUS),
            V.f("remediation_note", "string", required=False),
        ],
    )
    target = values["to_status"]
    if target == "REMEDIATION_SUBMITTED":
        require_transition_role(caller, ("PoolManager",))
    else:
        require_transition_role(caller, ("HealthInspector",))
    finding = E.need("inspection_findings", finding_id)
    current = finding["status"]

    if target == "VERIFIED_CLOSED":
        require_segregation(caller, finding["recorded_by_user_id"])
    if target == "REMEDIATION_SUBMITTED" and not values["remediation_note"]:
        fail("ERR_VALIDATION", "Field 'remediation_note' is required on a remediation.")

    if current == "VERIFIED_CLOSED":
        fail("ERR_ALREADY_TERMINAL", "This finding is already verified and closed.")
    allowed = {
        "OPEN": ("REMEDIATION_SUBMITTED",),
        "REOPENED": ("REMEDIATION_SUBMITTED",),
        "REMEDIATION_SUBMITTED": ("REOPENED", "VERIFIED_CLOSED"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    season = DB.get("seasons", finding["season_id"])
    if target == "REMEDIATION_SUBMITTED":
        finding["status"] = "REMEDIATION_SUBMITTED"
        finding["remediation_note"] = values["remediation_note"]
        finding["remediation_submitted_at"] = clock.now_iso()
        DB.touch(finding)
    elif target == "REOPENED":
        finding["status"] = "REOPENED"
        finding["reopen_count"] += 1
        DB.touch(finding)
    else:
        finding["status"] = "VERIFIED_CLOSED"
        finding["verified_by_user_id"] = caller.user_id
        DB.touch(finding)

    if season is not None:
        changed = E.derive_posture(season)
        if changed or target == "VERIFIED_CLOSED":
            DB.touch(season)
    return ok(serialize(finding))


@bp.route("/inspection-findings/<finding_id>", methods=["GET"])
def read_finding(finding_id):
    guard(FINDING_ROLES)
    return ok(serialize(E.need("inspection_findings", finding_id)))


@bp.route("/inspection-findings", methods=["GET"])
def list_findings():
    guard(FINDING_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("inspection_findings"),
        request,
        string_fields=("season_id", "severity", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ================================================== conduct cases §3.9
CASE_SPECS = [
    V.f("household_id", "string"),
    V.f("subject_name", "string"),
    V.f("severity", "enum", enum=C.CONDUCT_SEVERITY),
    V.f("narrative", "string"),
]
CASE_TERMINAL = ("DISMISSED", "CLOSED")


@bp.route("/conduct-cases", methods=["POST"])
def report_case():
    caller = guard(("PoolManager", "BoardPresident"))
    body = V.body_of(request)
    values = V.validate(body, CASE_SPECS)
    household = E.need("households", values["household_id"])

    case = DB.insert(
        "conduct_cases",
        {
            "household_id": household["id"],
            "subject_name": values["subject_name"],
            "severity": values["severity"],
            "narrative": values["narrative"],
            "status": "REPORTED",
            "reported_by_user_id": caller.user_id,
            "decided_by_user_id": None,
            "sanction_type": None,
            "points_assessed": 0,
            "sanctioned_at": None,
            "appeal_count": 0,
        },
    )
    return created(serialize(case))


@bp.route("/conduct-cases/<case_id>/transitions", methods=["POST"])
def transition_case(case_id):
    caller = guard(("BoardPresident", "Member"))
    body = V.body_of(request)
    values = V.validate(
        body,
        [
            V.f("to_status", "enum", enum=C.CONDUCT_STATUS),
            V.f("sanction_type", "enum", required=False, enum=C.SANCTION_TYPE),
        ],
    )
    target = values["to_status"]
    if target == "APPEALED":
        require_transition_role(caller, ("Member",))
    elif target in ("UNDER_REVIEW", "SANCTIONED", "DISMISSED", "CLOSED"):
        require_transition_role(caller, ("BoardPresident",))
    known = DB.get("conduct_cases", case_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    case = E.need("conduct_cases", case_id)
    current = case["status"]

    if target in ("SANCTIONED", "DISMISSED"):
        require_segregation(caller, case["reported_by_user_id"])
    if target == "SANCTIONED" and not values["sanction_type"]:
        fail("ERR_VALIDATION", "Field 'sanction_type' is required on a sanction.")

    if current in CASE_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This case is already dismissed or closed.")
    allowed = {
        "REPORTED": ("UNDER_REVIEW",),
        "UNDER_REVIEW": ("SANCTIONED", "DISMISSED"),
        "SANCTIONED": ("APPEALED", "CLOSED"),
        "APPEALED": ("UNDER_REVIEW",),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    household = DB.get("households", case["household_id"])
    now = clock.now()
    if target == "UNDER_REVIEW" and current == "REPORTED":
        case["status"] = "UNDER_REVIEW"
        DB.touch(case)
    elif target == "UNDER_REVIEW":
        # The re-hearing edge is the one place that gives points back.
        case["status"] = "UNDER_REVIEW"
        case["points_assessed"] = 0
        DB.touch(case)
        if household is not None and E.recompute_conduct_points(household):
            DB.touch(household)
    elif target == "SANCTIONED":
        case["status"] = "SANCTIONED"
        case["sanction_type"] = values["sanction_type"]
        case["decided_by_user_id"] = caller.user_id
        case["sanctioned_at"] = clock.now_iso()
        case["points_assessed"] = C.CONDUCT_POINTS[case["severity"]]
        DB.touch(case)
        if household is not None:
            changed = E.recompute_conduct_points(household)
            new_standing = E.harden_standing(household, values["sanction_type"])
            changed = E.apply_standing(household, new_standing) or changed
            if changed:
                DB.touch(household)
    elif target == "DISMISSED":
        case["status"] = "DISMISSED"
        case["decided_by_user_id"] = caller.user_id
        case["points_assessed"] = 0
        DB.touch(case)
        if household is not None and E.recompute_conduct_points(household):
            DB.touch(household)
    elif target == "APPEALED":
        if case["appeal_count"] >= C.MAX_APPEALS:
            fail("ERR_INVALID_TRANSITION", "The household has exhausted its appeals.")
        deadline = clock.parse_instant(case["sanctioned_at"]) + timedelta(
            days=C.APPEAL_WINDOW_DAYS
        )
        if now > deadline:
            fail("ERR_INVALID_TRANSITION", "The appeal window has elapsed.")
        case["status"] = "APPEALED"
        case["appeal_count"] += 1
        DB.touch(case)
    else:
        deadline = clock.parse_instant(case["sanctioned_at"]) + timedelta(
            days=C.APPEAL_WINDOW_DAYS
        )
        if now <= deadline:
            fail("ERR_INVALID_TRANSITION", "The appeal window has not yet elapsed.")
        case["status"] = "CLOSED"
        DB.touch(case)
    return ok(serialize(case))


@bp.route("/conduct-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    caller = guard(CASE_READ_ROLES)
    known = DB.get("conduct_cases", case_id)
    if known is not None:
        require_owner(caller, known["household_id"])
    return ok(serialize(E.need("conduct_cases", case_id)))


@bp.route("/conduct-cases", methods=["GET"])
def list_cases():
    guard(CASE_READ_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("conduct_cases"),
        request,
        string_fields=("household_id", "severity", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)


# ============================================== the capital reserve §3.10
PROJECT_SPECS = [
    V.f("funding_season_id", "string"),
    V.f("project_kind", "enum", enum=C.PROJECT_KIND),
    V.f("title", "string"),
    V.f("budget_cents", "int", minimum=1),
]
PROJECT_TERMINAL = ("COMPLETED", "REJECTED", "CANCELLED")


@bp.route("/capital-projects", methods=["POST"])
def propose_project():
    caller = guard(("Treasurer",))
    body = V.body_of(request)
    values = V.validate(body, PROJECT_SPECS)
    season = E.need("seasons", values["funding_season_id"])

    project = DB.insert(
        "capital_projects",
        {
            "funding_season_id": season["id"],
            "project_kind": values["project_kind"],
            "title": values["title"],
            "budget_cents": values["budget_cents"],
            "funded_cents": 0,
            "status": "PROPOSED",
            "requested_by_user_id": caller.user_id,
            "approved_by_user_id": None,
        },
    )
    return created(serialize(project))


@bp.route("/capital-projects/<project_id>/transitions", methods=["POST"])
def transition_project(project_id):
    caller = guard(PROJECT_ROLES)
    body = V.body_of(request)
    values = V.validate(body, [V.f("to_status", "enum", enum=C.PROJECT_STATUS)])
    target = values["to_status"]
    project = E.need("capital_projects", project_id)
    current = project["status"]

    # PRD §2.8: "the check is an authorisation concern evaluated before any state
    # or business rule on the same request", and §3.10 names the outcome for this
    # exact caller: "a treasurer-turned-president approving their own proposal is
    # ERR_SEGREGATION_OF_DUTIES". The Treasurer is on this endpoint's §4 role
    # list, so it clears band 2 and must be answered on band 4 — the per-edge
    # role narrowing below cannot pre-empt it.
    if target in ("APPROVED", "REJECTED"):
        require_segregation(caller, project["requested_by_user_id"])

    if target in ("APPROVED", "REJECTED", "CANCELLED"):
        require_transition_role(caller, ("BoardPresident",))
    elif target in ("IN_PROGRESS", "COMPLETED"):
        require_transition_role(caller, ("Treasurer",))

    if current in PROJECT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This project is already in a terminal state.")
    allowed = {
        "PROPOSED": ("APPROVED", "REJECTED"),
        "APPROVED": ("CANCELLED",),
        "FUNDED": ("IN_PROGRESS", "CANCELLED"),
        "IN_PROGRESS": ("COMPLETED", "CANCELLED"),
    }
    if target not in allowed.get(current, ()):
        fail("ERR_INVALID_TRANSITION", "%s is not an edge from %s." % (target, current))

    season = DB.get("seasons", project["funding_season_id"])
    if target == "APPROVED":
        project["status"] = "APPROVED"
        project["approved_by_user_id"] = caller.user_id
        DB.touch(project)
    elif target == "REJECTED":
        project["status"] = "REJECTED"
        DB.touch(project)
    elif target == "IN_PROGRESS":
        if project["funded_cents"] <= 0:
            fail("ERR_INVALID_TRANSITION", "No contractor starts on an unfunded authorisation.")
        project["status"] = "IN_PROGRESS"
        DB.touch(project)
    elif target == "COMPLETED":
        project["status"] = "COMPLETED"
        DB.touch(project)
    else:
        returned = project["funded_cents"]
        project["status"] = "CANCELLED"
        project["funded_cents"] = 0
        DB.touch(project)
        if returned > 0 and season is not None:
            season["reserve_unallocated_cents"] += returned
            DB.touch(season)
    return ok(serialize(project))


FUND_SPECS = [
    V.f("draw_amount_cents", "int", minimum=0),
    V.f("expected_capital_project_version", "int", minimum=0),
    V.f("season_id", "string", required=False),
]


@bp.route("/capital-projects/<project_id>/fund", methods=["POST"])
def fund_project(project_id):
    guard(("Treasurer",))
    body = V.body_of(request)
    values = V.validate(body, FUND_SPECS)
    project = E.need("capital_projects", project_id)
    season = E.need("seasons", project["funding_season_id"])

    if values["expected_capital_project_version"] != project["version"]:
        fail("ERR_STALE_PROJECT_VERSION", "The project has moved since it was last read.")

    if project["status"] in PROJECT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "This project is already in a terminal state.")
    if project["status"] not in ("APPROVED", "FUNDED"):
        fail("ERR_INVALID_TRANSITION", "A draw is available from APPROVED and from FUNDED only.")

    named_season = values["season_id"]
    if named_season and named_season != project["funding_season_id"]:
        fail("ERR_SEASON_MISMATCH", "The project is funded from a different season's reserve.")

    amount = values["draw_amount_cents"]
    if amount > season["reserve_unallocated_cents"]:
        fail("ERR_INSUFFICIENT_RESERVE", "The season's unallocated reserve is too small.")
    if project["funded_cents"] + amount > project["budget_cents"]:
        fail("ERR_DRAW_EXCEEDS_BUDGET", "The draw would exceed the project's authorised budget.")

    project["funded_cents"] += amount
    if project["status"] == "APPROVED":
        project["status"] = "FUNDED"
    DB.touch(project)
    season["reserve_unallocated_cents"] -= amount
    DB.touch(season)
    return ok(serialize(project))


@bp.route("/capital-projects/<project_id>", methods=["GET"])
def read_project(project_id):
    guard(PROJECT_ROLES)
    return ok(serialize(E.need("capital_projects", project_id)))


@bp.route("/capital-projects", methods=["GET"])
def list_projects():
    guard(PROJECT_ROLES)
    limit, offset = V.pagination(request)
    rows = V.apply_filters(
        DB.all("capital_projects"),
        request,
        string_fields=("funding_season_id", "project_kind", "status"),
    )
    page, total = V.paginate(rows, limit, offset)
    return ok_list(serialize_many(page), limit, offset, total)
