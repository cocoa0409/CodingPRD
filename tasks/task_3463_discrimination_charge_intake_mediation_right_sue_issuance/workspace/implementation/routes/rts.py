"""Right-to-sue notices and settlement vacatur (PRD 3.8)."""

from datetime import timedelta
from flask import Blueprint

import constants
import serializers
from domain import cascades
from errors import (
    ApiError,
    ERR_CHARGE_ALREADY_CLOSED,
    ERR_CONCILIATION_ACTIVE,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_RTS_PREMATURE,
    ERR_VACATE_WINDOW_EXPIRED,
)
from helpers import (
    authenticate,
    bump,
    check_party_ownership,
    common_fields,
    now,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
    today,
)
from serializers import charge_days_elapsed
from store import db
from validation import req_string
from routes.charges import get_charge_or_404

bp = Blueprint("rts", __name__, url_prefix="/eeoc")

# States from which a right-to-sue notice may be issued (the six non-terminal,
# non-conciliating, non-settled states per the Charge state machine).
_RTS_ISSUABLE_STATES = (
    constants.CHARGE_DOCKETED,
    constants.CHARGE_IN_MEDIATION,
    constants.CHARGE_UNDER_INVESTIGATION,
    constants.CHARGE_DETERMINATION_REVIEW,
    constants.CHARGE_DELEGATED_TO_FEPA,
    constants.CHARGE_LITIGATION_REFERRED,
)

_LIST_ROLES = (
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_DIRECTOR,
    constants.ROLE_INTAKE_OFFICER,
)


@bp.post("/charges/<charge_id>/right-to-sue-notices")
def issue_right_to_sue(charge_id):
    user_id, role = authenticate()
    require_roles(
        role, (constants.ROLE_CHARGING_PARTY, constants.ROLE_DIRECTOR)
    )
    request_body(required=False)
    charge = get_charge_or_404(charge_id)

    # Step 5: ownership.
    if role == constants.ROLE_CHARGING_PARTY and user_id != charge["complainant_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "ChargingParty may only request notices on its own charges.",
        )
    # Step 6: state. A terminal charge reports its closedness (outranking the
    # prematurity check); a live conciliation blocks issuance specifically.
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if charge["case_status"] == constants.CHARGE_CONCILIATION:
        raise ApiError(
            ERR_CONCILIATION_ACTIVE,
            "A non-terminal conciliation blocks right-to-sue issuance.",
        )
    if charge["case_status"] not in _RTS_ISSUABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Right-to-sue cannot be issued from %s." % charge["case_status"],
        )
    # Exactly one notice per charge.
    for existing in db.right_to_sue_notices.values():
        if existing["charge_id"] == charge["id"]:
            raise ApiError(
                ERR_INVALID_STATE,
                "A right-to-sue notice already exists for this charge.",
            )
    # Step 9: the charging-party path requires 180 days elapsed; the Director
    # path is unconditional.
    if role == constants.ROLE_CHARGING_PARTY:
        if charge_days_elapsed(charge) < constants.RTS_MIN_ELAPSED_DAYS:
            raise ApiError(
                ERR_RTS_PREMATURE,
                "Fewer than %d days have elapsed since filing."
                % constants.RTS_MIN_ELAPSED_DAYS,
            )

    issued = today()
    notice = {
        **common_fields(),
        "charge_id": charge["id"],
        "issuance_basis": (
            constants.RTS_BASIS_ELAPSED
            if role == constants.ROLE_CHARGING_PARTY
            else constants.RTS_BASIS_DIRECTOR
        ),
        "requested_by_role": role,
        "issued_date": issued,
        "court_filing_deadline": issued
        + timedelta(days=constants.RTS_COURT_FILING_DAYS),
        "status": constants.RTS_ISSUED,
    }
    db.right_to_sue_notices[notice["id"]] = notice

    # The issuance cascade is deliberately asymmetric by prior state
    # (PRD 3.8): from IN_MEDIATION the mediation case is NOT touched (it may
    # be orphaned), while the investigation is closed in every state that has
    # one; from DOCKETED an OFFERED mediation is DECLINED.
    if charge["case_status"] == constants.CHARGE_DOCKETED:
        cascades.decline_open_mediations(charge)
    investigation = cascades.investigation_for_charge(charge)
    if investigation is not None:
        cascades.close_investigation(investigation)

    charge["case_status"] = constants.CHARGE_RTS_ISSUED
    bump(charge)
    cascades.reeval_systemic_for_charge(charge)
    return respond_object(
        serializers.serialize_right_to_sue_notice(notice), status=201
    )


@bp.get("/charges/<charge_id>/right-to-sue-notices")
def list_right_to_sue_notices(charge_id):
    user_id, role = authenticate()
    require_roles(role, _LIST_ROLES)
    charge = get_charge_or_404(charge_id)
    check_party_ownership(user_id, role, charge)
    rows = [
        n for n in db.right_to_sue_notices.values() if n["charge_id"] == charge["id"]
    ]
    for notice in rows:
        cascades.refresh_notice_lazy(notice)
    return paginate_and_respond(rows, serializers.serialize_right_to_sue_notice)


@bp.post("/charges/<charge_id>/vacate-settlement")
def vacate_settlement(charge_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_DIRECTOR,))
    body = request_body()
    req_string(body, "reason")

    charge = get_charge_or_404(charge_id)
    # Step 6: vacatur requires CLOSED_SETTLED via MEDIATION; conciliation
    # settlements are final.
    if charge["case_status"] in constants.CHARGE_TERMINAL_STATES:
        raise ApiError(ERR_CHARGE_ALREADY_CLOSED, "Charge is in a terminal state.")
    if charge["case_status"] != constants.CHARGE_CLOSED_SETTLED:
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a CLOSED_SETTLED charge can be vacated.",
        )
    if charge["settled_via"] != constants.SETTLED_VIA_MEDIATION:
        raise ApiError(
            ERR_INVALID_STATE,
            "Conciliation settlements are final and cannot be vacated.",
        )
    # Step 9: the window is settled_at + VACATE_WINDOW_DAYS, inclusive.
    if now() > charge["settled_at"] + timedelta(days=constants.VACATE_WINDOW_DAYS):
        raise ApiError(
            ERR_VACATE_WINDOW_EXPIRED,
            "The %d-day vacatur window has expired."
            % constants.VACATE_WINDOW_DAYS,
        )

    charge["case_status"] = constants.CHARGE_UNDER_INVESTIGATION
    charge["settled_amount_cents"] = 0
    charge["settled_via"] = None
    charge["settled_at"] = None
    bump(charge)

    # The SETTLED mediation case moves to VACATED (retaining its own
    # settlement_amount_cents for audit).
    for mediation in cascades.mediations_for_charge(charge):
        if mediation["status"] == constants.MEDIATION_SETTLED:
            mediation["status"] = constants.MEDIATION_VACATED
            bump(mediation)

    # The investigation reopens: CLOSED -> GATHERING, or auto-create OPEN.
    investigation = cascades.investigation_for_charge(charge)
    if investigation is None:
        cascades.auto_create_investigation(charge)
    elif investigation["status"] == constants.INVESTIGATION_CLOSED:
        investigation["status"] = constants.INVESTIGATION_GATHERING
        bump(investigation)

    cascades.reeval_systemic_for_charge(charge)
    return respond_object(serializers.serialize_charge(charge), status=200)
