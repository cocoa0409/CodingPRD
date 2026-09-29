"""PRD 3.10 — warranty claims, adjudication, the credit waterfall and the
dispute cycle."""

from decimal import Decimal

from flask import Blueprint, request

from auth import authorize, own_distributor_id
from calc import (unit_standard_cost_cents, warranty_credit_waterfall,
                  warranty_misuse_index)
from envelope import created, paginate, single
from errors import fail
from helpers import bool_filter, eq_filter, load, rows
from ledgers import recompute_credit_balance, recompute_presumed_defects
from store import base_row, db, now, touch
from validate import (opt_str, parse_body, present, req_enum, req_int, req_num,
                      req_str)

bp = Blueprint("warranty", __name__)

FAILURE_MODES = ("BEARING_FAILURE", "WINDING_SHORT", "ROTOR_BAR_CRACK",
                 "SHAFT_FRACTURE", "INSULATION_BREAKDOWN")
ANALYSIS_BASES = ("FIELD_DATA", "TEARDOWN")
CLAIM_READERS = ("ComplianceOfficer", "Distributor", "QualityCertifier", "PlantAdmin")
ADJUDICATED = ("DEFECT_CONFIRMED", "MISUSE_DETERMINED")
MAX_DISPUTE_ROUNDS = 2


@bp.post("/warranty-claims")
def create_claim():
    user_id, role = authorize("Distributor", "ComplianceOfficer")
    body = parse_body()
    raw_distributor = body.get("distributor_id")
    own_distributor_id(user_id, role,
                       raw_distributor if isinstance(raw_distributor, str) else None)

    work_order_id = req_str(body, "work_order_id")
    distributor_id = req_str(body, "distributor_id")
    failure_mode = req_enum(body, "failure_mode", FAILURE_MODES)
    operating_hours = req_int(body, "operating_hours", 0, 200000)
    measured_load_pct = req_num(body, "measured_load_pct", places=1)
    measured_ambient_c = req_num(body, "measured_ambient_c", places=1)
    measured_voltage_unbalance_pct = req_num(body, "measured_voltage_unbalance_pct",
                                             places=1)
    measured_starts_per_hour = req_int(body, "measured_starts_per_hour", 0, 500)
    claimed_parts_cents = req_int(body, "claimed_parts_cents", 0)
    claimed_labor_cents = req_int(body, "claimed_labor_cents", 0)
    claimed_freight_cents = req_int(body, "claimed_freight_cents", 0)

    distributor = load("distributors", distributor_id)
    work_order = load("work_orders", work_order_id)
    own_distributor_id(user_id, role, distributor_id)

    order = db.orders.get(work_order["order_id"])
    if order is None or order["distributor_id"] != distributor_id:
        fail("ERR_NOT_OWNER",
             "The claiming distributor must own the customer order behind this motor.")

    row = base_row()
    row.update({
        "work_order_id": work_order_id,
        "distributor_id": distributor_id,
        "failure_mode": failure_mode,
        "operating_hours": operating_hours,
        "measured_load_pct": measured_load_pct,
        "measured_ambient_c": measured_ambient_c,
        "measured_voltage_unbalance_pct": measured_voltage_unbalance_pct,
        "measured_starts_per_hour": measured_starts_per_hour,
        "claimed_parts_cents": claimed_parts_cents,
        "claimed_labor_cents": claimed_labor_cents,
        "claimed_freight_cents": claimed_freight_cents,
        "status": "SUBMITTED",
        "reported_at": now(),
        "dispute_round": 0,
        "warranty_credit_cents": 0,
        "credit_posted": False,
        "defect_presumption_applied": False,
        "analysis_basis": None,
        "teardown_defect_evidence_pct": None,
        "misuse_index": None,
        "adjudication": None,
        "claim_unit_standard_cost_cents": None,
        "dispute_reason": None,
        "closure_notes": None,
    })
    db.warranty_claims[row["id"]] = row
    return created({k: v for k, v in row.items() if not k.startswith("_")})


@bp.get("/warranty-claims/<row_id>")
def read_claim(row_id):
    user_id, role = authorize(*CLAIM_READERS)
    claim = load("warranty_claims", row_id)
    own_distributor_id(user_id, role, claim["distributor_id"])
    return single(claim)


@bp.get("/warranty-claims")
def list_claims():
    user_id, role = authorize(*CLAIM_READERS)
    collection = rows("warranty_claims")
    if role == "Distributor":
        requested = request.args.get("distributor_id")
        if requested is not None and requested != user_id:
            fail("ERR_NOT_OWNER", "A distributor may only list its own claims.")
        collection = [c for c in collection if c["distributor_id"] == user_id]
    collection = eq_filter(collection, "work_order_id")
    collection = eq_filter(collection, "distributor_id")
    collection = eq_filter(collection, "status")
    collection = eq_filter(collection, "failure_mode")
    collection = bool_filter(collection, "defect_presumption_applied")
    return paginate(collection)


@bp.post("/warranty-claims/<row_id>/analyze")
def analyze_claim(row_id):
    authorize("ComplianceOfficer")
    claim = load("warranty_claims", row_id)
    body = parse_body()
    analysis_basis = req_enum(body, "analysis_basis", ANALYSIS_BASES)
    evidence = None
    if present(body, "teardown_defect_evidence_pct"):
        evidence = req_num(body, "teardown_defect_evidence_pct", places=1)

    if claim["status"] not in ("SUBMITTED", "UNDER_ANALYSIS"):
        fail("ERR_INVALID_CLAIM_STATE",
             "Only a SUBMITTED or UNDER_ANALYSIS claim may be adjudicated.")

    # PRD 3.10 — the three teardown-evidence consistency conditions.
    if analysis_basis == "TEARDOWN":
        if evidence is None or evidence < Decimal("0.0") or evidence > Decimal("100.0"):
            fail("ERR_TEARDOWN_EVIDENCE_REQUIRED",
                 "A TEARDOWN analysis requires teardown_defect_evidence_pct within "
                 "0.0 to 100.0 inclusive.")
    else:
        if evidence is not None:
            fail("ERR_TEARDOWN_EVIDENCE_REQUIRED",
                 "A FIELD_DATA analysis must not carry teardown_defect_evidence_pct.")
        if claim["defect_presumption_applied"]:
            fail("ERR_TEARDOWN_EVIDENCE_REQUIRED",
                 "A claim carrying a defect presumption may only be analysed on the "
                 "TEARDOWN basis.")

    work_order = db.work_orders[claim["work_order_id"]]
    design = db.designs[work_order["design_id"]]
    index, adjudication = warranty_misuse_index(
        claim, design["duty_type"], analysis_basis, evidence)

    claim["analysis_basis"] = analysis_basis
    claim["teardown_defect_evidence_pct"] = evidence
    claim["misuse_index"] = index
    claim["adjudication"] = adjudication
    claim["status"] = adjudication

    if adjudication == "DEFECT_CONFIRMED":
        unit_cost = unit_standard_cost_cents(work_order)
        claim["claim_unit_standard_cost_cents"] = unit_cost
        claim["warranty_credit_cents"] = warranty_credit_waterfall(
            unit_cost, work_order.get("shipped_at"), now(),
            claim["claimed_parts_cents"], claim["claimed_labor_cents"],
            claim["claimed_freight_cents"])
        claim["credit_posted"] = True
    else:
        claim["warranty_credit_cents"] = 0
        claim["credit_posted"] = False

    touch(claim)
    recompute_credit_balance(db.distributors[claim["distributor_id"]])
    return single(claim)


@bp.post("/warranty-claims/<row_id>/dispute")
def dispute_claim(row_id):
    user_id, role = authorize("Distributor")
    claim = load("warranty_claims", row_id)
    own_distributor_id(user_id, role, claim["distributor_id"])
    body = parse_body()
    reason = req_str(body, "dispute_reason", 1)

    if claim["status"] not in ADJUDICATED:
        fail("ERR_INVALID_CLAIM_STATE", "Only an adjudicated claim may be disputed.")
    if claim["dispute_round"] >= MAX_DISPUTE_ROUNDS:
        fail("ERR_ROUND_LIMIT_EXCEEDED",
             "The dispute round counter must remain below %d." % MAX_DISPUTE_ROUNDS)

    claim["dispute_round"] = claim["dispute_round"] + 1
    claim["dispute_reason"] = reason
    claim["credit_posted"] = False
    claim["warranty_credit_cents"] = 0
    claim["adjudication"] = None
    claim["misuse_index"] = None
    claim["status"] = "UNDER_ANALYSIS"
    touch(claim)
    recompute_credit_balance(db.distributors[claim["distributor_id"]])
    return single(claim)


@bp.post("/warranty-claims/<row_id>/close")
def close_claim(row_id):
    authorize("ComplianceOfficer")
    claim = load("warranty_claims", row_id)
    body = parse_body()
    notes = opt_str(body, "closure_notes", min_len=0)

    if claim["status"] not in ADJUDICATED:
        fail("ERR_INVALID_CLAIM_STATE", "Only an adjudicated claim may be closed.")

    if notes is not None:
        claim["closure_notes"] = notes
    claim["status"] = "CLOSED"
    touch(claim)
    recompute_presumed_defects(db.distributors[claim["distributor_id"]])
    return single(claim)
