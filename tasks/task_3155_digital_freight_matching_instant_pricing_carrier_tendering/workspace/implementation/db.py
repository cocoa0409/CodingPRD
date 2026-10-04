"""In-memory data store, logical clock and shared record helpers.

Storage is process-local and wiped on every boot: nothing is ever written to
disk, and no entity is created at import time.  Every row a test needs is
constructed through the declared API surface.
"""

import random
import string
import uuid
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Logical clock — PRD 3.10: starts at exactly 2026-09-01T00:00:00Z and never
# falls back to real wall-clock time before the first call.
# --------------------------------------------------------------------------
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_START}


def clock_now():
    return _clock["now"]


def set_clock(instant):
    _clock["now"] = instant


def reset_clock():
    _clock["now"] = CLOCK_START


# --------------------------------------------------------------------------
# Timestamp helpers — ISO 8601 UTC with exactly three fractional digits.
# --------------------------------------------------------------------------
def fmt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def mint_id():
    return str(uuid.uuid4())


def mint_request_id():
    suffix = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(12))
    return "req_" + suffix


# --------------------------------------------------------------------------
# Collections.  Ordered dicts: insertion order is the creation order used by
# the default list ordering ("creation timestamp ascending", PRD 2.3).
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.shippers = {}
        self.carriers = {}
        self.equipment = {}
        self.facilities = {}
        self.contracts = {}
        self.loads = {}
        self.quotes = {}
        self.bookings = {}
        self.appointments = {}
        self.detention_events = {}
        self.tracking_pings = {}
        self.status_events = {}
        self.claims = {}
        self.settlements = {}
        # idempotency: key -> stored response payload
        self.void_keys = {}
        self.payout_keys = {}

    def wipe(self):
        self.__init__()


db = Store()


def reset_all():
    db.wipe()
    reset_clock()


# --------------------------------------------------------------------------
# Common resource properties (PRD 2.5)
# --------------------------------------------------------------------------
def touch(row):
    """An accepted mutation refreshes updated_at and bumps version by one."""
    row["updated_at"] = clock_now()
    row["version"] = row.get("version", 1) + 1


def _mark(row):
    row["_new"] = True
    return row


# --------------------------------------------------------------------------
# Field ordering — the JSON key order the narratives present.
# --------------------------------------------------------------------------
ORDER = {
    "Shipper": [
        "id", "name", "billing_state_code", "payment_terms_days", "quick_pay_discount_pct",
        "credit_limit_cents", "credit_used_cents", "credit_available_cents",
        "load_credit_limit", "load_credits_committed", "load_credits_available",
        "blocked_carrier_ids", "breached_pickup_count", "last_repriced_lane",
        "status", "created_at", "updated_at", "version",
    ],
    "Carrier": [
        "id", "legal_name", "mc_number", "dot_number", "operating_authority_status",
        "authority_verified_at", "insurance_expires_at", "insurance_liability_limit_cents",
        "cargo_coverage_limit_cents", "insurance_attested_at", "certificate_reference",
        "safety_score", "equipment_types", "claims_clawback_count",
        "operational_risk_score", "suspension_reason", "status",
        "created_at", "updated_at", "version",
    ],
    "CarrierEquipment": [
        "id", "carrier_id", "equipment_type", "unit_number", "driver_name", "status",
        "created_at", "updated_at", "version",
    ],
    "Facility": [
        "id", "name", "state_code", "dock_capacity", "default_appointment_minutes",
        "free_dwell_minutes", "detention_rate_per_hour_cents", "docks_committed_today",
        "status", "created_at", "updated_at", "version",
    ],
    "LaneContract": [
        "id", "shipper_id", "origin_facility_id", "destination_facility_id",
        "equipment_type", "committed_weekly_volume", "committed_rate_cents",
        "accessorial_allowance_cents", "start_date", "end_date",
        "loads_committed_this_period", "period_start", "contract_carrier_ids",
        "status", "created_at", "updated_at", "version",
    ],
    "Load": [
        "id", "shipper_id", "origin_facility_id", "destination_facility_id",
        "lane_contract_id", "lane_key", "pricing_mode", "market_band", "equipment_type",
        "commodity", "weight_lbs", "declared_cargo_value_cents", "distance_miles",
        "pickup_window_start", "pickup_window_end", "delivery_deadline",
        "posted_rate_cents", "booked_rate_cents", "reprice_count", "repost_count",
        "carrier_id", "equipment_id", "accessorial_total_cents", "actual_pickup_at",
        "pickup_breach_flag", "tracking_status_rank", "shipper_version",
        "projected_delay_minutes", "status", "created_at", "updated_at", "version",
    ],
    "RateQuote": [
        "id", "load_id", "quote_kind", "base_rate_cents", "repriced_rate_cents",
        "effective_miles", "quoted_cents_per_mile", "market_level_cents_per_mile",
        "acceptance_deadline", "viewed_carrier_ids", "declined_carrier_ids",
        "min_rate_cents", "status", "created_at", "updated_at", "version",
    ],
    "Booking": [
        "id", "load_id", "carrier_id", "rate_quote_id", "equipment_id",
        "agreed_rate_cents", "booked_at", "booking_window_start", "booking_window_end",
        "appointment_id", "contract_lane_draw", "quick_pay_elected",
        "quick_pay_discount_cents", "settled_at", "status",
        "created_at", "updated_at", "version",
    ],
    "AppointmentSlot": [
        "id", "facility_id", "load_id", "carrier_id", "slot_kind", "dock_position",
        "window_start", "window_end", "scheduled_date", "status",
        "created_at", "updated_at", "version",
    ],
    "DetentionEvent": [
        "id", "appointment_id", "facility_id", "load_id", "carrier_id", "arrived_at",
        "departed_at", "dwell_minutes", "billable_detention_minutes",
        "detention_charge_cents", "status", "created_at", "updated_at", "version",
    ],
    "TrackingPing": [
        "id", "load_id", "carrier_id", "sequence", "reported_status", "status_rank",
        "location_code", "eta_utc", "recorded_at", "created_at",
    ],
    "StatusEvent": [
        "id", "load_id", "event_type", "source", "occurred_at", "note", "created_at",
    ],
    "ClaimsCase": [
        "id", "load_id", "carrier_id", "claimed_amount_cents", "damage_description",
        "filed_by_role", "liability_limit_cents", "price_cap_cents",
        "provisional_liability_cents", "approved_amount_cents", "review_rounds",
        "escalated", "status", "created_at", "updated_at", "version",
    ],
    "CarrierSettlement": [
        "id", "carrier_id", "booking_id", "load_id", "line_haul_cents", "accessorial_cents",
        "claims_deduction_cents", "gross_payable_cents", "quick_pay_discount_cents",
        "net_payable_cents", "payout_due_at", "paid_at", "reversal_of_settlement_id",
        "settlement_status", "created_at", "updated_at", "version",
    ],
}

DATETIME_FIELDS = frozenset([
    "created_at", "updated_at", "authority_verified_at", "insurance_expires_at",
    "insurance_attested_at", "start_date", "end_date", "pickup_window_start",
    "pickup_window_end", "delivery_deadline", "actual_pickup_at", "acceptance_deadline",
    "booked_at", "booking_window_start", "booking_window_end", "settled_at",
    "window_start", "window_end", "scheduled_date", "arrived_at", "departed_at",
    "eta_utc", "recorded_at", "occurred_at", "paid_at", "payout_due_at", "period_start",
])


def serialize(kind, row):
    """Render a row for the wire: ISO timestamps, scaffold field order.

    Only the declared fields of the entity are emitted; internal bookkeeping
    keys (anything not listed in ORDER) never reach the wire.
    """
    out = {}
    for key in ORDER.get(kind, []):
        if key not in row:
            continue
        value = row[key]
        out[key] = fmt(value) if key in DATETIME_FIELDS else value
    return out