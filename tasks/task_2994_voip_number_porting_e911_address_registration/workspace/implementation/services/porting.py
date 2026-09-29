"""CSR comparison, the firm-order-commitment floor, cutover-window overlap and
the reject/cancel unwind cascade (PRD 3.4 - 3.6)."""
from datetime import datetime, timedelta, timezone

import store
import util
from common import bump
from errors import ApiError
from services import derive

WEIGHTS = (
    ("account_number", "claimed_account_number", "account_number_on_file", 40),
    ("billing_name", "claimed_billing_name", "billing_name_on_file", 15),
    ("pin", "claimed_pin", "pin_on_file", 30),
    ("service_address_line1", "claimed_address_line1", "address_line1_on_file", 10),
    ("service_zip", "claimed_zip", "zip_on_file", 5),
)

THRESHOLD_STRICT = 100
THRESHOLD_RELAXED = 85
MAX_RESUBMISSIONS = 2
RESUBMITTABLE_REJECTION_CODES = (
    "CSR_MISMATCH", "PIN_INVALID", "ACCOUNT_NOT_FOUND", "PENDING_BALANCE",
)
REJECTION_CODES = (
    "CSR_MISMATCH", "PIN_INVALID", "ACCOUNT_NOT_FOUND", "PENDING_BALANCE",
    "NUMBER_NOT_PORTABLE", "DUPLICATE_REQUEST",
)
MIN_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 480


def evaluate_csr(port_request, snapshot_values, carrier):
    """Weighted comparison of the subscriber's claim against the carrier record."""
    match_points = 0
    mismatch_fields = []
    for name, claimed_field, file_field, weight in WEIGHTS:
        claimed = util.normalize_alnum(port_request[claimed_field])
        on_file = util.normalize_alnum(snapshot_values[file_field])
        if claimed == on_file:
            match_points += weight
        else:
            mismatch_fields.append(name)
    threshold = THRESHOLD_STRICT if carrier["csr_match_policy"] == "STRICT" else THRESHOLD_RELAXED
    status = "MATCHED" if match_points >= threshold else "MISMATCHED"
    return match_points, threshold, status, sorted(mismatch_fields)


def earliest_cutover_floor(validated_at, foc_business_days):
    """Midnight UTC of the nth business day strictly after the validation date."""
    cursor = datetime(validated_at.year, validated_at.month, validated_at.day,
                      tzinfo=timezone.utc)
    counted = 0
    while counted < foc_business_days:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() <= 4:
            counted += 1
    return datetime(cursor.year, cursor.month, cursor.day, 0, 0, 0, 0, tzinfo=timezone.utc)


def window_length_minutes(window_start, window_end):
    return int((window_end - window_start).total_seconds() // 60)


def check_window_length(window_start, window_end):
    if window_end <= window_start:
        raise ApiError("ERR_CUTOVER_WINDOW_LENGTH_INVALID",
                       "window_end must be strictly later than window_start.")
    length = window_length_minutes(window_start, window_end)
    if length < MIN_WINDOW_MINUTES or length > MAX_WINDOW_MINUTES:
        raise ApiError("ERR_CUTOVER_WINDOW_LENGTH_INVALID",
                       "The cutover window must run between 60 and 480 minutes.")


def check_slot_overlap(carrier, window_start, window_end):
    """Buffer-expanded half-open overlap scan over live slots of the same carrier."""
    buffer = timedelta(minutes=carrier["porting_buffer_minutes"])
    blocking = [s for s in store.cutover_slots.values()
                if s["carrier_id"] == carrier["id"] and s["status"] in ("OPEN", "BOOKED")]
    blocking.sort(key=lambda s: (s["window_start"], s["created_at"], s["_seq"]))
    for slot in blocking:
        expanded_start = slot["window_start"] - buffer
        expanded_end = slot["window_end"] + buffer
        if window_start < expanded_end and expanded_start < window_end:
            raise ApiError("ERR_CUTOVER_SLOT_OVERLAP",
                           "The candidate window collides with a live slot of this carrier.")


def booked_slot_for(port_request_id):
    for slot in store.cutover_slots.values():
        if slot["booked_port_request_id"] == port_request_id and slot["status"] == "BOOKED":
            return slot
    return None


def live_bridges_for(port_request_id):
    rows = [b for b in store.temporary_bridges.values()
            if b["port_request_id"] == port_request_id
            and b["status"] in ("PROVISIONED", "ACTIVE")]
    return sorted(rows, key=lambda b: (b["created_at"], b["_seq"]))


def _release_reservation(bridge, reason):
    """Release the reservation a bridge consumed and settle its phone number."""
    reservation = store.number_reservations.get(bridge["reservation_id"])
    if reservation is None or reservation["status"] not in ("HELD", "CONSUMED"):
        return
    reservation["status"] = "RELEASED"
    reservation["released_reason"] = reason
    bump(reservation)
    number = store.phone_numbers.get(reservation["number_id"])
    if number is None or number["status"] != "RESERVED":
        return
    if derive.other_held_reservation_exists(number["id"], reservation["id"]):
        return
    if reason == "BRIDGE_ORPHANED":
        derive.park_number(number)
    else:
        number["status"] = "AVAILABLE"
        bump(number)
    block = store.number_blocks.get(number["block_id"])
    if block is not None:
        derive.recompute_census(block)


def unwind_cascade(port_request):
    """The slot -> bridge -> reservation -> number -> block chain of a reject or cancel.

    Each link fires only because the previous one did, and only if the row it
    needs exists.
    """
    slot = booked_slot_for(port_request["id"])
    if slot is None:
        return
    slot["status"] = "RELEASED"
    slot["booked_port_request_id"] = None
    slot["booked_at"] = None
    bump(slot)
    for bridge in live_bridges_for(port_request["id"]):
        bridge["status"] = "ORPHANED"
        bridge["released_at"] = store.now()
        bump(bridge)
        _release_reservation(bridge, "BRIDGE_ORPHANED")


def complete_cascade(port_request):
    """Consume the booked slot and release any ACTIVE bridge of a completing port."""
    slot = booked_slot_for(port_request["id"])
    if slot is not None:
        slot["status"] = "CONSUMED"
        bump(slot)
    active = [b for b in store.temporary_bridges.values()
              if b["port_request_id"] == port_request["id"] and b["status"] == "ACTIVE"]
    for bridge in sorted(active, key=lambda b: (b["created_at"], b["_seq"])):
        bridge["status"] = "RELEASED"
        bridge["released_at"] = store.now()
        bump(bridge)
        _release_reservation(bridge, "CUTOVER_COMPLETED")


def supersede_current_snapshot(port_request_id):
    for snap in store.csr_snapshots.values():
        if snap["port_request_id"] == port_request_id and snap["superseded_at"] is None:
            snap["superseded_at"] = store.now()
            bump(snap)
