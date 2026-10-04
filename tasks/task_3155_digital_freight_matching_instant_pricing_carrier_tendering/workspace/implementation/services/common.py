"""Cross-cutting lookups and derived-field reconciliation."""

from datetime import datetime, timedelta

from constants import (
    COMMODITY_LIABILITY_CAP, RISK_BREACH_PENALTY, RISK_CLAIM_PENALTY,
    RISK_CLAWBACK_PENALTY, RISK_SLACK_MINUTES_PER_POINT, round4, round_half_up,
    d, minutes_between, utc,
)
from db import clock_now, db, touch
from errors import ApiError


# --------------------------------------------------------------------------
# Resolvers — each answers the not-found error specific to the kind of id.
# --------------------------------------------------------------------------
def get_shipper(shipper_id):
    row = db.shippers.get(shipper_id)
    if row is None:
        raise ApiError("ERR_SHIPPER_NOT_FOUND")
    return row


def get_carrier(carrier_id):
    row = db.carriers.get(carrier_id)
    if row is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    return row


def get_equipment(equipment_id):
    row = db.equipment.get(equipment_id)
    if row is None:
        raise ApiError("ERR_EQUIPMENT_NOT_FOUND")
    return row


def get_facility(facility_id):
    row = db.facilities.get(facility_id)
    if row is None:
        raise ApiError("ERR_FACILITY_NOT_FOUND")
    return row


def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return row


def get_load(load_id):
    row = db.loads.get(load_id)
    if row is None:
        raise ApiError("ERR_LOAD_NOT_FOUND")
    return row


def get_quote(quote_id):
    row = db.quotes.get(quote_id)
    if row is None:
        raise ApiError("ERR_QUOTE_NOT_FOUND")
    return row


def get_booking(booking_id):
    row = db.bookings.get(booking_id)
    if row is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    return row


def get_appointment(appointment_id):
    row = db.appointments.get(appointment_id)
    if row is None:
        raise ApiError("ERR_APPOINTMENT_NOT_FOUND")
    return row


def get_detention(detention_id):
    row = db.detention_events.get(detention_id)
    if row is None:
        raise ApiError("ERR_DETENTION_NOT_FOUND")
    return row


def get_ping(ping_id):
    row = db.tracking_pings.get(ping_id)
    if row is None:
        raise ApiError("ERR_LOAD_NOT_FOUND")
    return row


def get_status_event(event_id):
    row = db.status_events.get(event_id)
    if row is None:
        raise ApiError("ERR_LOAD_NOT_FOUND")
    return row


def get_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return row


def get_settlement(settlement_id):
    row = db.settlements.get(settlement_id)
    if row is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND")
    return row


# --------------------------------------------------------------------------
# Derived fields
# --------------------------------------------------------------------------
def compute_risk_score(carrier):
    """PRD 2.10 — 100 less 8/claim-breached-load, 12/approved-or-settled
    claim, 5/clawback, clamped into [0, 100], one decimal place."""
    breached = 0
    for load in db.loads.values():
        if load["carrier_id"] == carrier["id"] and load["pickup_breach_flag"]:
            breached += 1
    approved = 0
    for claim in db.claims.values():
        if claim["carrier_id"] == carrier["id"] and claim["status"] in ("APPROVED", "SETTLED"):
            approved += 1
    raw = (100
           - RISK_BREACH_PENALTY * breached
           - RISK_CLAIM_PENALTY * approved
           - RISK_CLAWBACK_PENALTY * carrier.get("claims_clawback_count", 0))
    clamped = max(0, min(100, raw))
    return round(float(d(clamped).quantize(d("0.1"))), 1)


def refresh_carrier_score(carrier, bump=False):
    score = compute_risk_score(carrier)
    carrier["operational_risk_score"] = score
    if bump:
        touch(carrier)
    return score


def refresh_shipper(shipper):
    shipper["credit_available_cents"] = shipper["credit_limit_cents"] - shipper["credit_used_cents"]
    shipper["load_credits_available"] = shipper["load_credit_limit"] - shipper["load_credits_committed"]
    return shipper


def refresh_contract(contract):
    """PRD 3.7 — draws inside the half-open ISO week of the most recent draw."""
    draws = []
    for load in db.loads.values():
        if load["lane_contract_id"] != contract["id"]:
            continue
        if load["status"] not in ("BOOKED", "IN_TRANSIT", "DELIVERED", "INVOICED", "PAID"):
            continue
        draws.append(load)
    draws.sort(key=lambda row: row["created_at"])
    if draws:
        start = iso_week_monday(draws[-1]["created_at"])
        end = start + timedelta(days=7)
        contract["period_start"] = start
        contract["loads_committed_this_period"] = sum(
            1 for load in draws if start <= load["created_at"] < end)
    else:
        contract["loads_committed_this_period"] = 0
    # PRD 3.7 — a contract whose term has passed reads EXPIRED.
    if contract["status"] == "ACTIVE" and clock_now() >= utc(contract["end_date"]):
        contract["status"] = "EXPIRED"
    return contract


def iso_week_monday(instant):
    """Monday 00:00:00Z of the ISO week containing `instant`."""
    instant = utc(instant)
    midnight = instant.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=instant.weekday())


def refresh_quote(quote):
    load = db.loads.get(quote["load_id"])
    if load is not None:
        quote["effective_miles"] = max(load["distance_miles"], 50)
    miles = quote["effective_miles"] or 50
    quote["quoted_cents_per_mile"] = round4(d(quote["base_rate_cents"]) / d(miles))
    return quote


def load_accessorial_total(load_id):
    total = 0
    for event in db.detention_events.values():
        if event["load_id"] == load_id and event["status"] in ("OPEN", "CLOSED"):
            total += event["detention_charge_cents"]
    return total


def load_effective_rate(load):
    """PRD 3.3/3.7 — the price in force for a load."""
    if load["booked_rate_cents"] is not None:
        return load["booked_rate_cents"]
    return load["posted_rate_cents"]


def refresh_load_derived(load, bump=False):
    """Reconcile the load's derived figures and the quote-expiry transition."""
    expire_quotes_for(load["id"])
    load["accessorial_total_cents"] = load_accessorial_total(load["id"])
    shipper = db.shippers.get(load["shipper_id"])
    if shipper is not None:
        load["shipper_version"] = shipper["version"]
    load["projected_delay_minutes"] = compute_projected_delay(load)
    if bump:
        touch(load)
    return load


def expire_quotes_for(load_id):
    """PRD 3.2 — a quote expires once the clock reaches its deadline."""
    now = clock_now()
    for quote in db.quotes.values():
        if quote["load_id"] != load_id:
            continue
        if quote["status"] in ("ACTIVE", "VIEWED") and utc(quote["acceptance_deadline"]) <= now:
            quote["status"] = "EXPIRED"
            touch(quote)


def expire_all_quotes():
    now = clock_now()
    for quote in db.quotes.values():
        if quote["status"] in ("ACTIVE", "VIEWED") and utc(quote["acceptance_deadline"]) <= now:
            quote["status"] = "EXPIRED"
            touch(quote)


def compute_projected_delay(load):
    """PRD 3.6 — only the greatest-sequence ping contributes."""
    pings = [p for p in db.tracking_pings.values() if p["load_id"] == load["id"]]
    if not pings:
        return 0
    newest = max(pings, key=lambda p: p["sequence"])
    if newest["eta_utc"] is None:
        return 0
    carrier = db.carriers.get(load["carrier_id"]) if load["carrier_id"] else None
    risk = carrier["operational_risk_score"] if carrier else 100.0
    risk = max(0.0, min(100.0, float(risk)))
    slack = round_half_up(d(100 - risk) * RISK_SLACK_MINUTES_PER_POINT)
    projected_eta = utc(newest["eta_utc"]) + _delta_minutes(slack)
    deadline = load["delivery_deadline"]
    if deadline is None:
        return 0
    if projected_eta <= utc(deadline):
        return 0
    return int((projected_eta - utc(deadline)).total_seconds() // 60)


def _delta_minutes(minutes):
    return timedelta(minutes=minutes)


def approved_claims_for(load_id):
    return [c for c in db.claims.values()
            if c["load_id"] == load_id and c["status"] in ("APPROVED", "SETTLED")]


def active_settlement_for_load(load_id):
    """The settlement a cascade touches: the live (non-reversed) row."""
    rows = [s for s in db.settlements.values()
            if s["load_id"] == load_id and s["settlement_status"] != "REVERSED"]
    if not rows:
        return None
    rows.sort(key=lambda row: row["created_at"])
    return rows[-1]


def live_quotes_for(load_id):
    """Quotes still on a board: ACTIVE or VIEWED and not yet past deadline."""
    now = clock_now()
    rows = []
    for quote in db.quotes.values():
        if quote["load_id"] != load_id:
            continue
        if quote["status"] not in ("ACTIVE", "VIEWED"):
            continue
        if utc(quote["acceptance_deadline"]) > now:
            rows.append(quote)
    return rows


def append_status_event(load_id, event_type, source, note=None):
    """Append to a load's audit trail (PRD 3.6)."""
    from db import mint_id
    now = clock_now()
    event = {
        "id": mint_id(),
        "load_id": load_id,
        "event_type": event_type,
        "source": source,
        "occurred_at": now,
        "note": note,
        "created_at": now,
    }
    db.status_events[event["id"]] = event
    return event


def open_detention_for_appointment(appointment_id):
    for event in db.detention_events.values():
        if event["appointment_id"] == appointment_id and event["status"] == "OPEN":
            return event
    return None


def refresh_live_settlement_for_load(load_id):
    """Re-strike the load's ACCRUED or READY settlement after a cascade."""
    from services.settlements import refresh_live_settlement_for_load as _refresh
    return _refresh(load_id)


def settle_minutes_floor(later, earlier):
    return minutes_between(later, earlier)


def is_iso(value):
    return isinstance(value, datetime)