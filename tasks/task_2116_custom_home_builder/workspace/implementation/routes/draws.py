"""Draw requests, the lender window, the cumulative cap and lien waivers."""
from decimal import Decimal

from flask import Blueprint

from errors import AppError
from store import db, base_row, now, bump, ordered
from util import (
    authorize, check_staff_identity, parse_body, ok, ok_list, paginate, qfilter,
    req_str, opt_str, req_enum, req_money, req_int, req_dt, add_days, q2,
)
from routes.common import fetch, own_project, own_subcontractor
from services.constants import WAIVER_TYPES
from services.calc import draw_funding_amounts
from services.ledger import (
    recompute_project, project_cost_entries, project_draw_requests,
    draw_lien_waivers, draw_cost_entries,
)
from services.rows import new_lien_waiver_row
from services.draws import recompute_waiver_compliance, fund_draw, release_draw_holdings

bp = Blueprint("draws", __name__)

DRAW_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Controller", "Client",
                   "Lender", "Subcontractor"]
WAIVER_READ_ROLES = ["PlatformAdmin", "ProjectManager", "Controller", "Lender",
                     "Subcontractor"]
LENDER_DECISIONS = ("CONDITIONALLY_APPROVE", "RETURN")
WAIVER_DECISIONS = ("VERIFY", "REJECT")


@bp.post("/draw-requests")
def create_draw_request():
    user_id, role = authorize(["Controller"])
    body = parse_body()
    project_id = req_str(body, "project_id")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    expected_project_version = req_int(body, "expected_project_version")

    if period_end <= period_start:
        raise AppError("ERR_INVALID_REQUEST",
                       "period_end must be strictly later than period_start.")

    # ladder step 6
    project = db.projects.get(project_id)
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")

    check_staff_identity(user_id, role)

    # ladder step 13
    if expected_project_version != project["version"]:
        raise AppError("ERR_STALE_PROJECT_VERSION")

    # ladder step 34
    if project.get("lender_id") is None:
        raise AppError("ERR_PROJECT_HAS_NO_LENDER")

    for existing in project_draw_requests(project_id):
        if existing["status"] == "DRAFT":
            existing["status"] = "VOIDED"
            existing["voided_at"] = now()
            existing["void_reason"] = "SUPERSEDED_BY_NEWER_DRAFT"
            bump(existing)

    row = base_row()
    row.update({
        "project_id": project_id,
        "submitted_by_staff_id": None,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
        "waiver_compliance": "PENDING",
        "requested_amount": Decimal("0.00"),
        "retainage_amount": Decimal("0.00"),
        "net_funding_amount": Decimal("0.00"),
        "included_cost_entry_count": 0,
        "required_waiver_count": 0,
        "verified_waiver_count": 0,
        "lender_decision_due_at": None,
        "condition_note": None,
        "void_reason": None,
        "submitted_at": None,
        "conditionally_approved_at": None,
        "returned_at": None,
        "funded_at": None,
        "voided_at": None,
    })
    db.draw_requests[row["id"]] = row

    bump(project)
    return ok(row, 201)


@bp.get("/draw-requests/<draw_id>")
def get_draw_request(draw_id):
    user_id, role = authorize(DRAW_READ_ROLES)
    draw = fetch("draw_requests", draw_id)
    check_staff_identity(user_id, role)
    return ok(draw, 200)


@bp.get("/draw-requests")
def list_draw_requests():
    user_id, role = authorize(DRAW_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.draw_requests.values())
    for name in ("project_id", "submitted_by_staff_id", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/draw-requests/<draw_id>/submit")
def submit_draw_request(draw_id):
    user_id, role = authorize(["Controller"])
    draw = fetch("draw_requests", draw_id)
    parse_body()
    check_staff_identity(user_id, role)

    # ladder step 10
    if draw["status"] != "DRAFT":
        raise AppError("ERR_DRAW_NOT_IN_DRAFT")

    project = db.projects.get(draw["project_id"])
    if project is None:
        raise AppError("ERR_PROJECT_NOT_FOUND")

    included = [ce for ce in project_cost_entries(draw["project_id"])
                if ce["status"] == "APPROVED"
                and draw["period_start"] <= ce["incurred_at"] <= draw["period_end"]]
    included.sort(key=lambda e: (e["incurred_at"], e["created_at"], e["_seq"]))

    # ladder step 20 - segregation of duties
    for entry in included:
        if entry.get("approved_by_staff_id") == user_id:
            raise AppError("ERR_SEGREGATION_OF_DUTIES",
                           "The draw submitter approved one of the included cost entries.")

    # ladder step 31
    if not included:
        raise AppError("ERR_DRAW_NO_ELIGIBLE_COSTS")

    lender = db.lenders.get(project.get("lender_id")) if project.get("lender_id") else None

    if lender is not None:
        requested_amount, retainage_amount, net_funding_amount = draw_funding_amounts(
            included, lender["retainage_pct"])
        # ladder step 33 - strict greater-than at the ceiling
        cap = q2(lender["max_cumulative_draw_pct"] * project["contract_sum_current"])
        exposure = q2(project["funded_to_date"] + project["pending_draw_amount"]
                      + requested_amount)
        if exposure > cap:
            raise AppError("ERR_DRAW_EXCEEDS_LENDER_CAP")

    # ladder step 34
    if lender is None:
        raise AppError("ERR_PROJECT_HAS_NO_LENDER")

    for entry in included:
        entry["status"] = "INCLUDED_IN_DRAW"
        entry["draw_request_id"] = draw["id"]
        bump(entry)

    required_type = ("UNCONDITIONAL_FINAL"
                     if project["status"] == "SUBSTANTIAL_COMPLETION"
                     else "CONDITIONAL_PROGRESS")

    totals = {}
    order = []
    for entry in included:
        sub_id = entry.get("subcontractor_id")
        if sub_id is None:
            continue
        subcontractor = db.subcontractors.get(sub_id)
        if subcontractor is None or not subcontractor.get("waiver_required"):
            continue
        if sub_id not in totals:
            totals[sub_id] = Decimal("0")
            order.append(sub_id)
        totals[sub_id] += entry["amount"]

    for sub_id in order:
        waiver = new_lien_waiver_row(draw["id"], sub_id, required_type, q2(totals[sub_id]))
        db.lien_waivers[waiver["id"]] = waiver

    draw["requested_amount"] = requested_amount
    draw["retainage_amount"] = retainage_amount
    draw["net_funding_amount"] = net_funding_amount
    draw["included_cost_entry_count"] = len(included)
    draw["required_waiver_count"] = len(order)
    draw["verified_waiver_count"] = 0
    draw["waiver_compliance"] = "COMPLETE" if not order else "PENDING"
    draw["submitted_by_staff_id"] = user_id
    draw["submitted_at"] = now()
    draw["lender_decision_due_at"] = add_days(draw["submitted_at"],
                                              lender["review_window_days"])
    draw["status"] = "LENDER_REVIEW"
    bump(draw)

    recompute_project(project)
    return ok(draw, 200)


@bp.post("/draw-requests/<draw_id>/lender-decision")
def lender_decision(draw_id):
    user_id, role = authorize(["Lender"])
    draw = fetch("draw_requests", draw_id)
    body = parse_body()
    decision = req_enum(body, "decision", LENDER_DECISIONS)
    condition_note = opt_str(body, "condition_note")

    project = db.projects.get(draw["project_id"])
    own_project(project, user_id, role)

    # ladder step 10
    if draw["status"] != "LENDER_REVIEW":
        raise AppError("ERR_DRAW_INVALID_STATE")

    # ladder step 29 - inclusive upper bound
    if draw.get("lender_decision_due_at") is not None:
        if now() > draw["lender_decision_due_at"]:
            raise AppError("ERR_LENDER_DECISION_WINDOW_EXPIRED")

    if decision == "CONDITIONALLY_APPROVE":
        draw["status"] = "CONDITIONALLY_APPROVED"
        draw["conditionally_approved_at"] = now()
        draw["condition_note"] = condition_note
        bump(draw)
        if draw["waiver_compliance"] == "COMPLETE":
            fund_draw(draw)
        return ok(draw, 200)

    draw["status"] = "RETURNED"
    draw["returned_at"] = now()
    draw["condition_note"] = condition_note
    bump(draw)
    release_draw_holdings(draw)
    return ok(draw, 200)


@bp.post("/draw-requests/<draw_id>/void")
def void_draw_request(draw_id):
    user_id, role = authorize(["Controller"])
    draw = fetch("draw_requests", draw_id)
    body = parse_body()
    void_reason = req_str(body, "void_reason")
    check_staff_identity(user_id, role)

    # ladder step 10
    if draw["status"] not in ("DRAFT", "LENDER_REVIEW", "RETURNED"):
        raise AppError("ERR_DRAW_INVALID_STATE")

    previous = draw["status"]
    draw["status"] = "VOIDED"
    draw["voided_at"] = now()
    draw["void_reason"] = void_reason
    bump(draw)

    if previous == "LENDER_REVIEW":
        release_draw_holdings(draw)
    else:
        project = db.projects.get(draw["project_id"])
        if project is not None:
            recompute_project(project)
    return ok(draw, 200)


# -------------------------------------------------------------- lien waivers
@bp.get("/lien-waivers/<waiver_id>")
def get_lien_waiver(waiver_id):
    user_id, role = authorize(WAIVER_READ_ROLES)
    waiver = fetch("lien_waivers", waiver_id)
    check_staff_identity(user_id, role)
    return ok(waiver, 200)


@bp.get("/lien-waivers")
def list_lien_waivers():
    user_id, role = authorize(WAIVER_READ_ROLES)
    check_staff_identity(user_id, role)
    rows = ordered(db.lien_waivers.values())
    for name in ("draw_request_id", "subcontractor_id", "status"):
        value = qfilter(name)
        if value:
            rows = [r for r in rows if r.get(name) == value]
    page, meta = paginate(rows)
    return ok_list(page, meta)


@bp.post("/lien-waivers/<waiver_id>/receive")
def receive_lien_waiver(waiver_id):
    user_id, role = authorize(["Subcontractor"])
    waiver = fetch("lien_waivers", waiver_id)
    body = parse_body()
    waiver_type = req_enum(body, "waiver_type", WAIVER_TYPES)
    through_date = req_dt(body, "through_date")
    amount_covered = req_money(body, "amount_covered", minimum=Decimal("0"))
    signed_document_ref = opt_str(body, "signed_document_ref")

    # ladder step 8
    own_subcontractor(waiver["subcontractor_id"], user_id, role)

    # ladder step 10
    if waiver["status"] not in ("REQUESTED", "REJECTED"):
        raise AppError("ERR_WAIVER_INVALID_STATE")

    draw = db.draw_requests.get(waiver["draw_request_id"])
    if draw is None or draw["status"] not in ("LENDER_REVIEW", "CONDITIONALLY_APPROVED"):
        raise AppError("ERR_DRAW_INVALID_STATE")

    if waiver["status"] == "REJECTED":
        waiver["resubmit_count"] = (waiver.get("resubmit_count") or 0) + 1

    waiver["waiver_type"] = waiver_type
    waiver["through_date"] = through_date
    waiver["amount_covered"] = q2(amount_covered)
    waiver["signed_document_ref"] = signed_document_ref
    waiver["received_at"] = now()
    waiver["status"] = "RECEIVED"
    bump(waiver)
    return ok(waiver, 200)


@bp.post("/lien-waivers/<waiver_id>/review")
def review_lien_waiver(waiver_id):
    user_id, role = authorize(["Controller"])
    waiver = fetch("lien_waivers", waiver_id)
    body = parse_body()
    decision = req_enum(body, "decision", WAIVER_DECISIONS)
    check_staff_identity(user_id, role)

    # ladder step 10
    if waiver["status"] != "RECEIVED":
        raise AppError("ERR_WAIVER_INVALID_STATE")

    if decision == "REJECT":
        waiver["status"] = "REJECTED"
        waiver["rejected_at"] = now()
        bump(waiver)
        return ok(waiver, 200)

    # ladder step 23 then step 32
    if waiver.get("waiver_type") != waiver.get("required_waiver_type"):
        raise AppError("ERR_WAIVER_TYPE_MISMATCH")
    if (waiver.get("amount_covered") or Decimal("0")) < waiver["required_amount"]:
        raise AppError("ERR_WAIVER_AMOUNT_INSUFFICIENT")

    waiver["status"] = "VERIFIED"
    waiver["verified_at"] = now()
    bump(waiver)

    draw = db.draw_requests.get(waiver["draw_request_id"])
    if draw is not None:
        recompute_waiver_compliance(draw)
    return ok(waiver, 200)
