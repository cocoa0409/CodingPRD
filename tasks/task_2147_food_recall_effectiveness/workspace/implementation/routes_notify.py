"""Consignee notifications (parallel delivery/response dimensions), retrieval receipts,
disposition orders."""
from flask import Blueprint, request

from core import (ALL_ROLES, ROLE_COORD, ROLE_FIELD, ROLE_FIRM, auth, body, created, db, err,
                  new_row, now, now_iso, ok, opt_str, paginate, parse_iso, public, req_enum,
                  req_int, req_str, upd)
from domain import (DISPOSITION_METHODS, METHOD_BUFFER_HOURS, NOTIFICATION_METHODS,
                    apply_metrics, consignee_children, maybe_enter_effectiveness_review,
                    maybe_enter_retrieval, recall_children, refresh_consignee_response_state,
                    refresh_notification_counts)
from resolve import (firm_scope, get_consignee_in_recall, get_recall, get_sub, not_terminated,
                     recall_state, sub_recall, sync)

bp = Blueprint("notify", __name__)


def _note_sort_key(row):
    return (row.get("sent_at") or "", row.get("created_at") or "", row.get("_seq") or 0)


# ------------------------------------------------------------------ notifications
@bp.post("/recalls/<recall_id>/notifications")
def dispatch_notification(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    consignee = None
    if data.get("consignee_id") is not None:                                 # rung 5
        consignee = get_consignee_in_recall(data.get("consignee_id"), recall)
    req_str(data, "consignee_id")                                            # rung 8
    method = req_enum(data, "method", NOTIFICATION_METHODS)
    expected = req_int(data, "expected_consignee_version")
    if expected != int(consignee.get("version") or 0):                       # rung 10
        err("ERR_STALE_CONSIGNEE_VERSION",
            "expected_consignee_version does not match the current consignee version")
    recall_state(recall, ("CLASSIFIED", "NOTIFICATION_IN_PROGRESS"))         # rung 11
    sync(recall)

    # rung 24 — the distribution list must be fully reconciled
    for record in recall_children(db.distribution_records, recall["id"]):
        if record.get("status") == "DECLARED":
            err("ERR_DISTRIBUTION_LIST_INCOMPLETE",
                "A distribution record of this recall is still DECLARED")

    prior_notes = consignee_children(db.notifications, consignee["id"])
    # rung 25 — cooling-off buffer against this consignee's most recent dispatch
    if prior_notes:
        prior = max(prior_notes, key=lambda n: ((n.get("sent_at") or ""),
                                                (n.get("created_at") or ""),
                                                (n.get("_seq") or 0)))
        buffer_hours = max(METHOD_BUFFER_HOURS[method],
                           METHOD_BUFFER_HOURS[prior.get("method")])
        sent = parse_iso(prior.get("sent_at"))
        if sent is not None:
            elapsed = (now() - sent).total_seconds() / 3600.0
            if elapsed < buffer_hours:
                err("ERR_NOTIFICATION_COOLING_OFF",
                    "The cooling-off buffer of %d hours has not elapsed" % buffer_hours)

    # rung 27 — no two in-flight dispatches to the same consignee
    for note in prior_notes:
        if note.get("delivery_state") == "SENT":
            err("ERR_DUPLICATE_ACTIVE_NOTIFICATION",
                "This consignee already holds a notification whose delivery is still in flight")

    stamp = now_iso()
    notification = new_row(db.notifications,
                           recall_id=recall["id"],
                           consignee_id=consignee["id"],
                           method=method,
                           attempt_no=len(prior_notes) + 1,
                           sent_at=stamp,
                           delivery_state="SENT",
                           response_state="AWAITING",
                           delivery_recorded_at=None,
                           response_recorded_at=None,
                           counts_toward_effectiveness=False,
                           response_note=None)
    upd(consignee, last_contact_at=stamp)
    if recall.get("status") == "CLASSIFIED":
        upd(recall, status="NOTIFICATION_IN_PROGRESS")
    apply_metrics(recall)
    return created(public(notification))


@bp.get("/recalls/<recall_id>/notifications")
def list_notifications(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.notifications, recall["id"])
    for field in ("delivery_state", "response_state"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return paginate(rows)


@bp.post("/notifications/<notification_id>/delivery")
def record_delivery(notification_id):
    user_id, role = auth([ROLE_FIRM])
    notification = get_sub(db.notifications, notification_id)
    recall = sub_recall(notification)
    firm_scope(role, user_id, recall)
    data = body()
    outcome = req_enum(data, "outcome", {"DELIVERED", "UNDELIVERABLE"})
    not_terminated(recall)
    if notification.get("delivery_state") != "SENT":                          # rung 15
        err("ERR_INVALID_NOTIFICATION_STATE",
            "delivery_state %s does not permit a delivery outcome"
            % notification.get("delivery_state"))
    sync(recall)

    upd(notification, delivery_state=outcome, delivery_recorded_at=now_iso())
    refresh_notification_counts(notification)
    consignee = db.consignees.get(notification.get("consignee_id"))
    if consignee is not None:
        if outcome == "UNDELIVERABLE":
            upd(consignee, escalation_level=int(consignee.get("escalation_level") or 0) + 1)
        refresh_consignee_response_state(consignee)
    apply_metrics(recall)
    maybe_enter_retrieval(recall)
    return ok(public(notification))


@bp.post("/notifications/<notification_id>/response")
def record_response(notification_id):
    user_id, role = auth([ROLE_FIRM])
    notification = get_sub(db.notifications, notification_id)
    recall = sub_recall(notification)
    firm_scope(role, user_id, recall)
    data = body()
    outcome = req_enum(data, "outcome", {"ACKNOWLEDGED", "REFUSED"})
    response_note = opt_str(data, "response_note")
    not_terminated(recall)
    if notification.get("response_state") != "AWAITING" or \
            notification.get("delivery_state") not in ("SENT", "DELIVERED"):   # rung 15
        err("ERR_INVALID_NOTIFICATION_STATE",
            "This notification does not permit a response outcome")
    sync(recall)

    upd(notification, response_state=outcome, response_recorded_at=now_iso())
    if response_note is not None:
        upd(notification, response_note=response_note)
    refresh_notification_counts(notification)
    consignee = db.consignees.get(notification.get("consignee_id"))
    if consignee is not None:
        refresh_consignee_response_state(consignee)
    apply_metrics(recall)
    maybe_enter_retrieval(recall)
    return ok(public(notification))


# ------------------------------------------------------------------ retrieval receipts
@bp.post("/recalls/<recall_id>/retrieval-receipts")
def create_receipt(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    consignee = None
    if data.get("consignee_id") is not None:                                   # rung 5
        consignee = get_consignee_in_recall(data.get("consignee_id"), recall)
    req_str(data, "consignee_id")                                              # rung 8
    returned = req_int(data, "quantity_returned", minimum=0)
    destroyed = req_int(data, "quantity_destroyed_onsite", minimum=0)
    held = req_int(data, "quantity_held_segregated", minimum=0)
    unrecoverable = req_int(data, "quantity_unrecoverable", minimum=0)
    recall_state(recall, ("NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
                          "EFFECTIVENESS_REVIEW"))                             # rung 11
    sync(recall)

    # rung 23 — the consignee must sit on the reconciled distribution list
    reconciled = [r for r in consignee_children(db.distribution_records, consignee["id"])
                  if r.get("recall_id") == recall["id"] and
                  r.get("status") in ("CONFIRMED", "CORRECTED")]
    if not reconciled:
        err("ERR_CONSIGNEE_NOT_ON_DISTRIBUTION_LIST",
            "This consignee has no reconciled distribution record on this recall")

    # rung 30 — cumulative reported units may not exceed the reconciled shipped total
    shipped = sum(int(r.get("effective_quantity") or 0) for r in reconciled)
    running = 0
    for existing in consignee_children(db.retrieval_receipts, consignee["id"]):
        if existing.get("recall_id") != recall["id"]:
            continue
        if existing.get("status") not in ("REPORTED", "VERIFIED"):
            continue
        running += (int(existing.get("quantity_returned") or 0)
                    + int(existing.get("quantity_destroyed_onsite") or 0)
                    + int(existing.get("quantity_held_segregated") or 0)
                    + int(existing.get("quantity_unrecoverable") or 0))
    incoming = returned + destroyed + held + unrecoverable
    if running + incoming > shipped:
        err("ERR_QUANTITY_EXCEEDS_SHIPPED",
            "Reported units exceed the consignee's reconciled shipped total")

    receipt = new_row(db.retrieval_receipts,
                      recall_id=recall["id"],
                      consignee_id=consignee["id"],
                      quantity_returned=returned,
                      quantity_destroyed_onsite=destroyed,
                      quantity_held_segregated=held,
                      quantity_unrecoverable=unrecoverable,
                      accounted_units=returned + destroyed + held,
                      status="REPORTED",
                      verified_by_user_id=None,
                      verification_note=None)
    apply_metrics(recall)
    return created(public(receipt))


@bp.get("/recalls/<recall_id>/retrieval-receipts")
def list_receipts(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.retrieval_receipts, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


_RECEIPT_FROM = {"VERIFY": ("REPORTED",), "DISPUTE": ("REPORTED",), "REOPEN": ("DISPUTED",)}


@bp.post("/retrieval-receipts/<receipt_id>/verify")
def verify_receipt(receipt_id):
    user_id, role = auth([ROLE_FIELD])
    receipt = get_sub(db.retrieval_receipts, receipt_id)
    recall = sub_recall(receipt)
    data = body()
    decision = req_enum(data, "decision", {"VERIFY", "DISPUTE", "REOPEN"})
    verification_note = opt_str(data, "verification_note")
    recall_state(recall, ("NOTIFICATION_IN_PROGRESS", "RETRIEVAL_ACCOUNTING",
                          "EFFECTIVENESS_REVIEW"))                             # rung 11
    if receipt.get("status") not in _RECEIPT_FROM[decision]:                   # rung 16
        err("ERR_INVALID_ACCOUNTING_STATE",
            "Receipt status %s does not permit %s" % (receipt.get("status"), decision))
    sync(recall)
    if verification_note is not None:
        upd(receipt, verification_note=verification_note)

    if decision == "VERIFY":
        # Cascade B hop 1
        upd(receipt, status="VERIFIED", verified_by_user_id=user_id)
        gained = int(receipt.get("quantity_returned") or 0) + \
            int(receipt.get("quantity_held_segregated") or 0)
        upd(recall, units_awaiting_disposition=int(recall.get("units_awaiting_disposition") or 0) + gained)
        apply_metrics(recall)
        # Cascade B hops 2-3
        maybe_enter_effectiveness_review(recall)
    elif decision == "DISPUTE":
        upd(receipt, status="DISPUTED", verified_by_user_id=user_id)
        apply_metrics(recall)
    else:
        upd(receipt, status="REPORTED", verified_by_user_id=None)
        apply_metrics(recall)
    return ok(public(receipt))


# ------------------------------------------------------------------ disposition orders
@bp.post("/recalls/<recall_id>/disposition-orders")
def create_disposition(recall_id):
    user_id, role = auth([ROLE_FIRM])
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    data = body()
    method = req_enum(data, "method", DISPOSITION_METHODS)
    quantity = req_int(data, "quantity", exclusive_min=0)
    facility_name = req_str(data, "facility_name")
    recall_state(recall, ("RETRIEVAL_ACCOUNTING", "EFFECTIVENESS_REVIEW"))
    sync(recall)
    order = new_row(db.disposition_orders,
                    recall_id=recall["id"],
                    method=method,
                    quantity=quantity,
                    facility_name=facility_name,
                    proposed_by_user_id=user_id,
                    authorized_by_user_id=None,
                    certificate_reference=None,
                    executed_at=None,
                    witness_user_id=None,
                    status="PROPOSED",
                    reject_count=0,
                    verification_note=None)
    return created(public(order))


@bp.get("/recalls/<recall_id>/disposition-orders")
def list_dispositions(recall_id):
    user_id, role = auth(ALL_ROLES)
    recall = get_recall(recall_id)
    firm_scope(role, user_id, recall)
    rows = recall_children(db.disposition_orders, recall["id"])
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r.get("status") == status]
    return paginate(rows)


@bp.post("/disposition-orders/<order_id>/authorize")
def authorize_disposition(order_id):
    user_id, role = auth([ROLE_COORD])
    order = get_sub(db.disposition_orders, order_id)
    recall = sub_recall(order)
    firm_scope(role, user_id, recall)
    recall_state(recall, ("RETRIEVAL_ACCOUNTING", "EFFECTIVENESS_REVIEW"))     # rung 11
    if order.get("status") != "PROPOSED":                                      # rung 14
        err("ERR_INVALID_DISPOSITION_STATE",
            "Disposition status %s does not permit authorization" % order.get("status"))
    sync(recall)
    if int(order.get("quantity") or 0) > int(recall.get("units_awaiting_disposition") or 0):
        err("ERR_DISPOSITION_EXCEEDS_ACCOUNTED_UNITS",
            "The order exceeds the units currently awaiting disposition")
    upd(order, status="AUTHORIZED", authorized_by_user_id=user_id)
    return ok(public(order))


@bp.post("/disposition-orders/<order_id>/execute")
def execute_disposition(order_id):
    user_id, role = auth([ROLE_FIRM])
    order = get_sub(db.disposition_orders, order_id)
    recall = sub_recall(order)
    firm_scope(role, user_id, recall)
    data = body()
    certificate_reference = req_str(data, "certificate_reference")
    not_terminated(recall)
    if order.get("status") != "AUTHORIZED":
        err("ERR_INVALID_DISPOSITION_STATE",
            "Disposition status %s does not permit execution" % order.get("status"))
    sync(recall)
    quantity = int(order.get("quantity") or 0)
    upd(order, status="EXECUTED", certificate_reference=certificate_reference,
        executed_at=now_iso())
    upd(recall,
        units_awaiting_disposition=int(recall.get("units_awaiting_disposition") or 0) - quantity,
        units_pending_verification=int(recall.get("units_pending_verification") or 0) + quantity)
    return ok(public(order))


@bp.post("/disposition-orders/<order_id>/verify")
def verify_disposition(order_id):
    user_id, role = auth([ROLE_FIELD])
    order = get_sub(db.disposition_orders, order_id)
    recall = sub_recall(order)
    data = body()
    decision = req_enum(data, "decision", {"VERIFY", "REJECT"})
    verification_note = opt_str(data, "verification_note")
    not_terminated(recall)
    if order.get("status") != "EXECUTED":
        err("ERR_INVALID_DISPOSITION_STATE",
            "Disposition status %s does not permit verification" % order.get("status"))
    sync(recall)
    if verification_note is not None:
        upd(order, verification_note=verification_note)
    quantity = int(order.get("quantity") or 0)
    if decision == "VERIFY":
        upd(order, status="VERIFIED", witness_user_id=user_id)
        upd(recall,
            units_pending_verification=int(recall.get("units_pending_verification") or 0) - quantity,
            units_disposed_verified=int(recall.get("units_disposed_verified") or 0) + quantity)
    else:
        upd(order, status="AUTHORIZED",
            reject_count=int(order.get("reject_count") or 0) + 1,
            certificate_reference=None, executed_at=None)
        upd(recall,
            units_pending_verification=int(recall.get("units_pending_verification") or 0) - quantity,
            units_awaiting_disposition=int(recall.get("units_awaiting_disposition") or 0) + quantity)
    return ok(public(order))
