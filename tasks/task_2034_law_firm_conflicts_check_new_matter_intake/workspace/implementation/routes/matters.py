"""Matter endpoints: open intake, read (wall-gated), amend (OCC), roster,
lifecycle transitions (PRD 3.3)."""

from flask import Blueprint, request

import db
from db import stamp_new, bump, now_iso
from errors import (
    ApiError, invalid, forbidden, not_found,
    ERR_WALL_EXCLUDED, ERR_NOT_RESPONSIBLE_ATTORNEY,
    ERR_MATTER_NOT_INTAKE, ERR_MATTER_NOT_OPEN, ERR_MATTER_TERMINAL,
    ERR_ATTORNEY_ADVERSE_OVERLAP, ERR_ATTORNEY_NOT_ACTIVE,
    ERR_PARTY_ALREADY_ON_MATTER,
)
from middleware import caller, admit, admit_action, body, ATTORNEY_ROLES
from response import ok_object, paginate, sort_by_created
from services.clearance import recompute_clearance, supersede_checks
from services.validate import (
    PRACTICE_GROUPS, ROLES_IN_MATTER, resolve, check_occ, require_occ,
    adverse_overlap_check,
)

bp = Blueprint("matters", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")


def _assignment_gates(attorney, client_party_id, roster, exclude_matter_id):
    """Tier 7 assignment gates: adverse overlap (V-T1) then attorney-active,
    in the scaffold's listed priority order."""
    if adverse_overlap_check(attorney["id"], client_party_id, roster,
                             exclude_matter_id=exclude_matter_id):
        raise ApiError(ERR_ATTORNEY_ADVERSE_OVERLAP, 422,
                       "Responsible-attorney adverse overlap with another "
                       "OPEN matter")
    if attorney["status"] != "ACTIVE":
        raise ApiError(ERR_ATTORNEY_NOT_ACTIVE, 422,
                       "responsible_attorney_id must reference an ACTIVE "
                       "attorney")


@bp.post("/intake/matters")
def create_matter():
    _, role = caller()
    admit(role, ("IntakeSpecialist",))
    data = body()

    # Tier 3: body FK resolution before state/shape tiers.
    client_party_id = data.get("client_party_id")
    responsible_attorney_id = data.get("responsible_attorney_id")
    client = resolve(db.store.parties, client_party_id) \
        if client_party_id is not None else None
    attorney = resolve(db.store.attorneys, responsible_attorney_id) \
        if responsible_attorney_id is not None else None

    # Tier 7: assignment gates (a new matter's roster is empty).
    if attorney is not None and client is not None:
        _assignment_gates(attorney, client["id"], [], exclude_matter_id=None)

    # Tier 12: request shape.
    if client is None:
        raise invalid("client_party_id is required")
    if attorney is None:
        raise invalid("responsible_attorney_id is required")
    practice_group = data.get("practice_group")
    if practice_group not in PRACTICE_GROUPS:
        raise invalid("practice_group must be one of " + ", ".join(PRACTICE_GROUPS))
    matter_title = data.get("matter_title", "")
    if not isinstance(matter_title, str):
        raise invalid("matter_title must be a string")

    matter = stamp_new({
        "matter_title": matter_title,
        "client_party_id": client_party_id,
        "responsible_attorney_id": responsible_attorney_id,
        "practice_group": practice_group,
        "lifecycle_status": "INTAKE",
        "clearance_status": "UNCHECKED",
        "matter_number": None,
        "opened_at": None,
        "closed_at": None,
        "decline_reason": "",
    })
    db.store.matters[matter["id"]] = matter
    return ok_object(matter, 201)


@bp.get("/intake/matters")
def list_matters():
    _, role = caller()
    admit(role, STAFF)
    rows = list(db.store.matters.values())
    for param in ("client_party_id", "responsible_attorney_id",
                  "lifecycle_status", "clearance_status"):
        value = request.args.get(param)
        if value is not None:
            rows = [m for m in rows if m[param] == value]
    return paginate(sort_by_created(rows), request.args)


@bp.get("/intake/matters/<mid>")
def get_matter(mid):
    user_id, role = caller()
    admit(role, STAFF + ("Client",))
    matter = resolve(db.store.matters, mid)

    # Tier 4 wall gate (PRD 2.9): entity-backed attorney callers only;
    # LATERAL_PENDING attorneys may not read any matter.
    if role in ATTORNEY_ROLES:
        attorney = db.store.attorneys.get(user_id)
        if attorney is not None and attorney["status"] == "LATERAL_PENDING":
            raise ApiError(ERR_WALL_EXCLUDED, 403,
                           "LATERAL_PENDING attorneys may not read matters")
        for wall in db.store.ethical_walls.values():
            if (wall["matter_id"] == matter["id"]
                    and wall["status"] == "ACTIVE"
                    and user_id in wall["excluded_attorney_ids"]):
                raise ApiError(ERR_WALL_EXCLUDED, 403,
                               "Caller is excluded by an active ethical wall")

    # Tier 5 ownership: a Client reads only its own matters.
    if role == "Client" and user_id != matter["client_party_id"]:
        raise forbidden("Client may read only its own matters")
    return ok_object(matter)


@bp.patch("/intake/matters/<mid>")
def patch_matter(mid):
    _, role = caller()
    admit(role, ("IntakeSpecialist",))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 3: body FK resolution.
    new_attorney = None
    if "responsible_attorney_id" in data and data["responsible_attorney_id"] is not None:
        new_attorney = resolve(db.store.attorneys, data["responsible_attorney_id"])

    # Tier 6: terminal gate, then OCC.
    if matter["lifecycle_status"] in ("CLOSED", "DECLINED"):
        raise ApiError(ERR_MATTER_TERMINAL, 409,
                       "Cannot amend a CLOSED or DECLINED matter")
    check_occ(data, matter)

    # Tier 7: changing the responsible attorney re-runs both gates.
    attorney_changed = (new_attorney is not None
                        and new_attorney["id"] != matter["responsible_attorney_id"])
    if attorney_changed:
        roster = [(mp["party_id"], mp["role_in_matter"])
                  for mp in db.store.matter_parties.values()
                  if mp["matter_id"] == matter["id"]]
        _assignment_gates(new_attorney, matter["client_party_id"], roster,
                          exclude_matter_id=matter["id"])

    # Tier 12: request shape.
    require_occ(data)
    if "practice_group" in data and data["practice_group"] is not None:
        if data["practice_group"] not in PRACTICE_GROUPS:
            raise invalid("practice_group must be one of " + ", ".join(PRACTICE_GROUPS))
    if "matter_title" in data and data["matter_title"] is not None:
        if not isinstance(data["matter_title"], str):
            raise invalid("matter_title must be a string")

    if "matter_title" in data and data["matter_title"] is not None:
        matter["matter_title"] = data["matter_title"]
    if "practice_group" in data and data["practice_group"] is not None:
        matter["practice_group"] = data["practice_group"]
    if attorney_changed:
        matter["responsible_attorney_id"] = new_attorney["id"]
        # Roster-affecting edit: supersede COMPLETED INTAKE checks (staling
        # their PENDING hits), then recompute clearance.
        supersede_checks(matter, "INTAKE")
        recompute_clearance(matter)
    bump(matter)
    return ok_object(matter)


@bp.post("/intake/matters/<mid>/parties")
def add_matter_party(mid):
    _, role = caller()
    admit(role, ("IntakeSpecialist",))
    matter = resolve(db.store.matters, mid)
    data = body()

    # Tier 3: party FK resolution.
    party_id = data.get("party_id")
    party = resolve(db.store.parties, party_id) if party_id is not None else None

    # Tier 6: roster changes rejected on terminal matters.
    if matter["lifecycle_status"] in ("CLOSED", "DECLINED"):
        raise ApiError(ERR_MATTER_TERMINAL, 409,
                       "Cannot change the roster of a CLOSED or DECLINED matter")

    # Tier 7: the identical adverse-overlap evaluation guards roster
    # additions, applied to the post-add roster.
    new_role = data.get("role_in_matter")
    if party is not None:
        roster = [(mp["party_id"], mp["role_in_matter"])
                  for mp in db.store.matter_parties.values()
                  if mp["matter_id"] == matter["id"]]
        roster.append((party["id"], new_role))
        if adverse_overlap_check(matter["responsible_attorney_id"],
                                 matter["client_party_id"], roster,
                                 exclude_matter_id=matter["id"]):
            raise ApiError(ERR_ATTORNEY_ADVERSE_OVERLAP, 422,
                           "Responsible-attorney adverse overlap with another "
                           "OPEN matter")

    # Tier 10: party already on the roster.
    if party is not None:
        for mp in db.store.matter_parties.values():
            if mp["matter_id"] == matter["id"] and mp["party_id"] == party["id"]:
                raise ApiError(ERR_PARTY_ALREADY_ON_MATTER, 409,
                               "Party is already on the matter roster")

    # Tier 12: request shape.
    if party is None:
        raise invalid("party_id is required")
    if new_role not in ROLES_IN_MATTER:
        raise invalid("role_in_matter must be one of " + ", ".join(ROLES_IN_MATTER))

    row = stamp_new({
        "matter_id": matter["id"],
        "party_id": party["id"],
        "role_in_matter": new_role,
    })
    db.store.matter_parties[row["id"]] = row

    # Roster additions supersede the matter's COMPLETED INTAKE checks,
    # stale their PENDING hits, recompute clearance, and bump the matter.
    supersede_checks(matter, "INTAKE")
    recompute_clearance(matter)
    bump(matter)
    return ok_object(row, 201)


@bp.get("/intake/matters/<mid>/parties")
def list_matter_parties(mid):
    _, role = caller()
    admit(role, STAFF)
    resolve(db.store.matters, mid)
    rows = [mp for mp in db.store.matter_parties.values()
            if mp["matter_id"] == mid]
    return paginate(sort_by_created(rows), request.args)


@bp.post("/intake/matters/<mid>/transition")
def matter_transition(mid):
    user_id, role = caller()
    admit(role, ("ResponsibleAttorney", "ConflictsPartner"))
    data = body()
    action = data.get("action")

    # Tier 2 per-action role rules (requires a recognized action).
    if action == "DECLINE":
        admit_action(role, ("ConflictsPartner",))
    elif action == "CLOSE":
        admit_action(role, ("ResponsibleAttorney", "ConflictsPartner"))

    # Tier 3: path resolution.
    matter = resolve(db.store.matters, mid)

    if action == "DECLINE":
        # Tier 6: INTAKE only.
        if matter["lifecycle_status"] != "INTAKE":
            raise ApiError(ERR_MATTER_NOT_INTAKE, 409,
                           "DECLINE requires lifecycle INTAKE")
        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise invalid("reason must be a string")
        matter["lifecycle_status"] = "DECLINED"
        matter["decline_reason"] = reason if reason is not None else ""
        bump(matter)
        return ok_object(matter)

    if action == "CLOSE":
        # Tier 5 ownership: a ResponsibleAttorney caller must be the
        # matter's responsible attorney.
        if (role == "ResponsibleAttorney"
                and user_id != matter["responsible_attorney_id"]):
            raise ApiError(ERR_NOT_RESPONSIBLE_ATTORNEY, 403,
                           "Caller is not the matter's responsible attorney")
        # Tier 6: OPEN only.
        if matter["lifecycle_status"] != "OPEN":
            raise ApiError(ERR_MATTER_NOT_OPEN, 409,
                           "CLOSE requires lifecycle OPEN")
        matter["lifecycle_status"] = "CLOSED"
        matter["closed_at"] = now_iso()
        bump(matter)
        return ok_object(matter)

    raise invalid("action must be DECLINE or CLOSE")
