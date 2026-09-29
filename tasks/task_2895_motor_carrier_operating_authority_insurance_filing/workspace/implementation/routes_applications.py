"""Authority applications: drafting, submission and vetting (PRD 3.2, 3.3, 3.4)."""

from flask import Blueprint, request

import calc
import clock
import domain
import helpers
import store
from errors import ApiError, invalid
from validation import (APPLICATION_KINDS, DISPOSITIONS, TRANSPORTATION_TYPES, Body,
                        authenticate)

bp = Blueprint("applications", __name__)

READ_ROLES = ("CarrierRep", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")


def _lenient_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def check_predecessor(kind, carrier_id, predecessor_id):
    """PRD 2.8 rung 25 -- enforced at draft creation and again at submission."""
    if kind == "NEW":
        if predecessor_id is not None:
            raise ApiError("ERR_PREDECESSOR_INVALID",
                           "A NEW application must omit predecessor_authority_id.")
        return
    if predecessor_id is None:
        raise ApiError("ERR_PREDECESSOR_INVALID",
                       "This application kind requires a predecessor_authority_id.")
    pred = store.AUTHORITIES.get(predecessor_id)
    if pred is None:
        raise ApiError("ERR_PREDECESSOR_INVALID", "The predecessor authority no longer exists.")
    if kind == "NAME_CHANGE":
        ok = pred["carrier_id"] == carrier_id and pred["authority_status"] == "ACTIVE"
    elif kind == "REINSTATEMENT":
        ok = pred["carrier_id"] == carrier_id and pred["authority_status"] == "REVOKED"
    else:
        ok = (pred["carrier_id"] != carrier_id
              and pred["authority_status"] in ("ACTIVE", "SUSPENDED"))
    if not ok:
        raise ApiError("ERR_PREDECESSOR_INVALID",
                       "The predecessor authority is incompatible with this application kind.")


def _price(app):
    bipd, cargo, bond = calc.required_insurance_minimums(
        app["transportation_type"], app["passenger_seating_capacity"],
        app["hazmat_endorsement_requested"], app["hazmat_bulk_capable"],
        app["requested_operating_states"])
    total, breakdown = calc.filing_fee_assessment(
        app["application_kind"], app["transportation_type"],
        app["requested_operating_states"], app["hazmat_endorsement_requested"])
    app["required_bipd_limit_cents"] = bipd
    app["required_cargo_limit_cents"] = cargo
    app["required_bond_limit_cents"] = bond
    app["filing_fee_cents"] = total
    app["filing_fee_breakdown"] = breakdown
    return app


@bp.post("/authority-applications")
def create_application():
    uid, role = authenticate(("CarrierRep",))
    raw = _lenient_body()

    # rung 4: ownership against the body's carrier_id
    carrier_ref = raw.get("carrier_id")
    predecessor_ref = raw.get("predecessor_authority_id")
    if isinstance(carrier_ref, str):
        helpers.require_carrier_owner(role, uid, carrier_ref)

    # rung 6: body foreign keys resolve
    if isinstance(carrier_ref, str):
        helpers.resolve_body_ref(store.CARRIERS, carrier_ref)
    if isinstance(predecessor_ref, str):
        helpers.resolve_body_ref(store.AUTHORITIES, predecessor_ref)

    # rung 7: structure
    body = Body()
    carrier = store.CARRIERS[body.req_str("carrier_id", min_len=None)]
    kind = body.req_enum("application_kind", APPLICATION_KINDS)
    transportation_type = body.req_enum("transportation_type", TRANSPORTATION_TYPES)
    states = body.req_state_list("requested_operating_states", min_n=1, max_n=51)
    hazmat = body.opt_bool("hazmat_endorsement_requested", default=False)
    hazmat_bulk = body.opt_bool("hazmat_bulk_capable", default=False)

    seats = body.opt_int("passenger_seating_capacity", min_v=1, default=None)
    if transportation_type == "PASSENGER" and seats is None:
        raise invalid("Field 'passenger_seating_capacity' is required for a PASSENGER application.")
    if transportation_type != "PASSENGER" and seats is not None:
        raise invalid("Field 'passenger_seating_capacity' must be null for this transportation type.")

    proposed = body.opt_str("proposed_legal_name", min_len=1, max_len=200, default=None)
    if kind == "NAME_CHANGE" and proposed is None:
        raise invalid("Field 'proposed_legal_name' is required for a NAME_CHANGE application.")
    if kind != "NAME_CHANGE" and proposed is not None:
        raise invalid("Field 'proposed_legal_name' must be null for this application kind.")

    if predecessor_ref is not None and not isinstance(predecessor_ref, str):
        raise invalid("Field 'predecessor_authority_id' must be a string.")

    # rung 25: predecessor compatibility
    check_predecessor(kind, carrier["id"], predecessor_ref)

    rec = store.base_record()
    rec.update({
        "carrier_id": carrier["id"],
        "application_kind": kind,
        "transportation_type": transportation_type,
        "predecessor_authority_id": predecessor_ref,
        "requested_operating_states": states,
        "hazmat_endorsement_requested": hazmat,
        "hazmat_bulk_capable": hazmat_bulk,
        "passenger_seating_capacity": seats,
        "proposed_legal_name": proposed,
        "status": "DRAFT",
        "submission_count": 0,
        "filing_fee_cents": 0,
        "filing_fee_breakdown": {},
        "required_bipd_limit_cents": 0,
        "required_cargo_limit_cents": 0,
        "required_bond_limit_cents": 0,
        "vetting_findings": None,
        "vetted_by_user_id": None,
        "published_at": None,
        "published_by_user_id": None,
        "denied_reason": None,
    })
    _price(rec)
    store.insert(store.APPLICATIONS, rec)
    return helpers.one(rec, 201)


@bp.get("/authority-applications/<application_id>")
def read_application(application_id):
    authenticate(READ_ROLES)
    return helpers.one(helpers.need_application(application_id))


@bp.get("/authority-applications")
def list_applications():
    authenticate(READ_ROLES)
    return helpers.listing(store.all_of(store.APPLICATIONS), {
        "carrier_id": "carrier_id",
        "predecessor_authority_id": "predecessor_authority_id",
        "application_kind": "application_kind",
        "status": "status",
    })


@bp.post("/authority-applications/<application_id>/submit")
def submit_application(application_id):
    uid, role = authenticate(("CarrierRep",))
    app = helpers.need_application(application_id)
    helpers.require_carrier_owner(role, uid, app["carrier_id"])

    if app["status"] not in ("DRAFT", "RETURNED_FOR_CORRECTION"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    check_predecessor(app["application_kind"], app["carrier_id"],
                      app["predecessor_authority_id"])

    carrier = store.CARRIERS[app["carrier_id"]]
    if carrier["biennial_delinquent"]:
        raise ApiError("ERR_BIENNIAL_UPDATE_DELINQUENT")

    app["status"] = "SUBMITTED"
    app["submission_count"] += 1
    if app["submission_count"] == 1:
        _price(app)
        domain.ledger_append(carrier, "FILING_FEE_DEBIT", app["filing_fee_cents"], app["id"],
                             "Filing fee assessed on first submission.")
    domain.touch(app)
    return helpers.one(app)


def _mint_authority(app, carrier):
    now = clock.now()
    required = sorted(set(app["requested_operating_states"]) | {carrier["domicile_state"]})
    rec = store.base_record()
    rec.update({
        "carrier_id": carrier["id"],
        "application_id": app["id"],
        "docket_number": store.next_docket(),
        "transportation_type": app["transportation_type"],
        "authority_status": "PENDING",
        "insurance_status": "NOT_FILED",
        "required_bipd_limit_cents": app["required_bipd_limit_cents"],
        "required_cargo_limit_cents": app["required_cargo_limit_cents"],
        "required_bond_limit_cents": app["required_bond_limit_cents"],
        "required_jurisdictions": required,
        "designated_state_count": 0,
        "designation_coverage_complete": False,
        "publication_at": now,
        "activation_eligible_at": calc.activation_eligible_at(now),
        "activated_at": None,
        "suspended_at": None,
        "suspension_reason": "NONE",
        "revoked_at": None,
        "rescinded_at": None,
        "hazmat_endorsed": app["hazmat_endorsement_requested"],
        "hazmat_bulk_capable": app["hazmat_bulk_capable"],
        "passenger_seating_capacity": app["passenger_seating_capacity"],
        "active_contract_count": 0,
        "suspended_contract_count": 0,
        "new_entrant_audit_deadline_at": None,
        "new_entrant_audit_status": "NOT_REQUIRED",
    })
    return store.insert(store.AUTHORITIES, rec)


@bp.post("/authority-applications/<application_id>/vetting-review")
def vetting_review(application_id):
    uid, _role = authenticate(("VettingAnalyst",))
    app = helpers.need_application(application_id)

    body = Body()
    disposition = body.req_enum("disposition", DISPOSITIONS)
    findings = body.req_text("findings")
    body.opt_str("denied_reason", min_len=None, max_len=None, default=None)

    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE")

    app["vetting_findings"] = findings
    app["vetted_by_user_id"] = uid
    carrier = store.CARRIERS[app["carrier_id"]]

    if disposition == "RETURN":
        app["status"] = "RETURNED_FOR_CORRECTION"
    elif disposition == "PUBLISH":
        app["status"] = "PUBLISHED"
        app["published_at"] = clock.now()
        app["published_by_user_id"] = uid
        _mint_authority(app, carrier)
    else:
        app["status"] = "DENIED"
        app["denied_reason"] = findings
        domain.ledger_append(carrier, "FILING_FEE_REVERSAL_CREDIT", -app["filing_fee_cents"],
                             app["id"], "Filing fee reversed on denial.")
    domain.touch(app)
    return helpers.one(app)
