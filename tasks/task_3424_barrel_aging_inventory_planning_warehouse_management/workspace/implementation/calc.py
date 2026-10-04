"""Calculations: barrel ledger replay, statutory projection, posture,
program eligibility/quotas, lazy auto-transitions, and report figures.

Precision doctrine:
  - ledger: floor at zero and round half-up to 2dp after EVERY event;
  - statutory: full precision through all blocks, round once at the end;
  - reports: round each barrel's contribution to 2dp half-up, THEN sum.
All arithmetic uses Decimal. Month = 30 days, year = 365 days everywhere.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import store

TWO_PLACES = Decimal("0.01")

# Statutory rate-table constants
BASE_QUARTERLY_RATE = Decimal("0.01")
BLOCK_DAYS = 90
YEAR_DAYS = 365
SEASON_MULT = {
    "WINTER": Decimal("0.7"),
    "SPRING": Decimal("1.0"),
    "SUMMER": Decimal("1.5"),
    "AUTUMN": Decimal("1.0"),
}
AGE_MULT_UNDER_2Y = Decimal("1.2")
AGE_MULT_2Y_TO_6Y = Decimal("1.0")
AGE_MULT_6Y_PLUS = Decimal("0.8")
SEASONED_THRESHOLD = 18
SEASONED_DISCOUNT = Decimal("0.95")
RATE_CAP = Decimal("0.05")

SAMPLE_BUFFER_DAYS = 30


def round2(d):
    return Decimal(d).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_dec(v):
    """JSON number -> Decimal without float artifacts."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def num(d):
    """Decimal -> plain JSON number (float)."""
    if d is None:
        return None
    return float(d)


# ---------------------------------------------------------------------------
# Lazy auto-transitions
# ---------------------------------------------------------------------------

def refresh_barrel(barrel):
    """AGING -> MATURE_ELIGIBLE when the maturation minimum has elapsed."""
    if barrel["maturation_status"] == "AGING":
        due = barrel["fill_date"] + timedelta(days=30 * barrel["min_maturation_months"])
        if store.now() >= due:
            barrel["maturation_status"] = "MATURE_ELIGIBLE"


def refresh_reservation(reservation):
    """ACTIVE -> EXPIRED when the clock has moved strictly past expires_at."""
    if reservation["state"] == "ACTIVE" and store.now() > reservation["expires_at"]:
        reservation["state"] = "EXPIRED"
        reservation["updated_at"] = store.now()
        program = store.programs.get(reservation["program_id"])
        if program is not None:
            program["version"] += 1
            program["updated_at"] = store.now()


def expire_due_reservations():
    for r in store.reservations.values():
        refresh_reservation(r)


def refresh_all():
    """Re-evaluate every lazy auto-transition (on clock-set)."""
    for b in store.barrels.values():
        refresh_barrel(b)
    expire_due_reservations()


# ---------------------------------------------------------------------------
# Occupancy helpers
# ---------------------------------------------------------------------------

def barrel_occupancies(barrel_id):
    return [o for o in store.occupancies.values() if o["barrel_id"] == barrel_id]


def slot_occupancies(slot_id):
    return [o for o in store.occupancies.values() if o["slot_id"] == slot_id]


def open_occupancy_of_barrel(barrel_id):
    for o in barrel_occupancies(barrel_id):
        if o["end_at"] is None:
            return o
    return None


def open_occupancy_on_slot(slot_id):
    for o in slot_occupancies(slot_id):
        if o["end_at"] is None:
            return o
    return None


def current_slot_id(barrel):
    occ = open_occupancy_of_barrel(barrel["id"])
    return occ["slot_id"] if occ else None


# ---------------------------------------------------------------------------
# Rickhouse posture (derived, never stored)
# ---------------------------------------------------------------------------

def rickhouse_for_slot(slot):
    return store.rickhouses.get(slot["rickhouse_id"])


def occupied_slots(rickhouse):
    count = 0
    for s in store.slots.values():
        if s["rickhouse_id"] != rickhouse["id"]:
            continue
        if open_occupancy_on_slot(s["id"]) is not None:
            count += 1
    return count


def total_slots(rickhouse):
    return rickhouse["floors"] * rickhouse["rows_per_floor"] * rickhouse["positions_per_row"]


def posture(rickhouse):
    project = store.projects.get(rickhouse["expansion_project_id"])
    if project is None or project["state"] != "COMMISSIONED":
        return "PLANNED"
    if occupied_slots(rickhouse) >= total_slots(rickhouse):
        return "FULL"
    return "OPERATING"


# ---------------------------------------------------------------------------
# Barrel volume: ledger variant
# ---------------------------------------------------------------------------

def barrel_assessments(barrel_id):
    return [a for a in store.assessments.values() if a["barrel_id"] == barrel_id]


def barrel_components(barrel_id):
    return [c for c in store.components.values() if c["barrel_id"] == barrel_id]


def ledger_events(barrel_id):
    """All ledger events for a barrel, sorted by (event_time, seq)."""
    events = []
    for a in barrel_assessments(barrel_id):
        events.append({
            "kind": a["kind"],
            "event_time": a["assessed_at"],
            "seq": a["_seq"],
            "measured": a.get("measured_volume_liters"),
            "draw": a.get("sample_draw_liters"),
        })
    for c in barrel_components(barrel_id):
        batch = store.batches.get(c["blend_batch_id"])
        if batch is None:
            continue
        if batch.get("committed_at") is not None:
            events.append({
                "kind": "COMMIT_DRAW",
                "event_time": batch["committed_at"],
                "seq": batch["_commit_seq"],
                "draw": c["drawn_volume_liters"],
            })
        if batch.get("committed_at") is not None and batch.get("_aborted_at") is not None:
            events.append({
                "kind": "ABORT_RESTORE",
                "event_time": batch["_aborted_at"],
                "seq": batch["_abort_seq"],
                "draw": c["drawn_volume_liters"],
            })
    events.sort(key=lambda e: (e["event_time"], e["seq"]))
    return events


def ledger_at(barrel, t=None):
    """Replay the ledger. When t is given, only events with event_time < t
    count; otherwise every recorded event applies (read-at-now semantics)."""
    v = to_dec(barrel["fill_volume_liters"])
    for e in ledger_events(barrel["id"]):
        if t is not None and not (e["event_time"] < t):
            continue
        if e["kind"] == "EVAPORATION_READING":
            v = to_dec(e["measured"])
        elif e["kind"] == "QUALITY_SAMPLE":
            v = v - to_dec(e["draw"])
        elif e["kind"] == "COMMIT_DRAW":
            v = v - to_dec(e["draw"])
        elif e["kind"] == "ABORT_RESTORE":
            v = v + to_dec(e["draw"])
        if v < 0:
            v = Decimal("0")
        v = round2(v)
    return v


# ---------------------------------------------------------------------------
# Barrel volume: statutory variant
# ---------------------------------------------------------------------------

def _season(month):
    if month in (12, 1, 2):
        return "WINTER"
    if month in (3, 4, 5):
        return "SPRING"
    if month in (6, 7, 8):
        return "SUMMER"
    return "AUTUMN"


def _age_mult(age_y):
    if age_y < 2:
        return AGE_MULT_UNDER_2Y
    if age_y < 6:
        return AGE_MULT_2Y_TO_6Y
    return AGE_MULT_6Y_PLUS


def heat_factor_at(barrel, t):
    """Heat factor of the barrel's slot at instant t: the slot of the
    occupancy open at t, else the slot of the most recently closed
    occupancy at/before t. Falls back to the earliest occupancy's slot,
    then to 1.0."""
    occs = barrel_occupancies(barrel["id"])
    if not occs:
        return Decimal("1.0")
    for o in sorted(occs, key=lambda o: (o["start_at"], o["_seq"]), reverse=True):
        if o["start_at"] <= t and (o["end_at"] is None or t < o["end_at"]):
            slot = store.slots.get(o["slot_id"])
            return Decimal(str(slot["heat_factor"])) if slot else Decimal("1.0")
    closed = [o for o in occs if o["end_at"] is not None and o["end_at"] <= t]
    if closed:
        o = max(closed, key=lambda o: (o["end_at"], o["_seq"]))
        slot = store.slots.get(o["slot_id"])
        return Decimal(str(slot["heat_factor"])) if slot else Decimal("1.0")
    earliest = min(occs, key=lambda o: (o["start_at"], o["_seq"]))
    slot = store.slots.get(earliest["slot_id"])
    return Decimal(str(slot["heat_factor"])) if slot else Decimal("1.0")


def statutory_at(barrel, t):
    """Rate-table projection at instant t. Full precision through every
    fully-elapsed 90-day block; rounded once at the end (2dp half-up)."""
    V = to_dec(barrel["fill_volume_liters"])
    fill = barrel["fill_date"]
    if t <= fill:
        return round2(max(V, Decimal("0")))
    elapsed_days = Decimal(str((t - fill).total_seconds())) / Decimal("86400")
    blocks = int(elapsed_days // Decimal(BLOCK_DAYS))
    heat = heat_factor_at(barrel, t)
    seasoned = barrel["seasoning_months"] >= SEASONED_THRESHOLD
    for n in range(blocks):
        s = fill + timedelta(days=BLOCK_DAYS * n)
        season = SEASON_MULT[_season(s.month)]
        age_y = (s - fill).days // YEAR_DAYS
        r = BASE_QUARTERLY_RATE * heat * season * _age_mult(age_y)
        if seasoned:
            r = r * SEASONED_DISCOUNT
        if r > RATE_CAP:
            r = RATE_CAP
        V = V * (Decimal("1") - r)
    if V < 0:
        V = Decimal("0")
    return round2(V)


# ---------------------------------------------------------------------------
# Age statements and program eligibility
# ---------------------------------------------------------------------------

def age_years_at(barrel, d):
    return (d - barrel["fill_date"]).days // YEAR_DAYS


def latest_quality_score(barrel):
    samples = [a for a in barrel_assessments(barrel["id"]) if a["kind"] == "QUALITY_SAMPLE"]
    if not samples:
        return 0
    best_at = max(a["assessed_at"] for a in samples)
    latest = min(
        (a for a in samples if a["assessed_at"] == best_at),
        key=lambda a: a["_seq"],
    )
    return latest["quality_score"] if latest["quality_score"] is not None else 0


def has_active_or_consumed_reservation(barrel_id):
    for r in store.reservations.values():
        if r["barrel_id"] == barrel_id:
            refresh_reservation(r)
            if r["state"] in ("ACTIVE", "CONSUMED"):
                return True
    return False


def has_committed_component(barrel_id):
    for c in barrel_components(barrel_id):
        batch = store.batches.get(c["blend_batch_id"])
        if batch is not None and batch["state"] == "COMMITTED":
            return True
    return False


def barrel_eligible_for_program(barrel, program):
    refresh_barrel(barrel)
    if barrel["custody_status"] != "BONDED":
        return False
    if barrel["maturation_status"] != "MATURE_ELIGIBLE":
        return False
    if barrel["spirit_type"] != program["spirit_type"]:
        return False
    if has_active_or_consumed_reservation(barrel["id"]):
        return False
    if has_committed_component(barrel["id"]):
        return False
    if latest_quality_score(barrel) < program["min_quality_score"]:
        return False
    return True


def program_reservations(program_id):
    return [r for r in store.reservations.values() if r["program_id"] == program_id]


def available_slots(program):
    active = consumed = 0
    for r in program_reservations(program["id"]):
        refresh_reservation(r)
        if r["state"] == "ACTIVE":
            active += 1
        elif r["state"] == "CONSUMED":
            consumed += 1
    return program["required_barrel_count"] - active - consumed


# ---------------------------------------------------------------------------
# Bonded period report figures
# ---------------------------------------------------------------------------

def compute_report_figures(report):
    ps = report["period_start"]
    pe = report["period_end"]

    opening = Decimal("0")
    for b in store.barrels.values():
        if b["fill_date"] < ps:
            opening += round2(ledger_at(b, ps))

    fills = Decimal("0")
    for b in store.barrels.values():
        if ps <= b["fill_date"] < pe:
            fills += to_dec(b["fill_volume_liters"])

    withdrawals = Decimal("0")
    for b in store.barrels.values():
        wa = b.get("withdrawn_at")
        if wa is not None and ps <= wa < pe:
            withdrawals += to_dec(b["withdrawn_volume_liters"])

    loss_actual = Decimal("0")
    loss_statutory = Decimal("0")
    for b in store.barrels.values():
        wa = b.get("withdrawn_at")
        if not (b["fill_date"] < pe and (wa is None or wa > ps)):
            continue
        s = max(ps, b["fill_date"])
        e = min(pe, wa) if wa is not None else pe
        # actual (ledger) method
        la_s = ledger_at(b, s)
        la_e = ledger_at(b, e)
        draws = Decimal("0")
        for a in barrel_assessments(b["id"]):
            if a["kind"] == "QUALITY_SAMPLE" and s <= a["assessed_at"] < e:
                draws += to_dec(a["sample_draw_liters"])
        for c in barrel_components(b["id"]):
            batch = store.batches.get(c["blend_batch_id"])
            if batch is None or batch.get("committed_at") is None:
                continue
            if s <= batch["committed_at"] < e:
                draws += to_dec(c["drawn_volume_liters"])
            if batch.get("_aborted_at") is not None and s <= batch["_aborted_at"] < e:
                draws -= to_dec(c["drawn_volume_liters"])
        loss_b = la_s - la_e - draws
        if loss_b < 0:
            loss_b = Decimal("0")
        loss_actual += round2(loss_b)
        # statutory (rate-table) method
        vs_s = statutory_at(b, s)
        vs_e = statutory_at(b, e)
        sloss_b = vs_s - vs_e
        if sloss_b < 0:
            sloss_b = Decimal("0")
        loss_statutory += round2(sloss_b)

    reported = loss_actual
    closing = opening + fills - withdrawals - reported
    return {
        "opening_inventory_liters": opening,
        "period_fills_liters": fills,
        "period_withdrawals_liters": withdrawals,
        "loss_actual_liters": loss_actual,
        "loss_statutory_liters": loss_statutory,
        "reported_loss_liters": reported,
        "closing_inventory_liters": closing,
    }
