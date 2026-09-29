"""Panel selection, defense engagement, billing and the guideline audit."""

from decimal import Decimal

from flask import Blueprint

import calc
import serialize
import store
from errors import ApiError
from envelope import created_response, list_response, object_response
from routes.claims import require_policy_in_force
from routes.common import (assignment_firm_id, invoice_firm_id, own_firm_filter,
                           scope_counsel_firm, sorted_by)
from services import ledger
from validate import (ENUMS, F, auth, enum_filter, interval_order, no_body,
                      pagination, parse_body, str_filter)

bp = Blueprint("defense", __name__)

DEFENSE_READERS = ("PlatformAdmin", "ClaimsAdjuster", "ClaimsManager",
                   "PanelCounsel")
LIVE_ASSIGNMENT_STATUSES = ("ACTIVE", "SUSPENDED_FUNDING")
LIVE_INVOICE_STATUSES = ("SUBMITTED", "UNDER_AUDIT", "ADJUSTED", "APPROVED")


# --------------------------------------------------------------------------
# defense assignment reads
# --------------------------------------------------------------------------
@bp.get("/epli/defense-assignments/<assignment_id>")
def get_assignment(assignment_id):
    user_id, role = auth(DEFENSE_READERS)
    row = store.find(store.ASSIGNMENTS, assignment_id,
                     "ERR_ASSIGNMENT_NOT_FOUND")
    scope_counsel_firm(role, user_id, row["panel_firm_id"])
    return object_response(serialize.assignment(row))


@bp.get("/epli/defense-assignments")
def list_assignments():
    user_id, role = auth(DEFENSE_READERS)
    limit, offset = pagination()
    claim_id = str_filter("claim_id")
    panel_firm_id = str_filter("panel_firm_id")
    status = enum_filter("status", "assignment_status")
    rows = list(store.ASSIGNMENTS.values())
    if claim_id is not None:
        rows = [r for r in rows if r["claim_id"] == claim_id]
    if panel_firm_id is not None:
        rows = [r for r in rows if r["panel_firm_id"] == panel_firm_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = own_firm_filter(role, user_id, rows, assignment_firm_id)
    rows = sorted_by(rows, [lambda r: r["engagement_from"],
                            lambda r: r["created_at"]])
    return list_response([serialize.assignment(r) for r in rows],
                         limit, offset)


# --------------------------------------------------------------------------
# engagement
# --------------------------------------------------------------------------
def _primary_code(claim):
    policy = store.policy_of_claim(claim)
    applicant = store.applicant_of_policy(policy) if policy else None
    return applicant["primary_jurisdiction_code"] if applicant else None


def _select_firm(claim, window_from, window_to, excluded):
    code = _primary_code(claim)
    candidates = []
    for firm in store.FIRMS.values():
        if firm["status"] != "PANEL_ACTIVE":
            continue
        if code is None or code not in firm["jurisdiction_codes"]:
            continue
        if firm["id"] in excluded:
            continue
        if (ledger.firm_window_matter_count(firm, window_from, window_to)
                >= firm["capacity_open_matters"]):
            continue
        candidates.append(firm)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_PANEL_FIRM",
                       "No panel firm satisfies every eligibility condition.")
    ranked = sorted_by(candidates, [
        lambda f: f["blended_rate_cents"],
        lambda f: calc.TIER_RANK[f["tier"]],
        lambda f: f["created_at"],
    ])
    return ranked[0]


@bp.post("/epli/claims/<claim_id>/defense-assignments")
def create_assignment(claim_id):
    auth(("ClaimsAdjuster",))
    body = parse_body([
        F("engagement_from", "instant", required=True),
        F("engagement_to", "instant", required=True),
        F("budget_cap_cents", "int", required=True, min=1),
        F("panel_firm_id", "id"),
        F("excluded_panel_firm_ids", "ids", default=None),
        F("litigation_guideline_version", "int", default=1, min=1),
    ])
    interval_order(body["engagement_from"], body["engagement_to"],
                   "engagement_from", "engagement_to")
    claim = store.find(store.CLAIMS, claim_id, "ERR_CLAIM_NOT_FOUND")
    excluded = list(body["excluded_panel_firm_ids"] or [])
    directed = None
    if body["panel_firm_id"] is not None:
        directed = store.find(store.FIRMS, body["panel_firm_id"],
                              "ERR_PANEL_FIRM_NOT_FOUND")
    for firm_id in excluded:
        store.find(store.FIRMS, firm_id, "ERR_PANEL_FIRM_NOT_FOUND")
    policy = store.policy_of_claim(claim)
    if claim["status"] not in ("COVERAGE_ACCEPTED", "DEFENSE_OPEN"):
        raise ApiError("ERR_POLICY_NOT_IN_FORCE",
                       "Defense counsel may only be engaged on a "
                       "COVERAGE_ACCEPTED or DEFENSE_OPEN claim.")
    require_policy_in_force(policy, claim)
    window_from = body["engagement_from"]
    window_to = body["engagement_to"]
    if directed is not None:
        if directed["status"] != "PANEL_ACTIVE":
            raise ApiError("ERR_PANEL_FIRM_NOT_ACTIVE",
                           "The named panel firm is not PANEL_ACTIVE.")
        if (ledger.firm_window_matter_count(directed, window_from, window_to)
                >= directed["capacity_open_matters"]):
            raise ApiError("ERR_PANEL_CAPACITY_EXCEEDED",
                           "The named panel firm has no capacity for this "
                           "engagement window.")
        code = _primary_code(claim)
        if (code is None or code not in directed["jurisdiction_codes"]
                or directed["id"] in excluded):
            raise ApiError("ERR_NO_ELIGIBLE_PANEL_FIRM",
                           "The named panel firm is not eligible for this "
                           "matter.")
        firm = directed
        selection_reason = "CLIENT_DIRECTED"
    else:
        firm = _select_firm(claim, window_from, window_to, excluded)
        selection_reason = "AUTO_SELECTED"
    row = store.new_row({
        "claim_id": claim["id"],
        "panel_firm_id": firm["id"],
        "engagement_from": window_from,
        "engagement_to": window_to,
        "partner_rate_cents_per_hour": firm["partner_rate_cents_per_hour"],
        "associate_rate_cents_per_hour": firm["associate_rate_cents_per_hour"],
        "paralegal_rate_cents_per_hour": firm["paralegal_rate_cents_per_hour"],
        "litigation_guideline_version": body["litigation_guideline_version"],
        "budget_cap_cents": body["budget_cap_cents"],
        "selection_reason": selection_reason,
        "hold_reason": None,
        "funding_ceased_at": None,
        "status": "ACTIVE",
    })
    store.ASSIGNMENTS[row["id"]] = row
    store.touch(firm)
    if claim["status"] == "COVERAGE_ACCEPTED":
        claim["status"] = "DEFENSE_OPEN"
        store.touch(claim)
    return created_response(serialize.assignment(row))


@bp.post("/epli/defense-assignments/<assignment_id>/close")
def close_assignment(assignment_id):
    auth(("ClaimsAdjuster",))
    no_body()
    row = store.find(store.ASSIGNMENTS, assignment_id,
                     "ERR_ASSIGNMENT_NOT_FOUND")
    if row["status"] not in LIVE_ASSIGNMENT_STATUSES:
        raise ApiError("ERR_ASSIGNMENT_NOT_CLOSABLE",
                       "Only an ACTIVE or SUSPENDED_FUNDING assignment may be "
                       "closed.")
    row["status"] = "CLOSED"
    store.touch(row)
    firm = store.FIRMS.get(row["panel_firm_id"])
    if firm is not None:
        store.touch(firm)
    return object_response(serialize.assignment(row))


# --------------------------------------------------------------------------
# defense invoices
# --------------------------------------------------------------------------
ZERO = Decimal("0")


@bp.get("/epli/defense-invoices/<invoice_id>")
def get_invoice(invoice_id):
    user_id, role = auth(DEFENSE_READERS)
    row = store.find(store.INVOICES, invoice_id, "ERR_INVOICE_NOT_FOUND")
    scope_counsel_firm(role, user_id, invoice_firm_id(row))
    return object_response(serialize.invoice(row))


@bp.get("/epli/defense-invoices")
def list_invoices():
    user_id, role = auth(DEFENSE_READERS)
    limit, offset = pagination()
    assignment_id = str_filter("defense_assignment_id")
    status = enum_filter("status", "invoice_status")
    rows = list(store.INVOICES.values())
    if assignment_id is not None:
        rows = [r for r in rows
                if r["defense_assignment_id"] == assignment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = own_firm_filter(role, user_id, rows, invoice_firm_id)
    rows = sorted_by(rows, [lambda r: r["period_start"],
                            lambda r: r["created_at"]])
    return list_response([serialize.invoice(r) for r in rows], limit, offset)


def _apply_audit(invoice, assignment):
    outputs = calc.defense_invoice_audit(assignment, invoice)
    invoice.update(outputs)


@bp.post("/epli/defense-assignments/<assignment_id>/invoices")
def submit_invoice(assignment_id):
    user_id, role = auth(("PanelCounsel",))
    body = parse_body([
        F("period_start", "instant", required=True),
        F("period_end", "instant", required=True),
        F("partner_hours", "num", dp=1, min=0, default=ZERO),
        F("associate_hours", "num", dp=1, min=0, default=ZERO),
        F("paralegal_hours", "num", dp=1, min=0, default=ZERO),
        F("block_billed_hours", "num", dp=1, min=0, default=ZERO),
        F("expenses_cents", "int", min=0, default=0),
    ])
    interval_order(body["period_start"], body["period_end"], "period_start",
                   "period_end", strict=False)
    timekeeper = (body["partner_hours"] + body["associate_hours"]
                  + body["paralegal_hours"])
    if body["block_billed_hours"] > timekeeper:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'block_billed_hours' may not exceed the sum of "
                       "the timekeeper hours.")
    assignment = store.find(store.ASSIGNMENTS, assignment_id,
                            "ERR_ASSIGNMENT_NOT_FOUND")
    scope_counsel_firm(role, user_id, assignment["panel_firm_id"])
    if assignment["status"] == "CLOSED":
        raise ApiError("ERR_ASSIGNMENT_CLOSED",
                       "A CLOSED assignment accepts no further invoices.")
    if not (assignment["engagement_from"] <= body["period_start"]
            and body["period_end"] < assignment["engagement_to"]):
        raise ApiError("ERR_INVOICE_OUTSIDE_ENGAGEMENT",
                       "The billing period escapes the engagement window.")
    for existing in store.invoices_of_assignment(assignment["id"]):
        if existing["status"] in ("VOIDED", "REJECTED"):
            continue
        if (body["period_start"] <= existing["period_end"]
                and existing["period_start"] <= body["period_end"]):
            raise ApiError("ERR_INVOICE_PERIOD_OVERLAP",
                           "The billing period collides with a live invoice.")
    row = store.new_row({
        "defense_assignment_id": assignment["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "partner_hours": body["partner_hours"],
        "associate_hours": body["associate_hours"],
        "paralegal_hours": body["paralegal_hours"],
        "block_billed_hours": body["block_billed_hours"],
        "expenses_cents": body["expenses_cents"],
        "dispute_note": None,
        "billed_fees_cents": None,
        "rate_cap_excess_cents": None,
        "block_reduction_cents": None,
        "expense_disallowance_cents": None,
        "guideline_reduction_cents": None,
        "allowed_amount_cents": None,
        "disallowed_amount_cents": None,
        "audited_by_user_id": None,
        "void_reason": None,
        "hold_reason": None,
        "status": "SUBMITTED",
    })
    store.INVOICES[row["id"]] = row
    return created_response(serialize.invoice(row))


@bp.post("/epli/defense-invoices/<invoice_id>/audit")
def audit_invoice(invoice_id):
    user_id, _role = auth(("ClaimsAdjuster",))
    no_body()
    row = store.find(store.INVOICES, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if row["status"] not in ("SUBMITTED", "ADJUSTED"):
        raise ApiError("ERR_INVOICE_NOT_AUDITABLE",
                       "Only a SUBMITTED or ADJUSTED invoice may be audited.")
    assignment = store.ASSIGNMENTS[row["defense_assignment_id"]]
    _apply_audit(row, assignment)
    row["audited_by_user_id"] = user_id
    row["status"] = "UNDER_AUDIT"
    store.touch(row)
    return object_response(serialize.invoice(row))


@bp.post("/epli/defense-invoices/<invoice_id>/dispute")
def dispute_invoice(invoice_id):
    user_id, role = auth(("PanelCounsel",))
    body = parse_body([
        F("dispute_note", "str", required=True),
        F("partner_hours", "num", dp=1, min=0),
        F("associate_hours", "num", dp=1, min=0),
        F("paralegal_hours", "num", dp=1, min=0),
        F("block_billed_hours", "num", dp=1, min=0),
        F("expenses_cents", "int", min=0),
    ])
    row = store.find(store.INVOICES, invoice_id, "ERR_INVOICE_NOT_FOUND")
    present = body["_present"]
    merged = {}
    for field in ("partner_hours", "associate_hours", "paralegal_hours",
                  "block_billed_hours", "expenses_cents"):
        merged[field] = (body[field] if field in present else row[field])
    timekeeper = (merged["partner_hours"] + merged["associate_hours"]
                  + merged["paralegal_hours"])
    if merged["block_billed_hours"] > timekeeper:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'block_billed_hours' may not exceed the sum of "
                       "the timekeeper hours.")
    scope_counsel_firm(role, user_id, invoice_firm_id(row))
    if row["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_INVOICE_NOT_DISPUTABLE",
                       "Only an UNDER_AUDIT invoice may be disputed.")
    row.update(merged)
    row["dispute_note"] = body["dispute_note"]
    assignment = store.ASSIGNMENTS[row["defense_assignment_id"]]
    _apply_audit(row, assignment)
    row["audited_by_user_id"] = None
    row["status"] = "ADJUSTED"
    store.touch(row)
    return object_response(serialize.invoice(row))


@bp.post("/epli/defense-invoices/<invoice_id>/approve")
def approve_invoice(invoice_id):
    user_id, _role = auth(("ClaimsAdjuster",))
    no_body()
    row = store.find(store.INVOICES, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if row["status"] != "UNDER_AUDIT":
        raise ApiError("ERR_INVOICE_NOT_APPROVABLE",
                       "Only an UNDER_AUDIT invoice may be approved.")
    if user_id == row["audited_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver must differ from the auditing user.")
    assignment = store.ASSIGNMENTS[row["defense_assignment_id"]]
    claim = store.CLAIMS[assignment["claim_id"]]
    policy = store.policy_of_claim(claim)
    group = ledger.group_of_claim(claim)
    satisfied = ledger.claim_retention_satisfied(claim)
    applied = ledger.claim_applied_retention(claim) or 0
    if not (satisfied >= applied
            or (group is not None and group["status"] == "LOCKED")):
        raise ApiError("ERR_RETENTION_NOT_SATISFIED",
                       "The claim's retention has not yet attached.")
    allowed = row["allowed_amount_cents"]
    if (ledger.assignment_budget_spent(assignment) + allowed
            > assignment["budget_cap_cents"]):
        raise ApiError("ERR_BUDGET_CAP_EXCEEDED",
                       "The matter budget cannot accommodate this invoice.")
    if allowed > ledger.policy_remaining(policy):
        raise ApiError("ERR_AGGREGATE_LIMIT_EXHAUSTED",
                       "The aggregate limit cannot absorb this invoice.")
    row["status"] = "APPROVED"
    store.touch(row)
    store.touch(assignment)
    store.touch(claim)
    store.touch(policy)
    return object_response(serialize.invoice(row))


@bp.post("/epli/defense-invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    auth(("ClaimsManager",))
    body = parse_body([F("void_reason", "str", required=True)])
    row = store.find(store.INVOICES, invoice_id, "ERR_INVOICE_NOT_FOUND")
    if row["status"] != "APPROVED":
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE",
                       "Only an APPROVED invoice may be voided.")
    row["void_reason"] = body["void_reason"]
    row["status"] = "VOIDED"
    store.touch(row)
    assignment = store.ASSIGNMENTS[row["defense_assignment_id"]]
    store.touch(assignment)
    claim = store.CLAIMS[assignment["claim_id"]]
    store.touch(claim)
    policy = store.policy_of_claim(claim)
    if policy is not None:
        store.touch(policy)
    return object_response(serialize.invoice(row))
