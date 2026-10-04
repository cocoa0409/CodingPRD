"""Weekly line-capacity pools (calculations.weekly_line_capacity) and the
changeover-class computation (calculations.changeover_class).

Pinned rules:
- ISO-8601 weeks, Monday-start.
- surge multiplier 1.25 for ISO weeks 44..52 inclusive, else 1.0.
- pool_kg = floor(capacity_kg_per_shift * 5 * surge_multiplier)   (whole-kg floor)
- scheduled_kg: runs in {SCHEDULED, COMPLETED} whose window_start falls in the week
- reserved_kg: reservations whose half-open window intersects the week's span
- free_kg = pool - scheduled - reserved must stay >= 0.
"""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR

from state import DB

SHIFTS_PER_WEEK = 5
SURGE_WEEK_START = 44
SURGE_WEEK_END = 52
SURGE_CAPACITY_MULTIPLIER = Decimal("1.25")


def week_monday(dt):
    d = dt.date()
    return d - timedelta(days=d.weekday())


def monday_dt(monday):
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


def surge_multiplier(week_no):
    return (SURGE_CAPACITY_MULTIPLIER
            if SURGE_WEEK_START <= week_no <= SURGE_WEEK_END else Decimal("1.0"))


def pool_kg(line, monday):
    week_no = monday.isocalendar()[1]
    raw = (Decimal(line["capacity_kg_per_shift"]) * Decimal(SHIFTS_PER_WEEK)
           * surge_multiplier(week_no))
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))


def weeks_intersecting(window_start, window_end):
    """All ISO weeks (identified by their Monday date) whose half-open
    [monday, next_monday) span intersects [window_start, window_end)."""
    m = week_monday(window_start)
    out = []
    while monday_dt(m) < window_end:
        out.append(m)
        m += timedelta(days=7)
    return out


def scheduled_kg(line_id, monday):
    total = Decimal("0")
    for r in DB.production_runs.values():
        if r["line_id"] != line_id or r["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if week_monday(r["window_start"]) == monday:
            total += r["quantity_kg"]
    return total


def reserved_kg(line_id, monday):
    ws = monday_dt(monday)
    we = ws + timedelta(days=7)
    total = 0
    for r in DB.reservations.values():
        if r["line_id"] != line_id:
            continue
        if r["window_start"] < we and r["window_end"] > ws:
            total += r["reserved_kg_per_week"]
    return total


def free_kg(line, monday):
    return (Decimal(pool_kg(line, monday))
            - scheduled_kg(line["id"], monday)
            - Decimal(reserved_kg(line["id"], monday)))


# ---------------------------------------------------------------------------
# Changeover class (calculations.changeover_class)
# ---------------------------------------------------------------------------
def formula_lines_of(formula_id):
    lines = [l for l in DB.formula_lines.values() if l["formula_id"] == formula_id]
    lines.sort(key=lambda l: (l["created_at"], l["_seq"]))
    return lines


def run_allergens(formula_id):
    """Set of the formula's FormulaLine allergen_profile values, excluding NONE."""
    return {l["allergen_profile"] for l in formula_lines_of(formula_id)
            if l["allergen_profile"] != "NONE"}


def run_high_seg(formula, agreement_id):
    if formula["brand_type"] != "PRIVATE_LABEL":
        return False
    ag = DB.agreements.get(agreement_id) if agreement_id else None
    return ag is not None and ag["confidentiality_level"] == "HIGH_SEGREGATION"


def run_organic(formula_id):
    lines = formula_lines_of(formula_id)
    if not lines:
        return False
    return all(l["organic_required"] for l in lines)


def find_predecessor(line_id, new_start):
    """Non-CANCELLED run on the same line with the greatest window_end <=
    new_start; ties broken by earliest created_at. None if none qualifies."""
    cands = [
        r for r in DB.production_runs.values()
        if r["line_id"] == line_id and r["status"] != "CANCELLED"
        and r["window_end"] <= new_start
    ]
    if not cands:
        return None
    cands.sort(key=lambda r: (-r["window_end"].timestamp(), r["_seq"]))
    return cands[0]


def changeover_class(pred, new_formula, new_agreement_id):
    if pred is None:
        return "NONE"
    p_formula = DB.formulas[pred["formula_id"]]
    p_ag = pred["private_label_agreement_id"]
    if run_high_seg(p_formula, p_ag) or run_high_seg(new_formula, new_agreement_id):
        return "FULL_SANITATION"
    p_allergens = run_allergens(p_formula["id"])
    n_allergens = run_allergens(new_formula["id"])
    if not p_allergens.issubset(n_allergens):
        return "WET_WASH"
    if run_organic(new_formula["id"]) and not run_organic(p_formula["id"]):
        return "WET_WASH"
    if (p_allergens == n_allergens
            and p_formula["brand_type"] == new_formula["brand_type"]
            and (p_formula["brand_type"] != "PRIVATE_LABEL"
                 or p_ag == new_agreement_id)):
        return "NONE"
    return "DRY_CLEAN"
