"""Participations: invite, read, execute-cia, designate-lead, withdraw."""
from flask import Blueprint

import auth
import db
import envelope
import errors
import serialize
import validate

bp = Blueprint("participations", __name__, url_prefix="/multistate")

CIA_TIERS = ("STANDARD", "RESTRICTED", "LEAD_ONLY")
AG_ROLES = ("ParticipatingStateAG", "LeadStateAG")


@bp.route("/investigations/<investigation_id>/participations", methods=["POST"])
def invite_participation(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    state_office_id = validate.req_str(body, "state_office_id")
    inv = validate.get_investigation_or_404(investigation_id)
    office = db.offices.get(state_office_id)
    if office is None:
        raise errors.office_not_found()
    for p in db.participations.values():
        if (
            p["investigation_id"] == inv["id"]
            and p["state_office_id"] == office["id"]
            and p["status"] != "WITHDRAWN"
        ):
            raise errors.ApiError(
                "ERR_DUPLICATE_PARTICIPATION",
                409,
                "Office already holds a non-WITHDRAWN participation in this investigation",
            )
    part = db.new_entity(db.participations)
    part.update(
        {
            "investigation_id": inv["id"],
            "state_office_id": office["id"],
            "status": "INVITED",
            "cia_status": "NOT_EXECUTED",
            "cia_tier": None,
            "committee_role": "MEMBER",
            "invited_at": db.now(),
            "cia_executed_at": None,
            "withdrawn_at": None,
            "_lead_seq": None,
        }
    )
    return envelope.success_object(serialize.serialize("participation", part), 201)


@bp.route("/participations/<participation_id>", methods=["GET"])
def get_participation(participation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    part = validate.get_participation_or_404(participation_id)
    return envelope.success_object(serialize.serialize("participation", part))


@bp.route("/participations/<participation_id>/execute-cia", methods=["POST"])
def execute_cia(participation_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, AG_ROLES)
    body = validate.body_json()
    tier = validate.req_enum(body, "confidentiality_tier", CIA_TIERS)
    part = validate.get_participation_or_404(participation_id)
    auth.require_own_office(part, uid)
    if part["status"] != "INVITED":
        raise errors.invalid_state("Participation is not INVITED")
    part["status"] = "ACTIVE"
    part["cia_status"] = "EXECUTED"
    part["cia_tier"] = tier
    part["cia_executed_at"] = db.now()
    db.touch(part)
    return envelope.success_object(serialize.serialize("participation", part))


@bp.route("/participations/<participation_id>/designate-lead", methods=["POST"])
def designate_lead(participation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    part = validate.get_participation_or_404(participation_id)
    if part["status"] != "ACTIVE":
        raise errors.ApiError(
            "ERR_PARTICIPATION_INACTIVE", 409, "Participation is not ACTIVE"
        )
    inv = db.investigations.get(part["investigation_id"])
    if inv is not None and inv["phase"] not in ("DRAFT", "OPEN"):
        raise errors.invalid_phase("Lead designation requires phase DRAFT or OPEN")
    if part["cia_tier"] not in ("RESTRICTED", "LEAD_ONLY"):
        raise errors.ApiError(
            "ERR_CIA_TIER_INSUFFICIENT",
            422,
            "Lead designation requires cia_tier RESTRICTED or LEAD_ONLY",
        )
    part["committee_role"] = "LEAD"
    part["_lead_seq"] = db.next_lead_seq()
    db.touch(part)
    return envelope.success_object(serialize.serialize("participation", part))


@bp.route("/participations/<participation_id>/withdraw", methods=["POST"])
def withdraw_participation(participation_id):
    role, uid = auth.authenticate()
    auth.require_roles(role, AG_ROLES + ("CommitteeChair",))
    part = validate.get_participation_or_404(participation_id)
    if role != "CommitteeChair":
        auth.require_own_office(part, uid)
    if part["status"] != "ACTIVE":
        raise errors.invalid_state("Participation is not ACTIVE")
    for settlement in db.settlements.values():
        if settlement["investigation_id"] != part["investigation_id"]:
            continue
        if settlement["term_status"] in ("COLLAPSED", "CLOSED_OUT"):
            continue
        for entry in settlement.get("sign_ons", []):
            if (
                entry["state_office_id"] == part["state_office_id"]
                and entry["status"] in ("SIGNED", "LOCKED")
            ):
                raise errors.ApiError(
                    "ERR_SIGNED_STATE_CANNOT_WITHDRAW",
                    409,
                    "Office holds a SIGNED/LOCKED sign-on on a non-terminal settlement",
                )
    part["status"] = "WITHDRAWN"
    part["committee_role"] = "MEMBER"
    part["withdrawn_at"] = db.now()
    db.touch(part)
    return envelope.success_object(serialize.serialize("participation", part))
