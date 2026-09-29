"""Trial sites, trial series, entries, phenotype observations and analyses."""

from flask import Blueprint

import auth
import calc
import derive
import lookup
import mut
import store
import validators as v
from envelope import respond, respond_list
from errors import ApiError, bad_request

bp = Blueprint("trials", __name__)

SERIES_STATUSES = ["PLANNING", "PLANTED", "DATA_COMPLETE", "ANALYZED", "CLOSED"]
ENTRY_STATUSES = ["ENTERED", "PLANTED", "HARVESTED", "WITHDRAWN", "INVALIDATED"]


def _series_not_closed(series):
    if series["status"] == "CLOSED":
        raise ApiError("ERR_SERIES_INVALID_STATE", "A CLOSED series accepts no mutation.")


# ===========================================================================
# TrialSite
# ===========================================================================
@bp.post("/trial-sites")
def create_site():
    auth.authorize("TrialAgronomist")
    body = v.json_body()
    site_code = v.req_str(body, "site_code")
    environment_class = v.req_enum(body, "environment_class", v.ENVIRONMENT_CLASSES)
    total_plot_capacity = v.req_int(body, "total_plot_capacity", minimum=1)
    plot_cost_usd = calc.rhu(v.req_num(body, "plot_cost_usd", gt=0), 2)
    season_start_date = v.req_date(body, "season_start_date")
    season_end_date = v.req_date(body, "season_end_date")
    if not season_end_date > season_start_date:
        bad_request("season_end_date must be strictly later than season_start_date.")

    for existing in store.sites.values():
        if existing["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "site_code '%s' is already registered." % site_code)

    rec = store.new_record()
    rec.update({
        "site_code": site_code,
        "environment_class": environment_class,
        "total_plot_capacity": total_plot_capacity,
        "plot_cost_usd": plot_cost_usd,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
        "peak_committed_plot_count": 0,
        "available_plot_count": total_plot_capacity,
        "capacity_posture": "OPEN",
    })
    store.sites[rec["id"]] = rec
    return respond(rec, 201)


@bp.get("/trial-sites/<sid>")
def read_site(sid):
    auth.authorize("PipelineDirector", "TrialAgronomist", "ProgramLead", "DataAnalyst")
    return respond(lookup.site(sid))


# ===========================================================================
# TrialSeries
# ===========================================================================
@bp.post("/trial-series")
def create_series():
    auth.authorize("ProgramLead", "TrialAgronomist")
    body = v.json_body()
    program_id = v.req_id(body, "program_id")
    stage = v.req_enum(body, "stage", v.SERIES_STAGES)
    season_year = v.req_int(body, "season_year", minimum=1)
    plot_design = v.req_enum(body, "plot_design", v.PLOT_DESIGNS)
    replication_count = v.req_int(body, "replication_count", minimum=2)
    min_locations = v.req_int(body, "min_locations", minimum=1)

    auth.scope(program_id)
    program = lookup.program(program_id)
    lookup.program_open(program)

    rec = store.new_record()
    rec.update({
        "program_id": program["id"],
        "stage": stage,
        "season_year": season_year,
        "plot_design": plot_design,
        "replication_count": replication_count,
        "min_locations": min_locations,
        "entry_count": 0,
        "location_count": 0,
        "plot_cost_subtotal_usd": None,
        "management_fee_usd": None,
        "total_trial_cost_usd": None,
        "status": "PLANNING",
    })
    store.series[rec["id"]] = rec
    return respond(rec, 201)


@bp.get("/trial-series/<sid>")
def read_series(sid):
    auth.authorize("PipelineDirector", "TrialAgronomist", "ProgramLead", "DataAnalyst")
    series = lookup.series(sid)
    auth.scope(series["program_id"])
    return respond(series)


# ---------------------------------------------------------------------------
# POST /trial-series/{id}/entries
# ---------------------------------------------------------------------------
@bp.post("/trial-series/<sid>/entries")
def create_entry(sid):
    auth.authorize("TrialAgronomist")
    body = v.json_body()
    line_id = v.req_id(body, "line_id")
    trial_site_id = v.req_id(body, "trial_site_id")
    plot_count = v.req_int(body, "plot_count", minimum=1)
    window_start = v.req_date(body, "planting_window_start")
    window_end = v.req_date(body, "planting_window_end")

    series = lookup.series(sid)
    line = lookup.line(line_id)
    site = lookup.site(trial_site_id)
    program = derive.program_of_series(series)
    lookup.program_open(program)
    if series["status"] != "PLANNING":
        raise ApiError("ERR_SERIES_INVALID_STATE",
                       "Entries may only be added while the series is PLANNING.")
    lookup.line_not_discarded(line)

    if site["capacity_posture"] == "FROZEN":
        raise ApiError("ERR_SITE_CAPACITY_FROZEN",
                       "The trial site's capacity posture is FROZEN.")
    if site["capacity_posture"] == "RESTRICTED" and series["stage"] not in ("STAGE_2", "STAGE_3"):
        raise ApiError("ERR_SITE_RESTRICTED_STAGE",
                       "A RESTRICTED site admits only STAGE_2 or STAGE_3 series.")
    if (window_start < site["season_start_date"] or window_end > site["season_end_date"]
            or window_end < window_start):
        raise ApiError("ERR_ENTRY_WINDOW_OUTSIDE_SEASON",
                       "The planting window must sit inside the site's season window.")
    for existing in derive.entries_of_series(series["id"]):
        if (existing["line_id"] == line["id"]
                and existing["trial_site_id"] == site["id"]
                and existing["status"] in derive.ENTRY_ACTIVE):
            raise ApiError("ERR_DUPLICATE_TRIAL_ENTRY",
                           "This line is already entered at this site in this series.")
    if plot_count % series["replication_count"] != 0:
        raise ApiError("ERR_PLOT_COUNT_NOT_DIVISIBLE",
                       "plot_count must be an exact multiple of the series replication_count.")
    peak = derive.site_peak(site, extra=(window_start, window_end, plot_count))
    if peak > site["total_plot_capacity"]:
        raise ApiError("ERR_SITE_PLOT_CAPACITY_EXCEEDED",
                       "The entry would push the site's daily peak beyond its capacity.")
    if plot_count > program["plot_budget_remaining"]:
        raise ApiError("ERR_PROGRAM_PLOT_BUDGET_EXCEEDED",
                       "The entry exceeds the programme's remaining plot budget.")

    rec = store.new_record()
    rec.update({
        "trial_series_id": series["id"],
        "line_id": line["id"],
        "trial_site_id": site["id"],
        "plot_count": plot_count,
        "planting_window_start": window_start,
        "planting_window_end": window_end,
        "valid_rep_count": 0,
        "plot_mean_yield_kg": None,
        "yield_kg_per_ha": None,
        "withdrawal_reason": None,
        "status": "ENTERED",
        "_in_census": True,
    })
    store.entries[rec["id"]] = rec
    derive.recompute_series_census(series)
    derive.recompute_site(site)
    derive.recompute_program(program)
    mut.commit()
    return respond(rec, 201)


# ---------------------------------------------------------------------------
# POST /trial-series/{id}/plant
# ---------------------------------------------------------------------------
@bp.post("/trial-series/<sid>/plant")
def plant_series(sid):
    auth.authorize("TrialAgronomist")
    series = lookup.series(sid)
    program = derive.program_of_series(series)
    lookup.program_open(program)
    if series["status"] != "PLANNING":
        raise ApiError("ERR_SERIES_INVALID_STATE",
                       "Only a PLANNING series may be committed to the ground.")
    if series["location_count"] < series["min_locations"] or series["entry_count"] < 2:
        raise ApiError("ERR_INSUFFICIENT_LOCATIONS",
                       "The network needs at least min_locations locations and 2 entries.")

    entered = [e for e in derive.entries_of_series(series["id"]) if e["status"] == "ENTERED"]
    pairs = []
    for entry in entered:
        site = store.sites.get(entry["trial_site_id"])
        pairs.append((entry["plot_count"], site["plot_cost_usd"]))
    subtotal, fee, total = calc.series_cost(pairs)

    available = (calc.dec(program["total_budget_usd"])
                 - calc.dec(program["committed_budget_usd"]))
    if total > available:
        raise ApiError("ERR_PROGRAM_BUDGET_USD_EXCEEDED",
                       "The trial cost exceeds the programme's uncommitted cash budget.")

    mut.force(series)
    series["status"] = "PLANTED"
    series["plot_cost_subtotal_usd"] = subtotal
    series["management_fee_usd"] = fee
    series["total_trial_cost_usd"] = total
    for entry in entered:
        mut.force(entry)
        entry["status"] = "PLANTED"
    derive.recompute_program(program)
    mut.commit()
    return respond(series)


# ---------------------------------------------------------------------------
# POST /trial-series/{id}/close
# ---------------------------------------------------------------------------
@bp.post("/trial-series/<sid>/close")
def close_series(sid):
    auth.authorize("PipelineDirector")
    series = lookup.series(sid)
    program = derive.program_of_series(series)
    lookup.program_open(program)
    if series["status"] != "ANALYZED":
        raise ApiError("ERR_SERIES_INVALID_STATE", "Only an ANALYZED series may be closed.")

    harvested_lines = {e["line_id"] for e in derive.entries_of_series(series["id"])
                       if e["status"] == "HARVESTED"}
    for line_id in harvested_lines:
        decided = any(d for d in store.decisions.values()
                      if d["line_id"] == line_id
                      and d["trial_series_id"] == series["id"]
                      and not d["is_superseded"])
        if not decided:
            raise ApiError("ERR_SERIES_INVALID_STATE",
                           "Every line with a HARVESTED entry needs a live advancement decision.")

    mut.force(series)
    series["status"] = "CLOSED"
    derive.recompute_program(program)
    mut.commit()
    return respond(series)


# ===========================================================================
# TrialEntry
# ===========================================================================
@bp.get("/trial-entries/<eid>")
def read_entry(eid):
    auth.authorize("PipelineDirector", "TrialAgronomist", "ProgramLead", "DataAnalyst")
    entry = lookup.entry(eid)
    program = derive.program_of_entry(entry)
    auth.scope(program["id"] if program else None)
    return respond(entry)


@bp.get("/trial-entries")
def list_entries():
    auth.authorize("PipelineDirector", "TrialAgronomist", "ProgramLead", "DataAnalyst")
    limit, offset = v.pagination()
    series_id = v.query_str("trial_series_id")
    line_id = v.query_str("line_id")
    site_id = v.query_str("trial_site_id")
    status = v.query_enum("status", ENTRY_STATUSES)
    rows = store.ordered(store.entries)
    if series_id is not None:
        rows = [r for r in rows if r["trial_series_id"] == series_id]
    if line_id is not None:
        rows = [r for r in rows if r["line_id"] == line_id]
    if site_id is not None:
        rows = [r for r in rows if r["trial_site_id"] == site_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# PhenotypeObservation
# ---------------------------------------------------------------------------
@bp.post("/trial-entries/<eid>/observations")
def create_observation(eid):
    auth.authorize("TrialAgronomist")
    body = v.json_body()
    trait_code = v.req_enum(body, "trait_code", v.TRAIT_CODES)
    rep_number = v.req_int(body, "rep_number", minimum=1)
    value = v.req_num(body, "value", ge=0)
    qc_status = v.opt_enum(body, "qc_status", v.QC_STATUSES, default="ACCEPTED")
    is_outlier = v.opt_bool(body, "is_outlier", default=False)

    entry = lookup.entry(eid)
    series = derive.series_of_entry(entry)
    program = derive.program_of_entry(entry)
    lookup.program_open(program)
    _series_not_closed(series)
    if entry["status"] not in ("ENTERED", "PLANTED"):
        raise ApiError("ERR_ENTRY_INVALID_STATE",
                       "Observations may only be recorded on an ENTERED or PLANTED entry.")
    if rep_number > series["replication_count"]:
        raise ApiError("ERR_DUPLICATE_OBSERVATION",
                       "rep_number must lie between 1 and the series replication_count.")
    for obs in derive.observations_of_entry(entry["id"]):
        if obs["trait_code"] == trait_code and obs["rep_number"] == rep_number:
            raise ApiError("ERR_DUPLICATE_OBSERVATION",
                           "An observation already exists for this trait and replication.")

    rec = store.new_record(versioned=False)
    rec.update({
        "trial_entry_id": entry["id"],
        "trait_code": trait_code,
        "rep_number": rep_number,
        "value": value,
        "qc_status": qc_status,
        "is_outlier": is_outlier,
        "recorded_by_user_id": auth.user_id(),
    })
    store.observations[rec["id"]] = rec
    derive.recompute_valid_rep_count(entry)
    mut.commit()
    return respond(rec, 201)


@bp.get("/trial-entries/<eid>/observations")
def list_observations(eid):
    auth.authorize("PipelineDirector", "TrialAgronomist", "DataAnalyst")
    limit, offset = v.pagination()
    trait_code = v.query_enum("trait_code", v.TRAIT_CODES)
    qc_status = v.query_enum("qc_status", v.QC_STATUSES)
    entry = lookup.entry(eid)
    rows = derive.observations_of_entry(entry["id"])
    if trait_code is not None:
        rows = [r for r in rows if r["trait_code"] == trait_code]
    if qc_status is not None:
        rows = [r for r in rows if r["qc_status"] == qc_status]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# entry endings
# ---------------------------------------------------------------------------
@bp.post("/trial-entries/<eid>/finalize")
def finalize_entry(eid):
    auth.authorize("TrialAgronomist")
    entry = lookup.entry(eid)
    series = derive.series_of_entry(entry)
    program = derive.program_of_entry(entry)
    lookup.program_open(program)
    _series_not_closed(series)
    if entry["status"] != "PLANTED":
        raise ApiError("ERR_ENTRY_INVALID_STATE", "Only a PLANTED entry may be finalised.")
    if entry["valid_rep_count"] < calc.MIN_VALID_REPS:
        raise ApiError("ERR_INSUFFICIENT_REPLICATION",
                       "At least 3 valid replications are needed to finalise the entry.")

    values = [o["value"] for o in derive.valid_yield_observations(entry["id"])]
    plot_mean, per_ha = calc.entry_yield_rollup(values)
    mut.force(entry)
    entry["plot_mean_yield_kg"] = plot_mean
    entry["yield_kg_per_ha"] = per_ha
    entry["status"] = "HARVESTED"
    derive.bubble_series_data_complete(series)
    derive.recompute_program(program)
    mut.commit()
    return respond(entry)


@bp.post("/trial-entries/<eid>/withdraw")
def withdraw_entry(eid):
    auth.authorize("TrialAgronomist")
    body = v.json_body()
    reason = v.req_str(body, "withdrawal_reason")

    entry = lookup.entry(eid)
    series = derive.series_of_entry(entry)
    program = derive.program_of_entry(entry)
    lookup.program_open(program)
    _series_not_closed(series)
    if entry["status"] not in ("ENTERED", "PLANTED"):
        raise ApiError("ERR_ENTRY_INVALID_STATE",
                       "Only an ENTERED or PLANTED entry may be withdrawn.")

    mut.force(entry)
    entry["status"] = "WITHDRAWN"
    entry["withdrawal_reason"] = reason
    entry["_in_census"] = False
    derive.recompute_site(derive.site_of_entry(entry))
    derive.recompute_series_census(series)
    derive.bubble_series_data_complete(series)
    derive.recompute_program(program)
    mut.commit()
    return respond(entry)


@bp.post("/trial-entries/<eid>/invalidate")
def invalidate_entry(eid):
    auth.authorize("TrialAgronomist")
    body = v.json_body()
    reason = v.req_str(body, "withdrawal_reason")

    entry = lookup.entry(eid)
    series = derive.series_of_entry(entry)
    program = derive.program_of_entry(entry)
    lookup.program_open(program)
    _series_not_closed(series)
    if entry["status"] != "PLANTED":
        raise ApiError("ERR_ENTRY_INVALID_STATE", "Only a PLANTED entry may be invalidated.")

    mut.force(entry)
    entry["status"] = "INVALIDATED"
    entry["withdrawal_reason"] = reason
    entry["plot_mean_yield_kg"] = None
    entry["yield_kg_per_ha"] = None
    derive.recompute_site(derive.site_of_entry(entry))
    derive.bubble_series_data_complete(series)
    derive.recompute_program(program)
    mut.commit()
    return respond(entry)


# ===========================================================================
# TrialSeriesAnalysis (PRD 3.7)
# ===========================================================================
def _core_sites(candidates):
    """A site is core when every line with a harvested entry anywhere in the
    series also has a harvested entry at that site."""
    all_lines = {e["line_id"] for e in candidates}
    by_site = {}
    for entry in candidates:
        by_site.setdefault(entry["trial_site_id"], set()).add(entry["line_id"])
    return {site_id for site_id, lines in by_site.items() if lines >= all_lines}


@bp.post("/trial-series/<sid>/analyses")
def create_analysis(sid):
    auth.authorize("DataAnalyst")
    body = v.json_body()
    variant = v.req_enum(body, "variant", v.ANALYSIS_VARIANTS)
    expected_series_version = v.req_int(body, "expected_series_version", minimum=1)

    series = lookup.series(sid)
    if expected_series_version != series["version"]:
        raise ApiError("ERR_STALE_SERIES_VERSION",
                       "expected_series_version does not match the series' current version.")
    program = derive.program_of_series(series)
    lookup.program_open(program)
    if series["status"] not in ("DATA_COMPLETE", "ANALYZED"):
        raise ApiError("ERR_SERIES_INVALID_STATE",
                       "A series may only be analysed while DATA_COMPLETE or ANALYZED.")

    candidates = [e for e in derive.entries_of_series(series["id"])
                  if e["status"] == "HARVESTED"]
    if not candidates:
        raise ApiError("ERR_EMPTY_BALANCED_CORE",
                       "The series has no HARVESTED entry to analyse.")
    if variant == "BALANCED_CORE":
        core = _core_sites(candidates)
        if not core:
            raise ApiError("ERR_EMPTY_BALANCED_CORE",
                           "No location qualifies as part of the balanced core.")
        included = [e for e in candidates if e["trial_site_id"] in core]
    else:
        included = list(candidates)
    if not included:
        raise ApiError("ERR_EMPTY_BALANCED_CORE",
                       "The inclusion set for this variant is empty.")

    # --- environment index, one unweighted mean per included location -------
    site_ids = []
    for entry in included:
        if entry["trial_site_id"] not in site_ids:
            site_ids.append(entry["trial_site_id"])
    site_index = {}
    environment_index = []
    for site_id in site_ids:
        rows = [e for e in included if e["trial_site_id"] == site_id]
        total = sum((calc.dec(e["yield_kg_per_ha"]) for e in rows), calc.Decimal(0))
        index = calc.rhu(total / calc.Decimal(len(rows)), 2)
        site_index[site_id] = index
        site = store.sites.get(site_id)
        environment_index.append({
            "trial_site_id": site_id,
            "environment_class": site["environment_class"],
            "index_kg_per_ha": index,
            "_created_at": site["created_at"],
            "_seq": site["_seq"],
        })

    # --- per-line adjusted means and stability -----------------------------
    line_ids = []
    for entry in included:
        if entry["line_id"] not in line_ids:
            line_ids.append(entry["line_id"])
    entry_means = []
    for line_id in line_ids:
        rows = [e for e in included if e["line_id"] == line_id]
        weight_total = sum(e["valid_rep_count"] for e in rows)
        if weight_total > 0:
            weighted = sum((calc.dec(e["yield_kg_per_ha"]) * calc.dec(e["valid_rep_count"])
                            for e in rows), calc.Decimal(0))
            adjusted = calc.rhu(weighted / calc.dec(weight_total), 2)
        else:
            plain = sum((calc.dec(e["yield_kg_per_ha"]) for e in rows), calc.Decimal(0))
            adjusted = calc.rhu(plain / calc.Decimal(len(rows)), 2)
        points = [(site_index[e["trial_site_id"]], calc.dec(e["yield_kg_per_ha"])) for e in rows]
        b, mse, cls = calc.stability(points)
        line = store.lines.get(line_id)
        entry_means.append({
            "line_id": line_id,
            "adjusted_mean_kg_per_ha": adjusted,
            "included_location_count": len({e["trial_site_id"] for e in rows}),
            "stability_regression_b": b,
            "deviation_mse": mse,
            "stability_class": cls,
            "_created_at": line["created_at"],
            "_seq": line["_seq"],
        })

    entry_means.sort(key=lambda r: (-r["adjusted_mean_kg_per_ha"], r["_created_at"], r["_seq"]))
    environment_index.sort(key=lambda r: (-r["index_kg_per_ha"], r["_created_at"], r["_seq"]))
    for row in entry_means:
        row.pop("_created_at", None)
        row.pop("_seq", None)
    for row in environment_index:
        row.pop("_created_at", None)
        row.pop("_seq", None)

    rec = store.new_record()
    rec.update({
        "trial_series_id": series["id"],
        "variant": variant,
        "included_location_count": len(site_ids),
        "included_line_count": len(line_ids),
        "entry_means": entry_means,
        "environment_index": environment_index,
        "is_superseded": False,
        "run_by_user_id": auth.user_id(),
    })

    for earlier in derive.analyses_of_series(series["id"]):
        if earlier["variant"] == variant and not earlier["is_superseded"]:
            mut.force(earlier)
            earlier["is_superseded"] = True
    store.analyses[rec["id"]] = rec

    mut.force(series)
    series["status"] = "ANALYZED"
    for row in entry_means:
        line = store.lines.get(row["line_id"])
        if line is not None:
            derive.recompute_provisional_index(line, series["id"])
    derive.recompute_program(program)
    mut.commit()
    return respond(rec, 201)


@bp.get("/trial-series/<sid>/analyses")
def list_analyses(sid):
    auth.authorize("PipelineDirector", "DataAnalyst", "ProgramLead", "TrialAgronomist")
    limit, offset = v.pagination()
    variant = v.query_enum("variant", v.ANALYSIS_VARIANTS)
    is_superseded = v.query_bool("is_superseded")
    series = lookup.series(sid)
    auth.scope(series["program_id"])
    rows = derive.analyses_of_series(series["id"])
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]
    if is_superseded is not None:
        rows = [r for r in rows if r["is_superseded"] == is_superseded]
    page, total = v.paginate(rows, limit, offset)
    return respond_list(page, limit, offset, total)
