"""Shop events, damage assessments and chargebacks."""

from flask import Blueprint

import calc
import envelope
import serializers
import services
import store
import validate
from auth import ALL_ROLES, authenticate, require_owner
from errors import fail

bp = Blueprint("shop", __name__)

EVENT_TYPES = ("PM_SERVICE", "DOT_INSPECTION", "DAMAGE_REPAIR")
ASSESSMENT_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED")
CHARGEBACK_STATUSES = ("PENDING", "DISPUTED", "APPROVED", "WAIVED", "SETTLED", "VOIDED")


# ---------------------------------------------------------------------------
# maintenance events
# ---------------------------------------------------------------------------
@bp.post("/fleet/maintenance-events")
def create_maintenance_event():
    caller = authenticate(["FleetAdmin", "Inspector"])
    payload = validate.body()
    trailer = None
    if validate.present(payload, "trailer_id") and isinstance(payload["trailer_id"], str):
        trailer = services.get_trailer(payload["trailer_id"])

    trailer_id = validate.req_string(payload, "trailer_id")
    event_type = validate.req_enum(payload, "event_type", EVENT_TYPES)
    performed_on = validate.req_date(payload, "performed_on")
    hub_miles_at_event = validate.req_int(payload, "hub_miles_at_event", minimum=0)
    cost_cents = validate.req_int(payload, "cost_cents", minimum=0)
    if event_type == "DOT_INSPECTION":
        passed = validate.req_bool(payload, "passed")
    else:
        passed = validate.opt_bool(payload, "passed")

    previous_status = calc.trailer_service_status(trailer)

    rec = store.new_record(with_common=False)
    rec.update({
        "trailer_id": trailer_id,
        "event_type": event_type,
        "performed_on": performed_on.isoformat(),
        "hub_miles_at_event": hub_miles_at_event,
        "cost_cents": cost_cents,
        "passed": passed,
        "inspector_user_id": caller.user_id,
    })
    store.maintenance_events[rec["id"]] = rec

    ttype = store.trailer_types.get(trailer["trailer_type_id"])
    if event_type == "PM_SERVICE":
        trailer["last_pm_hub_miles"] = hub_miles_at_event
    elif event_type == "DOT_INSPECTION":
        if passed:
            trailer["last_dot_inspection_date"] = performed_on.isoformat()
            trailer["dot_expires_on"] = calc.compute_dot_expires_on(performed_on.isoformat(), ttype)
            trailer["last_dot_passed"] = True
        else:
            trailer["last_dot_passed"] = False
    else:
        trailer["last_damage_repair_at"] = rec["created_at"]
        trailer["_last_damage_repair_seq"] = rec["_seq"]
    store.touch(trailer)

    services.apply_service_status_cascades(trailer, previous_status)
    return envelope.created(serializers.maintenance_event(rec))


@bp.get("/fleet/maintenance-events/<maintenance_event_id>")
def read_maintenance_event(maintenance_event_id):
    authenticate(["FleetAdmin", "BranchManager", "Inspector"])
    return envelope.ok(serializers.maintenance_event(
        services.get_maintenance_event(maintenance_event_id)))


@bp.get("/fleet/maintenance-events")
def list_maintenance_events():
    authenticate(["FleetAdmin", "BranchManager", "Inspector"])
    limit, offset = validate.pagination()
    trailer_id = validate.query("trailer_id")
    event_type = validate.query_enum("event_type", EVENT_TYPES)
    rows = []
    for e in store.maintenance_events.values():
        if trailer_id is not None and e["trailer_id"] != trailer_id:
            continue
        if event_type is not None and e["event_type"] != event_type:
            continue
        rows.append(e)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.maintenance_event(r) for r in page], limit, offset, len(rows))


# ---------------------------------------------------------------------------
# damage assessments
# ---------------------------------------------------------------------------
@bp.get("/fleet/damage-assessments/<damage_assessment_id>")
def read_assessment(damage_assessment_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.damage_assessment(services.get_assessment(damage_assessment_id)))


@bp.get("/fleet/damage-assessments")
def list_assessments():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    unit_id = validate.query("agreement_unit_id")
    trailer_id = validate.query("trailer_id")
    supersedes = validate.query("supersedes_assessment_id")
    status = validate.query_enum("status", ASSESSMENT_STATUSES)
    rows = []
    for a in store.damage_assessments.values():
        if unit_id is not None and a["agreement_unit_id"] != unit_id:
            continue
        if trailer_id is not None and a["trailer_id"] != trailer_id:
            continue
        if supersedes is not None and a.get("supersedes_assessment_id") != supersedes:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.damage_assessment(r) for r in page], limit, offset, len(rows))


@bp.post("/fleet/damage-assessments/<damage_assessment_id>/submit")
def submit_assessment(damage_assessment_id):
    authenticate(["Inspector"])
    assessment = services.get_assessment(damage_assessment_id)
    validate.body()

    if assessment["status"] != "DRAFT":
        fail("ERR_ASSESSMENT_NOT_DRAFT", "Assessment is not in DRAFT")

    unit = store.agreement_units.get(assessment["agreement_unit_id"])
    if unit is None or unit["status"] not in ("RETURNED", "SETTLED"):
        fail("ERR_UNIT_NOT_RETURNED", "The assessed unit has not been returned")

    predecessor = None
    if assessment.get("supersedes_assessment_id"):
        predecessor = store.damage_assessments.get(assessment["supersedes_assessment_id"])
        if predecessor is None or predecessor["status"] != "SUBMITTED":
            fail("ERR_ASSESSMENT_SUPERSEDED", "The superseded assessment is not in SUBMITTED")

    agreement = store.agreements.get(unit["agreement_id"])
    customer = store.customers.get(agreement["customer_id"]) if agreement else None
    certificate = None
    if agreement is not None and agreement.get("insurance_certificate_id"):
        candidate = store.certificates.get(agreement["insurance_certificate_id"])
        if candidate is not None and serializers.certificate_status(candidate) == "ACTIVE":
            certificate = candidate

    trailer = store.trailers.get(assessment["trailer_id"])
    previous_status = calc.trailer_service_status(trailer) if trailer else None

    result = calc.damage_liability(assessment["line_items"], customer or {}, certificate)
    assessment["assessed_amount_cents"] = result["assessed_amount_cents"]
    assessment["insured_portion_cents"] = result["insured_portion_cents"]
    assessment["customer_liable_cents"] = result["customer_liable_cents"]
    assessment["admin_fee_cents"] = result["admin_fee_cents"]
    assessment["damage_points"] = result["damage_points"]
    assessment["status"] = "SUBMITTED"
    store.touch(assessment)

    chargeback = store.new_record()
    chargeback.update({
        "damage_assessment_id": assessment["id"],
        "customer_id": agreement["customer_id"] if agreement else None,
        "amount_cents": result["chargeback_amount_cents"],
        "status": "PENDING",
        "approver_user_id": None,
        "dispute_reason": None,
        "waiver_reason": None,
        "paid_amount_cents": None,
    })
    store.chargebacks[chargeback["id"]] = chargeback

    if predecessor is not None:
        predecessor["status"] = "SUPERSEDED"
        store.touch(predecessor)
        for cb in store.chargebacks.values():
            if cb["damage_assessment_id"] == predecessor["id"] and cb["status"] in ("PENDING", "DISPUTED"):
                cb["status"] = "VOIDED"
                store.touch(cb)

    if trailer is not None:
        services.apply_service_status_cascades(trailer, previous_status)

    return envelope.ok(serializers.damage_assessment(assessment))


# ---------------------------------------------------------------------------
# chargebacks
# ---------------------------------------------------------------------------
@bp.get("/fleet/chargebacks/<chargeback_id>")
def read_chargeback(chargeback_id):
    authenticate(ALL_ROLES)
    return envelope.ok(serializers.chargeback(services.get_chargeback(chargeback_id)))


@bp.get("/fleet/chargebacks")
def list_chargebacks():
    authenticate(ALL_ROLES)
    limit, offset = validate.pagination()
    assessment_id = validate.query("damage_assessment_id")
    customer_id = validate.query("customer_id")
    status = validate.query_enum("status", CHARGEBACK_STATUSES)
    rows = []
    for cb in store.chargebacks.values():
        if assessment_id is not None and cb["damage_assessment_id"] != assessment_id:
            continue
        if customer_id is not None and cb["customer_id"] != customer_id:
            continue
        if status is not None and cb["status"] != status:
            continue
        rows.append(cb)
    rows = store.sorted_rows(rows)
    page = validate.paginate(rows, limit, offset)
    return envelope.listing([serializers.chargeback(r) for r in page], limit, offset, len(rows))


def _segregation_guard(caller, chargeback):
    assessment = store.damage_assessments.get(chargeback["damage_assessment_id"])
    if assessment is not None and assessment.get("assessor_user_id") == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "The assessment author may not adjudicate this chargeback")
    return assessment


@bp.post("/fleet/chargebacks/<chargeback_id>/approve")
def approve_chargeback(chargeback_id):
    caller = authenticate(["ChargebackApprover"])
    chargeback = services.get_chargeback(chargeback_id)
    validate.body()
    assessment = _segregation_guard(caller, chargeback)

    if chargeback["status"] != "PENDING":
        fail("ERR_CHARGEBACK_NOT_PENDING", "Chargeback is not PENDING")

    chargeback["status"] = "APPROVED"
    chargeback["approver_user_id"] = caller.user_id
    store.touch(chargeback)
    if assessment is not None and assessment["status"] == "SUBMITTED":
        assessment["status"] = "APPROVED"
        store.touch(assessment)
    return envelope.ok(serializers.chargeback(chargeback))


@bp.post("/fleet/chargebacks/<chargeback_id>/dispute")
def dispute_chargeback(chargeback_id):
    caller = authenticate(["Customer"])
    chargeback = services.get_chargeback(chargeback_id)
    payload = validate.body()
    reason = validate.req_string(payload, "dispute_reason")
    require_owner(caller, chargeback["customer_id"])

    if chargeback["status"] != "PENDING":
        fail("ERR_CHARGEBACK_NOT_PENDING", "Chargeback is not PENDING")

    chargeback["status"] = "DISPUTED"
    chargeback["dispute_reason"] = reason
    store.touch(chargeback)
    return envelope.ok(serializers.chargeback(chargeback))


@bp.post("/fleet/chargebacks/<chargeback_id>/reopen")
def reopen_chargeback(chargeback_id):
    authenticate(["ChargebackApprover"])
    chargeback = services.get_chargeback(chargeback_id)
    validate.body()

    if chargeback["status"] != "DISPUTED":
        fail("ERR_CHARGEBACK_NOT_DISPUTED", "Chargeback is not DISPUTED")

    chargeback["status"] = "PENDING"
    chargeback["dispute_reason"] = None
    store.touch(chargeback)
    return envelope.ok(serializers.chargeback(chargeback))


@bp.post("/fleet/chargebacks/<chargeback_id>/waive")
def waive_chargeback(chargeback_id):
    caller = authenticate(["ChargebackApprover"])
    chargeback = services.get_chargeback(chargeback_id)
    payload = validate.body()
    reason = validate.req_string(payload, "waiver_reason")
    assessment = _segregation_guard(caller, chargeback)

    if chargeback["status"] not in ("PENDING", "DISPUTED"):
        fail("ERR_CHARGEBACK_TERMINAL", "Chargeback can no longer be waived")

    chargeback["status"] = "WAIVED"
    chargeback["approver_user_id"] = caller.user_id
    chargeback["waiver_reason"] = reason
    store.touch(chargeback)

    if assessment is not None and assessment["status"] == "SUBMITTED":
        assessment["status"] = "REJECTED"
        store.touch(assessment)
    return envelope.ok(serializers.chargeback(chargeback))


@bp.post("/fleet/chargebacks/<chargeback_id>/record-payment")
def record_payment(chargeback_id):
    authenticate(["FleetAdmin"])
    chargeback = services.get_chargeback(chargeback_id)
    payload = validate.body()
    paid = validate.req_int(payload, "paid_amount_cents", minimum=0)

    if chargeback["status"] != "APPROVED":
        fail("ERR_CHARGEBACK_NOT_APPROVED", "Chargeback is not APPROVED")
    if paid != chargeback["amount_cents"]:
        fail("ERR_INVALID_REQUEST", "paid_amount_cents must equal the chargeback amount")

    chargeback["status"] = "SETTLED"
    chargeback["paid_amount_cents"] = paid
    store.touch(chargeback)
    return envelope.ok(serializers.chargeback(chargeback))
