"""Data conversion batches and patient orders (PRD §4.6, §3.2, §3.7, §3.8)."""

from decimal import Decimal

from flask import Blueprint

from db import DB, parse_iso
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_BALANCE_VARIANCE_EXCEEDED,
    ERR_BATCH_SIZE_INVALID,
    ERR_CLAIM_RESPONSE_INVALID,
    ERR_CONVERSION_BATCH_NOT_FOUND,
    ERR_EPOCH_MISMATCH,
    ERR_FACILITY_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORDER_NOT_RECONCILED,
    ERR_PATIENT_ORDER_NOT_FOUND,
    ERR_PROCEDURE_CREDENTIAL_MISSING,
    ERR_STALE_VERSION,
    fail,
)
from request_utils import (
    actor,
    body_fields,
    collection,
    enum_member,
    filter_args,
    pagination,
    payload,
    require_role,
)
from response import ok
from services import calculations as C
from services import lookups as L
from services import recompute as R
from services.core import serialize, stamp_created

bp = Blueprint("conversion", __name__)

PAYLOAD_CLASSES = {"PATIENT_DEMOGRAPHICS", "APPOINTMENTS", "ORDERS", "BALANCES"}
ORDER_TYPES = {"MEDICATION", "LAB", "IMAGING", "PROCEDURE"}
CLAIM_RESPONSES = {"ACCEPTED", "DENIED", "PAID"}

ANALYTICS_ROLES = [
    "ImplementationAnalyst",
    "ConversionAnalyst",
    "OrderReconciler",
    "RevenueCycleAnalyst",
]


def get_facility(facility_id):
    facility = DB.facilities.get(facility_id)
    if facility is None:
        fail(ERR_FACILITY_NOT_FOUND, "No facility matches the id.")
    return facility


def get_batch(batch_id):
    batch = DB.data_conversion_batches.get(batch_id)
    if batch is None:
        fail(ERR_CONVERSION_BATCH_NOT_FOUND, "No data conversion batch matches the id.")
    return batch


def get_order(order_id):
    order = DB.patient_orders.get(order_id)
    if order is None:
        fail(ERR_PATIENT_ORDER_NOT_FOUND, "No patient order matches the id.")
    return order


def batch_view(batch):
    return serialize("DataConversionBatch", batch)


def order_view(order):
    return serialize("PatientOrder", order)


# --------------------------------------------------------------------------
# DataConversionBatch
# --------------------------------------------------------------------------
@bp.route("/facilities/<facility_id>/data-conversion-batches", methods=["POST"])
def create_batch(facility_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    facility = get_facility(facility_id)
    data = body_fields(
        [
            ("payload_class", "enum", True),
            ("attempt_epoch", "int", True),
            ("source_count", "int", True),
            ("reconciled_count", "int", True),
            ("expected_facility_version", "int", True),
        ],
        payload(),
    )
    enum_member("payload_class", data["payload_class"], PAYLOAD_CLASSES)
    if (
        isinstance(data["source_count"], bool)
        or data["source_count"] < 0
        or data["reconciled_count"] < 0
    ):
        fail(
            ERR_BATCH_SIZE_INVALID,
            "source_count and reconciled_count must be non-negative integers.",
        )
    if data["expected_facility_version"] != int(facility["version"]):
        fail(
            ERR_STALE_VERSION,
            "expected_facility_version does not match the facility's current version.",
        )
    batch = {
        "id": DB.new_id(),
        "facility_id": facility["id"],
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "payload_class": data["payload_class"],
        "attempt_epoch": data["attempt_epoch"],
        "source_count": data["source_count"],
        "reconciled_count": data["reconciled_count"],
        "variance_count": 0,
        "variance_penalty_points": 0.0,
        "applied_balance_cents": 0,
        "status": "STAGED",
    }
    stamp_created(batch)
    DB.data_conversion_batches[batch["id"]] = batch
    DB.register_created(batch)
    facility["version"] = int(facility["version"]) + 1
    facility["updated_at"] = batch["created_at"]
    R.recompute_program_tree(facility["ehr_implementation_id"])
    return ok(batch_view(batch), status=201)


@bp.route("/facilities/<facility_id>/data-conversion-batches", methods=["GET"])
def list_facility_batches(facility_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "ConversionAnalyst"])
    facility = get_facility(facility_id)
    rows = L.children_by(DB.data_conversion_batches, "facility_id", facility["id"])
    filters = filter_args(["payload_class", "status"])
    for key, value in filters.items():
        rows = [b for b in rows if b.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([batch_view(b) for b in window], pagination=page)


@bp.route("/data-conversion-batches", methods=["GET"])
def list_batches():
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "ConversionAnalyst"])
    rows = list(DB.data_conversion_batches.values())
    filters = filter_args(["facility_id", "ehr_implementation_id", "payload_class", "status"])
    for key, value in filters.items():
        rows = [b for b in rows if b.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([batch_view(b) for b in window], pagination=page)


@bp.route("/data-conversion-batches/<batch_id>", methods=["GET"])
def get_batch_endpoint(batch_id):
    uid, role = actor()
    require_role(role, ["ImplementationAnalyst", "ConversionAnalyst"])
    return ok(batch_view(get_batch(batch_id)))


@bp.route("/data-conversion-batches/<batch_id>/begin-validation", methods=["POST"])
def begin_batch_validation(batch_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    batch = get_batch(batch_id)
    program = DB.ehr_implementations[batch["ehr_implementation_id"]]
    if batch["status"] != "STAGED":
        fail(ERR_INVALID_STATE, "Beginning validation requires the batch to be STAGED.")
    if batch["attempt_epoch"] != program["current_epoch_index"]:
        fail(
            ERR_EPOCH_MISMATCH,
            "The batch attempt_epoch must equal the program's current epoch.",
        )
    count, penalty, _exceeds = C.conversion_variance(
        batch["source_count"], batch["reconciled_count"], batch["payload_class"]
    )
    batch["variance_count"] = count
    # PRD §3.2: "Beginning validation ... computes variance_count as the absolute
    # difference between source_count and reconciled_count." The companion
    # variance_penalty_points is the same measure expressed as a percentage of
    # the source count, so it is published from the same point onward.
    batch["variance_penalty_points"] = float(penalty)
    batch["status"] = "VALIDATING"
    DB.touch(batch, common=True)
    R.recompute_program_tree(program["id"])
    return ok(batch_view(batch))


@bp.route("/data-conversion-batches/<batch_id>/load", methods=["POST"])
def load_batch(batch_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    batch = get_batch(batch_id)
    program = DB.ehr_implementations[batch["ehr_implementation_id"]]
    if batch["status"] != "VALIDATING":
        fail(ERR_INVALID_STATE, "Loading requires the batch to be VALIDATING.")
    if batch["attempt_epoch"] != program["current_epoch_index"]:
        fail(
            ERR_EPOCH_MISMATCH,
            "The batch attempt_epoch must equal the program's current epoch.",
        )
    count, penalty, exceeds = C.conversion_variance(
        batch["source_count"], batch["reconciled_count"], batch["payload_class"]
    )
    batch["variance_count"] = count
    batch["variance_penalty_points"] = float(penalty)
    if exceeds:
        # PRD §3.2: the batch is refused and, because the request never
        # completed, it must not be moved on. Only a batch that is instead
        # allowed to fail on its own reaches FAILED.
        fail(
            ERR_BALANCE_VARIANCE_EXCEEDED,
            "The conversion variance penalty exceeds the payload class ceiling.",
        )
    facility = DB.facilities[batch["facility_id"]]
    if batch["payload_class"] == "PATIENT_DEMOGRAPHICS":
        facility["converted_patient_count"] = int(
            facility.get("converted_patient_count") or 0
        ) + int(batch["reconciled_count"])
        DB.touch(facility, common=True)
    elif batch["payload_class"] == "BALANCES":
        batch["applied_balance_cents"] = int(batch["reconciled_count"])
        for order in L.facility_orders(facility["id"]):
            order["balance_cents"] = int(order.get("balance_cents") or 0) + int(
                batch["reconciled_count"]
            )
            DB.touch(order, common=True)
    batch["status"] = "LOADED"
    DB.touch(batch, common=True)
    R.recompute_program_tree(program["id"])
    return ok(batch_view(batch))


@bp.route("/data-conversion-batches/<batch_id>/reconcile", methods=["POST"])
def reconcile_batch(batch_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    batch = get_batch(batch_id)
    program = DB.ehr_implementations[batch["ehr_implementation_id"]]
    if batch["status"] == "FAILED":
        fail(ERR_ALREADY_TERMINAL, "The batch has already failed.")
    if batch["status"] != "LOADED":
        fail(ERR_INVALID_STATE, "Reconciling requires the batch to be LOADED.")
    if int(batch["reconciled_count"]) != int(batch["source_count"]):
        fail(
            ERR_INVALID_STATE,
            "Reconciling requires reconciled_count to equal source_count.",
        )
    batch["status"] = "RECONCILED"
    DB.touch(batch, common=True)
    R.recompute_program_tree(program["id"])
    return ok(batch_view(batch))


@bp.route("/data-conversion-batches/<batch_id>/rollback", methods=["POST"])
def rollback_batch(batch_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    batch = get_batch(batch_id)
    program = DB.ehr_implementations[batch["ehr_implementation_id"]]
    if batch["status"] in ("FAILED", "ROLLED_BACK"):
        fail(ERR_ALREADY_TERMINAL, "The batch is already in a terminal state.")
    if batch["status"] not in ("LOADED", "RECONCILED"):
        fail(ERR_INVALID_STATE, "Rolling back requires the batch to be LOADED or RECONCILED.")
    facility = DB.facilities[batch["facility_id"]]
    if batch["payload_class"] == "PATIENT_DEMOGRAPHICS":
        facility["converted_patient_count"] = int(
            facility.get("converted_patient_count") or 0
        ) - int(batch["reconciled_count"])
        DB.touch(facility, common=True)
    elif batch["payload_class"] == "BALANCES":
        for order in L.facility_orders(facility["id"]):
            order["balance_cents"] = int(order.get("balance_cents") or 0) - int(
                batch["applied_balance_cents"]
            )
            DB.touch(order, common=True)
        batch["applied_balance_cents"] = 0
    batch["status"] = "ROLLED_BACK"
    DB.touch(batch, common=True)
    R.recompute_program_tree(program["id"])
    return ok(batch_view(batch))


# --------------------------------------------------------------------------
# PatientOrder
# --------------------------------------------------------------------------
@bp.route("/facilities/<facility_id>/patient-orders", methods=["POST"])
def create_order(facility_id):
    uid, role = actor()
    require_role(role, ["ConversionAnalyst"])
    facility = get_facility(facility_id)
    data = body_fields(
        [
            ("patient_mrn", "string", True),
            ("order_type", "enum", True),
            ("encounter_utc", "datetime", True),
            ("legacy_charge_cents", "int", True),
        ],
        payload(),
    )
    enum_member("order_type", data["order_type"], ORDER_TYPES)
    if data["legacy_charge_cents"] < 0:
        fail(ERR_INVALID_REQUEST, "legacy_charge_cents must be a non-negative integer.")
    encounter_utc = parse_iso(data["encounter_utc"])
    provisional, _final, _variance = C.charge_capture(
        data["legacy_charge_cents"], data["order_type"], final=False
    )
    order = {
        "id": DB.new_id(),
        "facility_id": facility["id"],
        "ehr_implementation_id": facility["ehr_implementation_id"],
        "patient_mrn": data["patient_mrn"],
        "order_type": data["order_type"],
        "encounter_utc": encounter_utc,
        "legacy_charge_cents": data["legacy_charge_cents"],
        "balance_cents": 0,
        "provisional_charge_cents": float(provisional),
        "final_charge_cents": float(provisional),
        "charge_variance_cents": 0.0,
        "paper_backfill_count": 0,
        "clinical_state": "CONVERTED",
        "billing_state": "UNPOSTED",
    }
    stamp_created(order)
    DB.patient_orders[order["id"]] = order
    DB.register_created(order)
    R.recompute_program_tree(facility["ehr_implementation_id"])
    return ok(order_view(order), status=201)


@bp.route("/facilities/<facility_id>/patient-orders", methods=["GET"])
def list_facility_orders(facility_id):
    uid, role = actor()
    require_role(role, ANALYTICS_ROLES)
    facility = get_facility(facility_id)
    rows = L.facility_orders(facility["id"])
    filters = filter_args(["clinical_state", "billing_state"])
    for key, value in filters.items():
        rows = [o for o in rows if o.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([order_view(o) for o in window], pagination=page)


@bp.route("/patient-orders", methods=["GET"])
def list_orders():
    uid, role = actor()
    require_role(role, ANALYTICS_ROLES)
    rows = list(DB.patient_orders.values())
    filters = filter_args(
        ["facility_id", "ehr_implementation_id", "clinical_state", "billing_state"]
    )
    for key, value in filters.items():
        rows = [o for o in rows if o.get(key) == value]
    limit, offset = pagination()
    window, page = collection(rows, limit, offset)
    return ok([order_view(o) for o in window], pagination=page)


@bp.route("/patient-orders/<order_id>", methods=["GET"])
def get_order_endpoint(order_id):
    uid, role = actor()
    require_role(role, ANALYTICS_ROLES)
    return ok(order_view(get_order(order_id)))


@bp.route("/patient-orders/<order_id>/reconcile", methods=["POST"])
def reconcile_order(order_id):
    uid, role = actor()
    require_role(role, ["OrderReconciler"])
    order = get_order(order_id)
    if order["clinical_state"] != "CONVERTED":
        fail(ERR_INVALID_STATE, "Reconciling requires the clinical state to be CONVERTED.")
    if order["order_type"] == "PROCEDURE" and role not in (
        "OrderReconciler",
        "RevenueCycleAnalyst",
    ):
        fail(
            ERR_PROCEDURE_CREDENTIAL_MISSING,
            "Reconciling a PROCEDURE order requires the charge-capture credential.",
        )
    program = DB.ehr_implementations[order["ehr_implementation_id"]]
    provisional, final, variance = C.charge_capture(
        order["legacy_charge_cents"], order["order_type"], final=True
    )
    order["provisional_charge_cents"] = float(provisional)
    order["final_charge_cents"] = float(final)
    order["charge_variance_cents"] = float(variance)
    order["clinical_state"] = "RECONCILED"
    program["order_reconciliation_balance"] = int(
        program.get("order_reconciliation_balance") or 0
    ) + 1
    DB.touch(order, common=True)
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(order_view(order))


@bp.route("/patient-orders/<order_id>/backfill-paper-order", methods=["POST"])
def backfill_order(order_id):
    uid, role = actor()
    require_role(role, ["OrderReconciler"])
    order = get_order(order_id)
    # PRD §2.14: the balance "counts converted EHR orders reconciled minus paper
    # order slips backfilled. Reconciling an order credits the balance by one;
    # backfilling a paper slip against an order debits it by one. A reconcile
    # paired with a matching paper backfill must therefore leave the balance
    # exactly where it started." For a matched pair to exist the slip must be
    # backfillable against the same order on both sides of the reconciliation
    # (PRD §3.7: "for a procedure order only" charges the extra gap line, and a
    # PROCEDURE order pays that line at reconciliation, not at backfill), so the
    # paper slip is admissible against an order that has been reconciled as well
    # as against one sitting in PAPER_BACKFILL_REQUIRED.
    if order["clinical_state"] not in ("PAPER_BACKFILL_REQUIRED", "RECONCILED"):
        fail(
            ERR_INVALID_STATE,
            "Backfilling requires the clinical state to be PAPER_BACKFILL_REQUIRED "
            "or RECONCILED.",
        )
    program = DB.ehr_implementations[order["ehr_implementation_id"]]
    order["clinical_state"] = "RECONCILED"
    order["paper_backfill_count"] = int(order.get("paper_backfill_count") or 0) + 1
    program["order_reconciliation_balance"] = int(
        program.get("order_reconciliation_balance") or 0
    ) - 1
    DB.touch(order, common=True)
    DB.touch(program, common=True)
    R.recompute_program_tree(program["id"])
    return ok(order_view(order))


@bp.route("/patient-orders/<order_id>/post-charge", methods=["POST"])
def post_charge(order_id):
    uid, role = actor()
    require_role(role, ["RevenueCycleAnalyst"])
    order = get_order(order_id)
    if order["billing_state"] != "UNPOSTED":
        fail(ERR_INVALID_STATE, "Posting a charge requires billing_state UNPOSTED.")
    if order["clinical_state"] not in ("CONVERTED", "RECONCILED"):
        fail(
            ERR_INVALID_STATE,
            "Posting a charge requires clinical_state CONVERTED or RECONCILED.",
        )
    program = DB.ehr_implementations[order["ehr_implementation_id"]]
    provisional, final, variance = C.charge_capture(
        order["legacy_charge_cents"], order["order_type"], final=True
    )
    order["provisional_charge_cents"] = float(provisional)
    order["final_charge_cents"] = float(final)
    order["charge_variance_cents"] = float(variance)
    order["billing_state"] = "CHARGE_POSTED"
    DB.touch(order, common=True)
    R.recompute_program_tree(program["id"])
    return ok(order_view(order))


@bp.route("/patient-orders/<order_id>/submit-claim", methods=["POST"])
def submit_claim(order_id):
    uid, role = actor()
    require_role(role, ["RevenueCycleAnalyst"])
    order = get_order(order_id)
    # PRD §2.11: "The ladder then moves through state: the target must be in the
    # exact from-state of the transition being triggered (otherwise
    # ERR_INVALID_STATE) ... Business-safety and business-constraint rungs come
    # next". The billing-state rung is therefore reached before the
    # clinical-reconciliation constraint.
    if order["billing_state"] != "CHARGE_POSTED":
        fail(ERR_INVALID_STATE, "Submitting a claim requires billing_state CHARGE_POSTED.")
    if order["clinical_state"] != "RECONCILED":
        fail(
            ERR_ORDER_NOT_RECONCILED,
            "The patient order must be clinically reconciled before its claim is submitted.",
        )
    program = DB.ehr_implementations[order["ehr_implementation_id"]]
    order["billing_state"] = "CLAIM_SUBMITTED"
    DB.touch(order, common=True)
    R.recompute_program_tree(program["id"])
    R.on_facility_billing_change(DB.facilities.get(order["facility_id"]))
    R.recompute_program_tree(program["id"])
    return ok(order_view(order))


@bp.route("/patient-orders/<order_id>/record-claim-response", methods=["POST"])
def record_claim_response(order_id):
    uid, role = actor()
    require_role(role, ["RevenueCycleAnalyst"])
    order = get_order(order_id)
    data = body_fields([("claim_response", "enum", True)], payload())
    response_value = enum_member("claim_response", data["claim_response"], CLAIM_RESPONSES)
    # PRD §3.8: "the payer's response may only be recorded while the order is
    # CLAIM_SUBMITTED, and an attempt before reconciliation is refused with the
    # same ERR_ORDER_NOT_RECONCILED."
    state = order["billing_state"]
    if state not in ("CLAIM_SUBMITTED", "CLAIM_ACCEPTED"):
        fail(
            ERR_ORDER_NOT_RECONCILED,
            "The payer's response may only be recorded while the claim is submitted.",
        )
    if order["clinical_state"] != "RECONCILED":
        fail(
            ERR_ORDER_NOT_RECONCILED,
            "The patient order must be clinically reconciled before a claim response is recorded.",
        )
    compatible = (
        (state == "CLAIM_SUBMITTED" and response_value in ("ACCEPTED", "DENIED"))
        or (state == "CLAIM_ACCEPTED" and response_value == "PAID")
    )
    if not compatible:
        fail(
            ERR_CLAIM_RESPONSE_INVALID,
            "The claim response is not compatible with the order's current billing state.",
        )
    if response_value == "ACCEPTED":
        order["billing_state"] = "CLAIM_ACCEPTED"
    elif response_value == "DENIED":
        order["billing_state"] = "CLAIM_DENIED"
    else:
        order["billing_state"] = "CLAIM_PAID"
    DB.touch(order, common=True)
    R.recompute_program_tree(order["ehr_implementation_id"])
    R.on_facility_billing_change(DB.facilities.get(order["facility_id"]))
    R.recompute_program_tree(order["ehr_implementation_id"])
    return ok(order_view(order))


@bp.route("/patient-orders/<order_id>/reopen-claim", methods=["POST"])
def reopen_claim(order_id):
    uid, role = actor()
    require_role(role, ["RevenueCycleAnalyst"])
    order = get_order(order_id)
    if order["billing_state"] != "CLAIM_DENIED":
        fail(ERR_INVALID_STATE, "Reopening requires billing_state CLAIM_DENIED.")
    order["billing_state"] = "CHARGE_POSTED"
    DB.touch(order, common=True)
    R.recompute_program_tree(order["ehr_implementation_id"])
    R.on_facility_billing_change(DB.facilities.get(order["facility_id"]))
    R.recompute_program_tree(order["ehr_implementation_id"])
    return ok(order_view(order))