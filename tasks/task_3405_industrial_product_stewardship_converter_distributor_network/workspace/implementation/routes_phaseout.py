"""Regulated-substance phase-out programs: announce, reformulate, qualify,
enforce (PRD §3.8). The REFORMULATING->QUALIFYING step designates the
successor; the QUALIFYING->ENFORCED step is hard-gated and fires the
enforcement sweep."""

from flask import Blueprint, request

import auth
import calcs
import cascades
import constants
import envelope
import serialization as ser
import store
import validation
from errors import api_err, invalid_request, invalid_state, not_found

bp = Blueprint("phaseout", __name__)


def _get_program(pid):
    row = store.STORE["phaseouts"].get(pid)
    if row is None:
        raise not_found("PhaseOutProgram not found")
    return row


@bp.post("/stewardship/phase-out-programs")
def create_phaseout():
    _uid, role = auth.authenticate()
    auth.require_role(role, ["RegulatoryManager"])
    payload = validation.get_payload()
    substance_id = validation.req_str(payload, "substance_id")
    codes = validation.req_list(payload, "jurisdiction_codes")
    if not codes:
        raise invalid_request("jurisdiction_codes must be a non-empty array")
    for code in codes:
        if not isinstance(code, str) or not code.strip():
            raise invalid_request(
                "jurisdiction_codes entries must be non-empty strings")
    trigger = validation.req_int(payload, "trigger_concentration_ppm")
    if trigger <= 0:
        raise invalid_request("trigger_concentration_ppm must be > 0")
    if store.STORE["substances"].get(substance_id) is None:
        raise not_found("Substance not found")
    row = store.stamp_new({
        "substance_id": substance_id,
        "jurisdiction_codes": list(codes),
        "trigger_concentration_ppm": trigger,
        "status": "ANNOUNCED",
        "successor_formulation_id": None,
        "qualified_customers": [],
        "qualified_customer_count": 0,
    })
    store.STORE["phaseouts"][row["id"]] = row
    return envelope.success_object(ser.phaseout_program(row), 201)


@bp.get("/stewardship/phase-out-programs/<pid>")
def get_phaseout(pid):
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    return envelope.success_object(ser.phaseout_program(_get_program(pid)), 200)


@bp.get("/stewardship/phase-out-programs")
def list_phaseouts():
    _uid, role = auth.authenticate()
    auth.require_role(role, auth.ANY_ROLE)
    limit, offset = validation.parse_pagination()
    rows = validation.apply_filters(
        store.STORE["phaseouts"].values(), request.args,
        ["substance_id", "successor_formulation_id", "status"])
    rows = sorted(rows, key=store.sort_key)
    page = rows[offset:offset + limit]
    return envelope.success_list(
        [ser.phaseout_program(r) for r in page], len(rows), limit, offset)


@bp.post("/stewardship/phase-out-programs/<pid>/advance")
def advance_phaseout(pid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["RegulatoryManager"])
    program = _get_program(pid)
    if program["status"] == "ANNOUNCED":
        program["status"] = "REFORMULATING"
        store.touch(program)
    elif program["status"] == "REFORMULATING":
        # Priority 23: the advance must designate a successor whose
        # successor_of_id resolves to a formulation affected by this program.
        payload = validation.get_payload()
        successor_id = payload.get("successor_formulation_id")
        if successor_id is None:
            raise api_err(
                "ERR_PHASEOUT_SUCCESSOR_REQUIRED",
                "REFORMULATING -> QUALIFYING requires successor_formulation_id")
        if not isinstance(successor_id, str) or not successor_id.strip():
            raise api_err(
                "ERR_PHASEOUT_SUCCESSOR_REQUIRED",
                "successor_formulation_id must be a non-empty string")
        successor = store.STORE["formulations"].get(successor_id)
        if successor is None:
            raise not_found("Successor formulation not found")
        predecessor_id = successor["successor_of_id"]
        predecessor = (store.STORE["formulations"].get(predecessor_id)
                       if predecessor_id is not None else None)
        if (predecessor is None
                or not calcs.formulation_is_affected(predecessor["id"], program)):
            raise api_err(
                "ERR_PHASEOUT_SUCCESSOR_REQUIRED",
                "The successor's lineage must resolve to a formulation "
                "affected by this program")
        program["successor_formulation_id"] = successor_id
        program["status"] = "QUALIFYING"
        store.touch(program)
    elif program["status"] == "QUALIFYING":
        # Priority 24: >= 2 qualified customers AND a CLEARED clearance for
        # the successor in every jurisdiction code of the program.
        if program["qualified_customer_count"] < constants.MIN_QUALIFIED_CUSTOMERS:
            raise api_err(
                "ERR_QUALIFICATION_GATE_UNMET",
                "At least %d qualified customers are required"
                % constants.MIN_QUALIFIED_CUSTOMERS)
        successor_id = program["successor_formulation_id"]
        for code in program["jurisdiction_codes"]:
            jurisdiction = next(
                (j for j in store.STORE["jurisdictions"].values()
                 if j["code"] == code), None)
            cleared = jurisdiction is not None and any(
                c["formulation_id"] == successor_id
                and c["jurisdiction_id"] == jurisdiction["id"]
                and c["status"] == "CLEARED"
                for c in store.STORE["clearances"].values())
            if not cleared:
                raise api_err(
                    "ERR_QUALIFICATION_GATE_UNMET",
                    "The successor must hold a CLEARED clearance in every "
                    "program jurisdiction")
        program["status"] = "ENFORCED"
        store.touch(program)
        cascades.phaseout_enforcement_sweep(program)
    else:
        raise invalid_state("An ENFORCED program cannot advance")
    return envelope.success_object(ser.phaseout_program(program), 200)


@bp.post("/stewardship/phase-out-programs/<pid>/record-qualification")
def record_qualification(pid):
    _uid, role = auth.authenticate()
    auth.require_role(role, ["TechnicalEngineer"])
    payload = validation.get_payload()
    customer_ref = validation.req_str(payload, "customer_ref")
    samples_passed = validation.req_int(payload, "samples_passed")
    if samples_passed < 0:
        raise invalid_request("samples_passed must be >= 0")
    program = _get_program(pid)
    if program["status"] != "QUALIFYING":
        raise invalid_state(
            "Qualifications can only be recorded while the program is "
            "QUALIFYING")
    if customer_ref in program["qualified_customers"]:
        raise invalid_request(
            "customer_ref has already been recorded for this program")
    if samples_passed >= constants.QUALIFICATION_MIN_SAMPLES:
        program["qualified_customers"].append(customer_ref)
        program["qualified_customer_count"] = len(program["qualified_customers"])
        store.touch(program)
    # Fewer than QUALIFICATION_MIN_SAMPLES samples: a no-op that still
    # succeeds with 200 and the unchanged program.
    return envelope.success_object(ser.phaseout_program(program), 200)
