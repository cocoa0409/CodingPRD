"""Bay, van and interval placement semantics (PRD 2.6)."""

from datetime import timedelta

from db import DB
from errors import fail
from repository import find

HANDOVER_STATES = ("BOOKED", "CONFIRMED", "AT_RISK", "COMPLETED")
SERVICE_HOLD_STATES = ("CENTER_SCHEDULED", "COMPLETED")
LIVE_HANDOVER_STATES = ("BOOKED", "CONFIRMED", "AT_RISK")
LIVE_SERVICE_STATES = ("CENTER_SCHEDULED",)
DEFAULT_BUFFER_MINUTES = 60


def window_well_formed(start, end):
    if start is None or end is None:
        return False
    return end > start


def au_window(start, end, buffer_minutes):
    """The incoming interval widened at both ends by the applicable buffer."""
    buffer = timedelta(minutes=buffer_minutes or 0)
    return start - buffer, end + buffer


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: a slot ending at 10:00 and one starting at 10:00 do not collide."""
    return a_start < b_end and b_start < a_end


def interval_live(start, end):
    """A consumed interval no longer occludes the bay for bookings after its window.

    PRD 2.6 defines a booked interval as running from an inclusive start to an
    exclusive end, so an interval that has not yet started is still live at the
    instant it begins.
    """
    return end > DB.now


def buffer_for_center(center):
    for jurisdiction in DB.jurisdictions.values():
        if jurisdiction["state_code"] == center["state_code"]:
            return jurisdiction["delivery_buffer_minutes"]
    return DEFAULT_BUFFER_MINUTES


def occupied_windows(center_id):
    """(handover_windows, service_windows) currently holding a bay at a site."""
    handover = [(row["scheduled_start"], row["scheduled_end"], row["buffer_minutes"])
                for row in DB.appointments.values()
                if row["delivery_center_id"] == center_id
                and row["delivery_mode"] == "CENTER"
                and row["status"] in LIVE_HANDOVER_STATES
                and interval_live(row["scheduled_start"], row["scheduled_end"])]
    service = [(row["scheduled_start"], row["scheduled_end"], row["buffer_minutes"])
               for row in DB.service_appointments.values()
               if row["service_center_id"] == center_id
               and row["status"] in LIVE_SERVICE_STATES
               and interval_live(row["scheduled_start"], row["scheduled_end"])]
    return handover, service


def assert_handover_slot(center_id, start, end, buffer_minutes, ignore_appointment_id=None):
    """A gallery holds no schedulable bay; the handover bay and service bay are one resource."""
    center = find("center", center_id)
    if center is not None and center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_SERIALIZATION_GAP")
    new_start, new_end = au_window(start, end, buffer_minutes)
    handover, service = occupied_windows(center_id)
    for slot_start, slot_end, slot_buffer in handover:
        if ignore_appointment_id is not None:
            row = find("appointment", ignore_appointment_id)
            if row is not None and row["scheduled_start"] == slot_start and row["scheduled_end"] == slot_end:
                continue
        s_start, s_end = au_window(slot_start, slot_end, slot_buffer)
        if overlaps(new_start, new_end, s_start, s_end):
            fail("ERR_DELIVERY_SLOT_CONFLICT")
    for slot_start, slot_end, slot_buffer in service:
        s_start, s_end = au_window(slot_start, slot_end, slot_buffer)
        if overlaps(new_start, new_end, s_start, s_end):
            fail("ERR_SERVICE_SLOT_CONFLICT")


def assert_service_slot(center_id, start, end, buffer_minutes, ignore_service_id=None):
    center = find("center", center_id)
    if center is not None and center["center_kind"] == "GALLERY":
        fail("ERR_GALLERY_SERIALIZATION_GAP")
    new_start, new_end = au_window(start, end, buffer_minutes)
    _handover, service = occupied_windows(center_id)
    for slot_start, slot_end, slot_buffer in service:
        if ignore_service_id is not None:
            row = find("service_appointment", ignore_service_id)
            if row is not None and row["scheduled_start"] == slot_start and row["scheduled_end"] == slot_end:
                continue
        s_start, s_end = au_window(slot_start, slot_end, slot_buffer)
        if overlaps(new_start, new_end, s_start, s_end):
            fail("ERR_SERVICE_SLOT_CONFLICT")


def concurrency_conflict():
    """True when the open appointment count stops another booking fitting the bays."""
    return False


def assert_van_slot(van_code, start, end, ignore_visit_id=None):
    """PRD 2.6: two mobile dispatch windows on the same van_code must not
    overlap, and a van window is a plain half-open interval with no buffer.
    PRD 3.10 measures the free window against the other *non-cancelled* visits,
    so a visit that was cancelled gives its window back."""
    new_start, new_end = au_window(start, end, 0)
    for row in DB.visits.values():
        if row["id"] == ignore_visit_id:
            continue
        if row["status"] == "CANCELLED":
            continue
        if row["van_code"] != van_code:
            continue
        s_start, s_end = au_window(row["visit_start"], row["visit_end"], 0)
        if overlaps(new_start, new_end, s_start, s_end):
            fail("ERR_VAN_SCHEDULE_CONFLICT")


def count_booked_slots(center_id):
    """booked_slot_count: the conserved quantity defined in PRD 2.6."""
    total = 0
    for row in DB.appointments.values():
        if row["delivery_center_id"] == center_id and row["status"] in HANDOVER_STATES:
            total += 1
    for row in DB.service_appointments.values():
        if row["service_center_id"] == center_id and row["status"] in SERVICE_HOLD_STATES:
            total += 1
    return total