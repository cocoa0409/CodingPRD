"""Recompute and cascade services.

Two kinds of function live here:

* `recompute_*` — derived-field reconciliation (§2.4 "Two derived counters feed
  the posture and are themselves recomputed upward from the corridor's children
  whenever a child mutates").
* cascade helpers — the one-directional propagation §2.4 describes: "filing a
  critical incident, voiding an inspection programme, letting a calibration
  window lapse, or rolling the ledger epoch will all reach upward and move
  corridor posture, corridor status, carrier standing, terminal staffing and
  apron reservations in the same operation."

Derived fields are written through `mark`, which only flags a row when the value
actually changes; `flush` then applies the §2.10 rule that "recomputing one is
itself a mutation that touches the parent's updated_at and version".
"""

from decimal import Decimal

import db
import core
from core import D, rhu, parse_iso, now_iso, epoch_day, to_iso
import calculations as calc
import models

_DIRTY = {}


def mark(row, field, value):
    if row.get(field) != value:
        row[field] = value
        _DIRTY[row["id"]] = True
        return True
    return False


def flush(row):
    if _DIRTY.pop(row["id"], False):
        db.touch(row, now_iso())
        return True
    return False


def discard(row):
    _DIRTY.pop(row["id"], None)


# ---------------------------------------------------------------------------
# Corridor
# ---------------------------------------------------------------------------


def corridor_terminals(corridor):
    out = []
    for key in ("origin_terminal_id", "destination_terminal_id"):
        t = db.get("terminals", corridor.get(key))
        if t is not None:
            out.append(t)
    return out


def corridor_checks(corridor_id):
    return db.by("launch_readiness_checks", "corridor_id", corridor_id)


def corridor_programs(corridor):
    """The maintenance programmes that hang off a corridor's fleet units.

    §3.1 step eight: "any fleet unit assigned to the corridor carries an
    inspection programme in OVERDUE status".  A unit is assigned to the corridor
    when it is staged at one of the corridor's hubs, or registered in one of the
    states the corridor's hubs sit in.
    """
    states = {t.get("state_code") for t in corridor_terminals(corridor)}
    tids = {t["id"] for t in corridor_terminals(corridor)}
    out = []
    for p in db.all_rows("maintenance_programs"):
        if p.get("state_code") in states:
            out.append(p)
            continue
        unit = db.get("fleet_units", p.get("fleet_unit_id"))
        if unit is not None and unit.get("home_terminal_id") in tids:
            out.append(p)
    return out


def corridor_has_overdue_program(corridor):
    return any(p.get("inspection_programs_status") == "OVERDUE"
               for p in corridor_programs(corridor))


def corridor_has_unfilled_void(corridor):
    return any(p.get("inspection_programs_status") == "UNFILLED"
               and p.get("program_status") == "VOIDED"
               for p in corridor_programs(corridor))


def compute_posture(corridor):
    """§2.4: posture is never set directly by a client.  A freshly registered
    corridor is FROZEN; opening the review moves it to RESTRICTED; passing the
    gate lands on OPEN when weather_risk_score is below 40 and RESTRICTED
    otherwise; a corridor that is suspended, failed or retired is FROZEN."""
    status = corridor.get("corridor_status")
    if status in ("RETIRED", "SUSPENDED", "PLANNED"):
        return "FROZEN"
    if status in ("READINESS_REVIEW", "LIMITED"):
        return "RESTRICTED"
    if status == "ACTIVE":
        return "OPEN" if D(corridor.get("weather_risk_score", 0)) < 40 else "RESTRICTED"
    return "FROZEN"


def recompute_corridor(corridor):
    """check_pass_count, check_count, has_blocking_incident, readiness_score,
    posture and the safety-case summary — §2.4, §2.6."""
    cid = corridor["id"]
    checks = corridor_checks(cid)
    # §2.4: `check_pass_count` counts the corridor's readiness-check rows that
    # have reached CALIBRATION_PASSED or later, while `check_count` counts the
    # rows in any non-terminal status; `is_test_payload` rows are excluded from
    # both.
    mark(corridor, "check_count",
         len([c for c in checks
              if c.get("check_status") != "EXPIRED_FAILED"
              and not c.get("is_test_payload")]))
    mark(corridor, "check_pass_count",
         len([c for c in checks
              if c.get("check_status") in ("CALIBRATION_PASSED", "VALIDATED")
              and not c.get("is_test_payload")]))
    mark(corridor, "has_blocking_incident", compute_blocking_incident(cid))
    mark(corridor, "readiness_score", calc.corridor_readiness_score(cid))
    mark(corridor, "posture", compute_posture(corridor))
    recompute_corridor_case_summary(corridor)
    return corridor


def compute_blocking_incident(corridor_id):
    """True when at least one incident report on the corridor sits in status
    INVESTIGATING or SUBMITTED and carries severity CRITICAL — §2.4."""
    for r in db.by("incident_reports", "corridor_id", corridor_id):
        if r.get("report_status") in ("INVESTIGATING", "SUBMITTED") \
                and r.get("severity") == "CRITICAL":
            return True
    return False


def recompute_corridor_case_summary(corridor):
    summary = corridor_case_summary(corridor)
    mark(corridor, "case_status_summary", summary)
    for sc in db.by("safety_cases", "corridor_id", corridor["id"]):
        mark(sc, "case_status_summary", case_summary_for(sc, corridor))
        flush(sc)
    return summary


def corridor_case_summary(corridor):
    filed = filed_case_for(corridor["id"])
    if filed is None:
        return "NOT_FILED"
    if corridor.get("corridor_status") == "SUSPENDED":
        return "STALE"
    return case_summary_for(filed, corridor)


def case_summary_for(case, corridor):
    """NOT_FILED when the corridor has no filed case, STALE when the filed case's
    filed_date is strictly more than the supervising state's
    engagement_window_days before the ledger clock — §3.7."""
    if case.get("case_status") == "SUPERSEDED":
        return "SUPERSEDED"
    if case.get("case_status") != "FILED":
        return "NOT_FILED"
    if corridor.get("corridor_status") == "SUSPENDED":
        return "STALE"
    window = supervising_window_days(corridor)
    filed = parse_iso(case.get("filed_date"))
    if filed is None or window is None:
        return "CURRENT"
    age = (core.now().date() - filed.date()).days
    if age > window:
        return "STALE"
    return "CURRENT"


def supervising_window_days(corridor):
    """The supervising state's engagement_window_days — §3.7."""
    states = {t.get("state_code") for t in corridor_terminals(corridor)}
    for a in db.all_rows("state_authorities"):
        if a.get("state_code") in states:
            return int(a.get("engagement_window_days") or 0)
    return None


def supervising_requires_safety_case(corridor):
    states = {t.get("state_code") for t in corridor_terminals(corridor)}
    for a in db.all_rows("state_authorities"):
        if a.get("state_code") in states:
            return bool(a.get("requires_safety_case_filed", True))
    return False


def filed_case_for(corridor_id):
    for sc in db.by("safety_cases", "corridor_id", corridor_id):
        if sc.get("case_status") == "FILED":
            return sc
    return None


def highest_safety_case_version(corridor_id):
    versions = [int(s.get("safety_case_version") or 0)
                for s in db.by("safety_cases", "corridor_id", corridor_id)]
    return max(versions) if versions else 0


def corridor_state_authorities(corridor):
    states = {t.get("state_code") for t in corridor_terminals(corridor)}
    return [a for a in db.all_rows("state_authorities") if a.get("state_code") in states]


def recompute_corridor_and_flush(corridor):
    recompute_corridor(corridor)
    flush(corridor)


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


def recompute_terminal(terminal):
    """§2.7: reserved_apron_units, total_handoff_minutes, approved_window_count
    and transfer_turnaround_minutes all ride on the same set of rows."""
    tid = terminal["id"]
    mark(terminal, "reserved_apron_units", calc.reserved_apron_units(tid))
    mark(terminal, "total_handoff_minutes", calc.total_handoff_minutes(tid))
    mark(terminal, "approved_window_count", calc.approved_window_count(tid))
    mark(terminal, "transfer_turnaround_minutes",
         calc.transfer_turnaround_minutes(tid))
    mark(terminal, "staffing_status", compute_staffing_status(terminal))
    return terminal


def compute_staffing_status(terminal):
    """§3.8: reconciled at finalization time against the number of transition
    enrolments staffing the hub relative to the managed fleet unit count staged
    there."""
    enrolled = [t for t in db.by("driver_transitions", "terminal_id", terminal["id"])
                if t.get("transition_status") not in ("CANCELLED", "REJECTED")]
    units = len(db.by("fleet_units", "home_terminal_id", terminal["id"]))
    if units == 0:
        return "STAFFED" if enrolled else "UNDERSTAFFED"
    return "STAFFED" if len(enrolled) >= units else "UNDERSTAFFED"


def windows_for_run(run_plan_id, statuses=None):
    out = db.by("terminal_service_windows", "run_plan_id", run_plan_id)
    if statuses is not None:
        out = [w for w in out if w.get("window_status") in statuses]
    return out


def recompute_terminal_for_window(window):
    t = db.get("terminals", window.get("terminal_id"))
    if t is not None:
        recompute_terminal(t)
        flush(t)


# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------


def recompute_carrier(carrier):
    """§3.6 safety bands, incident bands and the backup mirror."""
    mark(carrier, "safety_tier", calc.safety_tier_for_score(carrier.get("safety_score", 0)))
    mark(carrier, "committed_discount_cents",
         calc.discount_for_tier(carrier.get("safety_tier")))
    mark(carrier, "incident_band",
         calc.incident_band_for(carrier.get("recordable_incidents_last_epoch")))
    backup = db.get("carriers", carrier.get("backup_carrier_id"))
    mark(carrier, "backup_carrier_score", int(backup.get("safety_score", 0)) if backup else 0)
    if carrier.get("carrier_status") == "ACTIVE" and carrier.get("incident_band") == "SUSPENDED":
        suspend_carrier(carrier)
    return carrier


def recompute_carrier_recordable(carrier):
    """recordable_incidents_last_epoch is the sum of recordable_incidents across
    incident reports on this carrier for the current ledger epoch — §3.5, §3.6."""
    key = core.epoch_key()
    total = 0
    for r in db.all_rows("incident_reports"):
        if r.get("_carrier_id") != carrier["id"]:
            continue
        if r.get("_epoch_key") != key:
            continue
        total += int(r.get("recordable_incidents") or 0)
    mark(carrier, "recordable_incidents_last_epoch", max(total, 0))
    mark(carrier, "incident_band",
         calc.incident_band_for(carrier.get("recordable_incidents_last_epoch")))
    return carrier


def carrier_of_run(run_plan):
    return db.get("carriers", run_plan.get("carrier_id"))


def recompute_carrier_rate_settlement(carrier):
    """rate_settlement_cents recomputes at every ledger rollover — §2.5, §3.11."""
    runs = db.by("run_plans", "carrier_id", carrier["id"])
    quote = Decimal(0)
    if runs:
        quote = max(calc.provisional_quote(r.get("posted_per_mile_cents", 0),
                                           carrier.get("committed_discount_cents", 0))
                    for r in runs)
    mark(carrier, "rate_settlement_cents", calc.settled_net(quote))
    return carrier


def recompute_carrier_safety_from_runs(carrier):
    """§3.4: completion recomputes the owning carrier's safety_score from its run
    plans.  §3.6 activation/reinstatement recompute it from the frozen incident
    count."""
    runs = db.by("run_plans", "carrier_id", carrier["id"])
    if runs:
        score = int(sum(int(r.get("safety_score") or 0) for r in runs) / len(runs) * 18)
    else:
        score = calc.carrier_safety_score(carrier.get("previous_epoch_incidents", 0))
    mark(carrier, "safety_score", max(0, min(1000, score)))
    mark(carrier, "safety_tier", calc.safety_tier_for_score(carrier.get("safety_score")))
    mark(carrier, "committed_discount_cents",
         calc.discount_for_tier(carrier.get("safety_tier")))
    return carrier


def carrier_has_live_runs(carrier_id):
    return any(r.get("run_status") in ("READINESS_PENDING", "DISPATCH_READY", "IN_TRANSIT")
               for r in db.by("run_plans", "carrier_id", carrier_id))


# ---------------------------------------------------------------------------
# Commitment
# ---------------------------------------------------------------------------


def recompute_commitment(commitment):
    """§3.2: consumed_slots counts the run plans claiming the loadboard slot whose
    run_status is READINESS_PENDING, DISPATCH_READY, IN_TRANSIT or COMPLETED;
    remaining_slots reads as committed_slots minus consumed_slots."""
    mark(commitment, "consumed_slots", calc.commitment_consumed_slots(commitment["id"]))
    mark(commitment, "remaining_slots",
         max(int(commitment.get("committed_slots") or 0) - int(commitment.get("consumed_slots") or 0), 0))
    mark(commitment, "verified_ride_along_count",
         calc.verified_ride_along_count(commitment["id"]))
    mark(commitment, "ride_along_credit_cents",
         calc.ride_along_credit(commitment.get("verified_ride_along_count", 0)))
    return commitment


# ---------------------------------------------------------------------------
# State authority
# ---------------------------------------------------------------------------


def recompute_authority(authority):
    mark(authority, "hours_used", calc.authority_hours_used(authority["id"]))
    mark(authority, "remaining_autonomous_hours", calc.remaining_autonomous_hours(authority))
    return authority


# ---------------------------------------------------------------------------
# Maintenance program / fleet unit
# ---------------------------------------------------------------------------


def recompute_program(program):
    """standard_inspection_due_date = the date exactly inspection_interval_days
    after the scheduled inspection anchor, at midnight; inspection_programs_status
    is OVERDUE when the anchor plus the interval falls strictly before the ledger
    clock — §3.7."""
    from datetime import timedelta
    interval = resolved_interval(program.get("inspection_interval_days"))
    anchor = parse_iso(program.get("_anchor_at"))
    if anchor is not None and interval is not None:
        due = anchor + timedelta(days=interval)
        mark(program, "standard_inspection_due_date", core.midnight_iso(to_iso(due)))
        if program.get("program_status") in ("CLOSED", "VOIDED"):
            mark(program, "inspection_programs_status", "UNFILLED")
        elif program.get("program_status") == "INSPECTED":
            mark(program, "inspection_programs_status", "COMPLIANT")
        elif due < core.now():
            mark(program, "inspection_programs_status", "OVERDUE")
        else:
            mark(program, "inspection_programs_status", "PENDING")
    return program


def resolved_interval(value):
    """0 selects the default programme length of 3 days — §3.7."""
    if value is None:
        return None
    v = int(value)
    if v == 0:
        return 3
    return v


def recompute_fleet_unit(unit):
    """§3.11 pinned evaluation order: maint_charges first, then
    maint_projection_cents; remain_hours = weather_clearance_hours -
    hours_posted_total, floored at 0."""
    charges = calc.fleet_maint_charges(unit.get("hours_posted_total", 0))
    mark(unit, "maint_charges", int(charges))
    mark(unit, "maint_projection_cents",
         calc.fleet_maint_projection(charges, unit.get("_weather_profile")))
    mark(unit, "remain_hours",
         calc.fleet_remain_hours(unit.get("weather_clearance_hours"),
                                 unit.get("hours_posted_total", 0)))
    mark(unit, "route_driven_hours_cents",
         calc.route_driven_hours_cents(unit.get("is_watch_squad")))
    return unit


# ---------------------------------------------------------------------------
# Shipping instruction
# ---------------------------------------------------------------------------


def recompute_instruction(instruction):
    iid = instruction["id"]
    mark(instruction, "booked_vgm_kg_sum", calc.booked_vgm_kg_sum(iid))
    mark(instruction, "booked_line_total_cents", calc.booked_line_total_cents(iid))
    mark(instruction, "vgm_override_fee_cents",
         calc.vgm_override_fee(instruction.get("booked_vgm_kg_sum", 0)))
    mark(instruction, "container_discount_cents", calc.container_discount_cents(iid))
    return instruction


# ---------------------------------------------------------------------------
# Run plan derived rates
# ---------------------------------------------------------------------------


def recompute_run_plan_rates(run_plan):
    """per_mile_rate_cents, committed_rate_cents and scenario_rate_cents — §3.2,
    §3.11.  recomputed whenever the run plan is repriced."""
    carrier = carrier_of_run(run_plan)
    commitment = db.get("shipper_commitments", run_plan.get("shipper_commitment_id"))
    corridor = db.get("corridors", run_plan.get("corridor_id"))
    discount = calc.discount_for_tier(carrier.get("safety_tier")) if carrier else Decimal(0)
    per_mile = calc.per_mile_rate(run_plan.get("posted_per_mile_cents", 0),
                                  run_plan.get("trailer_count", 0))
    mark(run_plan, "per_mile_rate_cents", per_mile)
    floor_rate = D(commitment.get("shipper_floor_per_mile_cents", 0)) if commitment else Decimal(0)
    mark(run_plan, "committed_rate_cents",
         calc.committed_rate(per_mile, floor_rate, discount))
    risk = D(corridor.get("weather_risk_score", 0)) if corridor else Decimal(0)
    mark(run_plan, "scenario_rate_cents",
         calc.scenario_rate(per_mile, floor_rate, risk))
    mark(run_plan, "run_window_rate_cents", run_window_rate_for(run_plan))
    return run_plan


def run_window_rate_for(run_plan):
    """run_window_rate_cents is the larger of the minimum chassis rate and
    per_mile_rate_cents multiplied by the coverage days of the run plan's
    chassis record — §3.11."""
    chassis = db.by("run_plan_chassis", "run_plan_id", run_plan["id"])
    if not chassis:
        return D(run_plan.get("run_window_rate_cents", 0))
    return calc.chassis_holding_rate(run_plan.get("per_mile_rate_cents", 0),
                                     chassis[0].get("coverage_days", 0))


def recompute_run_plan_safety(run_plan):
    band = band_for_safety_score(run_plan.get("safety_score", 50))
    mark(run_plan, "safety_band", band)
    return run_plan


def band_for_safety_score(score):
    """LOW < 40, MEDIUM 40–79, HIGH 80–99, CRITICAL >= 100."""
    s = int(score or 0)
    if s >= 100:
        return "CRITICAL"
    if s >= 80:
        return "HIGH"
    if s >= 40:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def cancel_run_windows(run_plan_id, statuses=("REQUESTED", "APPROVED")):
    """§3.3: 'Aborting cancels every apron window on the run that was REQUESTED or
    APPROVED'."""
    terminals = set()
    for w in windows_for_run(run_plan_id, statuses):
        mark(w, "window_status", "CANCELLED")
        flush(w)
        terminals.add(w.get("terminal_id"))
    for tid in terminals:
        t = db.get("terminals", tid)
        if t is not None:
            recompute_terminal(t)
            flush(t)


def abort_run_plan(run_plan, release_slot=True):
    """Move a run plan to ABORTED and release its apron windows and its slot."""
    if run_plan.get("run_status") in ("COMPLETED", "ABORTED"):
        return run_plan
    mark(run_plan, "run_status", "ABORTED")
    cancel_run_windows(run_plan["id"])
    if release_slot:
        c = db.get("shipper_commitments", run_plan.get("shipper_commitment_id"))
        if c is not None:
            recompute_commitment(c)
            flush(c)
    corridor = db.get("corridors", run_plan.get("corridor_id"))
    if corridor is not None:
        recompute_corridor(corridor)
        flush(corridor)
    carrier = carrier_of_run(run_plan)
    if carrier is not None:
        # §3.3: aborting touches the carrier — its recordable_incidents_last_epoch
        # recomputes, and its safety_tier and committed_discount_cents recompute
        # from the carrier's current safety_score.
        recompute_carrier_recordable(carrier)
        recompute_carrier(carrier)
        flush(carrier)
    flush(run_plan)
    return run_plan


def limit_corridor(corridor):
    """§3.1: an ACTIVE corridor moves to LIMITED, posture recomputes to
    RESTRICTED, every RunPlan in READINESS_PENDING or DISPATCH_READY on this
    corridor moves to ABORTED and every REQUESTED window on those runs moves to
    DISPLACED."""
    if corridor.get("corridor_status") != "ACTIVE":
        return corridor
    mark(corridor, "corridor_status", "LIMITED")
    for run in db.by("run_plans", "corridor_id", corridor["id"]):
        if run.get("run_status") in ("READINESS_PENDING", "DISPATCH_READY"):
            _abort_for_corridor(run)
    recompute_corridor(corridor)
    flush(corridor)
    return corridor


def _abort_for_corridor(run):
    mark(run, "run_status", "ABORTED")
    terminals = set()
    for w in windows_for_run(run["id"], ("REQUESTED", "APPROVED")):
        mark(w, "window_status", "CANCELLED")
        flush(w)
        terminals.add(w.get("terminal_id"))
    for tid in terminals:
        t = db.get("terminals", tid)
        if t is not None:
            recompute_terminal(t)
            flush(t)
    c = db.get("shipper_commitments", run.get("shipper_commitment_id"))
    if c is not None:
        recompute_commitment(c)
        flush(c)
    flush(run)


def suspend_corridor(corridor):
    """§3.1: posture recomputes to FROZEN, every run plan on the corridor still in
    DRAFT, READINESS_PENDING or DISPATCH_READY is aborted, referenced state
    authorities get filing_required_next = true and the safety case reads STALE."""
    mark(corridor, "corridor_status", "SUSPENDED")
    for run in db.by("run_plans", "corridor_id", corridor["id"]):
        if run.get("run_status") in ("DRAFT", "READINESS_PENDING", "DISPATCH_READY"):
            _abort_for_corridor(run)
    for a in corridor_state_authorities(corridor):
        mark(a, "filing_required_next", True)
        flush(a)
    for sc in db.by("safety_cases", "corridor_id", corridor["id"]):
        if sc.get("case_status") == "FILED":
            mark(sc, "case_status_summary", "STALE")
            flush(sc)
    recompute_corridor(corridor)
    flush(corridor)
    return corridor


def maybe_recover_limited(corridor):
    """§3.1 LIMITED → ACTIVE: no MaintenanceProgram in OVERDUE status,
    weather_risk_score below 80 and has_blocking_incident false."""
    if corridor.get("corridor_status") != "LIMITED":
        return corridor
    if compute_blocking_incident(corridor["id"]):
        return corridor
    if corridor_has_overdue_program(corridor):
        return corridor
    if D(corridor.get("weather_risk_score", 0)) >= 80:
        return corridor
    mark(corridor, "corridor_status", "ACTIVE")
    recompute_corridor(corridor)
    flush(corridor)
    return corridor


def maybe_limit_active(corridor):
    """§3.1 ACTIVE → LIMITED preconditions."""
    if corridor.get("corridor_status") != "ACTIVE":
        return corridor
    if (D(corridor.get("weather_risk_score", 0)) >= 80
            or corridor_has_overdue_program(corridor)
            or corridor_has_unfilled_void(corridor)):
        return limit_corridor(corridor)
    return corridor


def suspend_carrier(carrier):
    """§3.6: a suspension sets committed_discount_cents to 40, aborts every run
    plan on the carrier sitting in DRAFT or READINESS_PENDING, and expires every
    monitoring assignment on those runs that was still SCHEDULED."""
    mark(carrier, "carrier_status", "SUSPENDED")
    mark(carrier, "committed_discount_cents", calc.discount_for_tier("LOW"))
    for run in db.by("run_plans", "carrier_id", carrier["id"]):
        if run.get("run_status") in ("DRAFT", "READINESS_PENDING"):
            for a in db.by("remote_support_assignments", "run_plan_id", run["id"]):
                if a.get("assignment_status") == "SCHEDULED":
                    mark(a, "assignment_status", "EXPIRED")
                    mark(a, "closure_source", "SAFE_STOP_EXPIRED")
                    flush(a)
            abort_run_plan(run)
    flush(carrier)
    return carrier


def expire_monitoring(assignment, source):
    mark(assignment, "assignment_status", "EXPIRED")
    mark(assignment, "closure_source", source)
    flush(assignment)
    return assignment