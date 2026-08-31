"""Derived counters, ledger plumbing and the cascade helpers (PRD 2.6, 2.9)."""

from decimal import Decimal

import calc
from errors import ApiError
from store import db, fmt_dt, new_record, now, sorted_rows, stamp, touch
from validation import parse_date, parse_datetime


# --------------------------------------------------------------- lookups
def rows(table):
    return list(getattr(db, table).values())


def engagement_bookings(engagement_id):
    return sorted_rows([b for b in db.appearance_bookings.values()
                        if b["engagement_id"] == engagement_id])


def engagement_deliverables(engagement_id):
    return sorted_rows([d for d in db.deliverables.values()
                        if d["engagement_id"] == engagement_id])


def engagement_ledger(engagement_id):
    return sorted_rows([e for e in db.ledger_entries.values()
                        if e["engagement_id"] == engagement_id])


def engagement_grants(engagement_id):
    return sorted_rows([g for g in db.exclusivity_grants.values()
                        if g["engagement_id"] == engagement_id])


def athlete_grants(athlete_id):
    return sorted_rows([g for g in db.exclusivity_grants.values()
                        if g["athlete_id"] == athlete_id])


def athlete_bookings(athlete_id):
    out = []
    for booking in db.appearance_bookings.values():
        engagement = db.engagements.get(booking["engagement_id"])
        if engagement and engagement["athlete_id"] == athlete_id:
            out.append(booking)
    return sorted_rows(out)


def deliverable_disclosures(deliverable_id):
    return sorted_rows([r for r in db.disclosure_records.values()
                        if r["deliverable_id"] == deliverable_id])


def engagement_statements(engagement_id):
    return sorted_rows([p for p in db.payout_statements.values()
                        if p["engagement_id"] == engagement_id])


def engagement_options(engagement_id):
    return sorted_rows([o for o in db.renewal_options.values()
                        if o["engagement_id"] == engagement_id])


def slot_deliverables(slot_id):
    return sorted_rows([d for d in db.deliverables.values()
                        if d.get("production_slot_id") == slot_id])


# --------------------------------------------------------------- ledger
def append_ledger(engagement, entry_type, amount_cents, memo, source_entity, source_id):
    entry = new_record({
        "engagement_id": engagement["id"],
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "memo": memo,
        "source_entity": source_entity,
        "source_id": source_id,
    }, common=False)
    db.ledger_entries[entry["id"]] = entry
    refresh_accrued(engagement)
    return entry


def refresh_accrued(engagement):
    total = 0
    for entry in db.ledger_entries.values():
        if entry["engagement_id"] != engagement["id"]:
            continue
        if entry["entry_type"] in calc.ACCRUAL_ENTRY_TYPES:
            total += entry["amount_cents"]
    engagement["accrued_fee_cents"] = total
    return total


def penalty_sum(engagement_id):
    return sum(e["amount_cents"] for e in db.ledger_entries.values()
               if e["engagement_id"] == engagement_id and e["entry_type"] == "PENALTY")


def refresh_gross_settled(engagement):
    total = 0
    for statement in db.payout_statements.values():
        if statement["engagement_id"] == engagement["id"] and statement["status"] == "DISBURSED":
            total += statement["gross_amount_cents"]
    engagement["gross_settled_cents"] = total
    return total


# ------------------------------------------------------- derived counters
def refresh_active_exclusivity_count(athlete):
    athlete["active_exclusivity_count"] = sum(
        1 for g in db.exclusivity_grants.values()
        if g["athlete_id"] == athlete["id"] and g["status"] == "ACTIVE"
    )


def refresh_no_show_count(athlete):
    count = 0
    for booking in db.appearance_bookings.values():
        engagement = db.engagements.get(booking["engagement_id"])
        if engagement and engagement["athlete_id"] == athlete["id"] and booking.get("outcome") == "NO_SHOW":
            count += 1
    athlete["no_show_count"] = count


def refresh_approved_deliverable_count(engagement):
    engagement["approved_deliverable_count"] = sum(
        1 for d in db.deliverables.values()
        if d["engagement_id"] == engagement["id"] and d["status"] == "APPROVED"
    )


def refresh_reserved_count(slot):
    slot["reserved_count"] = sum(
        1 for d in db.deliverables.values()
        if d.get("production_slot_id") == slot["id"] and d["status"] != "VOIDED"
    )


# ------------------------------------------------- athlete_exposure_risk
def exposure(athlete, variant="ROSTER_SNAPSHOT"):
    athlete_id = athlete["id"]

    category_load = 0
    for grant in db.exclusivity_grants.values():
        if grant["athlete_id"] != athlete_id:
            continue
        if grant["status"] == "ACTIVE":
            category_load += 1
        elif variant == "PIPELINE_PROJECTED" and grant["status"] == "PENDING":
            category_load += 1

    morals_exposure = 0
    for engagement in db.engagements.values():
        if engagement["athlete_id"] != athlete_id:
            continue
        if engagement["contract_status"] == "ACTIVE":
            morals_exposure += calc.MORALS_WEIGHT[engagement["morals_clause_tier"]]
        elif variant == "PIPELINE_PROJECTED" and engagement["contract_status"] == "PENDING_COUNTERSIGN":
            morals_exposure += calc.MORALS_WEIGHT[engagement["morals_clause_tier"]]

    if variant == "PIPELINE_PROJECTED":
        for sheet in db.term_sheets.values():
            if sheet["status"] not in ("SUBMITTED", "COUNTERED"):
                continue
            opportunity = db.opportunities.get(sheet["opportunity_id"])
            if opportunity and opportunity["athlete_id"] == athlete_id:
                morals_exposure += calc.MORALS_WEIGHT[sheet["morals_clause_tier"]]

    noncompliance_hits = 0
    for record in db.disclosure_records.values():
        if record["status"] != "NON_COMPLIANT":
            continue
        deliverable = db.deliverables.get(record["deliverable_id"])
        if not deliverable:
            continue
        engagement = db.engagements.get(deliverable["engagement_id"])
        if engagement and engagement["athlete_id"] == athlete_id:
            noncompliance_hits += 1

    score = (calc.RISK_CATEGORY_WEIGHT * category_load
             + calc.RISK_MORALS_WEIGHT * morals_exposure
             + calc.RISK_DISCLOSURE_WEIGHT * noncompliance_hits)
    score = min(calc.RISK_SCORE_CAP, score)
    return {
        "athlete_id": athlete_id,
        "variant": variant,
        "category_load": category_load,
        "morals_exposure": morals_exposure,
        "noncompliance_hits": noncompliance_hits,
        "score": score,
    }


def refresh_exposure_snapshot(athlete):
    """The ROSTER_SNAPSHOT figure denormalised onto the athlete."""
    athlete["exposure_risk_snapshot_score"] = exposure(athlete, "ROSTER_SNAPSHOT")["score"]


# --------------------------------------------------- path / body resolution
_NOT_FOUND = {
    "athletes": "ERR_ATHLETE_NOT_FOUND",
    "brands": "ERR_BRAND_NOT_FOUND",
    "opportunities": "ERR_OPPORTUNITY_NOT_FOUND",
    "term_sheets": "ERR_TERM_SHEET_NOT_FOUND",
    "engagements": "ERR_ENGAGEMENT_NOT_FOUND",
    "appearance_bookings": "ERR_BOOKING_NOT_FOUND",
    "deliverables": "ERR_DELIVERABLE_NOT_FOUND",
    "disclosure_records": "ERR_DISCLOSURE_NOT_FOUND",
    "production_slots": "ERR_SLOT_NOT_FOUND",
    "payout_statements": "ERR_PAYOUT_NOT_FOUND",
    "renewal_options": "ERR_RENEWAL_NOT_FOUND",
}


def must_get(table, row_id):
    record = getattr(db, table).get(row_id)
    if record is None:
        raise ApiError(_NOT_FOUND[table], "%s not found" % table[:-1].replace("_", " "))
    return record


# ------------------------------------------------------------ occupancy
def exclusivity_conflict(athlete_id, category, start_date, end_date, ignore_grant_ids=()):
    """Inclusive whole-day ranges; a shared boundary day is a conflict."""
    if end_date < start_date:
        return False
    for grant in db.exclusivity_grants.values():
        if grant["id"] in ignore_grant_ids:
            continue
        if grant["athlete_id"] != athlete_id or grant["category"] != category:
            continue
        if grant["status"] not in ("PENDING", "ACTIVE"):
            continue
        other_start = parse_date(grant["start_date"], "start_date")
        other_end = parse_date(grant["end_date"], "end_date")
        if other_end < other_start:
            continue
        if start_date <= other_end and end_date >= other_start:
            return True
    return False


def calendar_conflict(athlete_id, start_at, end_at, buffer_hours, ignore_booking_ids=()):
    """Closed intervals inflated on both sides; touching endpoints collide."""
    import datetime as _dt

    new_start = start_at - _dt.timedelta(hours=buffer_hours)
    new_end = end_at + _dt.timedelta(hours=buffer_hours)
    for booking in athlete_bookings(athlete_id):
        if booking["id"] in ignore_booking_ids:
            continue
        if booking["status"] not in ("HOLD", "CONFIRMED"):
            continue
        other_start = parse_datetime(booking["start_at"], "start_at") - _dt.timedelta(
            hours=booking["travel_buffer_hours"])
        other_end = parse_datetime(booking["end_at"], "end_at") + _dt.timedelta(
            hours=booking["travel_buffer_hours"])
        if new_start <= other_end and new_end >= other_start:
            return True
    return False


def slot_capacity_exceeded(slot, new_start, new_end, ignore_deliverable_ids=()):
    """Half-open intervals; the aggregate ceiling is the slot's capacity."""
    intervals = [(new_start, new_end)]
    for deliverable in db.deliverables.values():
        if deliverable["id"] in ignore_deliverable_ids:
            continue
        if deliverable.get("production_slot_id") != slot["id"]:
            continue
        if deliverable["status"] == "VOIDED":
            continue
        if not deliverable.get("shoot_start_at") or not deliverable.get("shoot_end_at"):
            continue
        intervals.append((
            parse_datetime(deliverable["shoot_start_at"], "shoot_start_at"),
            parse_datetime(deliverable["shoot_end_at"], "shoot_end_at"),
        ))

    events = []
    for start, end in intervals:
        if end <= start:
            continue
        events.append((start, 1))
        events.append((end, -1))
    # Half-open: at a shared instant the ending reservation frees its unit first.
    events.sort(key=lambda item: (item[0], item[1]))
    running = 0
    peak = 0
    for _, delta in events:
        running += delta
        if running > peak:
            peak = running
    return peak > slot["capacity"]


# ------------------------------------------------------------- cascades
def void_deliverable(deliverable):
    """PENDING / SUBMITTED / REVISION_REQUESTED -> VOIDED, freeing slot capacity."""
    if deliverable["status"] not in ("PENDING", "SUBMITTED", "REVISION_REQUESTED"):
        return False
    deliverable["status"] = "VOIDED"
    touch(deliverable)
    if deliverable["type"] == "SHOOT" and deliverable.get("production_slot_id"):
        slot = db.production_slots.get(deliverable["production_slot_id"])
        if slot is not None:
            refresh_reserved_count(slot)
            touch(slot)
    return True


def void_booking_deliverables(booking):
    for deliverable in engagement_deliverables(booking["engagement_id"]):
        if deliverable["type"] != "APPEARANCE":
            continue
        if deliverable.get("booking_id") != booking["id"]:
            continue
        void_deliverable(deliverable)


def open_settlement(engagement):
    """The only two doors into billability are COMPLETED and TERMINATED."""
    if engagement["settlement_status"] == "UNBILLED":
        engagement["settlement_status"] = "BILLABLE"


def sync_athlete_after_contract_change(engagement):
    athlete = db.athletes.get(engagement["athlete_id"])
    if athlete is None:
        return
    refresh_active_exclusivity_count(athlete)
    refresh_exposure_snapshot(athlete)
    touch(athlete)
