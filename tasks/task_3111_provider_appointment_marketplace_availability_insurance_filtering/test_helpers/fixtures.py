"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints — the runner restarts the server (and resets the database) before
every test, so nothing can be carried over between tests.

Identity threading: every ownership-gated call uses make_<role>_headers with
the actual entity id captured at creation time.

The default logical clock is 2026-09-01T00:00:00Z. All slot times used by
these fixtures are strictly in the future relative to that clock unless the
fixture itself advances the clock.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    bulk_publish_payload,
    create_appointment_type_payload,
    create_attestation_payload,
    create_booking_payload,
    create_complaint_payload,
    create_contact_event_payload,
    create_insurance_plan_payload,
    create_patient_payload,
    create_practice_payload,
    create_provider_payload,
    create_review_payload,
    create_slot_payload,
    generate_invoices_payload,
    respond_complaint_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_ops_admin_headers,
    make_patient_headers,
    make_practice_staff_headers,
    make_provider_headers,
)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slot_time(hours_from_default: float, duration_minutes: int = 30) -> Tuple[str, str]:
    """Return (start_at, end_at) ISO strings offset from the default clock."""
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    start = base + timedelta(hours=hours_from_default)
    end = start + timedelta(minutes=duration_minutes)
    return _iso(start), _iso(end)


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(set_clock_payload(to_iso8601), TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: State Progression
# ---------------------------------------------------------------------------

def create_practice(**overrides) -> Dict[str, Any]:
    resp = api_client.create_practice(create_practice_payload(**overrides), TEST_USERS["ops_admin_headers"])
    return get_success_data(resp, 201)


def create_and_activate_practice(**overrides) -> Dict[str, Any]:
    practice = create_practice(**overrides)
    resp = api_client.activate_practice(practice["id"], TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def create_provider(practice_id: str, **overrides) -> Dict[str, Any]:
    headers = make_practice_staff_headers(practice_id)
    resp = api_client.create_provider(create_provider_payload(practice_id, **overrides), headers)
    return get_success_data(resp, 201)


def activate_provider(provider_id: str) -> Dict[str, Any]:
    resp = api_client.activate_provider(provider_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def create_active_practice_with_provider(
    practice_overrides: Optional[Dict] = None,
    provider_overrides: Optional[Dict] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """ACTIVE practice + ACTIVE provider. Returns (practice, provider)."""
    practice = create_and_activate_practice(**(practice_overrides or {}))
    provider = create_provider(practice["id"], **(provider_overrides or {}))
    provider = activate_provider(provider["id"])
    return practice, provider


# ---------------------------------------------------------------------------
# Tier 2: Entity Hierarchy
# ---------------------------------------------------------------------------

def create_appointment_type(provider_id: str, **overrides) -> Dict[str, Any]:
    headers = make_provider_headers(provider_id)
    resp = api_client.create_appointment_type(provider_id, create_appointment_type_payload(**overrides), headers)
    return get_success_data(resp, 201)


def create_slot(provider_id: str, start_at: str, end_at: str) -> Dict[str, Any]:
    headers = make_provider_headers(provider_id)
    resp = api_client.create_slot(provider_id, create_slot_payload(start_at=start_at, end_at=end_at), headers)
    return get_success_data(resp, 201)


def create_patient(**overrides) -> Dict[str, Any]:
    resp = api_client.create_patient(create_patient_payload(**overrides), TEST_USERS["anonymous_headers"])
    return get_success_data(resp, 201)


def create_plan(**overrides) -> Dict[str, Any]:
    resp = api_client.create_insurance_plan(create_insurance_plan_payload(**overrides), TEST_USERS["ops_admin_headers"])
    return get_success_data(resp, 201)


def create_attestation(provider_id: str, plan_id: str, **overrides) -> Dict[str, Any]:
    headers = make_provider_headers(provider_id)
    resp = api_client.create_attestation(create_attestation_payload(provider_id, plan_id, **overrides), headers)
    return get_success_data(resp, 201)


def verify_attestation(attestation_id: str, decision: str = "VERIFY") -> Dict[str, Any]:
    from .factories import verify_attestation_payload
    resp = api_client.verify_attestation(attestation_id, verify_attestation_payload(decision), TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def create_verified_attestation(provider_id: str, plan_id: str, **overrides) -> Dict[str, Any]:
    att = create_attestation(provider_id, plan_id, **overrides)
    return verify_attestation(att["id"], "VERIFY")


def create_slots(provider_id: str, windows: List[Tuple[str, str]]) -> List[Dict[str, Any]]:
    return [create_slot(provider_id, s, e) for (s, e) in windows]


def setup_bookable_practice(
    copay_cents: int = 10000,
    slot_windows: Optional[List[Tuple[str, str]]] = None,
    practice_overrides: Optional[Dict] = None,
    type_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """ACTIVE practice + ACTIVE provider + one appointment type + N slots.

    Returns dict with keys: practice, provider, type, slots.
    """
    practice, provider = create_active_practice_with_provider(practice_overrides=practice_overrides)
    appt_type = create_appointment_type(provider["id"], **(type_overrides or {"booked_copay_cents": copay_cents}))
    windows = slot_windows if slot_windows is not None else [slot_time(48)]
    slots = create_slots(provider["id"], windows)
    return {"practice": practice, "provider": provider, "type": appt_type, "slots": slots}


# ---------------------------------------------------------------------------
# Tier 3: Full Lifecycle Shortcuts
# ---------------------------------------------------------------------------

def book_slot(slot_id: str, patient_id: str, appointment_type_id: str, **overrides) -> Dict[str, Any]:
    headers = make_patient_headers(patient_id)
    resp = api_client.create_booking(slot_id, create_booking_payload(patient_id, appointment_type_id, **overrides), headers)
    return get_success_data(resp, 201)


def check_in_booking(booking_id: str, practice_id: str) -> Dict[str, Any]:
    resp = api_client.check_in_booking(booking_id, make_practice_staff_headers(practice_id))
    return get_success_data(resp)


def complete_booking(booking_id: str, practice_id: str) -> Dict[str, Any]:
    resp = api_client.complete_booking(booking_id, make_practice_staff_headers(practice_id))
    return get_success_data(resp)


def mark_no_show(booking_id: str, practice_id: str) -> Dict[str, Any]:
    resp = api_client.mark_no_show(booking_id, make_practice_staff_headers(practice_id))
    return get_success_data(resp)


def cancel_booking_as_patient(booking_id: str, patient_id: str) -> Dict[str, Any]:
    resp = api_client.cancel_booking(booking_id, make_patient_headers(patient_id))
    return get_success_data(resp)


def setup_completed_booking(
    copay_cents: int = 10000,
    slot_offset_hours: float = 48,
    patient_overrides: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Bookable practice/provider/type, one slot, one patient whose booking is
    COMPLETED (clock advanced past start, check-in + complete).

    Returns dict with keys: practice, provider, type, slot, patient, booking.
    """
    ctx = setup_bookable_practice(copay_cents=copay_cents, slot_windows=[slot_time(slot_offset_hours)])
    patient = create_patient(**(patient_overrides or {}))
    booking = book_slot(ctx["slots"][0]["id"], patient["id"], ctx["type"]["id"])
    start = datetime.fromisoformat(ctx["slots"][0]["start_at"].replace("Z", "+00:00"))
    set_clock(_iso(start + timedelta(minutes=5)))
    check_in_booking(booking["id"], ctx["practice"]["id"])
    booking = complete_booking(booking["id"], ctx["practice"]["id"])
    ctx.update({"patient": patient, "booking": booking})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: Accumulation / Threshold Targeting
# ---------------------------------------------------------------------------

def generate_invoice(practice_id: str, period: str = "2026-09") -> Dict[str, Any]:
    resp = api_client.generate_invoices(generate_invoices_payload(practice_id, period), TEST_USERS["ops_admin_headers"])
    return get_success_data(resp, 201)


def setup_invoiced_practice(num_bookings: int, copay_cents: int = 10000, period: str = "2026-09") -> Dict[str, Any]:
    """PER_BOOKING practice with `num_bookings` ATTRIBUTED bookings swept into a
    single ISSUED invoice.

    Slots are laid out starting 48h after the default clock, one hour apart,
    rolling over days as needed. Bookings are made at the default clock so
    their created_at falls inside period 2026-09.

    Returns dict with keys: practice, provider, type, slots, patient,
    bookings, invoice.
    """
    windows = []
    for i in range(num_bookings):
        # 48h base offset keeps every slot comfortably beyond the 24h lead.
        windows.append(slot_time(48 + i))
    ctx = setup_bookable_practice(copay_cents=copay_cents, slot_windows=windows)
    patient = create_patient()
    bookings = [book_slot(s["id"], patient["id"], ctx["type"]["id"]) for s in ctx["slots"]]
    invoice = generate_invoice(ctx["practice"]["id"], period)
    ctx.update({"patient": patient, "bookings": bookings, "invoice": invoice})
    return ctx


def list_charges_for_invoice(invoice_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_charges(TEST_USERS["ops_admin_headers"], params={"invoice_id": invoice_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)


def list_charges_for_booking(booking_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_charges(TEST_USERS["ops_admin_headers"], params={"booking_id": booking_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)


def list_ledger_entries_for_invoice(invoice_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_ledger_entries(TEST_USERS["ops_admin_headers"], params={"invoice_id": invoice_id, "limit": 100})
    data = get_success_data(resp)
    return data if isinstance(data, list) else data.get("data", data)


def get_patient(patient_id: str) -> Dict[str, Any]:
    resp = api_client.get_patient(patient_id, make_patient_headers(patient_id))
    return get_success_data(resp)


def get_booking(booking_id: str) -> Dict[str, Any]:
    resp = api_client.get_booking(booking_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def get_slot(slot_id: str) -> Dict[str, Any]:
    resp = api_client.get_slot(slot_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def get_provider(provider_id: str) -> Dict[str, Any]:
    resp = api_client.get_provider(provider_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def get_attestation(attestation_id: str) -> Dict[str, Any]:
    resp = api_client.get_attestation(attestation_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def get_invoice(invoice_id: str) -> Dict[str, Any]:
    resp = api_client.get_invoice(invoice_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


def get_charge(charge_id: str) -> Dict[str, Any]:
    resp = api_client.get_charge(charge_id, TEST_USERS["ops_admin_headers"])
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: Strikes / reliability shortcuts
# ---------------------------------------------------------------------------

def give_no_show_strike(ctx: Dict[str, Any], booking: Dict[str, Any]) -> Dict[str, Any]:
    """Mark a booking NO_SHOW. Advances the clock to just past the booking's
    start first (no-show requires now >= start_at)."""
    start = datetime.fromisoformat(booking["start_at"].replace("Z", "+00:00"))
    set_clock(_iso(start + timedelta(minutes=5)))
    return mark_no_show(booking["id"], ctx["practice"]["id"])
