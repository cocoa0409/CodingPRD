"""Party designations, expulsion cascade, seats, conduct violations (PRD 3.3-3.4).

POST /party-designations                                         PartyCoordinator
GET  /party-designations                                         all roles
GET  /party-designations/{id}                                    all roles
POST /party-designations/{id}/expel                              ManagingDirector
POST /party-designations/{id}/seats                              IIC
POST /party-designations/{id}/seats/{seat_id}/conduct-violations IIC
"""

from flask import Blueprint, request

import clock
import db
import domain
from auth import get_context, require_iic, require_roles
from constants import (
    EXCLUDED_PARTY_ORG_TYPES,
    ROLES,
    SUSPENSION_STRIKE_THRESHOLD,
    VIOLATION_KINDS,
)
from envelope import ok_list, ok_object, paginate, parse_pagination
from errors import api_error
from serializers import designation_public
from validate import get_body, opt_str, req_enum, req_str

bp = Blueprint("designations", __name__)


def _investigation_of(designation):
    """The designation's investigation (its creation was FK-validated)."""
    return db.store["investigations"].get(designation["investigation_id"])


@bp.route("/party-designations", methods=["POST"])
def create_designation():
    _user_id, role = get_context()
    require_roles(role, ("PartyCoordinator",))
    body = get_body()
    investigation_id = req_str(body, "investigation_id")
    organization_id = req_str(body, "organization_id")
    investigation = domain.get_investigation(investigation_id)
    organization = domain.get_organization(organization_id)

    if organization["org_type"] in EXCLUDED_PARTY_ORG_TYPES:
        raise api_error(
            "ERR_PARTY_TYPE_EXCLUDED",
            "organizations of type %s are statutorily excluded from party "
            "status" % organization["org_type"],
        )
    for existing in db.store["party_designations"].values():
        if (
            existing["investigation_id"] == investigation["id"]
            and existing["organization_id"] == organization["id"]
            and existing["status"] == "ACTIVE"
        ):
            raise api_error(
                "ERR_DUPLICATE_DESIGNATION",
                "an ACTIVE designation already exists for this investigation "
                "and organization",
            )

    designation = db.add(
        "party_designations",
        {
            "investigation_id": investigation["id"],
            "organization_id": organization["id"],
            "status": "ACTIVE",
            "designated_at": clock.get_clock(),
            "expulsion_reason": None,
            "group_seats": [],
        },
    )
    return ok_object(designation_public(designation), status=201)


@bp.route("/party-designations", methods=["GET"])
def list_designations():
    _user_id, role = get_context()
    require_roles(role, ROLES)
    limit, offset = parse_pagination(request.args)
    items = db.all_of("party_designations")
    investigation_id = request.args.get("investigation_id")
    if investigation_id is not None:
        items = [d for d in items if d["investigation_id"] == investigation_id]
    organization_id = request.args.get("organization_id")
    if organization_id is not None:
        items = [d for d in items if d["organization_id"] == organization_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list(
        [designation_public(d) for d in page], limit, offset, total
    )


@bp.route("/party-designations/<designation_id>", methods=["GET"])
def get_designation(designation_id):
    _user_id, role = get_context()
    require_roles(role, ROLES)
    designation = domain.get_designation(designation_id)
    return ok_object(designation_public(designation), status=200)


@bp.route("/party-designations/<designation_id>/expel", methods=["POST"])
def expel_designation(designation_id):
    _user_id, role = get_context()
    require_roles(role, ("ManagingDirector",))
    designation = domain.get_designation(designation_id)

    if designation["status"] != "ACTIVE":
        raise api_error(
            "ERR_DESIGNATION_NOT_ACTIVE",
            "only an ACTIVE designation may be expelled",
        )
    qualifying = any(
        entry["violation_kind"] == "PREMATURE_PUBLIC_STATEMENT"
        for seat in designation["group_seats"]
        for entry in seat["conduct_log"]
    )
    if not qualifying:
        raise api_error(
            "ERR_EXPULSION_WITHOUT_QUALIFYING_VIOLATION",
            "expulsion requires at least one PREMATURE_PUBLIC_STATEMENT "
            "conduct violation on the designation's seats",
        )

    body = get_body()
    reason = opt_str(body, "reason")

    designation["status"] = "EXPELLED"
    designation["expulsion_reason"] = reason

    # Cascade link 2: every SEATED or SUSPENDED seat is REMOVED.
    affected_group_ids = []
    for seat in designation["group_seats"]:
        if seat["status"] in ("SEATED", "SUSPENDED"):
            seat["status"] = "REMOVED"
            affected_group_ids.append(seat["group_id"])

    # Cascade link 3: a group left with zero seated parties reverts from
    # COMPLETE back to ACTIVE.
    for group_id in dict.fromkeys(affected_group_ids):
        group = db.store["groups"].get(group_id)
        if group is None:
            continue
        domain.recompute_seated_count(group)
        if group["status"] == "COMPLETE" and group["seated_count"] == 0:
            group["status"] = "ACTIVE"
            db.touch(group)

    # Cascade link 4: recompute completeness and bump the investigation.
    investigation = _investigation_of(designation)
    if investigation is not None:
        domain.recompute_docket_pct(investigation)
        db.touch(investigation)

    db.touch(designation)
    return ok_object(designation_public(designation), status=200)


@bp.route("/party-designations/<designation_id>/seats", methods=["POST"])
def create_seat(designation_id):
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    designation = domain.get_designation(designation_id)
    investigation = _investigation_of(designation)
    if investigation is not None:
        require_iic(user_id, investigation)
    body = get_body()
    group_id = req_str(body, "group_id")
    group = domain.get_group(group_id)

    # State checks: path-addressed designation before body-referenced group.
    if designation["status"] != "ACTIVE":
        raise api_error(
            "ERR_DESIGNATION_NOT_ACTIVE",
            "seats may only be added to an ACTIVE designation",
        )
    if group["status"] != "ACTIVE":
        raise api_error(
            "ERR_GROUP_NOT_ACTIVE",
            "seats may only be added to an ACTIVE group",
        )
    for seat in designation["group_seats"]:
        if seat["group_id"] == group["id"] and seat["status"] == "SEATED":
            raise api_error(
                "ERR_DUPLICATE_SEAT",
                "the designation already holds a SEATED seat on this group",
            )

    seat = {
        "seat_id": db.new_id(),
        "group_id": group["id"],
        "status": "SEATED",
        "strike_count": 0,
        "conduct_log": [],
    }
    designation["group_seats"].append(seat)
    domain.recompute_seated_count(group)
    db.touch(designation)
    return ok_object(designation_public(designation), status=201)


@bp.route(
    "/party-designations/<designation_id>/seats/<seat_id>/conduct-violations",
    methods=["POST"],
)
def record_conduct_violation(designation_id, seat_id):
    user_id, role = get_context()
    require_roles(role, ("IIC",))
    designation = domain.get_designation(designation_id)
    investigation = _investigation_of(designation)
    if investigation is not None:
        require_iic(user_id, investigation)
    seat = domain.find_seat(designation, seat_id)
    body = get_body()
    violation_kind = req_enum(body, "violation_kind", VIOLATION_KINDS)
    detail = req_str(body, "detail")

    # State checks: outer designation before the embedded seat (section 2.6).
    if designation["status"] != "ACTIVE":
        raise api_error(
            "ERR_DESIGNATION_NOT_ACTIVE",
            "conduct violations require an ACTIVE designation",
        )
    if seat["status"] != "SEATED":
        raise api_error(
            "ERR_SEAT_NOT_SEATED",
            "a conduct violation can only be recorded against a SEATED seat",
        )

    seat["conduct_log"].append(
        {
            "violation_kind": violation_kind,
            "detail": detail,
            "recorded_at": clock.get_clock(),
        }
    )
    seat["strike_count"] = len(seat["conduct_log"])
    if (
        seat["strike_count"] >= SUSPENSION_STRIKE_THRESHOLD
        and seat["status"] == "SEATED"
    ):
        seat["status"] = "SUSPENDED"
        group = db.store["groups"].get(seat["group_id"])
        if group is not None:
            domain.recompute_seated_count(group)
    db.touch(designation)
    return ok_object(designation_public(designation), status=201)
