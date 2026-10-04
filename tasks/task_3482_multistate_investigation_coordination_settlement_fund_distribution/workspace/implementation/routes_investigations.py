"""Investigations: create, read, phase advance, investigation-scoped lists."""
from flask import Blueprint

import auth
import calc
import db
import envelope
import errors
import serialize
import services
import validate

bp = Blueprint("investigations", __name__, url_prefix="/multistate")

CHAIN = (
    "DRAFT",
    "OPEN",
    "DISCOVERY",
    "NEGOTIATION",
    "SETTLEMENT_PENDING",
    "SETTLED",
    "MONITORING",
    "CLOSED",
)
SETTABLE_TARGETS = ("OPEN", "DISCOVERY", "NEGOTIATION", "SETTLEMENT_PENDING", "SETTLED", "MONITORING")
LEAD_WINDOW_PHASES = ("OPEN", "DISCOVERY", "NEGOTIATION", "SETTLEMENT_PENDING")


@bp.route("/investigations", methods=["POST"])
def create_investigation():
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    title = validate.req_str(body, "title")
    target_name = validate.req_str(body, "target_name")
    summary = validate.req_str(body, "summary")
    inv = db.new_entity(db.investigations)
    inv.update(
        {
            "title": title,
            "target_name": target_name,
            "summary": summary,
            "phase": "DRAFT",
            "opened_at": None,
            "settled_at": None,
            "active_settlement_id": None,
        }
    )
    return envelope.success_object(serialize.serialize("investigation", inv), 201)


@bp.route("/investigations/<investigation_id>", methods=["GET"])
def get_investigation(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    inv = validate.get_investigation_or_404(investigation_id)
    return envelope.success_object(serialize.serialize("investigation", inv))


def _lead_window_conflict(inv):
    """True iff a LEAD office of this investigation already holds committee_role
    LEAD on another investigation in an active lead-window phase (PRD §3.1)."""
    lead_office_ids = {
        p["state_office_id"]
        for p in db.participations.values()
        if p["investigation_id"] == inv["id"]
        and p["status"] == "ACTIVE"
        and p["committee_role"] == "LEAD"
    }
    for office_id in lead_office_ids:
        for other_p in db.participations.values():
            if other_p["investigation_id"] == inv["id"]:
                continue
            if other_p["state_office_id"] != office_id or other_p["committee_role"] != "LEAD":
                continue
            other_inv = db.investigations.get(other_p["investigation_id"])
            if other_inv is not None and other_inv["phase"] in LEAD_WINDOW_PHASES:
                return True
    return False


@bp.route("/investigations/<investigation_id>/advance", methods=["POST"])
def advance_investigation(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, ("CommitteeChair",))
    body = validate.body_json()
    to_phase = validate.req_enum(body, "to_phase", CHAIN)
    inv = validate.get_investigation_or_404(investigation_id)
    current = inv["phase"]
    if to_phase not in SETTABLE_TARGETS or CHAIN.index(to_phase) != CHAIN.index(current) + 1:
        raise errors.invalid_phase(
            f"Advance from {current} to {to_phase} is not a declared one-step transition"
        )
    if to_phase == "OPEN":
        # Rung 10 (temporal) before rung 11 (business constraint).
        if _lead_window_conflict(inv):
            raise errors.ApiError(
                "ERR_LEAD_WINDOW_OVERLAP",
                409,
                "A lead office already occupies an active lead window on another investigation",
            )
        actives = services.active_participations_of(inv["id"])
        leads = [p for p in actives if p["committee_role"] == "LEAD"]
        if len(leads) < calc.LEAD_MIN_COUNT or len(actives) < calc.ACTIVE_PARTICIPATION_MIN:
            raise errors.ApiError(
                "ERR_ACTIVATION_QUORUM_MISSING",
                422,
                "Fewer than 2 leads or fewer than 3 active participations at activation",
            )
        inv["opened_at"] = db.now()
    elif to_phase == "NEGOTIATION":
        covered = any(
            r["investigation_id"] == inv["id"] and r["status"] in ("ACCEPTED", "FULFILLED")
            for r in db.responses.values()
        )
        if not covered:
            raise errors.ApiError(
                "ERR_NO_ACCEPTED_RESPONSE",
                422,
                "Advance to NEGOTIATION requires an ACCEPTED or FULFILLED consolidated response",
            )
    elif to_phase == "SETTLEMENT_PENDING":
        settlement = services.live_settlement_of_investigation(inv["id"])
        if settlement is None or settlement["term_status"] not in ("TERMS_AGREED", "SIGN_ON_OPEN"):
            raise errors.ApiError(
                "ERR_NO_AGREED_SETTLEMENT",
                422,
                "Advance to SETTLEMENT_PENDING requires a TERMS_AGREED or later settlement",
            )
    elif to_phase == "SETTLED":
        settlement = services.live_settlement_of_investigation(inv["id"])
        if settlement is None or settlement["term_status"] != "EXECUTED":
            raise errors.invalid_state("Advance to SETTLED requires an EXECUTED active settlement")
        inv["settled_at"] = db.now()
    elif to_phase == "MONITORING":
        settlement = services.live_settlement_of_investigation(inv["id"])
        if settlement is None or settlement["fund_status"] not in (
            "FUNDED",
            "DISBURSING",
            "DISBURSED",
        ):
            raise errors.ApiError(
                "ERR_SETTLEMENT_NOT_FUNDED",
                409,
                "Active settlement fund is below FUNDED; cannot enter MONITORING",
            )
    inv["phase"] = to_phase
    db.touch(inv)
    return envelope.success_object(serialize.serialize("investigation", inv))


@bp.route("/investigations/<investigation_id>/participations", methods=["GET"])
def list_investigation_participations(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_investigation_or_404(investigation_id)
    items = [p for p in db.participations.values() if p["investigation_id"] == investigation_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("participation", page), limit, offset, total
    )


@bp.route("/investigations/<investigation_id>/responses", methods=["GET"])
def list_investigation_responses(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_investigation_or_404(investigation_id)
    items = [r for r in db.responses.values() if r["investigation_id"] == investigation_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("response", page), limit, offset, total
    )


@bp.route("/investigations/<investigation_id>/settlements", methods=["GET"])
def list_investigation_settlements(investigation_id):
    role, _uid = auth.authenticate()
    auth.require_roles(role, auth.ALL_ROLES)
    limit, offset = validate.pagination_params()
    validate.get_investigation_or_404(investigation_id)
    items = [s for s in db.settlements.values() if s["investigation_id"] == investigation_id]
    page, total = validate.paginate(items, limit, offset)
    return envelope.success_list(
        serialize.serialize_list("settlement", page), limit, offset, total
    )
