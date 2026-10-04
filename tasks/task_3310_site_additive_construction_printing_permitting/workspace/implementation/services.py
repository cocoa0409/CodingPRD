"""Derived-field, posture, lazy-evaluation and calculation services."""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, fmt_dt, parse_dt, touch

# --- Calculation constants (SCAFFOLD §1.3) ---
BASE_PERMIT_FEE_CENTS = 250000
PER_M2_FEE_CENTS = 4500
AM_SURCHARGE_CENTS = 175000
AM_RESUBMIT_MARKUP_PCT = Decimal("0.10")
MAX_AM_REVIEW_ROUNDS = 3

LAYER_PRINT_MIN_PER_LAYER = 8
BASELINE_WINDOW = 3
ROLLING_WINDOW = 3

CURE_PENALTY_WINDOW_MIN = 10
HARD_INTERRUPTION_CAP_MIN = 60
MAX_INTERRUPTION_MIN = {"LAVACRETE_A": 30, "LAVACRETE_B": 20, "LAVACRETE_C": 45}

FOUNDATION_CURE_HOURS = 72

PUMP_WINDOWS = {"LAVACRETE_A": (40, 60), "LAVACRETE_B": (55, 75), "LAVACRETE_C": (30, 50)}
SLUMP_TOLERANCE_MM = 15

BOND_MIN_MPA = Decimal("1.5")
DIM_TOL_MM = 6

WEATHER_OBSERVATION_VALID_MIN = 30


# ---------------- derived helpers ----------------

def batch_derived(batch):
    win = PUMP_WINDOWS[batch["mix_code"]]
    batch["pump_window_kg_per_min"] = [win[0], win[1]]
    batch["slump_within_band"] = (
        abs(batch["measured_slump_mm"] - batch["target_slump_mm"]) <= SLUMP_TOLERANCE_MM
    )
    flow = batch["pump_consistency_kg_per_min"]
    batch["is_pumpable"] = batch["slump_within_band"] and win[0] <= flow <= win[1]


def weather_derived(obs):
    obs["is_print_permissible"] = (
        4 <= obs["air_temp_c"] <= 38
        and obs["relative_humidity_pct"] <= 90
        and obs["wind_speed_mps"] <= 12
        and obs["precipitation_mm"] == 0
    )


def inspection_derived(insp):
    insp["passes_bond"] = Decimal(str(insp["bond_strength_mpa"])) >= BOND_MIN_MPA
    insp["passes_dimensional"] = insp["dimensional_deviation_mm"] <= DIM_TOL_MM
    if insp["passes_bond"] and insp["passes_dimensional"]:
        insp["outcome"] = "PASS"
    elif not insp["passes_bond"] and insp["passes_dimensional"]:
        insp["outcome"] = "FAIL_BOND"
    elif insp["passes_bond"] and not insp["passes_dimensional"]:
        insp["outcome"] = "FAIL_DIMENSIONAL"
    else:
        insp["outcome"] = "FAIL_BOTH"


def latest_weather(site_id):
    obs = [o for o in store.weather.values() if o["site_id"] == site_id]
    if not obs:
        return None
    # newest observed_at, tie-break earliest created_at
    obs.sort(key=lambda o: (-parse_dt(o["observed_at"]).timestamp(), o["created_at"]))
    return obs[0]


def site_jobs(site_id):
    return [j for j in store.print_jobs.values() if j["site_id"] == site_id]


def job_inspections(job_id):
    return [i for i in store.inspections.values() if i["print_job_id"] == job_id]


def job_interruptions(job_id):
    return [i for i in store.interruptions.values() if i["print_job_id"] == job_id]


def open_interruption(job_id):
    for i in job_interruptions(job_id):
        if i["status"] == "OPEN":
            return i
    return None


def site_posture(site_id):
    site = store.sites.get(site_id)
    if site is None:
        return "OPERATING"
    if site["status"] == "SUSPENDED":
        return "STOP"
    jobs = site_jobs(site_id)
    job_ids = {j["id"] for j in jobs}
    insps = [i for i in store.inspections.values() if i["print_job_id"] in job_ids]
    if any(i["disposition"] == "DEMOLISH_REQUIRED" for i in insps):
        return "STOP"
    active_ids = {j["id"] for j in jobs if j["status"] in ("PRINTING", "PAUSED")}
    inters = [i for i in store.interruptions.values() if i["print_job_id"] in active_ids]
    if any(i["status"] == "OVERRUN" for i in inters):
        return "STOP"
    lw = latest_weather(site_id)
    if lw is not None and not lw["is_print_permissible"] and any(
        j["status"] in ("PRINTING", "PAUSED") for j in jobs
    ):
        return "PRECAUTIONARY"
    if any(i["disposition"] == "REPAIR_REQUIRED" for i in insps):
        return "PRECAUTIONARY"
    return "OPERATING"


def recompute_posture(site_id):
    site = store.sites.get(site_id)
    if site is not None:
        site["posture"] = site_posture(site_id)


# ---------------- lazy system evaluations ----------------

def lazy_eval_site(site):
    """Apply clock-driven lazy transitions for everything under this site."""
    # AM review expiry
    for p in store.permits.values():
        if p["site_id"] == site["id"] and p["status"] == "AM_REVIEW":
            if p.get("am_decision_due_at") and parse_dt(p["am_decision_due_at"]) < now():
                # Record the state the application was in when the deadline
                # passed so the DECIDE temporal gate (PRD §2.11 item 7) can
                # still surface ERR_AM_REVIEW_EXPIRED after the auto-transition.
                p["am_expired_from_status"] = "AM_REVIEW"
                p["status"] = "RESUBMIT_REQUIRED"
                touch(p)
    # interruption OVERRUN flagging
    for j in site_jobs(site["id"]):
        if j["status"] == "PAUSED":
            intr = open_interruption(j["id"])
            if intr is not None and intr.get("max_permissible_interruption_minutes") is not None:
                elapsed = (now() - parse_dt(intr["paused_at"])).total_seconds() / 60.0
                if elapsed > intr["max_permissible_interruption_minutes"]:
                    intr["status"] = "OVERRUN"
                    touch(intr)
                    j["posture"] = "BLOCKED"
                    touch(j)
    recompute_posture(site["id"])
    # trade task readiness: PLANNED -> READY the moment dependencies are
    # satisfied, re-evaluated on every dependency change (PRD §3.10) — the
    # logical clock advancing past earliest_start_at is such a change.
    reevaluate_trade_tasks(site["id"])


def lazy_eval_permit(permit):
    if permit["status"] == "AM_REVIEW":
        if permit.get("am_decision_due_at") and parse_dt(permit["am_decision_due_at"]) < now():
            permit["am_expired_from_status"] = "AM_REVIEW"
            permit["status"] = "RESUBMIT_REQUIRED"
            touch(permit)


def lazy_eval_all():
    """Clock-set triggers every deferred evaluation system-wide."""
    for p in store.permits.values():
        lazy_eval_permit(p)
    for j in store.print_jobs.values():
        if j["status"] == "PAUSED":
            intr = open_interruption(j["id"])
            if intr is not None and intr.get("max_permissible_interruption_minutes") is not None:
                elapsed = (now() - parse_dt(intr["paused_at"])).total_seconds() / 60.0
                if elapsed > intr["max_permissible_interruption_minutes"]:
                    intr["status"] = "OVERRUN"
                    touch(intr)
                    j["posture"] = "BLOCKED"
                    touch(j)
    for site in store.sites.values():
        recompute_posture(site["id"])
        # clock-driven trade-task readiness (PLANNED -> READY)
        reevaluate_trade_tasks(site["id"])


# ---------------- permit fee ----------------

def permit_fee(permit, routed_to_am):
    revision = store.revisions.get(permit["plan_revision_id"])
    plan = store.plans.get(revision["plan_id"]) if revision else None
    area = Decimal(str(plan["plan_area_m2"])) if plan else Decimal("0")
    area_component = int(area.to_integral_value(rounding="ROUND_FLOOR")) * PER_M2_FEE_CENTS
    base = BASE_PERMIT_FEE_CENTS + area_component
    if routed_to_am:
        base += AM_SURCHARGE_CENTS
    rnd = permit.get("review_round", 0)
    if rnd == 0:
        multiplier = Decimal("1.0")
    else:
        multiplier = Decimal("1.0") + AM_RESUBMIT_MARKUP_PCT * rnd
    fee = (Decimal(base) * multiplier).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee)


# ---------------- interruptions ----------------

def close_interruption(intr):
    resumed = now()
    paused = parse_dt(intr["paused_at"])
    duration = int((resumed - paused).total_seconds() // 60)
    intr["resumed_at"] = fmt_dt(resumed)
    intr["duration_minutes"] = duration
    if intr["cause"] in ("WEATHER", "MATERIAL"):
        intr["cure_penalty_layers"] = int(math.ceil(duration / CURE_PENALTY_WINDOW_MIN)) if duration > 0 else 0
    else:
        intr["cure_penalty_layers"] = 0
    intr["status"] = "CLOSED"
    touch(intr)


def recompute_cumulative_interruption(job):
    total = 0
    for i in job_interruptions(job["id"]):
        if i["status"] in ("CLOSED",) and i.get("duration_minutes") is not None:
            total += i["duration_minutes"]
    job["cumulative_interruption_minutes"] = total


# ---------------- learning curve ----------------

def fwd_estimate_minutes(job):
    return int(math.ceil(job["total_layers_planned"] * LAYER_PRINT_MIN_PER_LAYER))


def deployment_sites(deployment_id):
    sites = [s for s in store.sites.values() if s.get("community_deployment_id") == deployment_id]
    return sites


def completed_units(deployment_id):
    """COMPLETED sites of a deployment, chronological by foundation_poured_at, tie created_at."""
    units = [s for s in deployment_sites(deployment_id) if s["status"] == "COMPLETED"]

    def key(s):
        poured = s.get("foundation_poured_at") or s["created_at"]
        return (parse_dt(poured).timestamp(), s["created_at"])

    units.sort(key=key)
    return units


def site_completed_job(site_id):
    """The completed print job on a completed site (first completed job)."""
    jobs = [j for j in site_jobs(site_id) if j["status"] == "COMPLETED"]
    jobs.sort(key=lambda j: j["created_at"])
    return jobs[0] if jobs else None


def _median(values):
    vals = sorted(values)
    n = len(vals)
    if n % 2 == 1:
        return Decimal(vals[n // 2])
    return (Decimal(vals[n // 2 - 1]) + Decimal(vals[n // 2])) / 2


def recompute_learning_curve(dep):
    dep_id = dep["id"]
    units = completed_units(dep_id)
    dep["completed_unit_count"] = len(units)

    if dep.get("learning_curve_baseline_minutes") is None:
        if len(units) >= BASELINE_WINDOW:
            first = units[:BASELINE_WINDOW]
            minutes = []
            for u in first:
                job = site_completed_job(u["id"])
                if job is not None and job.get("continuous_run_minutes") is not None:
                    minutes.append(job["continuous_run_minutes"])
            if len(minutes) >= BASELINE_WINDOW:
                dep["learning_curve_baseline_minutes"] = int(
                    _median(minutes).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
    baseline = dep.get("learning_curve_baseline_minutes")
    if baseline is None:
        dep["learning_curve_factor"] = None
        return

    # rolling average over last ROLLING_WINDOW completed units
    last_units = units[-ROLLING_WINDOW:]
    values = []
    for u in last_units:
        job = site_completed_job(u["id"])
        if job is not None and job.get("continuous_run_minutes") is not None:
            values.append(Decimal(job["continuous_run_minutes"]))

    if dep.get("learning_curve_variant") == "FORWARD_LOOKING":
        # mix in currently PRINTING jobs on deployment sites at forward-looking estimate
        site_ids = {s["id"] for s in deployment_sites(dep_id)}
        inflight = [
            j for j in store.print_jobs.values()
            if j["site_id"] in site_ids and j["status"] == "PRINTING"
        ]
        inflight.sort(key=lambda j: j["created_at"])
        for j in inflight:
            values.append(Decimal(fwd_estimate_minutes(j)))

    if not values:
        dep["learning_curve_factor"] = None
        return
    avg = sum(values) / Decimal(len(values))
    factor = (avg / Decimal(baseline)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    dep["learning_curve_factor"] = float(factor)


def job_utilization(job, site):
    """utilization reported at completion time, variant from deployment."""
    variant = "FORWARD_LOOKING"
    dep_id = site.get("community_deployment_id")
    if dep_id:
        dep = store.deployments.get(dep_id)
        if dep:
            variant = dep.get("learning_curve_variant", "FORWARD_LOOKING")
    start = parse_dt(job["scheduled_start_at"])
    end = parse_dt(job["scheduled_end_at"])
    scheduled_min = max(1, int((end - start).total_seconds() // 60))
    if variant == "FORWARD_LOOKING":
        est = fwd_estimate_minutes(job)
        util = Decimal(est) / Decimal(scheduled_min)
    else:
        a_start = parse_dt(job["actual_start_at"])
        a_end = parse_dt(job["actual_end_at"])
        actual_min = max(1, int((a_end - a_start).total_seconds() // 60))
        util = Decimal(job["continuous_run_minutes"]) / Decimal(actual_min)
    if util > 1:
        util = Decimal("1.0")
    return float(util.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------- trade tasks ----------------

def trade_blockers(task):
    site = store.sites[task["site_id"]]
    blockers = []
    job = store.print_jobs.get(task["depends_on_print_job_id"])
    if job is None or job["status"] != "COMPLETED":
        blockers.append("PRINT_INCOMPLETE")
    else:
        insps = job_inspections(job["id"])
        fails = [
            i for i in insps
            if i["outcome"] in ("FAIL_BOND", "FAIL_DIMENSIONAL", "FAIL_BOTH")
            and i["disposition"] == "PENDING"
        ]
        if fails:
            blockers.append("INSPECTION_PENDING")
    if task.get("depends_on_trade_task_id"):
        prior = store.trade_tasks.get(task["depends_on_trade_task_id"])
        if prior is None or prior["status"] != "COMPLETED":
            blockers.append("PRIOR_TRADE_INCOMPLETE")
    if now() < parse_dt(task["earliest_start_at"]):
        blockers.append("TOO_EARLY")
    if site["posture"] == "STOP":
        blockers.append("SITE_STOPPED")
    return blockers


def recompute_trade_task(task):
    blockers = trade_blockers(task)
    task["start_blockers"] = blockers
    task["is_startable"] = len(blockers) == 0


def reevaluate_trade_tasks(site_id):
    for t in store.trade_tasks.values():
        if t["site_id"] != site_id:
            continue
        recompute_trade_task(t)
        if t["status"] == "PLANNED":
            job = store.print_jobs.get(t["depends_on_print_job_id"])
            deps_ok = (
                job is not None
                and job["status"] == "COMPLETED"
                and all(
                    i["disposition"] != "PENDING"
                    for i in job_inspections(job["id"])
                    if i["outcome"] in ("FAIL_BOND", "FAIL_DIMENSIONAL", "FAIL_BOTH")
                )
            )
            prior_ok = True
            if t.get("depends_on_trade_task_id"):
                prior = store.trade_tasks.get(t["depends_on_trade_task_id"])
                prior_ok = prior is not None and prior["status"] == "COMPLETED"
            if deps_ok and prior_ok:
                t["status"] = "READY"
                touch(t)
