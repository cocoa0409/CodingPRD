"""Booking, service delivery, cancellation, retail attachments, settlements and
the guest folio (PRD §3.5 to §3.9).
"""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import domain
import envelope
import errors
import store
import validation as v
from errors import ApiError
from store import db, touch

bp = Blueprint("appointments", __name__)

SCHEDULE_STATUSES = ("REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_SERVICE",
                     "COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW")
CLEARANCE_STATUSES = ("PENDING", "CLEARED", "BLOCKED")
ATTACHMENT_STATUSES = ("RECOMMENDED", "PURCHASED", "DECLINED", "EXPIRED")
OUTCOMES = ("PURCHASED", "DECLINED")
SETTLEMENT_VARIANTS = ("PROVISIONAL", "FINAL")
FOLIO_KINDS = ("TREATMENT", "RETAIL", "SETTLEMENT_ADJUSTMENT", "REVERSAL",
               "LATE_CANCEL", "NO_SHOW")


# --------------------------------------------------------------------------
# shared gates
# --------------------------------------------------------------------------

def clinical_gate(guest, treatment_type):
    """Ladder rungs 12, 13 and 14."""
    form_id = guest.get("authoritative_intake_form_id")
    form = db.intake_forms.get(form_id) if form_id else None
    if form is None or form["status"] not in domain.CLEARED_INTAKE_STATES:
        raise ApiError(errors.ERR_INTAKE_NOT_CLEARED,
                       "The guest has no cleared authoritative intake form.")
    if (form.get("consent_signed_at") is None
            or form.get("consent_version") != treatment_type["required_consent_version"]):
        raise ApiError(errors.ERR_CONSENT_MISSING,
                       "The intake form carries no consent signature at version %s."
                       % treatment_type["required_consent_version"])
    barred = [code for code in guest["screened_condition_codes"]
              if code in treatment_type["contraindication_codes"]]
    if barred:
        raise ApiError(errors.ERR_CONTRAINDICATION_PRESENT,
                       "Screened condition codes %s bar this treatment."
                       % ", ".join(barred))
    return form


def credential_gate(therapist, treatment_type):
    """Ladder rungs 15, 16, 19 and 20."""
    verified = domain.practice_state_verified_licenses(therapist)
    if not verified:
        raise ApiError(errors.ERR_LICENSE_NOT_VERIFIED,
                       "The therapist holds no VERIFIED licence for their practice "
                       "state.")
    if not any(domain.unexpired(row) for row in verified):
        raise ApiError(errors.ERR_LICENSE_EXPIRED,
                       "The therapist's licence has expired.")
    required_rank = calc.SCOPE_RANK[treatment_type["required_scope_level"]]
    if domain.best_grant_rank(therapist["id"],
                              treatment_type["required_skill_code"],
                              required_rank) is None:
        raise ApiError(errors.ERR_SCOPE_OF_PRACTICE_VIOLATION,
                       "The therapist holds no ACTIVE unexpired grant for skill %s at "
                       "scope %s." % (treatment_type["required_skill_code"],
                                      treatment_type["required_scope_level"]))
    if therapist["status"] != "ACTIVE":
        raise ApiError(errors.ERR_THERAPIST_NOT_ACTIVE,
                       "The therapist is not ACTIVE.")


def room_gate(room, treatment_type, check_class=True):
    """Ladder rungs 21 and 22."""
    if check_class:
        if (room["room_class"] != treatment_type["room_class_required"]
                or room["capacity_guests"] < 1):
            raise ApiError(errors.ERR_ROOM_CLASS_MISMATCH,
                           "The room class does not match the treatment requirement.")
    if room["status"] != "ACTIVE":
        raise ApiError(errors.ERR_ROOM_UNAVAILABLE, "The room is not ACTIVE.")


# --------------------------------------------------------------------------
# booking
# --------------------------------------------------------------------------

@bp.route("/appointments", methods=["POST"])
def book_appointment():
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.GUEST)
    body = v.json_body()
    guest_id = v.field_id(body, "guest_id")
    treatment_type_id = v.field_id(body, "treatment_type_id")
    room_id = v.field_id(body, "room_id")
    therapist_id = v.field_id(body, "therapist_id", required=False)
    start_at = v.field_instant(body, "start_at")

    guest = domain.find_guest(guest_id)
    treatment_type = domain.find_treatment_type(treatment_type_id)
    room = domain.find_room(room_id)
    therapist = domain.find_therapist(therapist_id) if therapist_id else None

    auth.require_guest_owner(caller, guest["id"])

    duration = treatment_type["duration_minutes"]
    end_at = start_at + timedelta(minutes=duration)

    clinical_gate(guest, treatment_type)

    if therapist is not None:
        credential_gate(therapist, treatment_type)

    room_gate(room, treatment_type, check_class=True)

    if therapist is not None:
        if not domain.contained_in_available_shift(therapist["id"], start_at, end_at):
            raise ApiError(errors.ERR_OUTSIDE_SHIFT_WINDOW,
                           "No AVAILABLE shift block contains the requested interval.")
        if domain.has_exclusion_conflict(therapist["id"], start_at, end_at) or \
                domain.has_appointment_conflict(therapist["id"], start_at, end_at):
            raise ApiError(errors.ERR_THERAPIST_DOUBLE_BOOKED,
                           "The therapist is not free over the requested interval.")

    if domain.has_room_turnover_conflict(room, start_at, end_at):
        raise ApiError(errors.ERR_ROOM_TURNOVER_CONFLICT,
                       "The room occupancy interval overlaps another appointment.")

    if start_at < db.clock + timedelta(minutes=calc.MIN_LEAD_MINUTES):
        raise ApiError(errors.ERR_BOOKING_LEAD_TIME,
                       "A booking must start at least %d minutes after the clock."
                       % calc.MIN_LEAD_MINUTES)

    if guest["booking_privilege"] != "OPEN":
        raise ApiError(errors.ERR_GUEST_BOOKING_RESTRICTED,
                       "The guest's booking privilege is RESTRICTED.")

    if therapist is None:
        therapist = domain.select_therapist(treatment_type, start_at, end_at)
        if therapist is None:
            raise ApiError(errors.ERR_NO_ELIGIBLE_THERAPIST,
                           "No therapist is eligible for the requested interval.")
        assignment_mode = "AUTO"
    else:
        assignment_mode = "EXPLICIT"

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "guest_id": guest["id"],
        "treatment_type_id": treatment_type["id"],
        "room_id": room["id"],
        "therapist_id": therapist["id"],
        "start_at": start_at,
        "end_at": end_at,
        "scheduled_duration_minutes": duration,
        "actual_duration_minutes": None,
        "high_demand_slot": bool(treatment_type["high_demand"])
        or (calc.PEAK_HOUR_START <= start_at.hour < calc.PEAK_HOUR_END),
        "quoted_price_cents": calc.appointment_price_quote(treatment_type, room, guest,
                                                          start_at),
        "realized_price_cents": None,
        "gratuity_cents": 0,
        "schedule_status": "REQUESTED",
        "clearance_status": "PENDING",
        "clearance_block_reason": None,
        "cancellation_charge_cents": 0,
        "assignment_mode": assignment_mode,
        "started_at": None,
        "completed_at": None,
    })
    db.appointments[entity["id"]] = entity
    domain.commit_capacity(entity, room, therapist)
    return envelope.created(entity)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR, auth.COMPLIANCE_OFFICER)
    limit, offset = v.pagination()
    guest_id = v.query_str("guest_id")
    therapist_id = v.query_str("therapist_id")
    room_id = v.query_str("room_id")
    treatment_type_id = v.query_str("treatment_type_id")
    schedule_status = v.query_enum("schedule_status", SCHEDULE_STATUSES)
    clearance_status = v.query_enum("clearance_status", CLEARANCE_STATUSES)
    from_at = v.query_instant("from_at")
    to_at = v.query_instant("to_at")

    rows = store.by_created(list(db.appointments.values()))
    if guest_id is not None:
        rows = [r for r in rows if r["guest_id"] == guest_id]
    if therapist_id is not None:
        rows = [r for r in rows if r["therapist_id"] == therapist_id]
    if room_id is not None:
        rows = [r for r in rows if r["room_id"] == room_id]
    if treatment_type_id is not None:
        rows = [r for r in rows if r["treatment_type_id"] == treatment_type_id]
    if schedule_status is not None:
        rows = [r for r in rows if r["schedule_status"] == schedule_status]
    if clearance_status is not None:
        rows = [r for r in rows if r["clearance_status"] == clearance_status]
    if from_at is not None:
        rows = [r for r in rows if r["start_at"] >= from_at]
    if to_at is not None:
        rows = [r for r in rows if r["start_at"] <= to_at]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/appointments/<appointment_id>", methods=["GET"])
def read_appointment(appointment_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR,
                               auth.COMPLIANCE_OFFICER, auth.THERAPIST, auth.GUEST)
    appointment = domain.find_appointment(appointment_id)
    auth.require_guest_owner(caller, appointment["guest_id"])
    auth.require_therapist_owner(caller, appointment["therapist_id"])
    return envelope.ok(appointment)


# --------------------------------------------------------------------------
# settlement helpers
# --------------------------------------------------------------------------

def compute_settlement(appointment, variant):
    therapist = db.therapists.get(appointment["therapist_id"])
    room = db.rooms.get(appointment["room_id"])
    purchased = domain.purchased_attachments(appointment["id"])
    return calc.settlement_distribution(variant, appointment, therapist, room,
                                        purchased)


def persist_settlement(appointment, variant, status, figures):
    row = {}
    store.stamp_common(row)
    row["appointment_id"] = appointment["id"]
    row["variant"] = variant
    row["status"] = status
    row.update(figures)
    db.settlements[row["id"]] = row
    return row


def provisional_row(appointment_id):
    for row in domain.settlements_of(appointment_id):
        if row["variant"] == "PROVISIONAL":
            return row
    return None


def final_row(appointment_id):
    for row in domain.settlements_of(appointment_id):
        if row["variant"] == "FINAL":
            return row
    return None


# --------------------------------------------------------------------------
# service delivery
# --------------------------------------------------------------------------

@bp.route("/appointments/<appointment_id>/confirm", methods=["POST"])
def confirm_appointment(appointment_id):
    auth.authenticate(auth.SPA_COORDINATOR)
    v.json_body()
    appointment = domain.find_appointment(appointment_id)

    if appointment["schedule_status"] != "REQUESTED":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only a REQUESTED appointment may be confirmed.")

    guest = db.guests.get(appointment["guest_id"])
    treatment_type = db.treatment_types.get(appointment["treatment_type_id"])
    therapist = db.therapists.get(appointment["therapist_id"])
    room = db.rooms.get(appointment["room_id"])

    clinical_gate(guest, treatment_type)
    credential_gate(therapist, treatment_type)
    room_gate(room, treatment_type, check_class=False)

    appointment["schedule_status"] = "CONFIRMED"
    appointment["clearance_status"] = "CLEARED"
    appointment["clearance_block_reason"] = None
    touch(appointment)
    return envelope.ok(appointment)


@bp.route("/appointments/<appointment_id>/check-in", methods=["POST"])
def check_in_appointment(appointment_id):
    auth.authenticate(auth.SPA_COORDINATOR)
    v.json_body()
    appointment = domain.find_appointment(appointment_id)

    if appointment["schedule_status"] != "CONFIRMED":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only a CONFIRMED appointment may be checked in.")
    if domain.settlements_of(appointment["id"]):
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "The appointment already carries a settlement row.")
    if appointment["clearance_status"] != "CLEARED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_CLEARED,
                       "The appointment's clearance status is not CLEARED.")

    guest = db.guests.get(appointment["guest_id"])
    figures = compute_settlement(appointment, "PROVISIONAL")
    if domain.folio_would_exceed(guest, figures["folio_total_cents"]):
        raise ApiError(errors.ERR_FOLIO_LIMIT_EXCEEDED,
                       "The posting would take the folio past its limit.")

    appointment["schedule_status"] = "CHECKED_IN"
    touch(appointment)
    persist_settlement(appointment, "PROVISIONAL", "PROVISIONAL", figures)
    domain.post_folio_charge(guest, appointment["id"], "TREATMENT",
                            figures["folio_total_cents"],
                            "Treatment charge at check-in")
    return envelope.ok(appointment)


@bp.route("/appointments/<appointment_id>/start", methods=["POST"])
def start_appointment(appointment_id):
    caller = auth.authenticate(auth.THERAPIST)
    v.json_body()
    appointment = domain.find_appointment(appointment_id)
    auth.require_therapist_owner(caller, appointment["therapist_id"])

    if appointment["schedule_status"] != "CHECKED_IN":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only a CHECKED_IN appointment may be started.")
    if appointment["clearance_status"] != "CLEARED":
        raise ApiError(errors.ERR_APPOINTMENT_NOT_CLEARED,
                       "The appointment's clearance status is not CLEARED.")

    therapist = db.therapists.get(appointment["therapist_id"])
    if therapist is None or therapist["status"] != "ACTIVE":
        raise ApiError(errors.ERR_THERAPIST_NOT_ACTIVE,
                       "The therapist is not ACTIVE.")

    appointment["schedule_status"] = "IN_SERVICE"
    appointment["started_at"] = db.clock
    touch(appointment)
    return envelope.ok(appointment)


@bp.route("/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    caller = auth.authenticate(auth.THERAPIST)
    body = v.json_body()
    actual_minutes = v.field_int(body, "actual_duration_minutes", minimum=1,
                                maximum=480)
    gratuity = v.field_int(body, "gratuity_cents", required=False, default=0,
                          minimum=0)
    appointment = domain.find_appointment(appointment_id)
    auth.require_therapist_owner(caller, appointment["therapist_id"])

    if appointment["schedule_status"] != "IN_SERVICE":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only an IN_SERVICE appointment may be completed.")

    if gratuity > calc.gratuity_cap_for(appointment):
        raise ApiError(errors.ERR_GRATUITY_LIMIT_EXCEEDED,
                       "The gratuity exceeds %d basis points of the quoted price."
                       % calc.GRATUITY_CAP_BP)

    appointment["schedule_status"] = "COMPLETED"
    appointment["actual_duration_minutes"] = actual_minutes
    appointment["gratuity_cents"] = gratuity
    appointment["completed_at"] = db.clock
    touch(appointment)
    return envelope.ok(appointment)


# --------------------------------------------------------------------------
# cancellation, no-show and the restriction cascade
# --------------------------------------------------------------------------

def cancel_other_requested(guest, exclude_id):
    """Restriction cascade: system-cancel the guest's other REQUESTED bookings."""
    cancelled = []
    for other in domain.appointments_of_guest(guest["id"]):
        if other["id"] == exclude_id:
            continue
        if other["schedule_status"] != "REQUESTED":
            continue
        other["schedule_status"] = "CANCELLED"
        other["cancellation_charge_cents"] = 0
        touch(other)
        domain.release_capacity(other)
        cancelled.append(other["id"])
    return cancelled


def charge_cascade(appointment, guest, kind, charge_cents, counter, threshold, memo):
    """Posting, counter, privilege flip and the restriction cascade."""
    guest[counter] = guest[counter] + 1
    if guest[counter] >= threshold:
        guest["booking_privilege"] = "RESTRICTED"
    domain.post_folio_charge(guest, appointment["id"], kind, charge_cents, memo)
    if guest["booking_privilege"] == "RESTRICTED":
        cancel_other_requested(guest, appointment["id"])


@bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.GUEST)
    body = v.json_body()
    v.field_str(body, "cancel_reason", required=False, default=None, max_len=500)
    appointment = domain.find_appointment(appointment_id)
    auth.require_guest_owner(caller, appointment["guest_id"])

    status = appointment["schedule_status"]
    if status not in ("REQUESTED", "CONFIRMED", "CHECKED_IN"):
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "An appointment in status '%s' cannot be cancelled." % status)

    guest = db.guests.get(appointment["guest_id"])

    if status == "CHECKED_IN":
        if caller.role == auth.GUEST:
            raise ApiError(errors.ERR_ROLE_NOT_PERMITTED,
                           "Only a SpaCoordinator may abort a checked-in appointment.")
        if appointment["clearance_status"] != "BLOCKED":
            raise ApiError(errors.ERR_APPOINTMENT_NOT_CLEARED,
                           "The checked-in abort requires BLOCKED clearance.")

        appointment["schedule_status"] = "CANCELLED"
        appointment["cancellation_charge_cents"] = 0
        touch(appointment)

        row = provisional_row(appointment["id"])
        if row is not None and row["status"] == "PROVISIONAL":
            row["status"] = "REVERSED"
            touch(row)
            domain.post_folio_charge(guest, appointment["id"], "REVERSAL",
                                    -row["folio_total_cents"],
                                    "Reversal of the check-in treatment charge")
        domain.release_capacity(appointment)
        return envelope.ok(appointment)

    charge_cents, charged = calc.cancellation_band(appointment, db.clock)
    if not charged:
        appointment["schedule_status"] = "CANCELLED"
        appointment["cancellation_charge_cents"] = 0
        touch(appointment)
        domain.release_capacity(appointment)
        return envelope.ok(appointment)

    appointment["schedule_status"] = "LATE_CANCELLED"
    appointment["cancellation_charge_cents"] = charge_cents
    touch(appointment)
    domain.release_capacity(appointment)
    charge_cascade(appointment, guest, "LATE_CANCEL", charge_cents,
                   "late_cancel_count", calc.LATE_CANCEL_RESTRICTION_THRESHOLD,
                   "Late cancellation charge")
    return envelope.ok(appointment)


@bp.route("/appointments/<appointment_id>/no-show", methods=["POST"])
def no_show_appointment(appointment_id):
    auth.authenticate(auth.SPA_COORDINATOR)
    v.json_body()
    appointment = domain.find_appointment(appointment_id)

    if appointment["schedule_status"] != "CONFIRMED":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only a CONFIRMED appointment may be marked as a no-show.")
    grace_end = appointment["start_at"] + timedelta(
        minutes=calc.NO_SHOW_GRACE_MINUTES)
    if db.clock < grace_end:
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "The %d-minute no-show grace period has not elapsed."
                       % calc.NO_SHOW_GRACE_MINUTES)

    guest = db.guests.get(appointment["guest_id"])
    charge_cents, _ = calc.cancellation_band(appointment, db.clock, no_show=True)

    appointment["schedule_status"] = "NO_SHOW"
    appointment["cancellation_charge_cents"] = charge_cents
    touch(appointment)
    domain.release_capacity(appointment)
    charge_cascade(appointment, guest, "NO_SHOW", charge_cents, "no_show_strikes",
                   calc.NO_SHOW_RESTRICTION_THRESHOLD, "No-show charge")
    return envelope.ok(appointment)


# --------------------------------------------------------------------------
# retail attachments
# --------------------------------------------------------------------------

@bp.route("/appointments/<appointment_id>/retail-attachments", methods=["POST"])
def create_attachment(appointment_id):
    caller = auth.authenticate(auth.THERAPIST)
    body = v.json_body()
    product_sku = v.field_str(body, "product_sku", max_len=64)
    product_line = v.field_str(body, "product_line", max_len=64)
    amount_cents = v.field_int(body, "amount_cents", minimum=1)
    appointment = domain.find_appointment(appointment_id)
    auth.require_therapist_owner(caller, appointment["therapist_id"])

    if appointment["schedule_status"] not in domain.ATTACHABLE_SCHEDULE_STATES:
        raise ApiError(errors.ERR_INVALID_ATTACHMENT_STATE,
                       "An appointment in status '%s' accepts no recommendation."
                       % appointment["schedule_status"])

    treatment_type = db.treatment_types.get(appointment["treatment_type_id"])
    if product_line != treatment_type["retail_product_line"]:
        raise ApiError(errors.ERR_PRODUCT_LINE_MISMATCH,
                       "The product line must equal the treatment's retail product "
                       "line '%s'." % treatment_type["retail_product_line"])

    entity = {}
    store.stamp_common(entity)
    entity.update({
        "appointment_id": appointment["id"],
        "product_sku": product_sku,
        "product_line": product_line,
        "amount_cents": amount_cents,
        "status": "RECOMMENDED",
        "resolved_by_user_id": None,
        "resolved_at": None,
    })
    db.retail_attachments[entity["id"]] = entity
    return envelope.created(entity)


@bp.route("/appointments/<appointment_id>/retail-attachments", methods=["GET"])
def list_attachments(appointment_id):
    caller = auth.authenticate(auth.THERAPIST, auth.SPA_COORDINATOR, auth.SPA_DIRECTOR,
                               auth.GUEST)
    limit, offset = v.pagination()
    status = v.query_enum("status", ATTACHMENT_STATUSES)
    appointment = domain.find_appointment(appointment_id)
    auth.require_guest_owner(caller, appointment["guest_id"])
    auth.require_therapist_owner(caller, appointment["therapist_id"])

    rows = domain.attachments_of(appointment["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/retail-attachments/<attachment_id>/resolve", methods=["POST"])
def resolve_attachment(attachment_id):
    caller = auth.authenticate(auth.GUEST, auth.SPA_COORDINATOR)
    body = v.json_body()
    outcome = v.field_enum(body, "outcome", OUTCOMES)
    attachment = domain.find_attachment(attachment_id)
    appointment = db.appointments.get(attachment["appointment_id"])
    auth.require_guest_owner(caller, appointment["guest_id"])

    if attachment["status"] != "RECOMMENDED":
        raise ApiError(errors.ERR_INVALID_ATTACHMENT_STATE,
                       "Only a RECOMMENDED attachment may be resolved.")
    if outcome == "PURCHASED" and \
            appointment["schedule_status"] not in domain.ATTACHABLE_SCHEDULE_STATES:
        raise ApiError(errors.ERR_INVALID_ATTACHMENT_STATE,
                       "The parent appointment is not in a purchasable state.")

    guest = db.guests.get(appointment["guest_id"])
    if outcome == "PURCHASED" and domain.folio_would_exceed(
            guest, attachment["amount_cents"]):
        raise ApiError(errors.ERR_FOLIO_LIMIT_EXCEEDED,
                       "The posting would take the folio past its limit.")

    attachment["status"] = outcome
    attachment["resolved_by_user_id"] = caller.user_id
    attachment["resolved_at"] = db.clock
    touch(attachment)

    if outcome == "PURCHASED":
        domain.post_folio_charge(guest, appointment["id"], "RETAIL",
                                attachment["amount_cents"],
                                "Retail purchase %s" % attachment["product_sku"])
    return envelope.ok(attachment)


# --------------------------------------------------------------------------
# settlements
# --------------------------------------------------------------------------

@bp.route("/appointments/<appointment_id>/settlements", methods=["POST"])
def create_settlement(appointment_id):
    auth.authenticate(auth.SPA_DIRECTOR)
    body = v.json_body()
    expected_version = v.field_int(body, "expected_appointment_version", minimum=0)
    appointment = domain.find_appointment(appointment_id)

    if expected_version != appointment["version"]:
        raise ApiError(errors.ERR_STALE_APPOINTMENT_VERSION,
                       "The appointment version has moved on; expected %s but found %s."
                       % (expected_version, appointment["version"]))
    if appointment["schedule_status"] != "COMPLETED":
        raise ApiError(errors.ERR_INVALID_APPOINTMENT_STATE,
                       "Only a COMPLETED appointment may be settled.")
    if final_row(appointment["id"]) is not None:
        raise ApiError(errors.ERR_SETTLEMENT_ALREADY_FINAL,
                       "A FINAL settlement row already exists.")

    figures = compute_settlement(appointment, "FINAL")
    row = persist_settlement(appointment, "FINAL", "FINALIZED", figures)

    appointment["realized_price_cents"] = figures["realized_price_cents"]
    touch(appointment)

    provisional = provisional_row(appointment["id"])
    if provisional is not None and provisional["status"] == "PROVISIONAL":
        provisional["status"] = "SUPERSEDED"
        touch(provisional)

    already_posted = sum(charge["amount_cents"] for charge
                         in domain.folio_charges_of_appointment(appointment["id"]))
    adjustment = figures["folio_total_cents"] - already_posted
    guest = db.guests.get(appointment["guest_id"])
    domain.post_folio_charge(guest, appointment["id"], "SETTLEMENT_ADJUSTMENT",
                            adjustment, "Final settlement adjustment")
    return envelope.created(row)


@bp.route("/appointments/<appointment_id>/settlements", methods=["GET"])
def list_settlements(appointment_id):
    auth.authenticate(auth.SPA_DIRECTOR, auth.SPA_COORDINATOR, auth.COMPLIANCE_OFFICER)
    limit, offset = v.pagination()
    variant = v.query_enum("variant", SETTLEMENT_VARIANTS)
    appointment = domain.find_appointment(appointment_id)

    rows = domain.settlements_of(appointment["id"])
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    rows.sort(key=lambda r: (0 if r["variant"] == "PROVISIONAL" else 1,
                             r["created_at"], r["_seq"]))
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


# --------------------------------------------------------------------------
# folio postings
# --------------------------------------------------------------------------

@bp.route("/guests/<guest_id>/folio-charges", methods=["GET"])
def list_guest_folio(guest_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR, auth.GUEST)
    limit, offset = v.pagination()
    kind = v.query_enum("kind", FOLIO_KINDS)
    guest = domain.find_guest(guest_id)
    auth.require_guest_owner(caller, guest["id"])

    rows = domain.folio_charges_of_guest(guest["id"])
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)


@bp.route("/appointments/<appointment_id>/folio-charges", methods=["GET"])
def list_appointment_folio(appointment_id):
    caller = auth.authenticate(auth.SPA_COORDINATOR, auth.SPA_DIRECTOR, auth.GUEST)
    limit, offset = v.pagination()
    kind = v.query_enum("kind", FOLIO_KINDS)
    appointment = domain.find_appointment(appointment_id)
    auth.require_guest_owner(caller, appointment["guest_id"])

    rows = domain.folio_charges_of_appointment(appointment["id"])
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return envelope.listing(v.paginate(rows, limit, offset), len(rows), limit, offset)
