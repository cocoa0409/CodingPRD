"""Registry endpoints: carriers, the fee ledger, process agents and insurers (PRD 3.1)."""

from flask import Blueprint

import calc
import clock
import domain
import envelope
import helpers
import store
from errors import invalid
from validation import Body, authenticate

bp = Blueprint("registry", __name__)

ALL_ROLES = ("CarrierRep", "InsuranceFiler", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")


@bp.post("/carriers")
def create_carrier():
    authenticate(("RegistryAdmin",))
    body = Body()
    legal_name = body.req_str("legal_name", min_len=1, max_len=200)
    dba_name = body.opt_str("dba_name", min_len=1, max_len=200, default=None)
    domicile_state = body.req_state("domicile_state")
    vehicles = body.req_int("self_reported_vehicle_count", min_v=1)
    drivers = body.req_int("self_reported_driver_count", min_v=1)
    oos = body.req_number("self_reported_oos_rate_pct", lo=0, hi=100, max_dp=2)

    rec = store.base_record()
    rec.update({
        "legal_name": legal_name,
        "dba_name": dba_name,
        "domicile_state": domicile_state,
        "usdot_number": store.next_usdot(),
        "unified_registration_status": "NOT_REGISTERED",
        "entrant_status": "NEW_ENTRANT",
        "self_reported_vehicle_count": vehicles,
        "self_reported_driver_count": drivers,
        "self_reported_oos_rate_pct": oos,
        "audited_oos_rate_pct": None,
        "compliance_risk_score": None,
        "compliance_risk_variant": "NONE",
        "fee_balance_cents": 0,
        "fees_assessed_total_cents": 0,
        "fees_reversed_total_cents": 0,
        "fees_paid_total_cents": 0,
        "biennial_update_due_at": calc.biennial_due(rec["created_at"]),
        "last_biennial_update_at": None,
        "biennial_delinquent": False,
        "active_authority_count": 0,
    })
    store.insert(store.CARRIERS, rec)
    return helpers.one(rec, 201)


@bp.get("/carriers/<carrier_id>")
def read_carrier(carrier_id):
    authenticate(ALL_ROLES)
    return helpers.one(helpers.need_carrier(carrier_id))


@bp.get("/carriers/<carrier_id>/safety-audits")
def list_safety_audits(carrier_id):
    authenticate(("CarrierRep", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin"))
    helpers.need_carrier(carrier_id)
    return helpers.listing(store.audits_of_carrier(carrier_id), {"status": "status"})


@bp.get("/carriers/<carrier_id>/fee-ledger-entries")
def list_ledger(carrier_id):
    authenticate(("CarrierRep", "ComplianceOfficer", "RegistryAdmin"))
    helpers.need_carrier(carrier_id)
    return helpers.listing(store.ledger_of_carrier(carrier_id), {"entry_type": "entry_type"})


@bp.post("/carriers/<carrier_id>/biennial-update")
def biennial_update(carrier_id):
    _uid, role = authenticate(("CarrierRep",))
    carrier = helpers.need_carrier(carrier_id)
    helpers.require_carrier_owner(role, _uid, carrier["id"])
    body = Body()
    vehicles = body.req_int("self_reported_vehicle_count", min_v=1)
    drivers = body.req_int("self_reported_driver_count", min_v=1)
    oos = body.req_number("self_reported_oos_rate_pct", lo=0, hi=100, max_dp=2)

    now = clock.now()
    carrier["self_reported_vehicle_count"] = vehicles
    carrier["self_reported_driver_count"] = drivers
    carrier["self_reported_oos_rate_pct"] = oos
    carrier["last_biennial_update_at"] = now
    carrier["biennial_update_due_at"] = calc.biennial_due(now)
    carrier["biennial_delinquent"] = False
    domain.touch(carrier)
    return helpers.one(carrier)


@bp.post("/carriers/<carrier_id>/fee-payments")
def record_payment(carrier_id):
    uid, role = authenticate(("CarrierRep", "RegistryAdmin"))
    carrier = helpers.need_carrier(carrier_id)
    helpers.require_carrier_owner(role, uid, carrier["id"])
    body = Body()
    amount = body.req_int("amount_cents", min_v=1)
    memo = body.opt_str("memo", min_len=None, max_len=None, default=None)

    domain.ledger_append(carrier, "FEE_PAYMENT_CREDIT", -amount, None,
                         memo if memo is not None else "Fee payment recorded.")
    return helpers.one(carrier, 201)


@bp.post("/process-agents")
def create_process_agent():
    authenticate(("RegistryAdmin",))
    body = Body()
    company_name = body.req_str("company_name", min_len=1, max_len=200)
    coverage_states = body.req_state_list("coverage_states", min_n=1, max_n=51)
    blanket = body.opt_bool("blanket_agent", default=False)

    rec = store.base_record(mutable=False)
    rec.update({
        "company_name": company_name,
        "coverage_states": coverage_states,
        "blanket_agent": blanket,
    })
    store.insert(store.PROCESS_AGENTS, rec)
    return helpers.one(rec, 201)


@bp.post("/insurers")
def create_insurer():
    authenticate(("RegistryAdmin",))
    body = Body()
    company_name = body.req_str("company_name", min_len=1, max_len=200)
    naic_code = body.req_str("naic_code", min_len=None)
    if len(naic_code) != 5 or not naic_code.isdigit():
        raise invalid("Field 'naic_code' must be exactly five digits.")
    authorized_states = body.req_state_list("authorized_states", min_n=1, max_n=51)
    for existing in store.INSURERS.values():
        if existing["naic_code"] == naic_code:
            raise invalid("Field 'naic_code' must be unique across all insurers.")

    rec = store.base_record()
    rec.update({
        "company_name": company_name,
        "naic_code": naic_code,
        "authorized_states": authorized_states,
    })
    store.insert(store.INSURERS, rec)
    return helpers.one(rec, 201)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(("RegistryAdmin", "ComplianceOfficer"))
    body = Body()
    moment = body.req_instant("to_iso8601")
    clock.set_now(moment)
    return envelope.obj({"current_utc": clock.fmt(clock.now())})
