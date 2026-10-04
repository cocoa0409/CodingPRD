"""Conciliation negotiation and remedy packages (PRD 3.7)."""

from flask import Blueprint

import constants
import serializers
from domain import cascades, remedy
from domain.screening import size_band_for_count
from errors import (
    ApiError,
    ERR_CONCILIATION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_OFFER_OUT_OF_TURN,
    ERR_STALE_VERSION,
)
from helpers import (
    authenticate,
    bump,
    check_party_ownership,
    now,
    paginate_and_respond,
    request_body,
    require_roles,
    respond_object,
    today,
)
from store import db
from validation import req_int, req_string
from routes.charges import get_charge_or_404

bp = Blueprint("conciliation", __name__, url_prefix="/eeoc")

_READ_ROLES = (
    constants.ROLE_DIRECTOR,
    constants.ROLE_COMMISSIONER,
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_RESPONDENT_REP,
)

_REMEDY_READ_ROLES = (
    constants.ROLE_DIRECTOR,
    constants.ROLE_CHARGING_PARTY,
    constants.ROLE_RESPONDENT_REP,
)


def get_conciliation_or_404(conciliation_id):
    conciliation = db.conciliation_processes.get(conciliation_id)
    if conciliation is None:
        raise ApiError(
            ERR_CONCILIATION_NOT_FOUND,
            "No conciliation process with the given id.",
        )
    return conciliation


def charge_of_conciliation(conciliation):
    return db.charges[conciliation["charge_id"]]


@bp.get("/charges/<charge_id>/conciliation-processes")
def list_conciliations_for_charge(charge_id):
    user_id, role = authenticate()
    require_roles(role, _READ_ROLES)
    charge = get_charge_or_404(charge_id)
    check_party_ownership(user_id, role, charge)
    rows = [
        c
        for c in db.conciliation_processes.values()
        if c["charge_id"] == charge["id"]
    ]
    return paginate_and_respond(rows, serializers.serialize_conciliation_process)


@bp.get("/conciliation-processes/<conciliation_id>")
def get_conciliation(conciliation_id):
    user_id, role = authenticate()
    require_roles(role, _READ_ROLES)
    conciliation = get_conciliation_or_404(conciliation_id)
    check_party_ownership(user_id, role, charge_of_conciliation(conciliation))
    return respond_object(
        serializers.serialize_conciliation_process(conciliation), status=200
    )


@bp.post("/conciliation-processes/<conciliation_id>/offers")
def table_offer(conciliation_id):
    user_id, role = authenticate()
    require_roles(
        role, (constants.ROLE_DIRECTOR, constants.ROLE_RESPONDENT_REP)
    )
    # Step 3: schema (both fields non-optional per PRD 2.7 / 3.7).
    body = request_body()
    amount_cents = req_int(body, "amount_cents")
    expected_version = req_int(body, "expected_conciliation_version")

    # Step 4: existence.
    conciliation = get_conciliation_or_404(conciliation_id)
    charge = charge_of_conciliation(conciliation)
    # Step 5: ownership -- the RespondentRep tables for its own employer.
    if role == constants.ROLE_RESPONDENT_REP and user_id != charge["employer_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "RespondentRep may only table offers on its own employer's cases.",
        )
    # Step 6: state -- the negotiation must be open.
    if conciliation["status"] not in constants.CONCILIATION_OPEN_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Conciliation in %s cannot accept offers." % conciliation["status"],
        )
    # Step 8: strict alternation of sides.
    side = (
        constants.SIDE_COMMISSION
        if role == constants.ROLE_DIRECTOR
        else constants.SIDE_RESPONDENT
    )
    if conciliation["last_offer_by"] == side:
        raise ApiError(
            ERR_OFFER_OUT_OF_TURN,
            "Offers must strictly alternate between COMMISSION and RESPONDENT.",
        )
    # Step 10: optimistic concurrency.
    if expected_version != conciliation["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_conciliation_version does not match the current version.",
        )

    conciliation["current_offer_cents"] = amount_cents
    conciliation["last_offer_by"] = side
    conciliation["rounds_count"] += 1
    # Two-state negotiation cycle: first offer INITIATED -> OFFER_TABLED,
    # then OFFER_TABLED <-> COUNTERED.
    if conciliation["status"] == constants.CONC_INITIATED:
        conciliation["status"] = constants.CONC_OFFER_TABLED
    elif conciliation["status"] == constants.CONC_OFFER_TABLED:
        conciliation["status"] = constants.CONC_COUNTERED
    else:
        conciliation["status"] = constants.CONC_OFFER_TABLED
    bump(conciliation)
    return respond_object(
        serializers.serialize_conciliation_process(conciliation), status=200
    )


@bp.post("/conciliation-processes/<conciliation_id>/accept")
def accept_conciliation(conciliation_id):
    user_id, role = authenticate()
    require_roles(role, (constants.ROLE_CHARGING_PARTY,))
    request_body(required=False)
    conciliation = get_conciliation_or_404(conciliation_id)
    charge = charge_of_conciliation(conciliation)
    if user_id != charge["complainant_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "Only the charging party may accept the outstanding offer.",
        )
    if conciliation["status"] not in constants.CONCILIATION_ACCEPTABLE_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "No outstanding offer to accept (status %s)." % conciliation["status"],
        )

    conciliation["status"] = constants.CONC_SETTLED
    bump(conciliation)

    # FINAL remedy: band from the charge's immutable incident snapshot;
    # interest accrues to the accept date; never recomputes again.
    package = remedy.package_for_conciliation(conciliation)
    if package is not None:
        band = size_band_for_count(charge["employee_count_at_incident"])
        remedy.compute_remedy(package, band, today())
        package["valuation_variant"] = constants.VALUATION_FINAL
        bump(package)

    charge["settled_amount_cents"] = conciliation["current_offer_cents"]
    charge["settled_via"] = constants.SETTLED_VIA_CONCILIATION
    charge["settled_at"] = now()
    charge["case_status"] = constants.CHARGE_CLOSED_SETTLED
    bump(charge)
    cascades.reeval_systemic_for_charge(charge)
    return respond_object(
        serializers.serialize_conciliation_process(conciliation), status=200
    )


@bp.post("/conciliation-processes/<conciliation_id>/fail")
def fail_conciliation(conciliation_id):
    _, role = authenticate()
    require_roles(role, (constants.ROLE_DIRECTOR,))
    body = request_body()
    req_string(body, "reason")

    conciliation = get_conciliation_or_404(conciliation_id)
    if conciliation["status"] not in constants.CONCILIATION_OPEN_STATES:
        raise ApiError(
            ERR_INVALID_STATE,
            "Conciliation in %s cannot be failed." % conciliation["status"],
        )
    conciliation["status"] = constants.CONC_FAILED
    bump(conciliation)
    charge = charge_of_conciliation(conciliation)
    charge["case_status"] = constants.CHARGE_LITIGATION_REFERRED
    bump(charge)
    return respond_object(
        serializers.serialize_conciliation_process(conciliation), status=200
    )


@bp.get("/conciliation-processes/<conciliation_id>/remedy-packages")
def list_remedy_packages(conciliation_id):
    user_id, role = authenticate()
    require_roles(role, _REMEDY_READ_ROLES)
    conciliation = get_conciliation_or_404(conciliation_id)
    charge = charge_of_conciliation(conciliation)
    # ChargingParty / RespondentRep ownership scopes apply.
    if role == constants.ROLE_CHARGING_PARTY and user_id != charge["complainant_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "ChargingParty may only view its own charge's remedy packages.",
        )
    if role == constants.ROLE_RESPONDENT_REP and user_id != charge["employer_id"]:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER,
            "RespondentRep may only view its own employer's remedy packages.",
        )
    rows = [
        p
        for p in db.remedy_packages.values()
        if p["conciliation_process_id"] == conciliation["id"]
    ]
    return paginate_and_respond(rows, serializers.serialize_remedy_package)
