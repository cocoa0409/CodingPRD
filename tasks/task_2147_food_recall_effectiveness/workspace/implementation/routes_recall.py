"""Firms, recalls, classification, checkpoint, effectiveness, termination, logical clock."""
from flask import Blueprint, request

from core import (ALL_ROLES, ROLE_COORD, ROLE_FIRM, body, created, db, err, iso, mark_dirty,
                  new_row, now_iso, ok, opt_int, paginate, parse_iso, public, req_enum,
                  req_str, upd)
from domain import (AGENCIES, HAZARD_CLASSES, INITIATION_TYPES, ROOT_CAUSE_CODES,
                    TERMINATION_MIN_EFFECTIVENESS_PCT, add_days, apply_cadence,
                    apply_compliance_posture, apply_metrics, compute_metrics, mint_report,
                    recall_children, refresh_sample_flags, run_checkpoint)
from resolve import firm_scope, get_firm, get_recall, recall_state, sync
from core import auth

bp = Blueprint("recall", __name__)

RECALL_DERIVED_ZERO = {
    "effectiveness_check_level": None,
    "sample_tier_scope": 0,
    "eligible_consignee_count": 0,
    "required_sample_size": 0,
    "responded_count": 0,
    "report_cadence_days": 0,
    "compliance_flag": "COMPLIANT",
    "overdue_report_count": 0,
    "total_shipped_units": 0,
    "accounted_units": 0,
    "units_awaiting_disposition": 0,
    "units_pending_verification": 0,
    "units_disposed_verified": 0,
    "contact_effectiveness_pct": 0,
    "quantity_effectiveness_pct": 0,
    "official_effectiveness_pct": 0,
    "total_loaded_cost_cents": 0,
    "insurable_loaded_cost_cents": 0,
    "termination_denied_count": 0,
}


def _eval_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


# ------------------------------------------------------------------ firms
@bp.post("/firms")
def create_firm():
    auth([ROLE_COORD])
    data = body()
    name = req_str(data, "name")
    registration_number = req_str(data, "registration_number")
    deductible = opt_int(data, "policy_deductible_cents", default=2500000, minimum=0)
    aggregate = opt_int(data, "policy_aggregate_cents", default=100000000, exclusive_min=0)
    for existing in db.firms.values():
        if existing.get("registration_number") == registration_number:
            err("ERR_INVALID_REQUEST", "registration_number must be unique across firms")
    firm = new_row(db.firms,
                   name=name,
                   registration_number=registration_number,
                   policy_deductible_cents=deductible,
                   policy_aggregate_cents=aggregate,
                   policy_paid_to_date_cents=0,
                   open_recall_count=0)
    return created(public(firm))


@bp.get("/firms/<firm_id>")
def read_firm(firm_id):
    auth(ALL_ROLES)
    firm = get_firm(firm_id)
    return ok(public(firm))


# ------------------------------------------------------------------ recalls
@bp.post("/recalls")
def create_recall():
    user_id, role = auth([ROLE_FIRM, ROLE_COORD])
    data = body()
    firm_id = data.get("firm_id")
    if firm_id is not None:
        firm = get_firm(firm_id)                                     # rung 3
        if role == ROLE_FIRM and firm["id"] != user_id:              # rung 7
            err("ERR_FIRM_SCOPE_VIOLATION", "A firm officer may only open recalls for its own firm")
    else:
        firm = None
    firm_id = req_str(data, "firm_id")                               # rung 8
    product_description = req_str(data, "product_description")
    agency = req_enum(data, "agency", AGENCIES)
    initiation_type = req_enum(data, "initiation_type", INITIATION_TYPES)
    lot_codes = data.get("lot_codes")
    if not isinstance(lot_codes, list) or len(lot_codes) < 1:
        err("ERR_INVALID_REQUEST", "lot_codes must be an array with at least one element")
    for code in lot_codes:
        if not isinstance(code, str) or not code.strip():
            err("ERR_INVALID_REQUEST", "lot_codes entries must be non-empty strings")

    fields = dict(RECALL_DERIVED_ZERO)
    fields.update(firm_id=firm_id,
                  product_description=product_description,
                  agency=agency,
                  initiation_type=initiation_type,
                  lot_codes=list(lot_codes),
                  status="DRAFT",
                  hazard_class=None,
                  classified_by_user_id=None,
                  root_cause_code=None,
                  capa_summary=None,
                  terminated_at=None)
    recall = new_row(db.recalls, **fields)
    recall["_classify_basis"] = None
    upd(firm, open_recall_count=int(firm.get("open_recall_count") or 0) + 1)
    return created(public(recall))


@bp.get("/recalls")
def list_recalls():
    user_id, role = auth(ALL_ROLES)
    rows = list(db.recalls.values())
    if role == ROLE_FIRM:
        rows = [r for r in rows if r.get("firm_id") == user_id]
    for field in ("firm_id", "status", "hazard_class"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if str(r.get(field)) == value]
    return paginate(rows)


@bp.get("/recalls/<recall_id>")
def read_recall(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    return ok(public(recall))


@bp.post("/recalls/<recall_id>/classify")
def classify(recall_id):
    user_id, role = auth([ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    hazard_class = req_enum(data, "hazard_class", HAZARD_CLASSES)
    recall_state(recall, ("DRAFT", "CLASSIFIED", "NOTIFICATION_IN_PROGRESS"))
    sync(recall)

    ratified = [e for e in recall_children(db.hazard_evaluations, recall["id"])
                if e.get("status") == "RATIFIED"]
    first = recall.get("status") == "DRAFT"
    if first:
        candidates = ratified
    else:
        basis = recall.get("_classify_basis")
        candidates = [e for e in ratified if basis is None or _eval_key(e) > tuple(basis)]
    if not candidates:
        err("ERR_NO_RATIFIED_EVALUATION",
            "No ratified hazard evaluation supports this classification")
    backing = max(candidates, key=_eval_key)

    # Cascade A hop 1
    upd(recall, hazard_class=hazard_class, classified_by_user_id=user_id)
    recall["_classify_basis"] = list(_eval_key(backing))
    if first:
        upd(recall, status="CLASSIFIED")
    apply_cadence(recall)
    pinned_cadence = int(recall.get("report_cadence_days") or 0)

    if first:
        apply_metrics(recall)
        refresh_sample_flags(recall)
        mint_report(recall, "PERIODIC", pinned_cadence)
    else:
        flipped = 0
        for report in sorted(recall_children(db.status_reports, recall["id"]),
                             key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0)):
            if report.get("status") != "PENDING":
                continue
            start = parse_iso(report.get("period_start"))
            if start is None:
                continue
            due = add_days(start, pinned_cadence)          # hop 2
            due_s = iso(due)
            upd(report, due_at=due_s, period_end=due_s)
            if due <= parse_iso(now_iso()):                # hop 3
                upd(report, status="OVERDUE")
                flipped += 1
        if flipped:                                        # hop 4
            upd(recall, overdue_report_count=int(recall.get("overdue_report_count") or 0) + flipped)
            apply_compliance_posture(recall)
            # PRD 3.8: "once the recall is ESCALATED or DELINQUENT, report_cadence_days
            # becomes 3 regardless of hazard class, and the cadence is recomputed at
            # classification".  The re-dating in hop 2 keeps the cadence pinned at hop 1;
            # only the stored field follows the new posture (no cascade re-iteration).
            apply_cadence(recall)
        apply_metrics(recall)
        refresh_sample_flags(recall)
    return ok(public(recall))


@bp.post("/recalls/<recall_id>/checkpoint")
def checkpoint(recall_id):
    user_id, role = auth([ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    recall_state(recall, ("CLASSIFIED", "NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
                          "EFFECTIVENESS_REVIEW", "TERMINATION_REQUESTED"))
    run_checkpoint(recall)
    return ok(public(recall))


@bp.get("/recalls/<recall_id>/effectiveness")
def effectiveness(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    values = compute_metrics(recall)
    return ok({
        "recall_id": recall["id"],
        "agency": recall.get("agency"),
        "effectiveness_check_level": values["effectiveness_check_level"],
        "sample_tier_scope": values["sample_tier_scope"],
        "eligible_consignee_count": values["eligible_consignee_count"],
        "required_sample_size": values["required_sample_size"],
        "responded_count": values["responded_count"],
        "contact_effectiveness_pct": values["contact_effectiveness_pct"],
        "shipped_units": values["_shipped_units"],
        "accounted_units": values["accounted_units"],
        "quantity_effectiveness_pct": values["quantity_effectiveness_pct"],
        "official_basis": values["_official_basis"],
        "official_effectiveness_pct": values["official_effectiveness_pct"],
    })


@bp.post("/recalls/<recall_id>/request-termination")
def request_termination(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    root_cause_code = req_enum(data, "root_cause_code", ROOT_CAUSE_CODES)
    capa_summary = req_str(data, "capa_summary")
    recall_state(recall, ("EFFECTIVENESS_REVIEW",))
    sync(recall)
    open_orders = [d for d in recall_children(db.disposition_orders, recall["id"])
                   if d.get("status") in ("PROPOSED", "AUTHORIZED", "EXECUTED")]
    if open_orders:
        err("ERR_OPEN_DISPOSITION_ORDERS", "Disposition orders are still open on this recall")
    if float(recall.get("official_effectiveness_pct") or 0) < TERMINATION_MIN_EFFECTIVENESS_PCT:
        err("ERR_EFFECTIVENESS_BELOW_TERMINATION_THRESHOLD",
            "Official effectiveness has not reached the termination floor")
    upd(recall, status="TERMINATION_REQUESTED",
        root_cause_code=root_cause_code, capa_summary=capa_summary)
    return ok(public(recall))


@bp.post("/recalls/<recall_id>/decide-termination")
def decide_termination(recall_id):
    user_id, role = auth([ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    decision = req_enum(data, "decision", {"TERMINATE", "DENY"})
    recall_state(recall, ("TERMINATION_REQUESTED",))
    if decision == "TERMINATE" and recall.get("compliance_flag") == "DELINQUENT":
        err("ERR_INVALID_RECALL_STATE", "A delinquent recall may not be terminated")
    if user_id == recall.get("classified_by_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES",
            "The coordinator who classified the recall may not decide its termination")
    sync(recall)

    if decision == "TERMINATE":
        upd(recall, status="TERMINATED", terminated_at=now_iso())
        for report in recall_children(db.status_reports, recall["id"]):
            if report.get("status") in ("PENDING", "OVERDUE"):
                upd(report, status="ACCEPTED")
        firm = db.firms.get(recall.get("firm_id"))
        if firm is not None:
            upd(firm, open_recall_count=max(0, int(firm.get("open_recall_count") or 0) - 1))
    else:
        upd(recall, status="RETRIEVAL_ACCOUNTING",
            termination_denied_count=int(recall.get("termination_denied_count") or 0) + 1)
        if recall.get("compliance_flag") == "COMPLIANT":
            upd(recall, compliance_flag="WATCH")
        apply_cadence(recall)
        mint_report(recall, "PERIODIC", int(recall.get("report_cadence_days") or 0))
    return ok(public(recall))


# ------------------------------------------------------------------ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(ALL_ROLES)
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    parsed = parse_iso(raw)
    if parsed is None:
        err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")
    db.clock = parsed
    return ok({"current_utc": iso(parsed)})
