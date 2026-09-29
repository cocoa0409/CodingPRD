"""Load calculations: creation, the review cycle and the sizing arithmetic."""

from flask import Blueprint, request

import shape
import store
from calc import load_sizing
from common import BACKUP_SCOPES, LOAD_METHODS, kw
from envelope import collection, created, ok
from errors import ApiError, invalid
from security import guard, path_ref, ref

bp = Blueprint("loadcalc", __name__)

READ_ROLES = (
    "CertifiedInstaller",
    "Homeowner",
    "AuthorityHavingJurisdiction",
    "UtilityInterconnectionReviewer",
)


def _consistency(method, scope, measured_peak_kw, circuits):
    if method == "NEC_220_87_MEASURED":
        if measured_peak_kw is None:
            raise invalid("'measured_peak_kw' is required for the measured method.")
    if scope == "ESSENTIAL_LOADS":
        if not circuits:
            raise invalid(
                "'essential_circuits' must be non-empty under essential-loads scoping."
            )
    elif circuits:
        raise invalid("'essential_circuits' must be empty under whole-home scoping.")


@bp.route("/load-calculations", methods=["POST"])
@guard("CertifiedInstaller")
def create_load_calculation(actor):
    payload = shape.body()
    site_id = payload.fk("site_id")
    ref("site", site_id)

    method = payload.enum("method", LOAD_METHODS)
    scope = payload.enum("backup_scope", BACKUP_SCOPES)
    lighting_area_sqft = payload.number("lighting_area_sqft")
    appliance_load_va = payload.number("appliance_load_va")
    heating_va = payload.number("heating_va")
    cooling_va = payload.number("cooling_va")
    measured_peak_kw = payload.number("measured_peak_kw", required=False, exclusive_min=True)
    if method == "NEC_220_82_STANDARD" and payload.present("measured_peak_kw"):
        raise invalid("'measured_peak_kw' must be omitted under the standard method.")
    circuits = shape.circuits(payload) or []
    _consistency(method, scope, measured_peak_kw, circuits)

    record = {
        "site_id": site_id,
        "method": method,
        "backup_scope": scope,
        "lighting_area_sqft": lighting_area_sqft,
        "appliance_load_va": appliance_load_va,
        "heating_va": heating_va,
        "cooling_va": cooling_va,
        "measured_peak_kw": kw(measured_peak_kw) if measured_peak_kw is not None else None,
        "essential_circuits": circuits,
        "status": "DRAFT",
        "revision_round_count": 0,
        "reviewer_notes": None,
        "connected_load_kw": None,
        "required_continuous_kw": None,
        "required_surge_kw": None,
    }
    load_sizing(record)
    return created(store.view(store.insert("load_calculations", record)))


@bp.route("/load-calculations/<calculation_id>", methods=["GET"])
@guard(*READ_ROLES)
def read_load_calculation(actor, calculation_id):
    record = path_ref(actor, "load_calculation", calculation_id)
    return ok(store.view(record))


@bp.route("/load-calculations", methods=["GET"])
@guard(*READ_ROLES)
def list_load_calculations(actor):
    records = store.where(
        "load_calculations",
        site_id=request.args.get("site_id"),
        status=request.args.get("status"),
    )
    return collection(records)


@bp.route("/load-calculations/<calculation_id>/submit", methods=["POST"])
@guard("CertifiedInstaller")
def submit_load_calculation(actor, calculation_id):
    record = path_ref(actor, "load_calculation", calculation_id)
    payload = shape.body()

    method = payload.enum("method", LOAD_METHODS, required=False, default=record["method"])
    scope = payload.enum(
        "backup_scope", BACKUP_SCOPES, required=False, default=record["backup_scope"]
    )
    lighting_area_sqft = payload.number(
        "lighting_area_sqft", required=False, default=record["lighting_area_sqft"]
    )
    appliance_load_va = payload.number(
        "appliance_load_va", required=False, default=record["appliance_load_va"]
    )
    heating_va = payload.number("heating_va", required=False, default=record["heating_va"])
    cooling_va = payload.number("cooling_va", required=False, default=record["cooling_va"])
    measured_peak_kw = payload.number(
        "measured_peak_kw",
        required=False,
        exclusive_min=True,
        default=record["measured_peak_kw"],
    )
    circuits = shape.circuits(payload)
    if circuits is None:
        circuits = record["essential_circuits"]
    _consistency(method, scope, measured_peak_kw, circuits)

    if record["status"] not in ("DRAFT", "REVISION_REQUIRED"):
        raise ApiError(
            "ERR_LOAD_CALC_STATE_INVALID",
            "A calculation in %s cannot be submitted." % record["status"],
        )

    record["method"] = method
    record["backup_scope"] = scope
    record["lighting_area_sqft"] = lighting_area_sqft
    record["appliance_load_va"] = appliance_load_va
    record["heating_va"] = heating_va
    record["cooling_va"] = cooling_va
    record["measured_peak_kw"] = (
        kw(measured_peak_kw) if measured_peak_kw is not None else None
    )
    record["essential_circuits"] = circuits
    load_sizing(record)
    record["status"] = "SUBMITTED"
    store.touch(record)
    return ok(store.view(record))


@bp.route("/load-calculations/<calculation_id>/review", methods=["POST"])
@guard("AuthorityHavingJurisdiction")
def review_load_calculation(actor, calculation_id):
    record = path_ref(actor, "load_calculation", calculation_id)
    payload = shape.body()
    decision = payload.enum("decision", ("APPROVE", "REQUEST_REVISION"))
    notes = payload.str_("reviewer_notes", required=False, allow_empty=True)

    if record["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_LOAD_CALC_STATE_INVALID",
            "A calculation in %s cannot be reviewed." % record["status"],
        )

    record["reviewer_notes"] = notes
    if decision == "APPROVE":
        record["status"] = "APPROVED"
    else:
        record["status"] = "REVISION_REQUIRED"
        record["revision_round_count"] += 1
    store.touch(record)
    return ok(store.view(record))
