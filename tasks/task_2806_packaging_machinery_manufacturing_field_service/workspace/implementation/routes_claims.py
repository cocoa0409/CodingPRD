"""Warranty claims: the two-branch fork, the join, and the goodwill pot
(PRD 3.9)."""
from decimal import Decimal

from flask import Blueprint, g

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("claims", __name__)

CLAIM_READERS = ("ServiceManager", "QualityInspector", "PlatformAdmin",
                 "CustomerContact")
CLAIM_STATUSES = ("SUBMITTED", "PRODUCT_VARIATION_REVIEW", "DEFECT_REVIEW",
                  "ADJUDICATED", "REJECTED", "VOID")


def _claim_machine(claim):
    return store.get("installed_machines", claim["installed_machine_id"])


def _claim_contract(claim):
    return store.get("service_contracts", claim["service_contract_id"])


def _claim_model(claim):
    machine = _claim_machine(claim)
    return domain.machine_model(machine) if machine is not None else None


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------
@bp.post("/warranty-claims")
def create_warranty_claim():
    auth.authorize(("ServiceManager", "CustomerContact"))
    payload = validation.body()
    installed_machine_id = validation.req_str(payload, "installed_machine_id",
                                              1, None)
    service_contract_id = validation.req_str(payload, "service_contract_id",
                                             1, None)
    failure_summary = validation.req_str(payload, "failure_summary", 1, 200)
    machine = domain.must_get("installed_machines", installed_machine_id)
    contract = domain.must_get("service_contracts", service_contract_id)
    auth.require_owner(g.role, g.user_id, machine["customer_id"])
    if contract["installed_machine_id"] != installed_machine_id:
        raise ApiError("ERR_CONTRACT_MACHINE_MISMATCH",
                       "The contract does not cover this machine.")
    row = store.insert("warranty_claims", {
        "installed_machine_id": installed_machine_id,
        "service_contract_id": service_contract_id,
        "failure_summary": failure_summary,
        "claimed_cost_cents": 0,
        "product_variation_review_done": False,
        "defect_review_done": False,
        "cause": "UNDETERMINED",
        "oem_share_cents": 0,
        "customer_share_cents": 0,
        "goodwill_charged_cents": 0,
        "status": "SUBMITTED",
    })
    domain.recompute_machine_open_claims(machine)
    return envelope.created(row)


@bp.get("/warranty-claims")
def list_warranty_claims():
    auth.authorize(CLAIM_READERS)
    limit, offset = validation.pagination()
    filters = {
        "installed_machine_id": validation.query_str("installed_machine_id"),
        "service_contract_id": validation.query_str("service_contract_id"),
        "status": validation.query_enum("status", CLAIM_STATUSES),
    }
    items = [row for row in store.rows("warranty_claims")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/warranty-claims/<warranty_claim_id>")
def read_warranty_claim(warranty_claim_id):
    auth.authorize(CLAIM_READERS)
    return envelope.ok(domain.must_get("warranty_claims", warranty_claim_id))


# --------------------------------------------------------------------------
# claim cost lines (immutable; no updated_at / version)
# --------------------------------------------------------------------------
@bp.post("/warranty-claim-lines")
def create_claim_line():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    warranty_claim_id = validation.req_str(payload, "warranty_claim_id", 1, None)
    line_label = validation.req_str(payload, "line_label", 1, 60)
    amount_cents = validation.req_int(payload, "amount_cents", 1)
    defect_attribution_pct = validation.req_pct(
        payload, "defect_attribution_pct", Decimal("0.00"), Decimal("100.00"))
    claim = domain.must_get("warranty_claims", warranty_claim_id)
    if claim["status"] not in domain.OPEN_CLAIM_STATUSES:
        raise ApiError("ERR_INVALID_CLAIM_STATE",
                       "The claim no longer admits new cost lines.")
    row = store.insert("claim_lines", {
        "warranty_claim_id": warranty_claim_id,
        "line_label": line_label,
        "amount_cents": amount_cents,
        "defect_attribution_pct": defect_attribution_pct,
        "oem_line_share_cents": 0,
    }, common_fields=False)
    domain.recompute_claimed_cost(claim)
    return envelope.created(row)


@bp.get("/warranty-claim-lines")
def list_claim_lines():
    auth.authorize(CLAIM_READERS)
    limit, offset = validation.pagination()
    claim_id = validation.query_str("warranty_claim_id")
    items = [row for row in store.rows("claim_lines")
             if claim_id is None or row["warranty_claim_id"] == claim_id]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/warranty-claim-lines/<claim_line_id>")
def read_claim_line(claim_line_id):
    auth.authorize(CLAIM_READERS)
    return envelope.ok(domain.must_get("claim_lines", claim_line_id))


# --------------------------------------------------------------------------
# the fork: two independent review branches
# --------------------------------------------------------------------------
@bp.post("/warranty-claims/<warranty_claim_id>/reviews/product-variation")
def sign_off_product_variation(warranty_claim_id):
    auth.authorize(("ServiceManager",))
    claim = domain.must_get("warranty_claims", warranty_claim_id)
    if (claim["status"] not in ("SUBMITTED", "DEFECT_REVIEW")
            or claim["product_variation_review_done"]):
        raise ApiError("ERR_INVALID_CLAIM_STATE",
                       "The product-variation branch cannot be signed off "
                       "from status %s." % claim["status"])
    if not domain.claim_lines_of(claim):
        raise ApiError("ERR_CLAIM_HAS_NO_LINES",
                       "The claim carries no cost lines.")
    claim["product_variation_review_done"] = True
    # branch A: money roll-up only; the first branch signed off owns status
    domain.recompute_claimed_cost(claim, bump=False)
    if claim["status"] == "SUBMITTED":
        claim["status"] = "PRODUCT_VARIATION_REVIEW"
    store.touch(claim)
    return envelope.ok(claim)


@bp.post("/warranty-claims/<warranty_claim_id>/reviews/defect")
def sign_off_defect(warranty_claim_id):
    auth.authorize(("QualityInspector",))
    claim = domain.must_get("warranty_claims", warranty_claim_id)
    if (claim["status"] not in ("SUBMITTED", "PRODUCT_VARIATION_REVIEW")
            or claim["defect_review_done"]):
        raise ApiError("ERR_INVALID_CLAIM_STATE",
                       "The defect branch cannot be signed off from status %s."
                       % claim["status"])
    if not domain.claim_lines_of(claim):
        raise ApiError("ERR_CLAIM_HAS_NO_LINES",
                       "The claim carries no cost lines.")
    claim["defect_review_done"] = True
    if claim["status"] == "SUBMITTED":
        claim["status"] = "DEFECT_REVIEW"
    store.touch(claim)
    # branch B: cross-aggregate tally on the model behind the machine's order
    model = _claim_model(claim)
    if model is not None:
        model["open_defect_review_count"] = int(
            model["open_defect_review_count"]) + 1
        store.touch(model)
    return envelope.ok(claim)


# --------------------------------------------------------------------------
# the join
# --------------------------------------------------------------------------
def _exhaustion_sweep(contract):
    """Hop 3: every SCHEDULED visit is put on billable hold."""
    for visit in domain.children("pm_visits", "service_contract_id",
                                 contract["id"]):
        if visit["status"] == "SCHEDULED":
            visit["status"] = "BILLABLE_HOLD"
            visit["billable"] = True
            store.touch(visit)


def _release_holds(contract):
    """Void compensation: holds return to SCHEDULED with billable recomputed."""
    for visit in domain.children("pm_visits", "service_contract_id",
                                 contract["id"]):
        if visit["status"] == "BILLABLE_HOLD":
            visit["status"] = "SCHEDULED"
            visit["billable"] = domain.compute_billable(
                contract, visit["visit_type"], visit["id"])
            store.touch(visit)


@bp.post("/warranty-claims/<warranty_claim_id>/adjudicate")
def adjudicate_warranty_claim(warranty_claim_id):
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    resolution = validation.req_enum(payload, "resolution",
                                     ("APPROVE", "REJECT"))
    claim = domain.must_get("warranty_claims", warranty_claim_id)
    contract = _claim_contract(claim)
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE",
                       "The funding contract is not ACTIVE.")
    if claim["status"] not in ("PRODUCT_VARIATION_REVIEW", "DEFECT_REVIEW"):
        raise ApiError("ERR_INVALID_CLAIM_STATE",
                       "The claim cannot be adjudicated from status %s."
                       % claim["status"])
    if not (claim["product_variation_review_done"]
            and claim["defect_review_done"]):
        raise ApiError("ERR_CLAIM_REVIEWS_INCOMPLETE",
                       "Both fork branches must be signed off first.")
    lines = domain.claim_lines_of(claim)
    claimed_cost_cents, _weighted_pct, cause = calc.claim_cause_classification(
        lines)
    claim["claimed_cost_cents"] = claimed_cost_cents
    claim["cause"] = cause
    machine = _claim_machine(claim)
    customer = (store.get("customers", machine["customer_id"])
                if machine is not None else None)
    variation_pct = (customer["product_variation_pct"]
                     if customer is not None else Decimal("0.00"))
    shares, oem_share_cents = calc.claim_cost_apportionment(lines,
                                                            variation_pct)
    for line, share in zip(lines, shares):
        line["oem_line_share_cents"] = share
    if resolution == "REJECT":
        claim["oem_share_cents"] = 0
        claim["customer_share_cents"] = claimed_cost_cents
        claim["status"] = "REJECTED"
        store.touch(claim)
        domain.recompute_machine_open_claims(machine)
        return envelope.ok(claim)
    claim["oem_share_cents"] = oem_share_cents
    claim["customer_share_cents"] = claimed_cost_cents - oem_share_cents
    # hop 1: the tier-absorbed amount, clamped by the remaining pot
    claim["goodwill_charged_cents"] = calc.claim_goodwill_charge(
        oem_share_cents, contract["tier"],
        int(contract["goodwill_budget_cents"]))
    claim["status"] = "ADJUDICATED"
    store.touch(claim)
    # hop 2: debit the contract's conserved ledger
    contract["goodwill_budget_cents"] = domain.goodwill_ledger_value(contract)
    # hop 3: re-derive the posture and, on exhaustion, hold the calendar
    was_exhausted = contract["coverage_posture"] == "BUDGET_EXHAUSTED"
    contract["coverage_posture"] = calc.coverage_posture(
        int(contract["goodwill_budget_cents"]))
    store.touch(contract)
    if contract["coverage_posture"] == "BUDGET_EXHAUSTED" and not was_exhausted:
        _exhaustion_sweep(contract)
    domain.recompute_machine_open_claims(machine)
    return envelope.ok(claim)


@bp.post("/warranty-claims/<warranty_claim_id>/void")
def void_warranty_claim(warranty_claim_id):
    auth.authorize(("ServiceManager",))
    claim = domain.must_get("warranty_claims", warranty_claim_id)
    contract = _claim_contract(claim)
    if contract is None or contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE",
                       "The funding contract is not ACTIVE.")
    if claim["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_CLAIM_STATE",
                       "Only an ADJUDICATED claim may be voided.")
    claim["status"] = "VOID"
    claim["goodwill_charged_cents"] = 0
    claim["oem_share_cents"] = 0
    claim["customer_share_cents"] = 0
    store.touch(claim)
    # exact reversal: the ledger identity re-derives the credit
    was_exhausted = contract["coverage_posture"] == "BUDGET_EXHAUSTED"
    contract["goodwill_budget_cents"] = domain.goodwill_ledger_value(contract)
    contract["coverage_posture"] = calc.coverage_posture(
        int(contract["goodwill_budget_cents"]))
    store.touch(contract)
    if was_exhausted and contract["coverage_posture"] != "BUDGET_EXHAUSTED":
        _release_holds(contract)
    model = _claim_model(claim)
    if model is not None:
        model["open_defect_review_count"] = int(
            model["open_defect_review_count"]) - 1
        store.touch(model)
    domain.recompute_machine_open_claims(_claim_machine(claim))
    return envelope.ok(claim)
