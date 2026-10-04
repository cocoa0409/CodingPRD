"""Premium and reconciliation calculations (PRD section 3.3 and 3.7)."""
from decimal import Decimal, ROUND_HALF_UP

from db import STORE
from helpers import (
    tables_covering_period, weeks_in_period, table_effective_at,
)


def _round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _rate_for(table, class_code):
    for entry in table["class_rates"]:
        if entry["class_code"] == class_code:
            return entry["rate_per_100_cents"]
    return None


def compute_line_basis(line, start_dt, end_dt):
    """Set line['remuneration_basis_cents'] per PRD remuneration_basis."""
    state_code = line["state_code"]
    base = line["gross_wages_cents"] - line["severance_cents"]
    ot_premium = line["ot_premium_cents"]

    # Step 2: OT premium subtraction allocated to segments by rating-table spans.
    segments = []  # (table, days_span, base_share, ot_share)
    tables = tables_covering_period(state_code, start_dt, end_dt)
    total_seconds = (end_dt - start_dt).total_seconds()
    remaining_base = base
    remaining_ot = ot_premium
    for idx, t in enumerate(tables):
        seg_start = max(t["_from"], start_dt)
        seg_end = min(t["_to"], end_dt)
        frac = Decimal((seg_end - seg_start).total_seconds()) / Decimal(total_seconds)
        if idx == len(tables) - 1:
            seg_base = remaining_base
            seg_ot = remaining_ot
        else:
            seg_base = int((Decimal(base) * frac).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            seg_ot = int((Decimal(ot_premium) * frac).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            remaining_base -= seg_base
            remaining_ot -= seg_ot
        segments.append((t, seg_base, seg_ot))

    weeks = weeks_in_period(start_dt, end_dt)

    # Executive component is capped against the whole-period weekly cap.
    # With multiple tables the cap uses the maximum weekly cap among segments.
    max_cap = max(
        (t["max_payroll_per_executive_cents"] for (t, _, _) in segments),
        default=0,
    )
    exec_wages = line["executive_wages_cents"]

    # Steps 1-2 combined basis before executive cap:
    adj_base = 0
    for (t, seg_base, seg_ot) in segments:
        if t["ot_basis"] == "NET":
            adj_base += seg_base - seg_ot
        else:
            adj_base += seg_base

    exec_component = min(exec_wages, weeks * max_cap)
    non_exec = adj_base - exec_wages
    if non_exec < 0:
        non_exec = 0
    line["remuneration_basis_cents"] = non_exec + exec_component


def _line_premiums(line, start_dt, end_dt, rate_class=None):
    """Return list of (table, premium_cents) segments for one line."""
    state_code = line["state_code"]
    cls = rate_class if rate_class is not None else line["class_code"]
    basis = line["remuneration_basis_cents"]
    tables = tables_covering_period(state_code, start_dt, end_dt)
    total_seconds = (end_dt - start_dt).total_seconds()
    segments = []
    remaining_basis = basis
    for idx, t in enumerate(tables):
        seg_start = max(t["_from"], start_dt)
        seg_end = min(t["_to"], end_dt)
        frac = Decimal((seg_end - seg_start).total_seconds()) / Decimal(total_seconds)
        if idx == len(tables) - 1:
            seg_basis = remaining_basis
        else:
            seg_basis = int((Decimal(basis) * frac).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            remaining_basis -= seg_basis
        rate = _rate_for(t, cls)
        if rate is None:
            rate = 0
        premium = _round_half_up_int(Decimal(seg_basis) * Decimal(rate) / Decimal(10000))
        segments.append((t, premium))
    return segments


def _mod_str(mod):
    """experience_mod_applied snapshots the factor actually applied. PRD §2.6
    carries experience_mod as a decimal to three places, so round the numeric
    value to three decimals but keep it a JSON number, not a string."""
    return round(float(mod), 3)


def compute_invoice_totals(lines, start_dt, end_dt, experience_mod, rate_overrides=None,
                           include_adders=True):
    """Compute invoice fields for a set of line records.

    lines: list of PayrollLine dicts with remuneration_basis_cents set.
    rate_overrides: optional dict mapping line id -> class_code used for rate lookup.
    include_adders: when False (audit true-up on excess wages), per-capita fees,
    minimum-premium substitution, and the expense constant are not applied — the
    invoice carries only the premium on the excess wages.
    Returns dict of computed invoice fields.
    """
    rate_overrides = rate_overrides or {}
    mod = Decimal(str(experience_mod))

    manual_premium = 0
    per_capita_fees = 0
    state_sums = {}   # state_code -> {"premium": int, "tables": set of table ids}
    state_tables = {} # state_code -> {table_id: table}

    for line in lines:
        override_cls = rate_overrides.get(line["id"])
        segments = _line_premiums(line, start_dt, end_dt, rate_class=override_cls)
        first_table = None
        for (t, premium) in segments:
            manual_premium += premium
            sc = t["state_code"]
            entry = state_sums.setdefault(sc, 0)
            state_sums[sc] = entry + premium
            state_tables.setdefault(sc, {})[t["id"]] = t
            if first_table is None:
                first_table = t
        if first_table is not None:
            per_capita_fees += line["headcount"] * first_table["per_capita_admin_fee_cents"]

    # Per-state post-mod subtotal with round-half-up, then min premium substitution.
    premium_after_mod = 0
    expense_constants = []
    for sc, summed in state_sums.items():
        post_mod = _round_half_up_int(Decimal(summed) * mod)
        # Threshold/min from the governing table (earliest segment's table for the state).
        tables_for_state = list(state_tables[sc].values())
        tables_for_state.sort(key=lambda t: t["_from"])
        governing = tables_for_state[0]
        if include_adders and post_mod < governing["min_payroll_threshold_cents"]:
            post_mod = governing["state_minimum_premium_cents"]
        premium_after_mod += post_mod
        if include_adders:
            for t in tables_for_state:
                expense_constants.append(t["expense_constant_cents"])

    if not include_adders:
        per_capita_fees = 0
    expense_constant = max(expense_constants) if expense_constants else 0
    total = premium_after_mod + per_capita_fees + expense_constant

    return {
        "manual_premium_cents": manual_premium,
        "experience_mod_applied": _mod_str(experience_mod),
        "premium_after_mod_cents": premium_after_mod,
        "per_capita_fees_cents": per_capita_fees,
        "expense_constant_cents": expense_constant,
        "total_cents": total,
    }
