"""The collection bench and the capture of an ejaculate (PRD 3.4, 3.5)."""

from flask import Blueprint

import auth
import calc
import config
import envelope
import resolve
import serializers
import store
import validate
from errors import fail
from validate import F

bp = Blueprint("bookings", __name__)


def _live_bookings(sire_id):
    """Only SCHEDULED and COMPLETED bookings are visible to the rest buffer."""
    return [b for b in store.rows("collection_bookings")
            if b["sire_id"] == sire_id and b["status"] in ("SCHEDULED", "COMPLETED")]


@bp.post("/collection-bookings")
def create_booking():
    values = validate.parse([
        F("sire_id", "id", required=True),
        F("facility_id", "id", required=True),
        F("start_at", "datetime", required=True),
        F("end_at", "datetime", required=True),
    ])
    auth.require_role(config.ROLE_FACILITY_MANAGER)
    auth.require_facility_scope(values["facility_id"])
    sire = resolve.need("sires", values["sire_id"])
    facility = resolve.need("facilities", values["facility_id"])
    start_at = values["start_at"]
    end_at = values["end_at"]
    if sire["collection_status"] != "ELIGIBLE":
        fail("ERR_SIRE_COLLECTION_STATE", "A booking requires collection_status ELIGIBLE.")
    if facility["approval_status"] != "APPROVED":
        fail("ERR_FACILITY_SUSPENDED", "A suspended facility cannot accept a new booking.")
    if not calc.health_current(sire["id"]):
        fail("ERR_HEALTH_TESTS_NOT_CURRENT", "The four base required assays are not current.")
    if sire["housing_facility_id"] != facility["id"]:
        fail("ERR_SIRE_NOT_AT_FACILITY", "The bull is not housed at this facility.")
    if not (start_at < end_at) or start_at < store.clock():
        fail("ERR_INVALID_WINDOW", "start_at must be before end_at and at or after the clock.")

    # Rest buffer -- both boundaries closed, so exactly 48 hours is permitted.
    previous = None
    following = None
    for booking in _live_bookings(sire["id"]):
        b_start = store.dt_of(booking["start_at"])
        b_end = store.dt_of(booking["end_at"])
        if b_start <= start_at:
            if previous is None or b_end > store.dt_of(previous["end_at"]):
                previous = booking
        else:
            if following is None or b_start < store.dt_of(following["start_at"]):
                following = booking
    if previous is not None:
        gap = (start_at - store.dt_of(previous["end_at"])).total_seconds()
        if gap < config.REST_BUFFER_SECONDS:
            fail("ERR_SIRE_REST_BUFFER", "At least 48 hours must follow the previous collection.")
    if following is not None:
        gap = (store.dt_of(following["start_at"]) - start_at).total_seconds()
        if gap < config.REST_BUFFER_SECONDS:
            fail("ERR_SIRE_REST_BUFFER", "At least 48 hours must precede the next collection.")

    # Bench capacity -- adjacency is explicitly not overlap.
    overlapping = 0
    for booking in store.rows("collection_bookings"):
        if booking["facility_id"] != facility["id"] or booking["status"] != "SCHEDULED":
            continue
        b_start = store.dt_of(booking["start_at"])
        b_end = store.dt_of(booking["end_at"])
        if b_start < end_at and start_at < b_end:
            overlapping += 1
    if overlapping + 1 > int(facility["bench_capacity"]):
        fail("ERR_BENCH_CAPACITY_EXCEEDED", "The bench has no overlapping slot left.")

    rec = store.new_record("collection_bookings", {
        "sire_id": sire["id"],
        "facility_id": facility["id"],
        "start_at": store.iso(start_at),
        "end_at": store.iso(end_at),
        "status": "SCHEDULED",
        "cancel_reason": None,
        "completed_at": None,
        "collected_by_ref": None,
    })
    return envelope.created(serializers.collection_booking(rec))


@bp.get("/collection-bookings/<booking_id>")
def read_booking(booking_id):
    auth.require_role(config.ROLE_FACILITY_MANAGER, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_STAFF_VET, config.ROLE_LAB_TECH)
    rec = resolve.need("collection_bookings", booking_id)
    return envelope.ok(serializers.collection_booking(rec))


@bp.get("/collection-bookings")
def list_bookings():
    auth.require_role(config.ROLE_FACILITY_MANAGER, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_STAFF_VET, config.ROLE_LAB_TECH)
    limit, offset = validate.pagination()
    sire_id = validate.qstr("sire_id")
    facility_id = validate.qstr("facility_id")
    status = validate.qenum("status", config.BOOKING_STATUSES)
    items = []
    for rec in store.rows("collection_bookings"):
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if facility_id is not None and rec["facility_id"] != facility_id:
            continue
        if status is not None and rec["status"] != status:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.collection_booking)


@bp.post("/collection-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    values = validate.parse([F("cancel_reason", "string", required=True)])
    auth.require_role(config.ROLE_FACILITY_MANAGER, config.ROLE_PROGRAM_DIRECTOR)
    rec = resolve.need("collection_bookings", booking_id)
    auth.require_facility_scope(rec["facility_id"])
    if rec["status"] != "SCHEDULED":
        fail("ERR_BOOKING_STATE", "Only a SCHEDULED booking may be cancelled.")
    rec["status"] = "CANCELLED"
    rec["cancel_reason"] = values["cancel_reason"]
    store.touch(rec)
    return envelope.ok(serializers.collection_booking(rec))


@bp.post("/collection-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    values = validate.parse([
        F("volume_ml", "number", required=True, gt=0),
        F("concentration_m_per_ml", "number", required=True, gt=0),
        F("motility_pct", "number", required=True, min=0, max=100),
        F("collected_by_ref", "string", default=None),
    ])
    auth.require_role(config.ROLE_FACILITY_MANAGER)
    rec = resolve.need("collection_bookings", booking_id)
    auth.require_facility_scope(rec["facility_id"])
    if rec["status"] != "SCHEDULED":
        fail("ERR_BOOKING_STATE", "Only a SCHEDULED booking may be completed.")
    sire = store.get("sires", rec["sire_id"])
    facility = store.get("facilities", rec["facility_id"])
    if sire is None or sire["collection_status"] != "ELIGIBLE":
        fail("ERR_SIRE_COLLECTION_STATE", "The bull must still be ELIGIBLE.")
    if facility is None or facility["approval_status"] != "APPROVED":
        fail("ERR_FACILITY_SUSPENDED", "The facility must still be APPROVED.")
    if store.clock() < store.dt_of(rec["start_at"]):
        fail("ERR_BOOKING_NOT_STARTED", "The booked window has not started yet.")
    rec["status"] = "COMPLETED"
    rec["completed_at"] = store.clock_iso()
    rec["collected_by_ref"] = values["collected_by_ref"]
    store.touch(rec)
    store.new_record("ejaculates", {
        "booking_id": rec["id"],
        "sire_id": rec["sire_id"],
        "volume_ml": values["volume_ml"],
        "concentration_m_per_ml": values["concentration_m_per_ml"],
        "motility_pct": values["motility_pct"],
        "collected_at": store.clock_iso(),
        "collected_by_ref": values["collected_by_ref"],
        "total_doses_theoretical": calc.theoretical_doses(
            values["volume_ml"], values["concentration_m_per_ml"]),
        "qc_status": "PENDING_QC",
        "post_thaw_motility_pct": None,
        "morphology_normal_pct": None,
        "evaluated_by_user_id": None,
        "qc_decided_at": None,
    })
    return envelope.ok(serializers.collection_booking(rec))


@bp.get("/ejaculates/<ejaculate_id>")
def read_ejaculate(ejaculate_id):
    auth.require_role(config.ROLE_LAB_TECH, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_FACILITY_MANAGER)
    rec = resolve.need("ejaculates", ejaculate_id)
    return envelope.ok(serializers.ejaculate(rec))


@bp.get("/ejaculates")
def list_ejaculates():
    auth.require_role(config.ROLE_LAB_TECH, config.ROLE_PROGRAM_DIRECTOR,
                      config.ROLE_FACILITY_MANAGER)
    limit, offset = validate.pagination()
    booking_id = validate.qstr("booking_id")
    sire_id = validate.qstr("sire_id")
    qc_status = validate.qenum("qc_status", config.QC_STATUSES)
    items = []
    for rec in store.rows("ejaculates"):
        if booking_id is not None and rec["booking_id"] != booking_id:
            continue
        if sire_id is not None and rec["sire_id"] != sire_id:
            continue
        if qc_status is not None and rec["qc_status"] != qc_status:
            continue
        items.append(rec)
    return envelope.listing(items, limit, offset, serializers.ejaculate)


@bp.post("/ejaculates/<ejaculate_id>/qc-evaluation")
def evaluate_ejaculate(ejaculate_id):
    values = validate.parse([
        F("post_thaw_motility_pct", "number", required=True, min=0, max=100),
        F("morphology_normal_pct", "number", required=True, min=0, max=100),
        F("verdict", "enum", required=True, enum=config.QC_VERDICTS),
    ])
    auth.require_role(config.ROLE_LAB_TECH)
    user = auth.require_user_id()
    rec = resolve.need("ejaculates", ejaculate_id)
    if rec["qc_status"] != "PENDING_QC":
        fail("ERR_EJACULATE_STATE", "Quality evaluation requires qc_status PENDING_QC.")
    if values["verdict"] == "ACCEPTED":
        if (calc.D(values["post_thaw_motility_pct"]) < calc.D(config.QC_MIN_POST_THAW_MOTILITY_PCT)
                or calc.D(values["morphology_normal_pct"])
                < calc.D(config.QC_MIN_MORPHOLOGY_NORMAL_PCT)):
            fail("ERR_QC_BELOW_THRESHOLD",
                 "An ACCEPTED verdict requires post-thaw motility >= 35.0 and morphology >= 70.0.")
    rec["post_thaw_motility_pct"] = values["post_thaw_motility_pct"]
    rec["morphology_normal_pct"] = values["morphology_normal_pct"]
    rec["evaluated_by_user_id"] = user
    rec["qc_decided_at"] = store.clock_iso()
    rec["qc_status"] = values["verdict"]
    store.touch(rec)
    return envelope.ok(serializers.ejaculate(rec))
