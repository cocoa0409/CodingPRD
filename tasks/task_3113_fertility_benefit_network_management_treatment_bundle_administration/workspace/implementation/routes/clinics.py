"""Clinic network, contracts and quality evidence (PRD 3.3, 3.10)."""

from flask import request

from body import body, opt, require
from bp import api
from clock import parse_dt
from db import db
from errors import APIError
from helpers import (
    block_plans_of_clinic,
    clinic_gates_satisfied,
    clinic_quality_breached,
    contracts_of_clinic,
    freeze_clinic_contracts,
    unfreeze_clinic_contracts,
    recompute_clinic_quality,
    recompute_member,
)
from listing import apply_filters, ordered, paginate
from lookups import (
    clinic as clinic_lookup,
    clinic_contract as contract_lookup,
)
from middleware import resolve_actor
from response import ok, created
from serializers import serialize

CONTRACTED_MIN_REPORTS = 3
POSTURE_TRIGGER_STATES = ("CONTRACTED", "PROBATION")
NOT_CREATABLE = ("IN_REVIEW",)


# --------------------------------------------------------------------------
# Clinic
# --------------------------------------------------------------------------

@api.route("/clinics", methods=["POST"])
def create_clinic():
    resolve_actor()
    data = body()
    legal_name = require(data, "legal_name")
    npi = require(data, "npi")
    state_code = require(data, "state_code")
    network_tier = require(data, "network_tier")
    if network_tier not in ("PREFERRED", "STANDARD", "OUT_OF_NETWORK"):
        raise APIError("ERR_INVALID_REQUEST", "network_tier is outside its declared enumeration.")
    min_live_birth_rate_bps = require(data, "min_live_birth_rate_bps")
    max_multiple_birth_rate_bps = require(data, "max_multiple_birth_rate_bps")
    required_quality_report_count = require(data, "required_quality_report_count")
    maturity_report_threshold = require(data, "maturity_report_threshold")
    bundles_offered = opt(data, "bundles_offered", [])

    if any(c["npi"] == npi for c in db.all("clinics")):
        raise APIError("ERR_INVALID_REQUEST", "npi must be globally unique.")

    row = db.common()
    row.update({
        "_collection": "clinics",
        "legal_name": legal_name,
        "npi": npi,
        "required_quality_report_count": required_quality_report_count,
        "state_code": state_code,
        "network_tier": network_tier,
        "min_live_birth_rate_bps": min_live_birth_rate_bps,
        "max_multiple_birth_rate_bps": max_multiple_birth_rate_bps,
        "maturity_report_threshold": maturity_report_threshold,
        "bundles_offered": bundles_offered,
        "live_birth_rate_bps": 0,
        "multiple_birth_rate_bps": 0,
        "composite_quality_bps": 0,
        "cycles_reported": 0,
        "clinic_status": "IN_REVIEW",
    })
    db.add(row)
    recompute_clinic_quality(db, row)
    return created(serialize("clinics", row))


@api.route("/clinics/<clinic_id>", methods=["GET"])
def get_clinic(clinic_id):
    resolve_actor()
    row = clinic_lookup(clinic_id)
    return ok(serialize("clinics", row))


@api.route("/clinics", methods=["GET"])
def list_clinics():
    resolve_actor()
    rows = ordered(db.all("clinics"))
    rows = apply_filters(rows, {
        "state_code": "state_code",
        "network_tier": "network_tier",
        "clinic_status": "clinic_status",
    })
    bundle_type = request.args.get("bundle_type")
    if bundle_type is not None:
        rows = [r for r in rows if bundle_type in (r.get("bundles_offered") or [])]
    min_quality = request.args.get("min_composite_quality_bps")
    if min_quality is not None:
        try:
            floor = int(min_quality)
        except (TypeError, ValueError):
            floor = 0
        rows = [r for r in rows if (r.get("composite_quality_bps") or 0) >= floor]
    return paginate(rows, "clinics")


@api.route("/clinics/<clinic_id>/contracts", methods=["POST"])
def create_contract(clinic_id):
    resolve_actor()
    clinic = clinic_lookup(clinic_id)
    data = body()
    effective_from = require(data, "effective_from")
    effective_to = require(data, "effective_to")
    bundle_rates = require(data, "bundle_rates")

    parsed_from = parse_dt(effective_from)
    parsed_to = parse_dt(effective_to)
    if parsed_to <= parsed_from:
        raise APIError("ERR_INVALID_REQUEST", "The contract interval end precedes its start.")
    if not isinstance(bundle_rates, dict) or not bundle_rates:
        raise APIError("ERR_INVALID_REQUEST", "bundle_rates must be a non-empty map.")

    row = db.common()
    row.update({
        "_collection": "clinic_contracts",
        "clinic_id": clinic["id"],
        "effective_from": parsed_from,
        "effective_to": parsed_to,
        "bundle_rates": bundle_rates,
        "contracting_status": "IN_REVIEW",
        "frozen_reason": None,
    })
    db.add(row)
    return created(serialize("clinic_contracts", row))


@api.route("/clinics/<clinic_id>/suspend", methods=["POST"])
def suspend_clinic(clinic_id):
    resolve_actor()
    clinic = clinic_lookup(clinic_id)
    if clinic["clinic_status"] not in POSTURE_TRIGGER_STATES:
        raise APIError("ERR_INVALID_STATE", "The clinic is not CONTRACTED or PROBATION.")

    clinic["clinic_status"] = "SUSPENDED"
    for contract in contracts_of_clinic(db, clinic["id"], ("ACTIVE", "FROZEN")):
        contract["contracting_status"] = "TERMINATED"
        db.touch(contract)

    block_plans_of_clinic(db, clinic["id"], ("CLINIC_SELECTED", "AUTHORIZATION_PENDING"))
    db.touch(clinic)
    return ok(serialize("clinics", clinic))


@api.route("/clinics/<clinic_id>/terminate", methods=["POST"])
def terminate_clinic(clinic_id):
    resolve_actor()
    clinic = clinic_lookup(clinic_id)
    if clinic["clinic_status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE", "The clinic is not SUSPENDED.")

    clinic["clinic_status"] = "TERMINATED"
    db.touch(clinic)
    return ok(serialize("clinics", clinic))


@api.route("/clinics/<clinic_id>/quality-recompute", methods=["POST"])
def quality_recompute(clinic_id):
    resolve_actor()
    clinic = clinic_lookup(clinic_id)

    recompute_clinic_quality(db, clinic)
    _apply_posture(clinic)

    # A clinic whose reading is eligible but whose latest ACTIVE contract
    # window has already closed is demoted so the stale agreement stops
    # gating clinic selection.
    if clinic["clinic_status"] in ("CONTRACTED", "PROBATION") and clinic_gates_satisfied(clinic):
        active = contracts_of_clinic(db, clinic["id"], ("ACTIVE",))
        if active and all(parse_dt(c["effective_to"]) <= db.now() for c in active):
            clinic["clinic_status"] = "SUSPENDED"

    db.touch(clinic)
    return ok(serialize("clinics", clinic))


def _apply_posture(clinic):
    """Derive the clinic posture from the current reading and its contracts."""
    if clinic["clinic_status"] == "CONTRACTED" and clinic_quality_breached(clinic):
        clinic["clinic_status"] = "PROBATION"
        freeze_clinic_contracts(db, clinic)
        block_plans_of_clinic(db, clinic["id"], ("CLINIC_SELECTED", "AUTHORIZATION_PENDING", "IN_PROGRESS"))
    elif clinic["clinic_status"] == "PROBATION" and clinic_gates_satisfied(clinic):
        clinic["clinic_status"] = "CONTRACTED"
        unfreeze_clinic_contracts(db, clinic)


# --------------------------------------------------------------------------
# ClinicContract
# --------------------------------------------------------------------------

@api.route("/clinic-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    resolve_actor()
    row = contract_lookup(contract_id)
    return ok(serialize("clinic_contracts", row))


@api.route("/clinic-contracts", methods=["GET"])
def list_contracts():
    resolve_actor()
    rows = ordered(db.all("clinic_contracts"))
    rows = apply_filters(rows, {
        "clinic_id": "clinic_id",
        "contracting_status": "contracting_status",
    })
    return paginate(rows, "clinic_contracts")


@api.route("/clinic-contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    resolve_actor()
    contract = contract_lookup(contract_id)
    clinic = clinic_lookup(contract["clinic_id"])
    data = request.get_json(silent=True) or {}
    expected = data.get("expected_clinic_version")

    if contract["contracting_status"] != "IN_REVIEW":
        raise APIError("ERR_INVALID_STATE", "The contract is not IN_REVIEW.")
    if clinic["clinic_status"] != "IN_REVIEW":
        raise APIError("ERR_INVALID_STATE", "The clinic is not IN_REVIEW.")

    if expected is not None and int(expected) != int(clinic["version"]):
        raise APIError("ERR_INVALID_REQUEST", "The clinic's version has advanced since it was observed.")

    start = parse_dt(contract["effective_from"])
    end = parse_dt(contract["effective_to"])
    if not (start <= db.now() < end):
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "The logical clock is outside the contract's coverage.")

    # The clinic must have accumulated the outcome reports its own readiness
    # threshold names; a clinic configured with a larger figure is held to it.
    required = clinic["required_quality_report_count"] or 0
    if clinic["cycles_reported"] < required:
        raise APIError("ERR_CLINIC_NOT_CONTRACTED",
                       "The clinic has not accumulated the required outcome reports.")

    if not (contract.get("bundle_rates") or {}):
        raise APIError("ERR_CLINIC_NOT_CONTRACTED", "The contract carries no negotiated rate.")

    contract["contracting_status"] = "ACTIVE"
    contract["_was_activated"] = True
    contract["frozen_reason"] = None
    db.touch(contract)

    clinic["clinic_status"] = "CONTRACTED"
    db.touch(clinic)
    return ok(serialize("clinic_contracts", contract))


@api.route("/clinic-contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    resolve_actor()
    contract = contract_lookup(contract_id)
    clinic = clinic_lookup(contract["clinic_id"])

    if contract["contracting_status"] not in ("ACTIVE", "FROZEN"):
        raise APIError("ERR_INVALID_STATE", "The contract is not ACTIVE or FROZEN.")

    contract["contracting_status"] = "TERMINATED"
    contract["frozen_reason"] = None
    db.touch(contract)

    clinic["clinic_status"] = "TERMINATED"
    db.touch(clinic)

    block_plans_of_clinic(db, clinic["id"], ("CLINIC_SELECTED", "AUTHORIZATION_PENDING"))
    return ok(serialize("clinic_contracts", contract))


# --------------------------------------------------------------------------
# Clinic-side outcome reporting
# --------------------------------------------------------------------------

@api.route("/clinics/<clinic_id>/report-outcome", methods=["POST"])
def report_outcome(clinic_id):
    resolve_actor()
    clinic = clinic_lookup(clinic_id)
    data = body()

    if "treatment_cycle_id" not in data or data["treatment_cycle_id"] is None:
        raise APIError("ERR_INVALID_REQUEST", "The required input 'treatment_cycle_id' is missing.")
    cycle = db.find("treatment_cycles", data["treatment_cycle_id"])
    if cycle is None:
        raise APIError("ERR_NOT_FOUND", "The treatment_cycle_id does not resolve.")

    if "expected_treatment_cycle_version" not in data or data["expected_treatment_cycle_version"] is None:
        raise APIError("ERR_INVALID_REQUEST",
                       "The required input 'expected_treatment_cycle_version' is missing.")

    # Priority 17: one live record per cycle, refused before the OCC check
    # because a second report is an operation already carried out.
    for existing in db.all("outcome_records"):
        if existing["treatment_cycle_id"] == cycle["id"] and existing["outcome_status"] in ("RECORDED", "AMENDED"):
            raise APIError("ERR_DUPLICATE_OPERATION", "A live outcome record already exists for this cycle.")

    # Priority 5: the cycle must already carry a recorded outcome.
    if cycle["cycle_status"] != "OUTCOME_RECORDED":
        raise APIError("ERR_INVALID_STATE", "The cycle has not reached OUTCOME_RECORDED.")

    # The mandatory concurrency token.
    if int(data["expected_treatment_cycle_version"]) != int(cycle["version"]):
        raise APIError("ERR_CYCLE_VERSION_STALE", "The cycle's version has advanced since it was observed.")

    row = db.common()
    row.update({
        "_collection": "outcome_records",
        "clinic_id": clinic["id"],
        "treatment_cycle_id": cycle["id"],
        "member_id": cycle["member_id"],
        "live_birth": bool(data.get("live_birth", False)),
        "births_count": data.get("births_count") or 0,
        "multiple_birth": bool(data.get("multiple_birth", False)),
        "gestational_weeks": data.get("gestational_weeks") or 0,
        "outcome_recorded_on": db.now(),
        "outcome_status": "RECORDED",
        "amendment_reason": None,
        "void_reason": None,
    })
    db.add(row)

    recompute_clinic_quality(db, clinic)
    _apply_posture(clinic)
    db.touch(clinic)

    member = db.find("members", cycle["member_id"])
    if member is not None:
        recompute_member(db, member)

    db.touch(cycle)
    return created(serialize("outcome_records", row))