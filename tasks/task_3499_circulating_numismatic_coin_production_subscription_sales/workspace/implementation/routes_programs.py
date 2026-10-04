"""Commemorative programs: statute intake, design decision, surcharge
disbursement (PRD §3.5)."""
from flask import Blueprint

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, need_datetime,
                     need_int, need_str, no_undeclared, not_found)

bp = Blueprint("programs", __name__)


@bp.route("/mint/commemorative-programs", methods=["POST"])
def create_program():
    uid, _ = auth("ProgramManager")
    b = body()
    no_undeclared(b, {"name", "statute_reference", "max_mintage_legal",
                      "surcharge_cents_per_unit", "beneficiary_name",
                      "beneficiary_cap_cents", "direct_costs_cents",
                      "sales_window_start", "sales_window_end"})
    name = need_str(b, "name")
    statute = need_str(b, "statute_reference")
    max_mintage = need_int(b, "max_mintage_legal")
    if max_mintage <= 0:
        bad_request("max_mintage_legal must be strictly positive")
    surcharge = need_int(b, "surcharge_cents_per_unit")
    if surcharge < 0:
        bad_request("surcharge_cents_per_unit must be zero or more")
    beneficiary = need_str(b, "beneficiary_name")
    cap = need_int(b, "beneficiary_cap_cents")
    if cap < 0:
        bad_request("beneficiary_cap_cents must be zero or more")
    direct = need_int(b, "direct_costs_cents")
    if direct < 0:
        bad_request("direct_costs_cents must be zero or more")
    ws_dt, ws_raw = need_datetime(b, "sales_window_start")
    we_dt, we_raw = need_datetime(b, "sales_window_end")
    if we_dt <= ws_dt:
        bad_request("sales_window_end must be after sales_window_start")
    p = store.mint_entity({
        "name": name,
        "statute_reference": statute,
        "max_mintage_legal": max_mintage,
        "surcharge_cents_per_unit": surcharge,
        "beneficiary_name": beneficiary,
        "beneficiary_cap_cents": cap,
        "direct_costs_cents": direct,
        "sales_window_start": ws_raw,
        "sales_window_end": we_raw,
        "_window_start": ws_dt,
        "_window_end": we_dt,
        "status": "DESIGN_REVIEW",
        "design_revision_count": 0,
        "created_by_user_id": uid,
        "disbursed_cents": 0,
    })
    store.db["programs"][p["id"]] = p
    return envelope(serialize.program(p), status=201)


def _get_program_or_404(pid):
    p = store.db["programs"].get(pid)
    if p is None:
        not_found("Commemorative program not found")
    return p


@bp.route("/mint/commemorative-programs/<pid>", methods=["GET"])
def get_program(pid):
    auth("ProgramManager", "MintDirector", "FinanceOfficer", "PlatformAdmin")
    return envelope(serialize.program(_get_program_or_404(pid)))


@bp.route("/mint/commemorative-programs/<pid>/decide-design", methods=["POST"])
def decide_design(pid):
    auth("MintDirector")
    p = _get_program_or_404(pid)
    # Rung 5: the decision endpoint only acts on programs in DESIGN_REVIEW.
    if p["status"] != "DESIGN_REVIEW":
        err("ERR_INVALID_STATE_TRANSITION", 422,
            "Design decisions may only be made while in DESIGN_REVIEW")
    b = body()
    no_undeclared(b, {"decision"})
    decision = b.get("decision")
    if decision not in ("APPROVED", "REVISION_REQUESTED"):
        bad_request("decision must be APPROVED or REVISION_REQUESTED")
    if decision == "APPROVED":
        p["status"] = "APPROVED_FOR_SALE"
    else:
        # Deliberate self-loop: stay in DESIGN_REVIEW, count the revision.
        p["design_revision_count"] += 1
    store.bump(p)
    return envelope(serialize.program(p))


@bp.route("/mint/commemorative-programs/<pid>/disburse-surcharges",
          methods=["POST"])
def disburse_surcharges(pid):
    uid, _ = auth("FinanceOfficer")
    p = _get_program_or_404(pid)
    if p["status"] != "SALES_CLOSED":
        err("ERR_PROGRAM_NOT_DISBURSABLE", 422,
            "Surcharges may be disbursed only after the sales window closes")
    if uid == p["created_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 422,
            "The disbursing officer must differ from the program creator")
    no_undeclared(body(), set())
    _, accrued, _ = serialize.program_financials(p)
    p["disbursed_cents"] = min(p["beneficiary_cap_cents"], accrued)
    p["status"] = "SURCHARGE_DISBURSED"
    store.bump(p)
    return envelope(serialize.program(p))
