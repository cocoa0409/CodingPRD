"""All calculation rules (SCAFFOLD 1.3)."""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

import store

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
ZONE_B_FLOOR = Decimal("1.40")
ZONE_C_FLOOR = Decimal("2.80")
ZONE_D_FLOOR = Decimal("4.50")

ZONE_PENALTY = {"A": 0, "B": 5, "C": 15, "D": 30}
REBUILD_PENALTY_PER_CYCLE = 6
GRADE_FLOORS = (("GRADE_A", 80), ("GRADE_B", 60), ("GRADE_C", 35), ("GRADE_D", 15))

DEFECT_RATIO_FLOOR = Decimal("3.0")
NORMAL_WEAR_REBUILD_FLOOR = 2

TIER_MULTIPLIER = {
    "GRADE_A": Decimal("1.00"),
    "GRADE_B": Decimal("0.75"),
    "GRADE_C": Decimal("0.45"),
    "GRADE_D": Decimal("0.20"),
    "SCRAP": Decimal("0.00"),
}
REBUILD_DECAY_PCT = Decimal("0.08")
REWORKABLE_DEDUCTION_FACTOR = Decimal("0.5")

LABOR_RATE_CENTS_PER_HOUR = Decimal("14500")
EXPEDITE_TIER_1_FLOOR = 100000
EXPEDITE_TIER_2_FLOOR = 500000
EXPEDITE_PCT_LOW = Decimal("0.30")
EXPEDITE_PCT_MID = Decimal("0.22")
EXPEDITE_PCT_HIGH = Decimal("0.15")
EXPEDITE_CALLOUT_CENTS = 25000
CORE_CREDIT_CAP_PCT = Decimal("0.40")
AFTERMARKET_COVERAGE_PCT = Decimal("0.50")

CUSTOMER_CREDIT_CEILING_CENTS = 2000000
DAYS_PER_WARRANTY_MONTH = 30
CHANGEOVER_BUFFER_HOURS = 24

SIX = Decimal("0.000001")
ONE = Decimal("1")


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------
def rhu_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu6(value):
    return Decimal(value).quantize(SIX, rounding=ROUND_HALF_UP)


def rhu0(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# 1 — clearance band evaluation
# ---------------------------------------------------------------------------
def clearance_band_evaluation(band, measured_um):
    lo = int(band["min_um"])
    hi = int(band["max_um"])
    ext = int(band.get("rework_extension_um") or 0)
    width = Decimal(hi - lo)
    if lo <= measured_um <= hi:
        band_result = "IN_SPEC"
        deviation = Decimal("0.000000")
    else:
        excess = (measured_um - hi) if measured_um > hi else (lo - measured_um)
        band_result = "REWORKABLE" if excess <= ext else "OUT_OF_SPEC"
        raw = Decimal(excess) / width
        if raw > ONE:
            raw = ONE
        deviation = rhu6(raw)
    score = rhu6(Decimal(100) * (ONE - deviation))
    return band_result, deviation, score


# ---------------------------------------------------------------------------
# 2 — vibration zone classification
# ---------------------------------------------------------------------------
def vibration_zone(velocity):
    if velocity < ZONE_B_FLOOR:
        return "A"
    if velocity < ZONE_C_FLOOR:
        return "B"
    if velocity < ZONE_D_FLOOR:
        return "C"
    return "D"


def defect_ratio(amplitude, baseline):
    return rhu6(Decimal(amplitude) / Decimal(baseline))


# ---------------------------------------------------------------------------
# helpers: entity traversal
# ---------------------------------------------------------------------------
def order_of(inspection):
    return store.get("orders", inspection["rebuild_order_id"])


def standard_for_order(order):
    if order is None:
        return None
    core = store.get("core_units", order["core_unit_id"])
    if core is None:
        return None
    return store.get("standards", core["clearance_standard_id"])


def band_map(standard):
    return {b["feature_code"]: b for b in (standard.get("feature_bands") or [])}


def measurements_of(inspection_id):
    return [m for m in store.all_rows("measurements") if m["inspection_id"] == inspection_id]


# ---------------------------------------------------------------------------
# governing measurement set (3.5 step 1)
# ---------------------------------------------------------------------------
def governing_measurements(inspection_id):
    governing = {}
    for m in measurements_of(inspection_id):
        code = m["feature_code"]
        current = governing.get(code)
        if current is None:
            governing[code] = m
            continue
        key_new = (m["created_at"], m["sequence_no"])
        key_old = (current["created_at"], current["sequence_no"])
        if key_new > key_old:
            governing[code] = m
    return governing


# ---------------------------------------------------------------------------
# 3 — remaining life score
# ---------------------------------------------------------------------------
def remaining_life(inspection, order, core, asset, standard, reading):
    governing = governing_measurements(inspection["id"])
    bands = band_map(standard)

    weighted_sum = Decimal(0)
    weight_sum = Decimal(0)
    minimum = None
    for code, m in governing.items():
        score = Decimal(m["feature_score"])
        weight = Decimal(bands[code]["weight"]) if code in bands else Decimal(1)
        weighted_sum += weight * score
        weight_sum += weight
        if minimum is None or score < minimum:
            minimum = score

    composite_raw = (weighted_sum / weight_sum) if weight_sum > 0 else Decimal(0)
    conservative_raw = minimum if minimum is not None else Decimal(0)

    if asset is not None and asset.get("criticality") == "CRITICAL":
        variant = "CONSERVATIVE"
        base_raw = conservative_raw
    else:
        variant = "COMPOSITE"
        base_raw = composite_raw

    vib_penalty = ZONE_PENALTY.get(reading["iso_zone"], 0) if reading else 0
    rebuild_penalty = REBUILD_PENALTY_PER_CYCLE * int(core.get("rebuild_count") or 0)
    score = rhu0(base_raw) - vib_penalty - rebuild_penalty
    score = max(0, min(100, score))

    grade = "SCRAP"
    for name, floor in GRADE_FLOORS:
        if score >= floor:
            grade = name
            break
    return variant, score, grade


# ---------------------------------------------------------------------------
# 4 — failure cause coding
# ---------------------------------------------------------------------------
def failure_cause(inspection, reading, core):
    if inspection.get("cause_code_override"):
        return inspection["cause_code_override"], "ASSERTED"
    outer = Decimal(reading["defect_ratio_outer"])
    inner = Decimal(reading["defect_ratio_inner"])
    if outer >= DEFECT_RATIO_FLOOR and outer >= inner:
        return "OUTER_RACE_SPALL", "HIGH"
    if inner >= DEFECT_RATIO_FLOOR:
        return "INNER_RACE_SPALL", "HIGH"
    if reading["iso_zone"] == "D":
        return "MISALIGNMENT", "MEDIUM"
    governing = governing_measurements(inspection["id"])
    housing = governing.get("HOUSING_FIT")
    if housing is not None and housing["band_result"] != "IN_SPEC":
        return "LOOSE_FIT", "MEDIUM"
    if reading["iso_zone"] == "C":
        return "LUBRICATION_FAILURE", "MEDIUM"
    if int(core.get("rebuild_count") or 0) >= NORMAL_WEAR_REBUILD_FLOOR:
        return "NORMAL_WEAR", "LOW"
    return "UNDETERMINED", "LOW"


# ---------------------------------------------------------------------------
# 5 — core credit valuation
# ---------------------------------------------------------------------------
def core_credit_valuation(base, grade, rebuild_count, governing=None, bands=None):
    base_d = Decimal(int(base))
    tiered = rhu_cents(base_d * TIER_MULTIPLIER.get(grade, Decimal(0)))
    decay = rhu_cents(base_d * REBUILD_DECAY_PCT * Decimal(int(rebuild_count or 0)))
    deduction = 0
    if governing:
        for code, m in governing.items():
            band = (bands or {}).get(code)
            if band is None:
                continue
            pct = Decimal(band.get("deduction_pct") or 0)
            if m["band_result"] == "OUT_OF_SPEC":
                deduction += rhu_cents(base_d * pct)
            elif m["band_result"] == "REWORKABLE":
                deduction += rhu_cents(base_d * pct * REWORKABLE_DEDUCTION_FACTOR)
    value = tiered - decay - deduction
    return max(0, min(int(base), value))


# ---------------------------------------------------------------------------
# 6 — order approval rollup
# ---------------------------------------------------------------------------
def part_lines_of(order_id):
    return [p for p in store.all_rows("part_lines") if p["rebuild_order_id"] == order_id]


def approval_rollup(order_id):
    lines = part_lines_of(order_id)
    if not lines:
        return "PENDING"
    pending = [l for l in lines if l["approval_status"] in ("PROPOSED", "SUBMITTED")]
    approved = [l for l in lines if l["approval_status"] == "APPROVED"]
    rejected = [l for l in lines if l["approval_status"] == "REJECTED"]
    if len(pending) == len(lines):
        return "PENDING"
    if len(approved) == len(lines):
        return "APPROVED"
    if len(pending) == 0 and len(rejected) >= 1:
        return "REJECTED"
    return "PARTIAL"


# ---------------------------------------------------------------------------
# 7 — order quote total
# ---------------------------------------------------------------------------
def quote_full(order):
    lines = [l for l in part_lines_of(order["id"]) if l["approval_status"] == "APPROVED"]
    parts_subtotal = sum(int(l["qty"]) * int(l["unit_cost_cents"]) for l in lines)
    labor_cents = rhu_cents(Decimal(order["labor_hours"]) * LABOR_RATE_CENTS_PER_HOUR)
    pre = parts_subtotal + labor_cents

    if not order.get("expedited"):
        surcharge = 0
    else:
        if pre < EXPEDITE_TIER_1_FLOOR:
            pct = EXPEDITE_PCT_LOW
        elif pre < EXPEDITE_TIER_2_FLOOR:
            pct = EXPEDITE_PCT_MID
        else:
            pct = EXPEDITE_PCT_HIGH
        surcharge = rhu_cents(Decimal(pre) * pct) + EXPEDITE_CALLOUT_CENTS

    gross = pre + surcharge

    covered = labor_cents
    for l in lines:
        factor = ONE if l["source_class"] == "OEM" else AFTERMARKET_COVERAGE_PCT
        covered += rhu_cents(Decimal(int(l["qty"]) * int(l["unit_cost_cents"])) * factor)

    order["parts_subtotal_cents"] = parts_subtotal
    order["labor_cents"] = labor_cents
    order["pre_credit_subtotal_cents"] = pre
    order["expedite_surcharge_cents"] = surcharge
    order["gross_total_cents"] = gross
    order["covered_base_cents"] = covered
    apply_credit(order)
    order["quoted_part_revision"] = order["part_revision_counter"]


def credit_cap_for(gross):
    if gross is None:
        return None
    return floor_int(Decimal(int(gross)) * CORE_CREDIT_CAP_PCT)


def apply_credit(order):
    """Steps 6-7 only."""
    gross = order.get("gross_total_cents")
    if gross is None:
        return
    cap = credit_cap_for(gross)
    customer = store.get("customers", order["customer_id"])
    balance = int(customer["total_credit_balance_cents"]) if customer else 0
    applied = min(balance, cap)
    order["core_credit_applied_cents"] = applied
    order["quote_total_cents"] = gross - applied


# ---------------------------------------------------------------------------
# 8 — warranty pro-rata credit
# ---------------------------------------------------------------------------
def elapsed_days_of(installation):
    start = store.parse_iso(installation["in_service_start_at"])
    end = store.parse_iso(installation.get("failed_at"))
    if start is None or end is None:
        return 0
    seconds = (end - start).total_seconds()
    if seconds < 0:
        return int(-((-seconds) // 86400))
    return int(seconds // 86400)


def accepted_inspection_of_order(order_id):
    for i in store.sorted_rows(store.all_rows("inspections")):
        if i["rebuild_order_id"] == order_id and i["status"] == "ACCEPTED":
            return i
    return None


def warranty_pro_rata(installation):
    elapsed_days = elapsed_days_of(installation)
    hours_snapshot = int(installation["warranty_hours_snapshot"])
    months_snapshot = int(installation["warranty_months_snapshot"])

    hours_fraction = Decimal(installation["run_hours"]) / Decimal(hours_snapshot)
    if hours_fraction > ONE:
        hours_fraction = ONE
    hours_fraction = rhu6(hours_fraction)

    calendar_days = Decimal(months_snapshot * DAYS_PER_WARRANTY_MONTH)
    calendar_fraction = Decimal(elapsed_days) / calendar_days
    if calendar_fraction > ONE:
        calendar_fraction = ONE
    calendar_fraction = rhu6(calendar_fraction)

    inspection = accepted_inspection_of_order(installation["rebuild_order_id"])
    if inspection is not None and inspection.get("failure_cause_code") == "WORKMANSHIP":
        basis = "GOODWILL"
        remaining = Decimal("1.000000")
    else:
        if hours_fraction >= calendar_fraction:
            basis = "HOURS"
        else:
            basis = "CALENDAR"
        remaining = rhu6(ONE - max(hours_fraction, calendar_fraction))

    credit = rhu_cents(Decimal(int(installation["covered_base_cents_snapshot"])) * remaining)
    return {
        "elapsed_days": elapsed_days,
        "hours_consumed_fraction": hours_fraction,
        "calendar_consumed_fraction": calendar_fraction,
        "governing_basis": basis,
        "remaining_fraction": remaining,
        "pro_rata_credit_cents": credit,
    }


# ---------------------------------------------------------------------------
# 9 — customer credit balances
# ---------------------------------------------------------------------------
def notes_of(customer_id):
    return [n for n in store.all_rows("credit_notes") if n["customer_id"] == customer_id]


def recompute_balances(customer):
    """Full recompute from the surviving POSTED notes; bumps the customer's version."""
    posted = [n for n in notes_of(customer["id"]) if n["status"] == "POSTED"]
    core = sum(int(n["amount_cents"]) for n in posted if n["kind"] == "CORE_EXCHANGE")
    warranty = sum(int(n["amount_cents"]) for n in posted if n["kind"] == "WARRANTY_PRORATA")
    manual = sum(int(n["amount_cents"]) for n in posted if n["kind"] == "MANUAL_ADJUSTMENT")
    customer["core_credit_balance_cents"] = core
    customer["warranty_credit_balance_cents"] = warranty
    customer["manual_credit_balance_cents"] = manual
    customer["total_credit_balance_cents"] = core + warranty + manual
    store.touch(customer)


def reprice_quoted_orders(customer_id):
    """Every QUOTED order of the customer re-derives steps 6-7 only."""
    for order in store.sorted_rows(store.all_rows("orders")):
        if order["customer_id"] == customer_id and order["work_status"] == "QUOTED":
            apply_credit(order)
            store.touch(order)


# ---------------------------------------------------------------------------
# 10-12 — bench capacity
# ---------------------------------------------------------------------------
def reservations_of_bench(bench_id):
    return [r for r in store.all_rows("reservations") if r["bench_id"] == bench_id]


def reservations_of_order(order_id):
    return store.sorted_rows(
        [r for r in store.all_rows("reservations") if r["rebuild_order_id"] == order_id]
    )


def recompute_committed_minutes(bench):
    total = 0
    for r in reservations_of_bench(bench["id"]):
        if r["status"] in ("HELD", "CONFIRMED"):
            total += int(r["window_minutes"])
    if bench["committed_minutes"] != total:
        bench["committed_minutes"] = total
        store.touch(bench)


def window_minutes(start, end):
    return int((end - start).total_seconds() // 60)


def _peak_occupancy(bench_id, start, end, exclude_id=None):
    active = [
        r for r in reservations_of_bench(bench_id)
        if r["status"] in ("HELD", "CONFIRMED") and r["id"] != exclude_id
    ]
    instants = [start]
    for r in active:
        r_start = store.parse_iso(r["window_start_at"])
        if start <= r_start < end:
            instants.append(r_start)
    peak = 0
    for t in instants:
        count = 0
        for r in active:
            r_start = store.parse_iso(r["window_start_at"])
            r_end = store.parse_iso(r["window_end_at"])
            if r_start <= t < r_end:
                count += 1
        if count > peak:
            peak = count
    return peak


def admits(bench, start, end):
    return _peak_occupancy(bench["id"], start, end) < int(bench["parallel_slots"])


def queue_promotion(bench):
    """Promote at most one QUEUED reservation whose window now fits."""
    candidates = []
    for r in reservations_of_bench(bench["id"]):
        if r["status"] != "QUEUED":
            continue
        start = store.parse_iso(r["window_start_at"])
        end = store.parse_iso(r["window_end_at"])
        if _peak_occupancy(bench["id"], start, end) < int(bench["parallel_slots"]):
            candidates.append(r)
    if not candidates:
        return None
    winner = min(
        candidates,
        key=lambda r: (r["created_at"], r["window_start_at"], int(r["window_minutes"]), r["_seq"]),
    )
    winner["status"] = "HELD"
    winner["promoted_at"] = store.logical_now_iso()
    store.touch(winner)
    return winner


# ---------------------------------------------------------------------------
# 13 — installation changeover admission
# ---------------------------------------------------------------------------
def installations_of_asset(asset_id):
    return [i for i in store.all_rows("installations") if i["customer_asset_id"] == asset_id]


def last_off_service(asset_id):
    best = None
    best_key = None
    for i in installations_of_asset(asset_id):
        if i["status"] not in ("REMOVED_PLANNED", "FAILED_IN_SERVICE"):
            continue
        stamp = i.get("removed_at") or i.get("failed_at")
        parsed = store.parse_iso(stamp)
        if parsed is None:
            continue
        key = (parsed, i["created_at"], i["_seq"])
        if best_key is None or key > best_key:
            best_key = key
            best = parsed
    return best
