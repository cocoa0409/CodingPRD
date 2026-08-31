"""Hazard evaluations, consignees and distribution records."""
from flask import Blueprint, request

from core import (ALL_ROLES, ROLE_COORD, ROLE_FIRM, ROLE_PANEL, auth, body, created, db, err,
                  mark_dirty, new_row, ok, opt_bool, opt_str, paginate, public, req_datetime,
                  req_enum, req_int, req_str, upd)
from domain import (CONSIGNEE_MAX_TIER, CONSIGNEE_TYPES, EVIDENCE_STRENGTHS, PROBABILITIES,
                    RECONCILE_OUTCOMES, apply_hazard_score, apply_metrics, consignee_children,
                    hazard_score_and_class, recall_children, refresh_sample_flags)
from resolve import (firm_scope, get_consignee, get_consignee_in_recall, get_recall, get_sub,
                     not_terminated, recall_state, sub_recall, sync)

bp = Blueprint("hazard", __name__)


# ------------------------------------------------------------------ hazard evaluations
@bp.post("/recalls/<recall_id>/hazard-evaluations")
def create_evaluation(recall_id):
    user_id, role = auth([ROLE_FIRM, ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    probability = req_enum(data, "probability_of_adverse_health", PROBABILITIES)
    severity = req_int(data, "severity_tier")
    if severity < 1 or severity > 4:
        err("ERR_INVALID_REQUEST", "severity_tier must be an integer in 1..4")
    exposure = req_int(data, "exposure_population", minimum=0)
    vulnerable = opt_bool(data, "vulnerable_population", False)
    evidence = req_enum(data, "evidence_strength", EVIDENCE_STRENGTHS)
    expected = req_int(data, "expected_recall_version")
    if expected != int(recall.get("version") or 0):                      # rung 9
        err("ERR_STALE_RECALL_VERSION",
            "expected_recall_version does not match the current recall version")
    not_terminated(recall)                                               # rung 11
    sync(recall)

    draft = {
        "probability_of_adverse_health": probability,
        "severity_tier": severity,
        "exposure_population": exposure,
        "vulnerable_population": vulnerable,
        "evidence_strength": evidence,
    }
    score, recommended = hazard_score_and_class(draft, "PRELIMINARY")
    evaluation = new_row(db.hazard_evaluations,
                         recall_id=recall["id"],
                         variant="PRELIMINARY",
                         hazard_score=score,
                         recommended_class=recommended,
                         status="DRAFT",
                         submitted_by_user_id=None,
                         ratified_by_user_id=None,
                         panel_note=None,
                         return_count=0,
                         **draft)
    mark_dirty(recall)   # a successful filing advances the recall's version by one
    return created(public(evaluation))


@bp.get("/recalls/<recall_id>/hazard-evaluations")
def list_evaluations(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.hazard_evaluations, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


@bp.post("/hazard-evaluations/<evaluation_id>/submit")
def submit_evaluation(evaluation_id):
    user_id, role = auth([ROLE_FIRM, ROLE_COORD])
    evaluation = get_sub(db.hazard_evaluations, evaluation_id)
    recall = sub_recall(evaluation)
    firm_scope(role, user_id, recall)
    not_terminated(recall)
    if evaluation.get("status") not in ("DRAFT", "RETURNED"):
        err("ERR_INVALID_EVALUATION_STATE",
            "Evaluation status %s does not permit submission" % evaluation.get("status"))
    sync(recall)
    upd(evaluation, status="SUBMITTED", submitted_by_user_id=user_id)
    apply_hazard_score(evaluation, "PRELIMINARY")
    return ok(public(evaluation))


@bp.post("/hazard-evaluations/<evaluation_id>/decide")
def decide_evaluation(evaluation_id):
    user_id, role = auth([ROLE_PANEL])
    evaluation = get_sub(db.hazard_evaluations, evaluation_id)
    recall = sub_recall(evaluation)
    data = body()
    decision = req_enum(data, "decision", {"RATIFY", "RETURN"})
    panel_note = opt_str(data, "panel_note")
    not_terminated(recall)
    if evaluation.get("status") != "SUBMITTED":
        err("ERR_INVALID_EVALUATION_STATE",
            "Evaluation status %s does not permit a panel decision" % evaluation.get("status"))
    sync(recall)
    if panel_note is not None:
        upd(evaluation, panel_note=panel_note)
    if decision == "RATIFY":
        upd(evaluation, status="RATIFIED", ratified_by_user_id=user_id)
        apply_hazard_score(evaluation, "RATIFIED")
        for other in recall_children(db.hazard_evaluations, recall["id"]):
            if other["id"] != evaluation["id"] and other.get("status") == "RATIFIED":
                upd(other, status="SUPERSEDED")
    else:
        upd(evaluation, status="RETURNED",
            return_count=int(evaluation.get("return_count") or 0) + 1)
    return ok(public(evaluation))


# ------------------------------------------------------------------ consignees
@bp.post("/recalls/<recall_id>/consignees")
def create_consignee(recall_id):
    user_id, role = auth([ROLE_FIRM, ROLE_COORD])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    parent = None
    if data.get("parent_consignee_id") is not None:                       # rung 5
        parent = get_consignee_in_recall(data.get("parent_consignee_id"), recall)
    name = req_str(data, "name")
    consignee_type = req_enum(data, "consignee_type", CONSIGNEE_TYPES)
    recall_state(recall, ("DRAFT", "CLASSIFIED", "NOTIFICATION_IN_PROGRESS"))
    sync(recall)
    tier = 1 if parent is None else int(parent.get("tier") or 1) + 1
    if tier > CONSIGNEE_MAX_TIER:                                         # rung 29
        err("ERR_CONSIGNEE_TIER_LIMIT",
            "The distribution tree is capped at %d levels" % CONSIGNEE_MAX_TIER)
    consignee = new_row(db.consignees,
                        recall_id=recall["id"],
                        parent_consignee_id=parent["id"] if parent else None,
                        name=name,
                        consignee_type=consignee_type,
                        tier=tier,
                        in_effectiveness_sample=(tier <= int(recall.get("sample_tier_scope") or 0)),
                        escalation_level=0,
                        last_contact_at=None,
                        response_state="AWAITING",
                        closed_without_response=False)
    apply_metrics(recall)
    refresh_sample_flags(recall)
    return created(public(consignee))


@bp.get("/recalls/<recall_id>/consignees")
def list_consignees(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.consignees, recall["id"])
    tier = request.args.get("tier")
    if tier is not None:
        rows = [r for r in rows if str(r.get("tier")) == str(tier)]
    return paginate(rows)


@bp.get("/consignees/<consignee_id>")
def read_consignee(consignee_id):
    user_id, role = auth(ALL_ROLES)
    consignee = get_consignee(consignee_id)
    firm_scope(role, user_id, db.recalls.get(consignee.get("recall_id")))
    return ok(public(consignee))


@bp.get("/consignees/<consignee_id>/sub-consignees")
def list_sub_consignees(consignee_id):
    user_id, role = auth(ALL_ROLES)
    consignee = get_consignee(consignee_id)
    firm_scope(role, user_id, db.recalls.get(consignee.get("recall_id")))
    rows = [c for c in db.consignees.values()
            if c.get("parent_consignee_id") == consignee["id"]]
    return paginate(rows)


@bp.get("/consignees/<consignee_id>/distribution-records")
def list_consignee_distribution(consignee_id):
    user_id, role = auth(ALL_ROLES)
    consignee = get_consignee(consignee_id)
    firm_scope(role, user_id, db.recalls.get(consignee.get("recall_id")))
    return paginate(consignee_children(db.distribution_records, consignee["id"]))


@bp.get("/consignees/<consignee_id>/notifications")
def list_consignee_notifications(consignee_id):
    user_id, role = auth(ALL_ROLES)
    consignee = get_consignee(consignee_id)
    firm_scope(role, user_id, db.recalls.get(consignee.get("recall_id")))
    return paginate(consignee_children(db.notifications, consignee["id"]))


@bp.get("/consignees/<consignee_id>/retrieval-receipts")
def list_consignee_receipts(consignee_id):
    user_id, role = auth(ALL_ROLES)
    consignee = get_consignee(consignee_id)
    firm_scope(role, user_id, db.recalls.get(consignee.get("recall_id")))
    return paginate(consignee_children(db.retrieval_receipts, consignee["id"]))


# ------------------------------------------------------------------ distribution records
@bp.post("/recalls/<recall_id>/distribution-records")
def create_distribution_record(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    if data.get("consignee_id") is not None:                               # rung 5
        consignee = get_consignee_in_recall(data.get("consignee_id"), recall)
    else:
        consignee = None
    consignee_id = req_str(data, "consignee_id")
    lot_code = req_str(data, "lot_code")
    quantity_shipped = req_int(data, "quantity_shipped", exclusive_min=0)
    ship_date_raw, _ = req_datetime(data, "ship_date")
    recall_state(recall, ("DRAFT", "CLASSIFIED", "NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING"))
    sync(recall)
    record = new_row(db.distribution_records,
                     recall_id=recall["id"],
                     consignee_id=consignee_id,
                     lot_code=lot_code,
                     quantity_shipped=quantity_shipped,
                     ship_date=ship_date_raw,
                     quantity_confirmed=None,
                     effective_quantity=0,
                     status="DECLARED",
                     reconcile_round=0)
    apply_metrics(recall)
    return created(public(record))


@bp.get("/recalls/<recall_id>/distribution-records")
def list_distribution_records(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.distribution_records, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


_RECONCILE_FROM = {
    "CONFIRM": ("DECLARED", "DISPUTED"),
    "DISPUTE": ("DECLARED", "CONFIRMED", "CORRECTED"),
    "CORRECT": ("DISPUTED",),
    "VOID": ("DISPUTED",),
}


@bp.post("/distribution-records/<record_id>/reconcile")
def reconcile(record_id):
    user_id, role = auth([ROLE_FIRM, ROLE_COORD])
    record = get_sub(db.distribution_records, record_id)
    recall = sub_recall(record)
    firm_scope(role, user_id, recall)
    data = body()
    outcome = req_enum(data, "outcome", RECONCILE_OUTCOMES)
    quantity_confirmed = None
    if outcome == "CORRECT":
        quantity_confirmed = req_int(data, "quantity_confirmed", exclusive_min=0)
    if outcome == "VOID" and role != ROLE_COORD:
        err("ERR_ROLE_NOT_PERMITTED", "Only a RecallCoordinator may void a distribution line")
    not_terminated(recall)
    if record.get("status") not in _RECONCILE_FROM[outcome]:
        err("ERR_INVALID_ACCOUNTING_STATE",
            "Distribution record status %s does not permit %s" % (record.get("status"), outcome))
    sync(recall)

    if outcome == "CONFIRM":
        upd(record, status="CONFIRMED", quantity_confirmed=None,
            effective_quantity=int(record.get("quantity_shipped") or 0))
    elif outcome == "DISPUTE":
        upd(record, status="DISPUTED", effective_quantity=0)
    elif outcome == "CORRECT":
        upd(record, status="CORRECTED", quantity_confirmed=quantity_confirmed,
            effective_quantity=quantity_confirmed)
    else:
        upd(record, status="VOIDED", effective_quantity=0)
    upd(record, reconcile_round=int(record.get("reconcile_round") or 0) + 1)
    apply_metrics(recall)
    return ok(public(record))
