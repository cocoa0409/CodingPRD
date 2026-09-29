"""Package induction, scan capture, movement outcomes and accessorials
(PRD 3.3, 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import domain
import pricing
import serializers as ser
import validators as v
from auth import (ROLE_BILLING_OPS, ROLE_CARRIER_OPS, ROLE_REVENUE_AUDITOR,
                  ROLE_SHIPPER_USER, authorize, caller_id,
                  enforce_named_shipper, enforce_shipper_scope, is_shipper_user)
from errors import ApiError
from response import pagination_params, paginate, success
from store import (date_of, day_string, db, iso, new_record, now, parse_instant,
                   sorted_records, touch)

bp = Blueprint("shipments", __name__)

MEASUREMENT_STATUSES = ("PENDING_SCAN", "SCANNED", "TOLERANCE_FLAGGED", "VERIFIED")
MOVEMENT_STATUSES = ("IN_TRANSIT", "DELIVERED", "UNDELIVERABLE", "REFUSED")
BILLING_STATUSES = ("UNBILLED", "BILLED", "ADJUSTED")
SCAN_SOURCES = ("AUTOMATED_DWS", "MANUAL_REWEIGH")
EXCEPTION_KINDS = ("UNDELIVERABLE", "REFUSED", "ADDRESS_CORRECTED")
CHARGE_STATUSES = ("ASSESSED", "WAIVED", "REVERSED")

MAX_DIMENSION_IN = 200
MAX_WEIGHT_LBS = 500


# --------------------------------------------------------------------------
# induction
# --------------------------------------------------------------------------

@bp.route("/shipments", methods=["POST"])
@authorize(ROLE_CARRIER_OPS)
def create_shipment():
    body = v.get_body()

    shipper = domain.shipper_or_404(v.peek_str(body, "shipper_id"))
    service_level = domain.service_level_or_404(v.peek_str(body, "service_level_id"))

    tracking_number = v.req_string(body, "tracking_number", min_len=8, max_len=32)
    zone = v.req_int(body, "zone", minimum=2, maximum=8)
    residential_declared = v.req_bool(body, "residential_declared")
    length_in = v.req_measure(body, "declared_length_in", MAX_DIMENSION_IN)
    width_in = v.req_measure(body, "declared_width_in", MAX_DIMENSION_IN)
    height_in = v.req_measure(body, "declared_height_in", MAX_DIMENSION_IN)
    weight_lbs = v.req_measure(body, "declared_weight_lbs", MAX_WEIGHT_LBS)
    delivery_area_class = v.opt_enum(body, "delivery_area_class",
                                    calc.DELIVERY_AREA_CLASSES, "NONE")
    non_conveyable_declared = v.opt_bool(body, "non_conveyable_declared", False)

    for existing in db.shipments.values():
        if existing["tracking_number"] == tracking_number:
            raise ApiError("ERR_DUPLICATE_KEY", "tracking_number is already inducted.")

    if shipper["status"] != "ACTIVE":
        raise ApiError("ERR_SHIPPER_SUSPENDED",
                       "The shipper account is SUSPENDED and admits no new packages.")

    picked_up_at = now()
    pickup_date = day_string(date_of(picked_up_at))
    contract = domain.select_contract(shipper["id"], pickup_date)

    guarantee_deadline = None
    if service_level["guaranteed"]:
        guarantee_deadline = iso(picked_up_at
                                 + timedelta(hours=service_level["guarantee_hours"]))

    record = new_record()
    record.update({
        "shipper_id": shipper["id"],
        "service_level_id": service_level["id"],
        "contract_id": contract["id"],
        "tracking_number": tracking_number,
        "zone": zone,
        "delivery_area_class": delivery_area_class,
        "residential_declared": residential_declared,
        "non_conveyable_declared": non_conveyable_declared,
        "declared_length_in": length_in,
        "declared_width_in": width_in,
        "declared_height_in": height_in,
        "declared_weight_lbs": weight_lbs,
        "picked_up_at": iso(picked_up_at),
        "pickup_date": pickup_date,
        "divisor_used": contract["dim_divisor"],
        "declared_cube_in3": 0,
        "preliminary_dim_weight_lbs": 0,
        "preliminary_billable_weight_lbs": 0,
        "preliminary_basis": "ACTUAL",
        "scanned_cube_in3": None,
        "final_dim_weight_lbs": None,
        "final_billable_weight_lbs": None,
        "final_basis": None,
        "billable_weight_lbs": 0,
        "dim_variance_pct": None,
        "weight_variance_lbs": None,
        "oversize_flag": False,
        "additional_handling_flag": False,
        "measurement_status": "PENDING_SCAN",
        "movement_status": "IN_TRANSIT",
        "billing_status": "UNBILLED",
        "delivered_at": None,
        "guarantee_deadline_utc": guarantee_deadline,
    })
    db.shipments[record["id"]] = record

    domain.apply_preliminary_measurement(record)
    domain.reassess_auto_accessorials(record, contract)

    return success(ser.shipment(record), 201)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def read_shipment(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)
    enforce_shipper_scope(shipment["shipper_id"])
    return success(ser.shipment(shipment))


@bp.route("/shipments", methods=["GET"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def list_shipments():
    shipper_id = request.args.get("shipper_id")
    enforce_named_shipper(shipper_id)
    limit, offset = pagination_params()

    rows = sorted_records(list(db.shipments.values()))
    if is_shipper_user():
        rows = [r for r in rows if r["shipper_id"] == caller_id()]
    if shipper_id is not None:
        rows = [r for r in rows if r["shipper_id"] == shipper_id]
    for key in ("service_level_id", "contract_id", "measurement_status",
                "movement_status", "billing_status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, ser.shipment, limit, offset)


@bp.route("/shipments/<shipment_id>/billing-preview", methods=["GET"])
@authorize(ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR)
def billing_preview(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)
    return success(pricing.price_shipment(shipment))


# --------------------------------------------------------------------------
# scan capture
# --------------------------------------------------------------------------

@bp.route("/shipments/<shipment_id>/scans", methods=["POST"])
@authorize(ROLE_CARRIER_OPS)
def create_scan(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)

    body = v.get_body()
    scan_source = v.req_enum(body, "scan_source", SCAN_SOURCES)
    length_in = v.req_measure(body, "scanned_length_in", MAX_DIMENSION_IN)
    width_in = v.req_measure(body, "scanned_width_in", MAX_DIMENSION_IN)
    height_in = v.req_measure(body, "scanned_height_in", MAX_DIMENSION_IN)
    weight_lbs = v.req_measure(body, "scanned_weight_lbs", MAX_WEIGHT_LBS)
    expected_version = v.req_int(body, "expected_shipment_version")
    non_conveyable_observed = v.opt_bool(body, "non_conveyable_observed", False)

    if expected_version != shipment["version"]:
        raise ApiError("ERR_STALE_SHIPMENT_VERSION",
                       "expected_shipment_version does not match the shipment's "
                       "current version.")

    if shipment["measurement_status"] == "VERIFIED":
        raise ApiError("ERR_MEASUREMENT_FINAL",
                       "A VERIFIED measurement is final and admits no further scan.")

    cube = calc.cube_of(length_in, width_in, height_in)
    verdict = calc.tolerance_verdict(cube, shipment["declared_cube_in3"],
                                     weight_lbs, shipment["declared_weight_lbs"])

    scan = new_record(versioned=False)
    scan.update({
        "shipment_id": shipment["id"],
        "scan_source": scan_source,
        "scanned_length_in": length_in,
        "scanned_width_in": width_in,
        "scanned_height_in": height_in,
        "scanned_weight_lbs": weight_lbs,
        "non_conveyable_observed": non_conveyable_observed,
        "scanned_cube_in3": cube,
        "dim_variance_pct": verdict["dim_variance_pct"],
        "weight_variance_lbs": verdict["weight_variance_lbs"],
        "tolerance_status": verdict["tolerance_status"],
        "captured_at": iso(now()),
    })
    db.dimension_scans[scan["id"]] = scan

    governing = domain.governing_scan(shipment["id"])
    domain.apply_final_measurement(shipment, governing)

    if scan_source == "MANUAL_REWEIGH":
        shipment["measurement_status"] = "VERIFIED"
    elif verdict["tolerance_status"] == "EXCEEDS_TOLERANCE":
        shipment["measurement_status"] = "TOLERANCE_FLAGGED"
    else:
        shipment["measurement_status"] = "SCANNED"

    domain.reassess_auto_accessorials(shipment, domain.contract_of_shipment(shipment))
    touch(shipment)

    trigger = (pricing.TRIGGER_SCAN_AUTOMATED if scan_source == "AUTOMATED_DWS"
               else pricing.TRIGGER_SCAN_MANUAL)
    pricing.reconcile(shipment, trigger)

    return success(ser.dimension_scan(scan), 201)


@bp.route("/shipments/<shipment_id>/scans", methods=["GET"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def list_scans(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)
    enforce_shipper_scope(shipment["shipper_id"])
    limit, offset = pagination_params()
    rows = domain.scans_of_shipment(shipment["id"])
    return paginate(rows, ser.dimension_scan, limit, offset)


# --------------------------------------------------------------------------
# movement outcomes
# --------------------------------------------------------------------------

@bp.route("/shipments/<shipment_id>/deliver", methods=["POST"])
@authorize(ROLE_CARRIER_OPS)
def deliver_shipment(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)
    if shipment["movement_status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT",
                       "The shipment has already left IN_TRANSIT.")
    shipment["movement_status"] = "DELIVERED"
    shipment["delivered_at"] = iso(now())
    touch(shipment)
    return success(ser.shipment(shipment))


@bp.route("/shipments/<shipment_id>/exceptions", methods=["POST"])
@authorize(ROLE_CARRIER_OPS)
def record_exception(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)

    body = v.get_body()
    kind = v.req_enum(body, "kind", EXCEPTION_KINDS)
    reason = v.opt_string(body, "reason")

    if shipment["movement_status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_NOT_IN_TRANSIT",
                       "The shipment has already left IN_TRANSIT.")

    pricing.assert_not_frozen(shipment)

    contract = domain.contract_of_shipment(shipment)

    def charge(code, basis):
        amount = calc.resolve_accessorial_rate(contract, code,
                                               shipment["delivery_area_class"])
        domain.create_charge(shipment, code, "AUTO", amount, basis, reason=reason)

    if kind == "UNDELIVERABLE":
        shipment["movement_status"] = "UNDELIVERABLE"
        charge("RETURN_UNDELIVERABLE", "exception_kind=UNDELIVERABLE")
    elif kind == "REFUSED":
        shipment["movement_status"] = "REFUSED"
        charge("REFUSAL", "exception_kind=REFUSED")
        charge("RETURN_UNDELIVERABLE", "exception_kind=REFUSED")
    else:
        charge("ADDRESS_CORRECTION", "exception_kind=ADDRESS_CORRECTED")

    touch(shipment)
    pricing.reconcile(shipment, pricing.TRIGGER_EXCEPTION)
    return success(ser.shipment(shipment))


# --------------------------------------------------------------------------
# accessorial charges
# --------------------------------------------------------------------------

@bp.route("/shipments/<shipment_id>/accessorials", methods=["POST"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS)
def create_manual_accessorial(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)

    body = v.get_body()
    code = v.req_enum(body, "code", calc.ACCESSORIAL_CODES)
    reason = v.opt_string(body, "reason")
    amount_cents = v.opt_int(body, "amount_cents", None, minimum=0)

    pricing.assert_not_frozen(shipment)

    contract = domain.contract_of_shipment(shipment)
    if amount_cents is None:
        amount_cents = calc.resolve_accessorial_rate(contract, code,
                                                     shipment["delivery_area_class"])

    charge = domain.create_charge(shipment, code, "MANUAL", amount_cents,
                                 "manual_entry=true", reason=reason)
    pricing.reconcile(shipment, pricing.TRIGGER_MANUAL_ACCESSORIAL)
    return success(ser.accessorial_charge(charge), 201)


@bp.route("/shipments/<shipment_id>/accessorials", methods=["GET"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def list_accessorials(shipment_id):
    shipment = domain.shipment_or_404(shipment_id)
    enforce_shipper_scope(shipment["shipper_id"])
    limit, offset = pagination_params()

    rows = domain.charges_of_shipment(shipment["id"])
    status = request.args.get("status")
    code = request.args.get("code")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    return paginate(rows, ser.accessorial_charge, limit, offset)


@bp.route("/accessorial-charges/<charge_id>/waive", methods=["POST"])
@authorize(ROLE_BILLING_OPS)
def waive_accessorial(charge_id):
    charge = domain.charge_or_404(charge_id)
    body = v.get_body()
    reason = v.opt_string(body, "reason")

    if charge["status"] != "ASSESSED":
        raise ApiError("ERR_ACCESSORIAL_NOT_WAIVABLE",
                       "Only an ASSESSED accessorial charge may be waived.")

    shipment = db.shipments.get(charge["shipment_id"])
    if shipment is not None:
        pricing.assert_not_frozen(shipment)

    charge["status"] = "WAIVED"
    if reason is not None:
        charge["reason"] = reason
    touch(charge)

    if shipment is not None:
        pricing.reconcile(shipment, pricing.TRIGGER_WAIVER)
    return success(ser.accessorial_charge(charge))


@bp.route("/accessorial-charges/<charge_id>", methods=["GET"])
@authorize(ROLE_CARRIER_OPS, ROLE_BILLING_OPS, ROLE_REVENUE_AUDITOR,
           ROLE_SHIPPER_USER)
def read_accessorial(charge_id):
    charge = domain.charge_or_404(charge_id)
    shipment = db.shipments.get(charge["shipment_id"])
    if shipment is not None:
        enforce_shipper_scope(shipment["shipper_id"])
    return success(ser.accessorial_charge(charge))
