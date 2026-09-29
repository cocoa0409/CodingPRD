"""Correction requests and the hire ledger (PRD sections 3.9, 3.11)."""
from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import correction, serialize

bp = Blueprint("corrections", __name__)


@bp.post("/car-hire/correction-requests")
@endpoint(roles=[db.ROLE_CLERK])
def file_correction():
    body = shapes.body()
    # --- step 6: the unconditional shape ---
    car_id = shapes.s_id(body, "car_id")
    junction_id = shapes.s_id(body, "junction_id")
    counterparty_road_id = shapes.s_id(body, "counterparty_road_id")
    correction_type = shapes.s_str(body, "correction_type")
    filing_note = shapes.s_str(body, "filing_note", required=False)
    target_event_id = shapes.s_id(body, "target_event_id", required=False)
    direction = shapes.s_str(body, "direction", required=False)
    proposed_interchange_at = shapes.s_dt(body, "proposed_interchange_at", required=False)
    proposed_odometer_miles = shapes.s_int(body, "proposed_odometer_miles", required=False, minimum=0)
    proposed_load_status = shapes.s_str(body, "proposed_load_status", required=False)

    # --- step 6 continued: the conditional shape, once the type is a member ---
    if correction_type == "MISSED_EVENT_INSERT":
        direction = shapes.s_str(body, "direction")
        proposed_interchange_at = shapes.s_dt(body, "proposed_interchange_at")
        proposed_odometer_miles = shapes.s_int(body, "proposed_odometer_miles", minimum=0)
        proposed_load_status = shapes.s_str(body, "proposed_load_status")
    elif correction_type == "TIMESTAMP_AMEND":
        target_event_id = shapes.s_id(body, "target_event_id")
        proposed_interchange_at = shapes.s_dt(body, "proposed_interchange_at")
    elif correction_type == "ERRONEOUS_EVENT_VOID":
        target_event_id = shapes.s_id(body, "target_event_id")

    # --- step 7: enums ---
    shapes.check_enum("correction_type", correction_type, db.CORRECTION_TYPE)
    shapes.check_enum("direction", direction, db.CORRECTION_DIRECTION)
    shapes.check_enum("proposed_load_status", proposed_load_status, db.LOAD_STATUS)

    # --- step 8: foreign keys ---
    car = db.lookup("car", car_id)
    db.lookup("junction", junction_id)
    db.lookup("railroad", counterparty_road_id)
    target = db.lookup("event", target_event_id) if target_event_id is not None else None

    if counterparty_road_id == middleware.acting():
        fail("ERR_INVALID_REQUEST", "counterparty_road_id must be the other road.")
    # --- step 18: suspension ---
    middleware.require_active(middleware.acting(), counterparty_road_id)
    # --- step 28: the type must match its target ---
    if correction_type == "MISSED_EVENT_INSERT":
        if target is not None:
            fail("ERR_CORRECTION_TARGET_NOT_VOIDABLE")
    else:
        if target["car_id"] != car["id"] or target["status"] != "RECORDED":
            fail("ERR_CORRECTION_TARGET_NOT_VOIDABLE")
        if (
            correction_type == "ERRONEOUS_EVENT_VOID"
            and target["event_type"] != "INTERCHANGE_REJECTION"
        ):
            fail("ERR_CORRECTION_TARGET_NOT_VOIDABLE")
    # PRD section 2.8 step 30 guards interchange capture, bad order reporting,
    # release to service and embargo lift only: a correction request may
    # reconstruct or amend an instant the clock has not reached, which is how a
    # MISSED_EVENT_INSERT escapes the direct capture limits at all.

    row = db.base_row()
    row.update(
        {
            "car_id": car["id"],
            "junction_id": junction_id,
            "filed_by_road_id": middleware.acting(),
            "counterparty_road_id": counterparty_road_id,
            "target_event_id": target_event_id,
            "resulting_event_id": None,
            "correction_type": correction_type,
            "direction": direction,
            "proposed_interchange_at": proposed_interchange_at,
            "proposed_odometer_miles": proposed_odometer_miles,
            "proposed_load_status": proposed_load_status,
            "filing_note": filing_note,
            "rejection_reason": None,
            "status": "FILED",
            "confirm_deadline_at": None,
            "confirmed_at": None,
            "rejected_at": None,
            "applied_at": None,
            "expired_at": None,
        }
    )
    row["confirm_deadline_at"] = row["created_at"] + db.hours(db.CORRECTION_CONFIRM_WINDOW_HOURS)
    db.corrections[row["id"]] = row
    return response.ok(serialize.correction(row), 201)


@bp.get("/car-hire/correction-requests")
@endpoint(roles=db.ALL_ROLES)
def list_corrections():
    response.page_params()
    correction_type = shapes.q_enum("correction_type", db.CORRECTION_TYPE)
    status = shapes.q_enum("status", db.CORRECTION_STATUS)
    car_id = shapes.q_str("car_id")
    junction_id = shapes.q_str("junction_id")
    filed_by = shapes.q_str("filed_by_road_id")
    counterparty = shapes.q_str("counterparty_road_id")
    target_event_id = shapes.q_str("target_event_id")
    resulting_event_id = shapes.q_str("resulting_event_id")

    rows = list(db.corrections.values())
    if correction_type is not None:
        rows = [r for r in rows if r["correction_type"] == correction_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if car_id is not None:
        rows = [r for r in rows if r["car_id"] == car_id]
    if junction_id is not None:
        rows = [r for r in rows if r["junction_id"] == junction_id]
    if filed_by is not None:
        rows = [r for r in rows if r["filed_by_road_id"] == filed_by]
    if counterparty is not None:
        rows = [r for r in rows if r["counterparty_road_id"] == counterparty]
    if target_event_id is not None:
        rows = [r for r in rows if r["target_event_id"] == target_event_id]
    if resulting_event_id is not None:
        rows = [r for r in rows if r["resulting_event_id"] == resulting_event_id]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.correction)


@bp.get("/car-hire/correction-requests/<correction_request_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("correction_request_id", "correction")])
def read_correction(request):
    middleware.party_correction(request)
    return response.ok(serialize.correction(request))


@bp.post("/car-hire/correction-requests/<correction_request_id>/confirm")
@endpoint(roles=[db.ROLE_CLERK], path_params=[("correction_request_id", "correction")])
def confirm_correction(request):
    body = shapes.body()
    shapes.s_str(body, "confirm_note", required=False)

    middleware.party_correction(request)
    # --- step 11: only a FILED request may be agreed ---
    if request["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), request["filed_by_road_id"], request["counterparty_road_id"]
    )
    # --- step 35: inclusive at the deadline ---
    if db.now() > request["confirm_deadline_at"]:
        fail("ERR_CORRECTION_CONFIRM_WINDOW_EXPIRED")
    # --- step 50: only the counterparty agrees ---
    if middleware.acting() != request["counterparty_road_id"]:
        fail("ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY")

    request["status"] = "CONFIRMED"
    request["confirmed_at"] = db.now()
    db.touch(request)
    return response.ok(serialize.correction(request))


@bp.post("/car-hire/correction-requests/<correction_request_id>/reject")
@endpoint(roles=[db.ROLE_CLERK], path_params=[("correction_request_id", "correction")])
def reject_correction(request):
    body = shapes.body()
    rejection_reason = shapes.s_str(body, "rejection_reason")

    middleware.party_correction(request)
    if request["status"] != "FILED":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(
        middleware.acting(), request["filed_by_road_id"], request["counterparty_road_id"]
    )
    if middleware.acting() != request["counterparty_road_id"]:
        fail("ERR_CORRECTION_CONFIRM_NOT_COUNTERPARTY")

    request["status"] = "REJECTED"
    request["rejection_reason"] = rejection_reason
    request["rejected_at"] = db.now()
    db.touch(request)
    return response.ok(serialize.correction(request))


@bp.post("/car-hire/correction-requests/<correction_request_id>/apply")
@endpoint(
    roles=[db.ROLE_CLERK, db.ROLE_ADMIN], path_params=[("correction_request_id", "correction")]
)
def apply_correction_request(request):
    # --- step 9: the application belongs to the filing road ---
    middleware.require_party(request["filed_by_road_id"])
    # --- step 14: nothing the cascade touches may sit in an ARCHIVED cycle ---
    for movement in correction.car_segments(request["car_id"]):
        cycle_id = movement["settlement_cycle_id"]
        if not cycle_id:
            continue
        cycle = db.cycles.get(cycle_id)
        if cycle is not None and cycle["status"] == "ARCHIVED":
            fail("ERR_CYCLE_ARCHIVED_IMMUTABLE")
    # --- step 15: the dedicated gate replacing the generic state gate ---
    if request["status"] != "CONFIRMED":
        fail("ERR_CORRECTION_NOT_CONFIRMED")
    # --- step 18: suspension ---
    middleware.require_active(
        middleware.acting(), request["filed_by_road_id"], request["counterparty_road_id"]
    )

    correction.apply_correction(request)
    return response.ok(serialize.correction(request))


@bp.post("/car-hire/correction-requests/expire-due")
@endpoint(roles=[db.ROLE_ADMIN])
def expire_due_corrections():
    evaluated_at = db.now()
    rows = [r for r in db.corrections.values() if r["status"] == "FILED"]
    rows.sort(key=db.order_key)
    expired = []
    for request in rows:
        if request["confirm_deadline_at"] is None or evaluated_at <= request["confirm_deadline_at"]:
            continue
        request["status"] = "EXPIRED"
        request["expired_at"] = evaluated_at
        db.touch(request)
        expired.append(request["id"])
    return response.ok(
        {
            "expired_count": len(expired),
            "expired_correction_request_ids": expired,
            "evaluated_at": db.iso(evaluated_at),
        }
    )


# --------------------------------------------------------------------------
# the hire ledger
# --------------------------------------------------------------------------
@bp.get("/car-hire/ledger-entries")
@endpoint(roles=[db.ROLE_ADMIN, db.ROLE_ACCOUNTANT])
def list_ledger_entries():
    response.page_params()
    entry_type = shapes.q_enum("entry_type", db.LEDGER_ENTRY_TYPE)
    cycle_id = shapes.q_str("settlement_cycle_id")
    movement_id = shapes.q_str("movement_id")
    repair_bill_id = shapes.q_str("repair_bill_id")
    reclaim_claim_id = shapes.q_str("reclaim_claim_id")
    dispute_id = shapes.q_str("dispute_id")
    debit_road_id = shapes.q_str("debit_road_id")
    credit_road_id = shapes.q_str("credit_road_id")
    at_from = shapes.q_dt("effective_at_from")
    at_to = shapes.q_dt("effective_at_to")

    rows = list(db.ledger.values())
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if cycle_id is not None:
        rows = [r for r in rows if r["settlement_cycle_id"] == cycle_id]
    if movement_id is not None:
        rows = [r for r in rows if r["movement_id"] == movement_id]
    if repair_bill_id is not None:
        rows = [r for r in rows if r["repair_bill_id"] == repair_bill_id]
    if reclaim_claim_id is not None:
        rows = [r for r in rows if r["reclaim_claim_id"] == reclaim_claim_id]
    if dispute_id is not None:
        rows = [r for r in rows if r["dispute_id"] == dispute_id]
    if debit_road_id is not None:
        rows = [r for r in rows if r["debit_road_id"] == debit_road_id]
    if credit_road_id is not None:
        rows = [r for r in rows if r["credit_road_id"] == credit_road_id]
    if at_from is not None:
        rows = [r for r in rows if r["effective_at"] >= at_from]
    if at_to is not None:
        rows = [r for r in rows if r["effective_at"] <= at_to]
    rows.sort(key=lambda r: (r["effective_at"], r["created_at"], r["_seq"]))
    return response.paginate(rows, serialize.ledger_entry)


@bp.get("/car-hire/ledger-entries/<hire_ledger_entry_id>")
@endpoint(
    roles=[db.ROLE_ADMIN, db.ROLE_ACCOUNTANT],
    path_params=[("hire_ledger_entry_id", "ledger_entry")],
)
def read_ledger_entry(entry):
    middleware.party_ledger(entry)
    return response.ok(serialize.ledger_entry(entry))
