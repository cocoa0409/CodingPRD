"""Cross-entity queries, ledgers and the program's shared cascades."""
import db
from services import calc
from utils import new_entity, sort_created, touch, utc_date, whole_minutes

CANCELLED_STATUSES = (
    "CANCELLED_BY_PERFORMER", "CANCELLED_BY_CLOSURE", "CANCELLED_BY_SUSPENSION",
    "CANCELLED_BY_REVOCATION", "CANCELLED_BY_EXPIRY",
)


# ---------------------------------------------------------------- child rows
def children(store, field, value):
    return sort_created([row for row in db.all_of(store) if row.get(field) == value])


def permit_invoices(permit):
    return children("invoices", "permit_id", permit["id"])


def permit_bookings(permit):
    return children("bookings", "permit_id", permit["id"])


def permit_entries(permit):
    return children("entries", "permit_id", permit["id"])


def performer_permits(performer):
    return children("permits", "performer_id", performer["id"])


def application_auditions(application):
    return children("auditions", "application_id", application["id"])


def audition_scores(audition):
    return children("audition_scores", "audition_id", audition["id"])


def draw_entries(draw):
    return children("entries", "draw_id", draw["id"])


def zone_pitches(zone):
    return children("pitches", "zone_id", zone["id"])


def performer_of(permit):
    return db.get("performers", permit["performer_id"])


def performer_complaints(performer):
    """Every complaint whose permit belongs to this performer, created_at ASC."""
    permit_ids = {permit["id"] for permit in performer_permits(performer)}
    return sort_created([c for c in db.all_of("complaints") if c["permit_id"] in permit_ids])


# ------------------------------------------------------------------- money
def has_past_due_invoice(permit):
    return any(inv["status"] == "PAST_DUE" for inv in permit_invoices(permit))


def has_outstanding_invoice(permit):
    return any(inv["status"] in ("PENDING", "PAST_DUE") for inv in permit_invoices(permit))


def net_fees_paid(permit):
    """The money-ledger invariant, recomputed from the invoice rows."""
    return sum(inv["amount_paid_cents"] - inv["refunded_cents"] for inv in permit_invoices(permit))


# ------------------------------------------------------------------ pitches
def pitch_occupations(pitch_id, exclude_booking_id=None):
    """Sessions in RESERVED/RELOCATED/COMPLETED plus OPEN/DRAWN draw slots."""
    spans = []
    for booking in db.all_of("bookings"):
        if booking["pitch_id"] != pitch_id or booking["id"] == exclude_booking_id:
            continue
        if booking["status"] in calc.OCCUPYING_BOOKING_STATUSES:
            spans.append((booking["start_at"], booking["end_at"]))
    for draw in db.all_of("draws"):
        if draw["pitch_id"] == pitch_id and draw["status"] in calc.OCCUPYING_DRAW_STATUSES:
            spans.append((draw["slot_start_at"], draw["slot_end_at"]))
    return spans


def has_slot_conflict(pitch_id, start_at, end_at, exclude_booking_id=None):
    for existing_start, existing_end in pitch_occupations(pitch_id, exclude_booking_id):
        if calc.conflicts(start_at, end_at, existing_start, existing_end):
            return True
    return False


def daily_session_count(pitch_id, start_at):
    day = utc_date(start_at)
    return sum(
        1 for booking in db.all_of("bookings")
        if booking["pitch_id"] == pitch_id
        and booking["status"] in calc.OCCUPYING_BOOKING_STATUSES
        and utc_date(booking["start_at"]) == day
    )


def booking_cap_inputs(booking):
    pitch = db.get("pitches", booking["pitch_id"])
    zone = db.get("zones", pitch["zone_id"]) if pitch else None
    permit = db.get("permits", booking["permit_id"])
    return zone, pitch, permit


def recompute_booking_cap(booking, instant=None):
    zone, pitch, permit = booking_cap_inputs(booking)
    return calc.effective_noise_cap(
        zone, pitch, booking["amplification_planned"], permit["compliance_status"],
        instant or booking["start_at"],
    )


# ---------------------------------------------------------------- minute ledger
def add_minutes(permit, minutes):
    permit["season_minutes_used"] = permit["season_minutes_used"] + minutes


def release_minutes(permit, minutes):
    permit["season_minutes_used"] = permit["season_minutes_used"] - minutes


def cancel_future_bookings(permit, status, credit_closure=False):
    """Cancel the permit's future RESERVED/RELOCATED sessions, crediting minutes."""
    clock = db.now()
    cancelled = 0
    for booking in permit_bookings(permit):
        if booking["status"] not in ("RESERVED", "RELOCATED"):
            continue
        if not booking["start_at"] > clock:
            continue
        booking["status"] = status
        touch(booking)
        release_minutes(permit, booking["duration_minutes"])
        if credit_closure:
            permit["closure_credit_minutes"] += booking["duration_minutes"]
        cancelled += 1
    return cancelled


def forfeit_submitted_entries(permit):
    for entry in permit_entries(permit):
        if entry["status"] == "SUBMITTED":
            entry["status"] = "FORFEITED"
            touch(entry)


# -------------------------------------------------------------- enforcement
def suspend_permit(permit):
    """The suspension cascade shared by noise escalation and a BARRED standing."""
    permit["compliance_status"] = "SUSPENDED"
    permit["suspended_at"] = db.now()
    cancel_future_bookings(permit, "CANCELLED_BY_SUSPENSION")
    forfeit_submitted_entries(permit)
    touch(permit)


def rescore_performer(performer):
    """Rewrite both conduct figures and the derived standing, then bar-cascade."""
    clock = db.now()
    complaints = [c for c in performer_complaints(performer) if c["status"] == "UPHELD"]
    live, renewal = calc.conduct_scores(complaints, clock)
    standing = calc.standing_for(live)
    changed = (performer["conduct_score"] != live
               or performer["renewal_conduct_score"] != renewal
               or performer["standing"] != standing
               or performer["upheld_complaint_count"] != len(complaints))
    performer["conduct_score"] = live
    performer["renewal_conduct_score"] = renewal
    performer["standing"] = standing
    performer["upheld_complaint_count"] = len(complaints)
    if changed:
        touch(performer)
    if standing == "BARRED":
        for permit in performer_permits(performer):
            if (permit["lifecycle_status"] in ("PENDING_FEE", "ACTIVE", "RENEWAL_PENDING")
                    and permit["compliance_status"] in ("CLEAR", "WARNED")):
                suspend_permit(permit)
    return changed


# ---------------------------------------------------------------- minting
def mint_invoice(permit, invoice_kind, act_type, amplified):
    issued_at = db.now()
    figures = calc.fee_assessment(act_type, amplified, invoice_kind, issued_at)
    invoice = new_entity("invoices", {
        "permit_id": permit["id"],
        "invoice_kind": invoice_kind,
        "fee_variant": figures["fee_variant"],
        "gross_fee_cents": figures["gross_fee_cents"],
        "discount_cents": figures["discount_cents"],
        "admin_fee_cents": figures["admin_fee_cents"],
        "months_covered": figures["months_covered"],
        "coverage_start_month": figures["coverage_start_month"],
        "amount_due_cents": figures["amount_due_cents"],
        "amount_paid_cents": 0,
        "refunded_cents": 0,
        "status": "PENDING",
        "issued_at": issued_at,
        "due_at": calc.invoice_due_at(issued_at),
        "paid_at": None,
    })
    return invoice


def mint_permit_for_application(application):
    """CASCADE L1/L2/L3 of an approval: permit, its INITIAL invoice, write-back."""
    permit = new_entity("permits", {
        "application_id": application["id"],
        "performer_id": application["performer_id"],
        "permit_number": db.next_permit_number(application["season_year"]),
        "season_year": application["season_year"],
        "next_season_year": None,
        "lifecycle_status": "PENDING_FEE",
        "compliance_status": "CLEAR",
        "amplification_endorsed": application["amplification_requested"],
        "season_minutes_used": 0,
        "closure_credit_minutes": 0,
        "noise_violation_count": 0,
        "net_fees_paid_cents": 0,
        "activated_at": None,
        "suspended_at": None,
    })
    invoice = mint_invoice(
        permit, "INITIAL",
        application["requested_act_type"], application["amplification_requested"],
    )
    application["assessed_fee_cents"] = invoice["amount_due_cents"]
    return permit, invoice


def mint_lottery_booking(draw, entry, permit):
    duration = whole_minutes(draw["slot_start_at"], draw["slot_end_at"])
    pitch = db.get("pitches", draw["pitch_id"])
    zone = db.get("zones", pitch["zone_id"])
    amplified = permit["amplification_endorsed"]
    booking = new_entity("bookings", {
        "permit_id": permit["id"],
        "pitch_id": draw["pitch_id"],
        "lottery_entry_id": entry["id"],
        "relocated_from_pitch_id": None,
        "start_at": draw["slot_start_at"],
        "end_at": draw["slot_end_at"],
        "duration_minutes": duration,
        "amplification_planned": amplified,
        "origin": "LOTTERY",
        "effective_noise_cap_db": calc.effective_noise_cap(
            zone, pitch, amplified, permit["compliance_status"], draw["slot_start_at"]),
        "noise_violation_count": 0,
        "status": "RESERVED",
    })
    add_minutes(permit, duration)
    touch(permit)
    return booking


# ------------------------------------------------------------------ revocation
def revoke_permit(permit, refund_mode):
    """The four-level revocation cascade of PRD section 3.5."""
    permit["lifecycle_status"] = "REVOKED"
    for invoice in permit_invoices(permit):
        if invoice["status"] == "PAID":
            refund = calc.revocation_refund(invoice, refund_mode, db.now())
            invoice["refunded_cents"] = refund
            invoice["status"] = "REFUNDED"
            permit["net_fees_paid_cents"] -= refund
            touch(invoice)
        elif invoice["status"] in ("PENDING", "PAST_DUE"):
            invoice["status"] = "VOID"
            touch(invoice)
    cancel_future_bookings(permit, "CANCELLED_BY_REVOCATION")
    forfeit_submitted_entries(permit)
    touch(permit)
