"""Project entity: registration, derived rollups and the five-tier posture ladder."""

from core import (CLOCK, DB, ApiError, dec, fail, new_record, num, rhu,
                  serialize, shift_days, to_dt, touch, whole_days_between)

CANONICAL_THRESHOLDS = {
    "SLIP_RELEASE_AT": 0.02,
    "SLIP_RECOVERY_AT": 0.05,
    "SLIP_HOLD_AT": 0.10,
    "SLIP_FREEZE_AT": 0.15,
}

INSTALL_PRODUCTIVITY_FLOOR = 0.40
FACTOR_TABLE = {"true": 11, "false": 16}
IDLE_WEIGHT_LADDER = [
    {"weight_floor_pct": 0.70, "multiplier": 0.85},
    {"weight_floor_pct": 0.85, "multiplier": 0.75},
    {"weight_floor_pct": None, "multiplier": 0.60},
]
VALUE_CLASSIFICATION = "JOURNEYMAN"


# --------------------------------------------------------------------------
# Rate resolution
# --------------------------------------------------------------------------

def rate_rows(jurisdiction_key=None, classification=None):
    rows = []
    for row in DB.all("trade_contract_rates"):
        if jurisdiction_key is not None and row.get("jurisdiction_key") != jurisdiction_key:
            continue
        if classification is not None and row.get("classification") != classification:
            continue
        rows.append(row)
    return rows


def governing_rate(jurisdiction_key, classification, apprentice_period=None, as_of=None):
    """Latest row whose effective_from_iso is at or before ``as_of``; ties by created_at asc."""
    if as_of is None:
        as_of = CLOCK.now()
    as_of = to_dt(as_of)
    candidates = []
    for row in rate_rows(jurisdiction_key, classification):
        if apprentice_period is not None and classification == "APPRENTICE":
            if row.get("apprentice_period") != apprentice_period:
                continue
        eff = to_dt(row.get("effective_from_iso"))
        if eff is not None and eff > as_of:
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (to_dt(r.get("effective_from_iso")) or as_of, r.get("created_at") or ""),
                    reverse=False)
    # order by effective date DESC, tie-break created_at ASC
    candidates.sort(key=lambda r: r.get("created_at") or "")
    candidates.sort(key=lambda r: to_dt(r.get("effective_from_iso")) or as_of, reverse=True)
    return candidates[0]


def rate_for(jurisdiction_key, classification, apprentice_period=None, as_of=None):
    row = governing_rate(jurisdiction_key, classification, apprentice_period, as_of)
    if row is None:
        return {"hourly_rate_cents": 0, "burden_pct": 0.0, "apprentice_ratio_max": None,
                "wait_ratio_max": None, "id": None, "found": False}
    out = dict(row)
    out["found"] = True
    return out


def journeyman_rate(dt=None):
    return rate_for(None, VALUE_CLASSIFICATION, as_of=dt)


def project_journeyman_rate(project, as_of=None):
    return rate_for(project.get("jurisdiction_key"), VALUE_CLASSIFICATION, as_of=as_of)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def create_project(body):
    if not isinstance(body, dict):
        fail("ERR_INVALID_PREFAB_TRANSITION", "request body must be an object")
    for required in ("project_code", "project_name"):
        if body.get(required) in (None, ""):
            fail("ERR_INVALID_PREFAB_TRANSITION", "%s is required" % required)

    thresholds = body.get("posture_thresholds")
    if not isinstance(thresholds, dict):
        thresholds = dict(CANONICAL_THRESHOLDS)
    else:
        merged = dict(CANONICAL_THRESHOLDS)
        for key in CANONICAL_THRESHOLDS:
            if thresholds.get(key) is not None:
                merged[key] = num(thresholds.get(key))
        thresholds = merged

    gate_commodities = body.get("material_gate_commodities")
    if gate_commodities is None:
        gate_commodities = []

    project = new_record(
        project_code=body.get("project_code"),
        project_name=body.get("project_name"),
        jurisdiction_key=body.get("jurisdiction_key"),
        planned_value_cents=body.get("planned_value_cents"),
        power_on_iso=body.get("power_on_iso"),
        laydown_slots=body.get("laydown_slots"),
        credit_policy=body.get("credit_policy") or "FIRST_ACCEPTED",
        posture_thresholds=thresholds,
        cumulative_narrative_count=body.get("cumulative_narrative_count", 0) or 0,
        insignificant_narrative_count=body.get("insignificant_narrative_count", 0) or 0,
        safety_program_required=bool(body.get("safety_program_required", False)),
        material_gate_commodities=list(gate_commodities),
        shop_utilization_pct=num(body.get("shop_utilization_pct"), 0.0),
        released_quantity=num(body.get("released_quantity"), 0.0),
        total_quantity=num(body.get("total_quantity"), 0.0),
        float_band_low_pct=num(body.get("float_band_low_pct"), 0.0),
        achieved_flow_margin_pct=num(body.get("achieved_flow_margin_pct"), 0.0),
        # computed rollups
        project_posture="ON_TRACK",
        slippage_pct=0.0,
        installed_pct=0.0,
        pipeline_value_cents=0,
        completed_value_cents=0,
        man_hours_total=0.0,
        apprentice_ratio_max=None,
        effective_flow_pct=0.0,
        approved_change_value_cents=0,
        apprentice_breach_flag=False,
        external_gate_open=True,
        fabrication_locked=False,
        fabricated_revision_active=False,
        craft_hours_credit=0.0,
        craft_hours_balance=0,
        idle_capacity_cents=0,
        delivery_gate="OPEN",
        critical_path_span_days=0,
        critical_path_shortfall_days=0,
    )
    DB.put("projects", project)
    refresh_project(project)
    return project


def require_project(project_id):
    """Resolve the project named in a path or body (ERR_PROJECT_NOT_FOUND, 404)."""
    if not project_id:
        fail("ERR_PROJECT_NOT_FOUND")
    project = DB.find("projects", project_id)
    if project is None:
        fail("ERR_PROJECT_NOT_FOUND")
    return project


# --------------------------------------------------------------------------
# Critical path / posture
# --------------------------------------------------------------------------

def critical_path(project):
    activities = [a for a in DB.all("trade_activities") if a.get("project_id") == project["id"]]
    span = 0
    shortfall = 0
    now = CLOCK.now()
    for activity in activities:
        if activity.get("status") == "COMPLETE":
            continue
        duration = num(activity.get("planned_duration_days"), 0)
        span += duration
        start = to_dt(activity.get("planned_start_iso"))
        if start is None:
            continue
        overdue = whole_days_between(start, now) - int(duration)
        if overdue > 0:
            shortfall += overdue
    return span, shortfall


def compute_slippage(project):
    span, shortfall = critical_path(project)
    project["critical_path_span_days"] = span
    project["critical_path_shortfall_days"] = shortfall
    if span > 0:
        return rhu(abs(shortfall) / float(span), 4)
    return 0.0


def posture_for_slippage(project, slippage_pct):
    thresholds = project.get("posture_thresholds") or CANONICAL_THRESHOLDS
    release_at = num(thresholds.get("SLIP_RELEASE_AT"), CANONICAL_THRESHOLDS["SLIP_RELEASE_AT"])
    recovery_at = num(thresholds.get("SLIP_RECOVERY_AT"), CANONICAL_THRESHOLDS["SLIP_RECOVERY_AT"])
    hold_at = num(thresholds.get("SLIP_HOLD_AT"), CANONICAL_THRESHOLDS["SLIP_HOLD_AT"])
    freeze_at = num(thresholds.get("SLIP_FREEZE_AT"), CANONICAL_THRESHOLDS["SLIP_FREEZE_AT"])
    if slippage_pct <= release_at:
        return "ON_TRACK"
    if slippage_pct <= recovery_at:
        return "RELEASE_PENDING"
    if slippage_pct <= hold_at:
        return "RECOVERY_MODE"
    if slippage_pct <= freeze_at:
        return "HOLD"
    return "FROZEN"


def fabricated_revision_active(project):
    for revision in DB.all("revisions"):
        if revision.get("project_id") != project["id"]:
            continue
        if revision.get("status") in ("APPROVED", "REJECTED", "SUPERSEDED"):
            continue
        if revision.get("affects_fabricated_content"):
            return True
    return False


def apprentice_breach_active(project):
    for row in DB.all("compliance_ledger"):
        if row.get("project_id") != project["id"]:
            continue
        if num(row.get("excess_apprentice_hours"), 0.0) > 0:
            return True
    return False


def refresh_project(project):
    """Re-derive every project-level rollup, in dependency order."""
    from calculations import (update_project_pipeline, craft_hours_credit,
                              craft_hours_balance, idle_capacity)

    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    project["apprentice_breach_flag"] = apprentice_breach_active(project)
    project["fabricated_revision_active"] = fabricated_revision_active(project)
    project["approved_change_value_cents"] = sum(
        int(r.get("approved_change_value_cents") or 0)
        for r in DB.all("revisions")
        if r.get("project_id") == project["id"] and r.get("status") == "APPROVED"
    )
    project["external_gate_open"] = project.get("delivery_gate") != "BLOCKED"
    return project


def refresh_project_soft(project):
    """Recompute the value rollups and ladder without touching the gate booleans."""
    from calculations import (update_project_pipeline, craft_hours_credit,
                              craft_hours_balance, idle_capacity)
    update_project_pipeline(project)
    craft_hours_credit(project)
    craft_hours_balance(project)
    idle_capacity(project)
    project["slippage_pct"] = compute_slippage(project)
    project["project_posture"] = posture_for_slippage(project, project["slippage_pct"])
    return project


def recompute_posture(project, propagate=True):
    """POST /projects/{id}/posture/recompute — walk the ladder and propagate."""
    from orders import recompute_all_releasable
    refresh_project(project)
    if propagate:
        recompute_all_releasable(project)
        fabrication_locked(project)
    touch(project)
    return project


def fabrication_locked(project):
    locked = False
    for order in DB.all("prefab_orders"):
        if order.get("project_id") != project["id"]:
            continue
        if order.get("releasable_status") == "ENGINEERING_HOLD" and order.get("rework_order_count", 0) > 0:
            locked = True
            break
    project["fabrication_locked"] = locked
    return locked


def set_external_gate(project, blocked):
    project["delivery_gate"] = "BLOCKED" if blocked else "OPEN"
    project["external_gate_open"] = not blocked
    from orders import recompute_all_releasable
    recompute_all_releasable(project)
    fabrication_locked(project)
    return project