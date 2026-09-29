"""The cold chain: cooler registration, receipt, disposition and containers.

Endpoints (9): POST/GET /shipments, GET /shipments/{id},
POST /shipments/{id}/receive, POST /shipments/{id}/disposition,
POST /shipments/{id}/donations, GET /donations, GET /donations/{id},
GET /donations/{id}/pool-components.
"""

from flask import Blueprint

import domain_donor
import domain_pool
import domain_shipment
import serializers
from auth import (ADMIN, DONOR, INTAKE_COORDINATOR, MEDICAL_DIRECTOR,
                  PROCESSING_TECHNICIAN, QA_OFFICER, actor_id, guard, is_donor,
                  require_own)
from envelope import ok, page, pagination
from errors import fail, not_found
from listing import apply_filters, sort_by
from store import db, find, insert, set_field, touch
from util import fmt_date
from validate import field, json_body, validate

bp = Blueprint("shipments", __name__)

MILK_CLASSES = ("PRETERM", "TERM")
DISPOSITIONS = ("ACCEPT", "REJECT")

SHIPMENT_READERS = (DONOR, INTAKE_COORDINATOR, MEDICAL_DIRECTOR, ADMIN)
DONATION_READERS = (INTAKE_COORDINATOR, MEDICAL_DIRECTOR, PROCESSING_TECHNICIAN,
                    ADMIN)
COMPONENT_READERS = (PROCESSING_TECHNICIAN, QA_OFFICER, MEDICAL_DIRECTOR, ADMIN)


def shipment_or_404(shipment_id):
    shipment = find("shipments", shipment_id)
    if shipment is None:
        not_found("Shipment '%s' does not exist." % shipment_id)
    return shipment


def donation_or_404(donation_id):
    donation = find("donations", donation_id)
    if donation is None:
        not_found("Donation '%s' does not exist." % donation_id)
    return donation


def shipment_state_gate(shipment, admitted):
    if shipment["status"] not in admitted:
        fail("ERR_SHIPMENT_STATE_INVALID",
             "A cooler in %s may not undergo this operation." % shipment["status"])


def require_qualified(donor):
    if donor is None or donor["status"] != "QUALIFIED":
        fail("ERR_DONOR_NOT_QUALIFIED", "The owning donor is not QUALIFIED.")


# --- POST /shipments -------------------------------------------------------
@bp.route("/shipments", methods=["POST"])
@guard(DONOR, INTAKE_COORDINATOR)
def create_shipment():
    body = json_body()
    raw_donor_id = body.get("donor_id")
    if is_donor() and isinstance(raw_donor_id, str):
        require_own(raw_donor_id)
    donor = None
    if isinstance(raw_donor_id, str):
        donor = find("donors", raw_donor_id)
        if donor is None:
            not_found("Donor '%s' does not exist." % raw_donor_id)

    values = validate(body, [
        field("donor_id", "string"),
        field("tracking_code", "string", regex=r"^TRK-[0-9]{4}$"),
        field("container_count", "integer", min=1, max=8),
        field("uses_dry_ice", "boolean"),
        field("declared_volume_ml", "integer", min=50, max=9600),
        field("shipped_on", "date"),
    ])
    for existing in db.rows("shipments"):
        if existing["tracking_code"] == values["tracking_code"]:
            fail("ERR_DUPLICATE_CODE",
                 "tracking_code '%s' is already registered." % values["tracking_code"])
    require_qualified(donor)

    shipment = insert("shipments", {
        "donor_id": donor["id"],
        "tracking_code": values["tracking_code"],
        "zone_code": donor["zone_code"],
        "container_count": values["container_count"],
        "uses_dry_ice": values["uses_dry_ice"],
        "declared_volume_ml": values["declared_volume_ml"],
        "shipped_on": fmt_date(values["shipped_on"]),
        "estimated_reimbursement_cents": 0,
        "final_reimbursement_cents": None,
        "credited_reimbursement_cents": None,
        "excursion_minutes": None,
        "arrival_max_temp_celsius": None,
        "verified_volume_ml": None,
        "status": "IN_TRANSIT",
        "received_at": None,
        "received_by_user_id": None,
    })
    shipment["estimated_reimbursement_cents"] = \
        domain_shipment.reimbursement_cents(shipment, None)
    return ok(serializers.shipment_out(shipment), 201)


# --- GET /shipments --------------------------------------------------------
@bp.route("/shipments", methods=["GET"])
@guard(*SHIPMENT_READERS)
def list_shipments():
    limit, offset = pagination()
    rows = db.rows("shipments")
    if is_donor():
        rows = [s for s in rows if s["donor_id"] == actor_id()]
    rows = apply_filters(rows, [("donor_id", "donor_id", "str"),
                                ("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], True),
                   (lambda r: r["tracking_code"], False)])
    return page(rows, limit, offset, serializers.shipment_out)


# --- GET /shipments/{id} ---------------------------------------------------
@bp.route("/shipments/<shipment_id>", methods=["GET"])
@guard(*SHIPMENT_READERS)
def get_shipment(shipment_id):
    shipment = shipment_or_404(shipment_id)
    require_own(shipment["donor_id"])
    return ok(serializers.shipment_out(shipment))


# --- POST /shipments/{id}/receive ------------------------------------------
@bp.route("/shipments/<shipment_id>/receive", methods=["POST"])
@guard(INTAKE_COORDINATOR)
def receive_shipment(shipment_id):
    shipment = shipment_or_404(shipment_id)
    body = json_body()
    values = validate(body, [
        field("excursion_minutes", "integer"),
        field("arrival_max_temp_celsius", "number"),
        field("verified_volume_ml", "integer"),
    ])
    shipment_state_gate(shipment, ("IN_TRANSIT",))

    excursion = values["excursion_minutes"]
    set_field(shipment, "excursion_minutes", excursion)
    set_field(shipment, "arrival_max_temp_celsius", values["arrival_max_temp_celsius"])
    set_field(shipment, "verified_volume_ml", values["verified_volume_ml"])
    set_field(shipment, "received_at", db.clock_instant())
    set_field(shipment, "received_by_user_id", actor_id())

    final_cents = domain_shipment.reimbursement_cents(shipment, excursion)
    set_field(shipment, "final_reimbursement_cents", final_cents)
    status = domain_shipment.receipt_disposition(
        values["arrival_max_temp_celsius"], excursion)
    set_field(shipment, "status", status)
    set_field(shipment, "credited_reimbursement_cents",
              domain_shipment.credited_for(status, final_cents))

    donor = find("donors", shipment["donor_id"])
    if donor is not None:
        domain_shipment.refresh_reimbursement_balance(donor)
    return ok(serializers.shipment_out(shipment))


# --- POST /shipments/{id}/disposition --------------------------------------
@bp.route("/shipments/<shipment_id>/disposition", methods=["POST"])
@guard(MEDICAL_DIRECTOR)
def disposition_shipment(shipment_id):
    shipment = shipment_or_404(shipment_id)
    body = json_body()
    values = validate(body, [
        field("disposition", "enum", enum=DISPOSITIONS),
    ])
    shipment_state_gate(shipment, ("QUARANTINED",))

    donor = find("donors", shipment["donor_id"])
    if values["disposition"] == "ACCEPT":
        set_field(shipment, "status", "ACCEPTED")
        set_field(shipment, "credited_reimbursement_cents",
                  shipment["final_reimbursement_cents"])
    else:
        set_field(shipment, "status", "REJECTED")
        set_field(shipment, "credited_reimbursement_cents", 0)
        for donation in db.rows("donations"):
            if donation["shipment_id"] != shipment["id"]:
                continue
            if donation["status"] == "ELIGIBLE":
                set_field(donation, "status", "DISCARDED")
    if donor is not None:
        domain_shipment.refresh_reimbursement_balance(donor)
        domain_donor.refresh_lifetime_volume(donor)
    return ok(serializers.shipment_out(shipment))


# --- POST /shipments/{id}/donations ----------------------------------------
@bp.route("/shipments/<shipment_id>/donations", methods=["POST"])
@guard(INTAKE_COORDINATOR)
def create_donation(shipment_id):
    shipment = shipment_or_404(shipment_id)
    body = json_body()
    values = validate(body, [
        field("container_label", "string", minlen=1, maxlen=16),
        field("expressed_on", "date"),
        field("volume_ml", "integer", min=50, max=1200),
        field("kcal_per_oz", "number", min="14.0", max="26.0"),
        field("milk_class", "enum", enum=MILK_CLASSES),
        field("expected_shipment_version", "integer"),
    ])
    for existing in db.rows("donations"):
        if existing["shipment_id"] == shipment["id"] \
                and existing["container_label"] == values["container_label"]:
            fail("ERR_DUPLICATE_CODE",
                 "container_label '%s' is already logged against this cooler."
                 % values["container_label"])
    shipment_state_gate(shipment, ("ACCEPTED",))
    if values["expected_shipment_version"] != shipment["version"]:
        fail("ERR_STALE_VERSION",
             "The cooler is at version %d." % shipment["version"])
    donor = find("donors", shipment["donor_id"])
    require_qualified(donor)

    donation = insert("donations", {
        "shipment_id": shipment["id"],
        "donor_id": shipment["donor_id"],
        "container_label": values["container_label"],
        "expressed_on": fmt_date(values["expressed_on"]),
        "volume_ml": values["volume_ml"],
        "kcal_per_oz": values["kcal_per_oz"],
        "milk_class": values["milk_class"],
        "remaining_ml": values["volume_ml"],
        "status": "ELIGIBLE",
    })
    domain_donor.refresh_lifetime_volume(donor)
    touch(shipment)
    return ok(serializers.donation_out(donation), 201)


# --- GET /donations --------------------------------------------------------
@bp.route("/donations", methods=["GET"])
@guard(*DONATION_READERS)
def list_donations():
    limit, offset = pagination()
    rows = apply_filters(db.rows("donations"),
                         [("donor_id", "donor_id", "str"),
                          ("shipment_id", "shipment_id", "str"),
                          ("status", "status", "str"),
                          ("milk_class", "milk_class", "str")])
    sort_by(rows, [(lambda r: r["created_at"], True),
                   (lambda r: r["container_label"], False)])
    return page(rows, limit, offset, serializers.donation_out)


# --- GET /donations/{id} ---------------------------------------------------
@bp.route("/donations/<donation_id>", methods=["GET"])
@guard(*DONATION_READERS)
def get_donation(donation_id):
    return ok(serializers.donation_out(donation_or_404(donation_id)))


# --- GET /donations/{id}/pool-components -----------------------------------
@bp.route("/donations/<donation_id>/pool-components", methods=["GET"])
@guard(*COMPONENT_READERS)
def list_donation_components(donation_id):
    donation = donation_or_404(donation_id)
    limit, offset = pagination()
    rows = apply_filters(domain_pool.components_of_donation(donation["id"]),
                         [("status", "status", "str")])
    sort_by(rows, [(lambda r: r["created_at"], False),
                   (lambda r: r["_seq"], False)])
    return page(rows, limit, offset, serializers.component_out)
