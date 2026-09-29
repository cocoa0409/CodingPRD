"""Server-derived state, counters, postures and cascades (PRD 2.10, 3.1-3.9).

Nothing in here is ever accepted from a client.  Every function recomputes a
value from the records that justify it, and every record it changes is handed to
mut.watch()/mut.force() so that the version/updated_at discipline of PRD 2.4
applies uniformly.
"""

from datetime import timedelta
from decimal import Decimal

import calc
import mut
import store

ENTRY_ACTIVE = ("ENTERED", "PLANTED", "HARVESTED")
PLANTING_COMMITTED = ("SCHEDULED", "PLANTED")
PLANTING_OCCUPYING = ("SCHEDULED", "PLANTED", "HARVESTED", "FAILED")
SERIES_COSTED = ("PLANTED", "DATA_COMPLETE", "ANALYZED", "CLOSED")
LOT_RESERVING = ("RESERVED", "IN_PRODUCTION", "ON_HOLD")
LOT_PLANNED = ("RESERVED", "IN_PRODUCTION", "COMPLETED")


# ---------------------------------------------------------------------------
# navigation helpers
# ---------------------------------------------------------------------------
def program_of_line(line):
    return store.programs.get(line["program_id"]) if line else None


def program_of_series(series):
    return store.programs.get(series["program_id"]) if series else None


def line_of_entry(entry):
    return store.lines.get(entry["line_id"])


def series_of_entry(entry):
    return store.series.get(entry["trial_series_id"])


def site_of_entry(entry):
    return store.sites.get(entry["trial_site_id"])


def program_of_entry(entry):
    return program_of_line(line_of_entry(entry))


def line_of_agreement(agreement):
    return store.lines.get(agreement["line_id"])


def line_of_lot(lot):
    return store.lines.get(lot["line_id"])


def lines_of_program(program_id):
    return [ln for ln in store.ordered(store.lines) if ln["program_id"] == program_id]


def entries_of_series(series_id):
    return [e for e in store.ordered(store.entries) if e["trial_series_id"] == series_id]


def entries_of_line(line_id):
    return [e for e in store.ordered(store.entries) if e["line_id"] == line_id]


def entries_of_site(site_id):
    return [e for e in store.ordered(store.entries) if e["trial_site_id"] == site_id]


def observations_of_entry(entry_id):
    return [o for o in store.ordered(store.observations) if o["trial_entry_id"] == entry_id]


def lots_of_line(line_id):
    return [l for l in store.ordered(store.lots) if l["line_id"] == line_id]


def agreements_of_line(line_id):
    return [a for a in store.ordered(store.agreements) if a["line_id"] == line_id]


def analyses_of_series(series_id):
    return [a for a in store.ordered(store.analyses) if a["trial_series_id"] == series_id]


def decisions_of_line(line_id):
    return [d for d in store.ordered(store.decisions) if d["line_id"] == line_id]


def projects_of_line(line_id):
    return [p for p in store.ordered(store.projects) if p["recurrent_line_id"] == line_id]


def plantings_of_block(block_id):
    return [p for p in store.ordered(store.plantings) if p["nursery_block_id"] == block_id]


def plantings_of_line(line_id):
    return [p for p in store.ordered(store.plantings) if p["line_id"] == line_id]


# ---------------------------------------------------------------------------
# BreedingProgram counters (PRD 3.1)
# ---------------------------------------------------------------------------
def recompute_program(program):
    if program is None:
        return
    mut.watch(program)
    pid = program["id"]

    committed = 0
    for entry in store.entries.values():
        if entry["status"] not in ENTRY_ACTIVE:
            continue
        series = store.series.get(entry["trial_series_id"])
        if series is not None and series["program_id"] == pid:
            committed += entry["plot_count"]
    for planting in store.plantings.values():
        if planting["status"] not in PLANTING_COMMITTED:
            continue
        line = store.lines.get(planting["line_id"])
        if line is not None and line["program_id"] == pid:
            committed += planting["plot_count"]
    for decision in store.decisions.values():
        if decision["decision"] != "ADVANCE" or decision["is_superseded"]:
            continue
        line = store.lines.get(decision["line_id"])
        if line is None or line["program_id"] != pid:
            continue
        if line["pipeline_stage"] == "DISCARDED":
            continue
        committed += decision["granted_plots"]

    program["committed_plot_count"] = committed
    program["plot_budget_remaining"] = program["total_plot_budget"] - committed

    cash = Decimal("0.00")
    for series in store.series.values():
        if series["program_id"] != pid:
            continue
        if series["status"] in SERIES_COSTED and series.get("total_trial_cost_usd") is not None:
            cash += calc.dec(series["total_trial_cost_usd"])
    program["committed_budget_usd"] = calc.rhu(cash, 2)

    active = 0
    for line in store.lines.values():
        if line["program_id"] != pid:
            continue
        if line["pipeline_stage"] not in ("DISCARDED", "COMMERCIAL"):
            active += 1
    program["active_line_count"] = active

    bags = 0
    for lot in store.lots.values():
        line = store.lines.get(lot["line_id"])
        if line is None or line["program_id"] != pid:
            continue
        if lot["status"] in LOT_PLANNED:
            bags += lot["planned_units_bags"]
    program["pre_commercial_units_bags"] = bags


# ---------------------------------------------------------------------------
# NurseryBlock occupancy (PRD 3.3) -- derived live from the logical clock
# ---------------------------------------------------------------------------
def block_occupancy_status(block):
    today = store.clock_date()
    candidates = []
    for planting in plantings_of_block(block["id"]):
        if planting["status"] not in PLANTING_OCCUPYING:
            continue
        sow = planting["sow_date"]
        harvest = planting["expected_harvest_date"]
        end = planting["occupancy_end_date"]
        if today < sow or today >= end:
            continue
        candidates.append(planting)
    if not candidates:
        return "AVAILABLE"
    candidates.sort(key=lambda p: (p["sow_date"], p["created_at"], p["_seq"]))
    chosen = candidates[0]
    if chosen["sow_date"] <= today < chosen["expected_harvest_date"]:
        return "OCCUPIED"
    return "FALLOW"


def block_intervals_conflict(block_id, sow_date, occupancy_end_date, skip_id=None):
    """Half-open [sow_date, occupancy_end_date) intersection test."""
    for planting in plantings_of_block(block_id):
        if skip_id is not None and planting["id"] == skip_id:
            continue
        if planting["status"] not in PLANTING_OCCUPYING:
            continue
        if sow_date < planting["occupancy_end_date"] and planting["sow_date"] < occupancy_end_date:
            return True
    return False


def occupancy_end(expected_harvest_date, fallow_buffer_days):
    return expected_harvest_date + timedelta(days=int(fallow_buffer_days))


# ---------------------------------------------------------------------------
# TrialSite peak occupancy and posture (PRD 3.5)
# ---------------------------------------------------------------------------
def site_peak(site, extra=None, exclude_entry_id=None):
    """Daily peak of committed plots across the site's season window.

    The daily occupancy function only steps up at a window start, so evaluating
    the season start plus every in-season window start finds the same maximum a
    day-by-day sweep would.
    """
    start = site["season_start_date"]
    end = site["season_end_date"]
    active = []
    for entry in entries_of_site(site["id"]):
        if exclude_entry_id is not None and entry["id"] == exclude_entry_id:
            continue
        if entry["status"] not in ENTRY_ACTIVE:
            continue
        active.append((entry["planting_window_start"], entry["planting_window_end"],
                       entry["plot_count"]))
    if extra is not None:
        active.append(extra)
    if not active:
        return 0
    candidates = {start}
    for ws, _we, _pc in active:
        if start <= ws <= end:
            candidates.add(ws)
    peak = 0
    for day in candidates:
        total = 0
        for ws, we, pc in active:
            if ws <= day <= we:
                total += pc
        if total > peak:
            peak = total
    return peak


def recompute_site(site):
    if site is None:
        return
    mut.watch(site)
    peak = site_peak(site)
    site["peak_committed_plot_count"] = peak
    available = site["total_plot_capacity"] - peak
    site["available_plot_count"] = available if available > 0 else 0
    site["capacity_posture"] = calc.capacity_posture(peak, site["total_plot_capacity"])


# ---------------------------------------------------------------------------
# TrialSeries census (PRD 3.5 / 3.6)
# ---------------------------------------------------------------------------
def recompute_series_census(series):
    if series is None:
        return
    mut.watch(series)
    # `_in_census` is set at creation and cleared only on withdrawal: an
    # INVALIDATED entry keeps its census place because the ground was used
    # (PRD 3.6), while a withdrawal drops out of both counters.
    counted = [e for e in entries_of_series(series["id"]) if e.get("_in_census")]
    series["entry_count"] = len(counted)
    series["location_count"] = len({e["trial_site_id"] for e in counted})


def bubble_series_data_complete(series):
    """PRD 3.6: PLANTED -> DATA_COMPLETE when nothing is left PLANTED and at
    least one entry reached HARVESTED."""
    if series is None or series["status"] != "PLANTED":
        return
    entries = entries_of_series(series["id"])
    if any(e["status"] == "PLANTED" for e in entries):
        return
    if not any(e["status"] == "HARVESTED" for e in entries):
        return
    mut.force(series)
    series["status"] = "DATA_COMPLETE"


# ---------------------------------------------------------------------------
# TrialEntry replication census and rollup (PRD 3.6)
# ---------------------------------------------------------------------------
def valid_yield_observations(entry_id):
    out = []
    for obs in observations_of_entry(entry_id):
        if obs["trait_code"] != "YIELD_KG_PLOT":
            continue
        if obs["qc_status"] != "ACCEPTED":
            continue
        if obs["is_outlier"]:
            continue
        out.append(obs)
    return out


def recompute_valid_rep_count(entry):
    mut.watch(entry)
    entry["valid_rep_count"] = len(valid_yield_observations(entry["id"]))


# ---------------------------------------------------------------------------
# BreedingLine seed ledger and readiness (PRD 3.2 / 3.9)
# ---------------------------------------------------------------------------
def recompute_line_ledger(line):
    if line is None:
        return
    mut.watch(line)
    reserved = 0
    consumed = 0
    bags = 0
    for lot in lots_of_line(line["id"]):
        if lot["status"] in LOT_RESERVING:
            reserved += lot["allocated_seed_g"]
        if lot["status"] == "COMPLETED":
            consumed += lot["allocated_seed_g"]
        if lot["status"] in LOT_PLANNED:
            bags += lot["planned_units_bags"]
    line["reserved_seed_g"] = reserved
    line["consumed_seed_g"] = consumed
    line["planned_launch_units_bags"] = bags


def derive_readiness(line):
    objective = store.objectives.get(line["objective_id"])
    if objective is None:
        return "NOT_READY"
    if line["generation_number"] >= objective["min_generation_number"]:
        return "READY"
    return "NOT_READY"


# ---------------------------------------------------------------------------
# advancement index plumbing (PRD 3.8)
# ---------------------------------------------------------------------------
def winning_analysis(series_id):
    """Non-superseded BALANCED_CORE first, then UNBALANCED_INCLUSIVE."""
    live = [a for a in analyses_of_series(series_id) if not a["is_superseded"]]
    for variant in ("BALANCED_CORE", "UNBALANCED_INCLUSIVE"):
        matches = [a for a in live if a["variant"] == variant]
        if matches:
            return matches[-1]
    return None


def _mean_from_analysis(analysis, line_id):
    if analysis is None:
        return None
    for row in analysis["entry_means"]:
        if row["line_id"] == line_id:
            return row["adjusted_mean_kg_per_ha"]
    return None


def source_mean_for_series(line_id, series_id):
    live = [a for a in analyses_of_series(series_id) if not a["is_superseded"]]
    for variant in ("BALANCED_CORE", "UNBALANCED_INCLUSIVE"):
        for analysis in reversed([a for a in live if a["variant"] == variant]):
            mean = _mean_from_analysis(analysis, line_id)
            if mean is not None:
                return mean
    return None


def source_mean_anywhere(line_id):
    """Used when a trait map changes outside any particular series context."""
    live = [a for a in store.ordered(store.analyses) if not a["is_superseded"]]
    for variant in ("BALANCED_CORE", "UNBALANCED_INCLUSIVE"):
        for analysis in reversed([a for a in live if a["variant"] == variant]):
            mean = _mean_from_analysis(analysis, line_id)
            if mean is not None:
                return mean
    return None


def recompute_provisional_index(line, series_id=None):
    objective = store.objectives.get(line["objective_id"])
    if objective is None:
        return
    mut.watch(line)
    if series_id is not None:
        source = source_mean_for_series(line["id"], series_id)
    else:
        source = source_mean_anywhere(line["id"])
    line["advancement_index_provisional"] = calc.provisional_index(objective, line, source)


def cumulative_index_for(line, series_id):
    objective = store.objectives.get(line["objective_id"])
    if objective is None:
        return None
    source = source_mean_for_series(line["id"], series_id)
    return calc.cumulative_index(objective, line, source)


# ---------------------------------------------------------------------------
# cascades
# ---------------------------------------------------------------------------
def withdraw_entry_for_discard(entry):
    mut.force(entry)
    entry["status"] = "WITHDRAWN"
    entry["withdrawal_reason"] = "LINE_DISCARDED"
    entry["_in_census"] = False
    recompute_site(site_of_entry(entry))
    recompute_series_census(series_of_entry(entry))


def discard_cascade(line, program):
    """PRD 3.8 pinned order: line, then entries (each re-deriving its site and
    the programme), then seed lots, then backcross projects, then the line's own
    live ADVANCE decisions."""
    mut.force(line)
    line["pipeline_stage"] = "DISCARDED"

    for entry in entries_of_line(line["id"]):
        if entry["status"] in ("ENTERED", "PLANTED"):
            withdraw_entry_for_discard(entry)
            recompute_program(program)
    recompute_program(program)

    for lot in lots_of_line(line["id"]):
        if lot["status"] in LOT_RESERVING:
            mut.force(lot)
            lot["status"] = "CANCELLED"
            lot["hold_reason"] = "LINE_DISCARDED"
            line["seed_inventory_g"] = line["seed_inventory_g"] + lot["allocated_seed_g"]
            recompute_line_ledger(line)
    recompute_program(program)

    for project in projects_of_line(line["id"]):
        if project["status"] == "ACTIVE":
            mut.force(project)
            project["status"] = "TERMINATED"

    for decision in decisions_of_line(line["id"]):
        if decision["decision"] == "ADVANCE" and not decision["is_superseded"]:
            mut.force(decision)
            decision["is_superseded"] = True
    recompute_program(program)


def suspension_cascade(agreement, line, program):
    """PRD 3.9 pinned order: agreement, line, lots, then the launch counters."""
    mut.force(line)
    line["stewardship_status"] = "SUSPENDED"
    for lot in lots_of_line(line["id"]):
        if lot["status"] in ("RESERVED", "IN_PRODUCTION"):
            mut.force(lot)
            lot["status"] = "ON_HOLD"
            lot["hold_reason"] = "STEWARDSHIP_SUSPENDED"
    recompute_line_ledger(line)
    recompute_program(program)
