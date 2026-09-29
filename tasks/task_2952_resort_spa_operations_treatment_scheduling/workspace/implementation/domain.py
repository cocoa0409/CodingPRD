"""Domain helpers: lookups, the clearance predicate and its cascades, the guest
folio, the two minute ledgers and automatic therapist assignment.
"""

from datetime import timedelta

import calc
import store
from store import db, touch

CLEARANCE_SCHEDULE_STATES = ("REQUESTED", "CONFIRMED", "CHECKED_IN")
NON_TERMINAL_SCHEDULE_STATES = ("REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_SERVICE")
TERMINAL_SCHEDULE_STATES = ("COMPLETED", "CANCELLED", "LATE_CANCELLED", "NO_SHOW")
SCREENED_STATES = ("SCREENED_CLEAR", "SCREENED_FLAGGED", "OVERRIDDEN")
CLEARED_INTAKE_STATES = ("SCREENED_CLEAR", "OVERRIDDEN")
ATTACHABLE_SCHEDULE_STATES = ("CONFIRMED", "CHECKED_IN", "IN_SERVICE", "COMPLETED")


# --------------------------------------------------------------------------
# collection lookups
# --------------------------------------------------------------------------

def licenses_of(therapist_id):
    return store.by_created([l for l in db.licenses.values()
                             if l["therapist_id"] == therapist_id])


def certifications_of(therapist_id):
    return store.by_created([c for c in db.certifications.values()
                             if c["therapist_id"] == therapist_id])


def ce_records_of(license_id):
    return store.by_created([r for r in db.ce_records.values()
                             if r["license_id"] == license_id])


def shift_blocks_of(therapist_id):
    return store.by_created([b for b in db.shift_blocks.values()
                             if b["therapist_id"] == therapist_id])


def intake_forms_of(guest_id):
    return store.by_created([f for f in db.intake_forms.values()
                             if f["guest_id"] == guest_id])


def appointments_of_guest(guest_id):
    return store.by_created([a for a in db.appointments.values()
                             if a["guest_id"] == guest_id])


def appointments_of_therapist(therapist_id):
    return store.by_created([a for a in db.appointments.values()
                             if a["therapist_id"] == therapist_id])


def appointments_of_room(room_id):
    return store.by_created([a for a in db.appointments.values()
                             if a["room_id"] == room_id])


def attachments_of(appointment_id):
    return store.by_created([r for r in db.retail_attachments.values()
                             if r["appointment_id"] == appointment_id])


def purchased_attachments(appointment_id):
    return [r for r in attachments_of(appointment_id) if r["status"] == "PURCHASED"]


def settlements_of(appointment_id):
    return store.by_created([s for s in db.settlements.values()
                             if s["appointment_id"] == appointment_id])


def folio_charges_of_guest(guest_id):
    rows = [f for f in db.folio_charges.values() if f["guest_id"] == guest_id]
    return sorted(rows, key=lambda r: (r["posted_at"], r["_seq"]))


def folio_charges_of_appointment(appointment_id):
    rows = [f for f in db.folio_charges.values()
            if f["appointment_id"] == appointment_id]
    return sorted(rows, key=lambda r: (r["posted_at"], r["_seq"]))


# --------------------------------------------------------------------------
# credential helpers
# --------------------------------------------------------------------------

def verified_licenses(therapist):
    return [l for l in licenses_of(therapist["id"])
            if l["verification_status"] == "VERIFIED"]


def practice_state_verified_licenses(therapist):
    return [l for l in verified_licenses(therapist)
            if l["state_code"] == therapist["practice_state_code"]]


def unexpired(license_row):
    return license_row["expires_on"] >= db.clock.date()


def valid_practice_license(therapist):
    """A VERIFIED licence for the practice state that has not lapsed."""
    for license_row in practice_state_verified_licenses(therapist):
        if unexpired(license_row):
            return license_row
    return None


def matching_grants(therapist_id, skill_code, required_rank):
    out = []
    for grant in certifications_of(therapist_id):
        if grant["skill_code"] != skill_code:
            continue
        if grant["status"] != "ACTIVE":
            continue
        if grant["expires_on"] < db.clock.date():
            continue
        if calc.SCOPE_RANK[grant["scope_level"]] < required_rank:
            continue
        out.append(grant)
    return out


def best_grant_rank(therapist_id, skill_code, required_rank):
    grants = matching_grants(therapist_id, skill_code, required_rank)
    if not grants:
        return None
    return max(calc.SCOPE_RANK[g["scope_level"]] for g in grants)


# --------------------------------------------------------------------------
# authoritative intake form (PRD §3.4)
# --------------------------------------------------------------------------

def authoritative_form(guest_id):
    candidates = [f for f in intake_forms_of(guest_id) if f["status"] in SCREENED_STATES]
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f["created_at"], f.get("version", 1), f["_seq"]))
    return candidates[-1]


def recompute_authoritative(guest):
    """Rewrite the computed pointer and the screened condition set."""
    form = authoritative_form(guest["id"])
    if form is None:
        guest["authoritative_intake_form_id"] = None
        guest["screened_condition_codes"] = []
    else:
        guest["authoritative_intake_form_id"] = form["id"]
        guest["screened_condition_codes"] = list(form["condition_codes"])
    return form


# --------------------------------------------------------------------------
# the guest folio (PRD §2.11)
# --------------------------------------------------------------------------

def folio_total_for_guest(guest_id):
    return sum(f["amount_cents"] for f in db.folio_charges.values()
               if f["guest_id"] == guest_id)


def post_folio_charge(guest, appointment_id, kind, amount_cents, memo):
    """Append an immutable posting, recompute the balance and bump the guest."""
    charge = {}
    store.stamp_common(charge, versioned=False)
    charge["guest_id"] = guest["id"]
    charge["appointment_id"] = appointment_id
    charge["kind"] = kind
    charge["amount_cents"] = amount_cents
    charge["memo"] = memo
    charge["posted_at"] = db.clock
    db.folio_charges[charge["id"]] = charge
    guest["folio_balance_cents"] = folio_total_for_guest(guest["id"])
    touch(guest)
    return charge


def folio_would_exceed(guest, amount_cents):
    return guest["folio_balance_cents"] + amount_cents > guest["folio_limit_cents"]


# --------------------------------------------------------------------------
# the room and therapist minute ledgers (PRD §2.12)
# --------------------------------------------------------------------------

def committed_minutes(appointment, room):
    return appointment["scheduled_duration_minutes"] + room["turnover_buffer_minutes"]


def commit_capacity(appointment, room, therapist):
    room["booked_minutes_total"] += committed_minutes(appointment, room)
    touch(room)
    therapist["assigned_minutes_total"] += appointment["scheduled_duration_minutes"]
    touch(therapist)


def release_capacity(appointment):
    room = db.rooms.get(appointment["room_id"])
    therapist = db.therapists.get(appointment["therapist_id"])
    if room is not None:
        room["booked_minutes_total"] -= committed_minutes(appointment, room)
        touch(room)
    if therapist is not None:
        therapist["assigned_minutes_total"] -= appointment["scheduled_duration_minutes"]
        touch(therapist)


# --------------------------------------------------------------------------
# the clearance dimension (PRD §2.10)
# --------------------------------------------------------------------------

def clearance_failure(appointment):
    """First failing clause of the four-clause predicate, or None when cleared."""
    guest = db.guests.get(appointment["guest_id"])
    form = None
    if guest is not None and guest.get("authoritative_intake_form_id"):
        form = db.intake_forms.get(guest["authoritative_intake_form_id"])
    if form is None or form["status"] not in CLEARED_INTAKE_STATES:
        return "INTAKE_FLAGGED"

    therapist = db.therapists.get(appointment["therapist_id"])
    if therapist is None or valid_practice_license(therapist) is None:
        return "LICENSE_INVALID"

    if therapist["status"] != "ACTIVE":
        return "THERAPIST_SUSPENDED"

    room = db.rooms.get(appointment["room_id"])
    if room is None or room["status"] != "ACTIVE":
        return "ROOM_UNAVAILABLE"
    return None


def expire_recommendations(appointment):
    expired = []
    for attachment in attachments_of(appointment["id"]):
        if attachment["status"] == "RECOMMENDED":
            attachment["status"] = "EXPIRED"
            touch(attachment)
            expired.append(attachment["id"])
    return expired


def block_order(rows):
    """Cascade order for clearance re-evaluation: start_at ASC, created_at ASC."""
    return sorted(rows, key=lambda a: (a["start_at"], a["created_at"], a["_seq"]))


def run_block_cascade(appointments):
    """Drive a set of appointments to BLOCKED, rewriting the reason each time.

    Returns (newly_blocked_ids, expired_attachment_ids).
    """
    blocked_ids = []
    expired_ids = []
    for appointment in block_order(appointments):
        if appointment["schedule_status"] not in CLEARANCE_SCHEDULE_STATES:
            continue
        reason = clearance_failure(appointment)
        if reason is None:
            continue
        was_blocked = appointment["clearance_status"] == "BLOCKED"
        changed = (not was_blocked) or appointment["clearance_block_reason"] != reason
        appointment["clearance_status"] = "BLOCKED"
        appointment["clearance_block_reason"] = reason
        if changed:
            touch(appointment)
        if not was_blocked:
            blocked_ids.append(appointment["id"])
            expired_ids.extend(expire_recommendations(appointment))
    return blocked_ids, expired_ids


def run_reclear_cascade(appointments):
    """Re-evaluate BLOCKED appointments; promote to CLEARED when all clauses hold."""
    cleared_ids = []
    for appointment in block_order(appointments):
        if appointment["schedule_status"] not in CLEARANCE_SCHEDULE_STATES:
            continue
        if appointment["clearance_status"] != "BLOCKED":
            continue
        reason = clearance_failure(appointment)
        if reason is None:
            appointment["clearance_status"] = "CLEARED"
            appointment["clearance_block_reason"] = None
            touch(appointment)
            cleared_ids.append(appointment["id"])
        elif appointment["clearance_block_reason"] != reason:
            appointment["clearance_block_reason"] = reason
            touch(appointment)
    return cleared_ids


# --------------------------------------------------------------------------
# interval geometry (PRD §3.5)
# --------------------------------------------------------------------------

def closed_intersects(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


def occupancy_end(appointment, room):
    return appointment["end_at"] + timedelta(minutes=room["turnover_buffer_minutes"])


def half_open_overlaps(a_start, a_end_excl, b_start, b_end_excl):
    return a_start < b_end_excl and b_start < a_end_excl


def contained_in_available_shift(therapist_id, start_at, end_at):
    for block in shift_blocks_of(therapist_id):
        if block["block_type"] != "AVAILABLE":
            continue
        if block["start_at"] <= start_at and block["end_at"] >= end_at:
            return True
    return False


def has_exclusion_conflict(therapist_id, start_at, end_at):
    for block in shift_blocks_of(therapist_id):
        if block["block_type"] not in ("BREAK", "ADMIN"):
            continue
        if closed_intersects(block["start_at"], block["end_at"], start_at, end_at):
            return True
    return False


def has_appointment_conflict(therapist_id, start_at, end_at, exclude_id=None):
    for appointment in appointments_of_therapist(therapist_id):
        if appointment["id"] == exclude_id:
            continue
        if appointment["schedule_status"] not in NON_TERMINAL_SCHEDULE_STATES:
            continue
        if closed_intersects(appointment["start_at"], appointment["end_at"],
                             start_at, end_at):
            return True
    return False


def has_room_turnover_conflict(room, start_at, end_at, exclude_id=None):
    new_end_excl = end_at + timedelta(minutes=room["turnover_buffer_minutes"])
    for appointment in appointments_of_room(room["id"]):
        if appointment["id"] == exclude_id:
            continue
        status = appointment["schedule_status"]
        if status not in NON_TERMINAL_SCHEDULE_STATES and status != "COMPLETED":
            continue
        other_end_excl = occupancy_end(appointment, room)
        if half_open_overlaps(start_at, new_end_excl,
                              appointment["start_at"], other_end_excl):
            return True
    return False


# --------------------------------------------------------------------------
# therapist_assignment_selector (PRD §3.5)
# --------------------------------------------------------------------------

def assigned_minutes_on_date(therapist_id, reference_date):
    total = 0
    for appointment in appointments_of_therapist(therapist_id):
        if appointment["schedule_status"] not in (
                "REQUESTED", "CONFIRMED", "CHECKED_IN", "IN_SERVICE", "COMPLETED"):
            continue
        if appointment["start_at"].date() != reference_date:
            continue
        total += appointment["scheduled_duration_minutes"]
    return total


def select_therapist(treatment_type, start_at, end_at):
    required_rank = calc.SCOPE_RANK[treatment_type["required_scope_level"]]
    skill = treatment_type["required_skill_code"]
    candidates = []
    for therapist in store.by_created(list(db.therapists.values())):
        if therapist["status"] != "ACTIVE":
            continue
        if valid_practice_license(therapist) is None:
            continue
        rank = best_grant_rank(therapist["id"], skill, required_rank)
        if rank is None:
            continue
        if not contained_in_available_shift(therapist["id"], start_at, end_at):
            continue
        if has_exclusion_conflict(therapist["id"], start_at, end_at):
            continue
        if has_appointment_conflict(therapist["id"], start_at, end_at):
            continue
        candidates.append((therapist, rank))
    if not candidates:
        return None
    reference_date = start_at.date()
    candidates.sort(key=lambda pair: (
        assigned_minutes_on_date(pair[0]["id"], reference_date),
        -pair[1],
        pair[0]["base_hourly_cost_cents"],
        pair[0]["created_at"],
        pair[0]["_seq"],
    ))
    return candidates[0][0]


# --------------------------------------------------------------------------
# path / body reference resolution (rungs 4 and 5)
# --------------------------------------------------------------------------

def resolve(collection, key, error_id, label):
    from errors import ApiError

    row = collection.get(key) if isinstance(key, str) else None
    if row is None:
        raise ApiError(error_id, "%s '%s' was not found." % (label, key))
    return row


def find_therapist(therapist_id):
    import errors

    return resolve(db.therapists, therapist_id, errors.ERR_THERAPIST_NOT_FOUND,
                   "Therapist")


def find_license(license_id):
    import errors

    return resolve(db.licenses, license_id, errors.ERR_LICENSE_NOT_FOUND, "Licence")


def find_certification(certification_id):
    import errors

    return resolve(db.certifications, certification_id,
                   errors.ERR_CERTIFICATION_NOT_FOUND, "Certification grant")


def find_guest(guest_id):
    import errors

    return resolve(db.guests, guest_id, errors.ERR_GUEST_NOT_FOUND, "Guest")


def find_intake_form(form_id):
    import errors

    return resolve(db.intake_forms, form_id, errors.ERR_INTAKE_FORM_NOT_FOUND,
                   "Intake form")


def find_appointment(appointment_id):
    import errors

    return resolve(db.appointments, appointment_id, errors.ERR_APPOINTMENT_NOT_FOUND,
                   "Appointment")


def find_room(room_id):
    import errors

    return resolve(db.rooms, room_id, errors.ERR_ROOM_NOT_FOUND, "Treatment room")


def find_treatment_type(treatment_type_id):
    import errors

    return resolve(db.treatment_types, treatment_type_id,
                   errors.ERR_TREATMENT_TYPE_NOT_FOUND, "Treatment type")


def find_attachment(attachment_id):
    import errors

    return resolve(db.retail_attachments, attachment_id,
                   errors.ERR_RETAIL_ATTACHMENT_NOT_FOUND, "Retail attachment")
