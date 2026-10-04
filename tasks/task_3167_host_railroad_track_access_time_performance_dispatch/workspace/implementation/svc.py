"""Business logic, calculations, state transition side-effects."""
from datetime import datetime, timedelta
from decimal import Decimal

import core
from core import (
    ApiError,
    D,
    db,
    new_row,
    now,
    rhu,
    rhu_int,
    sort_created,
    touch,
    UTC,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SERVICE_TYPES = ("LONG_DISTANCE", "STATE_SUPPORTED")
TRACK_CLASSES = ("SINGLE", "DOUBLE")
CORRIDOR_STATUSES = ("ACTIVE", "SUSPENDED")
SEGMENT_STATUSES = ("OPERABLE", "CAPITAL_HOLD")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
TIMETABLE_STATUSES = (
    "DRAFT",
    "PROPOSED",
    "UNDER_REVIEW",
    "RATIFIED",
    "PUBLISHED",
    "SUSPENDED",
    "SUPERSEDED",
)
RUN_STATUSES = ("SCHEDULED", "EN_ROUTE", "COMPLETED", "CANCELLED", "DISRUPTED")
PASSAGE_STATUSES = ("PLANNED", "ACTUALIZED", "SKIPPED")
CAUSE_CODES = (
    "HOST_FREIGHT_HOLD",
    "HOST_SIGNAL",
    "HOST_TRACK",
    "MECHANICAL",
    "STATION_DWELL",
    "WEATHER",
    "DISRUPTION",
)
HOST_CAUSES = frozenset({"HOST_FREIGHT_HOLD", "HOST_SIGNAL", "HOST_TRACK"})
INCIDENT_STATUSES = ("OPEN", "CONFIRMED", "DISPUTED", "REVERSED")
DISPUTE_STATUSES = ("UNDER_REVIEW", "ESCALATED", "RESOLVED")
RESOLUTIONS = ("UPHELD", "OVERTURNED")
PROJECT_TYPES = ("SIDING", "SIGNAL", "DOUBLE_TRACK")
PROJECT_STATUSES = ("PROPOSED", "FUNDED", "IN_PROGRESS", "SUSPENDED", "COMPLETED")
WINDOW_STATUSES = ("PLANNED", "LOCKED", "RELEASED")
DISRUPTION_TYPES = ("WEATHER", "TRACK_FAILURE", "GRADE_CROSSING", "SECURITY")
REACCOMMODATION_POLICIES = ("BUS_BRIDGE", "REFUND", "REBOOK_NEXT")
DISRUPTION_STATUSES = ("OPEN", "BRIDGED", "RECOVERED")
FUNDING_STATUSES = ("DRAFT", "COMMITTED", "SETTLED")
STATEMENT_STATUSES = ("DRAFT", "ISSUED", "DISPUTED", "REISSUED", "PAID")

WEEKLY_EQUIPMENT_ALLOWANCE_HOURS = D("40.00")


# ---------------------------------------------------------------------------
# Existence helpers (tier 4: ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def need(coll, rid, label="Resource"):
    core.raise_deferred_auth()
    row = getattr(db, coll).get(rid)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "%s %s not found." % (label, rid))
    return row


def need_host(rid):
    return need("host_railroads", rid, "HostRailroad")


def need_corridor(rid):
    return need("corridors", rid, "Corridor")


def need_segment(rid):
    return need("track_segments", rid, "TrackSegment")


def need_agreement(rid):
    return need("operating_agreements", rid, "OperatingAgreement")


def need_timetable(rid):
    return need("timetables", rid, "Timetable")


def need_run(rid):
    return need("train_runs", rid, "TrainRun")


def need_passage(rid):
    return need("segment_passages", rid, "SegmentPassage")


def need_incident(rid):
    return need("delay_incidents", rid, "DelayIncident")


def need_dispute(rid):
    return need("disputes", rid, "DispatchPriorityDispute")


def need_project(rid):
    return need("capital_projects", rid, "CapitalProject")


def need_window(rid):
    return need("maintenance_windows", rid, "MaintenanceWindow")


def need_disruption(rid):
    return need("service_disruptions", rid, "ServiceDisruption")


def need_funding(rid):
    return need("funding_agreements", rid, "FundingAgreement")


def need_statement(rid):
    return need("settlement_statements", rid, "SettlementStatement")


# ---------------------------------------------------------------------------
# Owning-host chain (for HostRailroadRep ownership checks)
# ---------------------------------------------------------------------------
def host_for_corridor(corridor):
    return corridor["host_railroad_id"]


def host_for_agreement(agreement):
    return agreement["host_railroad_id"]


def host_for_timetable(timetable):
    corridor = db.corridors.get(timetable["corridor_id"])
    return corridor["host_railroad_id"] if corridor else None


def host_for_run(run):
    timetable = db.timetables.get(run["timetable_id"])
    return host_for_timetable(timetable) if timetable else None


def host_for_passage(passage):
    run = db.train_runs.get(passage["train_run_id"])
    return host_for_run(run) if run else None


def host_for_incident(incident):
    run = db.train_runs.get(incident["train_run_id"])
    return host_for_run(run) if run else None


def host_for_dispute(dispute):
    return host_for_incident(db.delay_incidents.get(dispute["delay_incident_id"]))


def host_for_project(project):
    agreement = db.operating_agreements.get(project["operating_agreement_id"])
    return agreement["host_railroad_id"] if agreement else None


def host_for_window(window):
    seg = db.track_segments.get(window["track_segment_id"])
    if seg is None:
        return None
    corridor = db.corridors.get(seg["corridor_id"])
    return corridor["host_railroad_id"] if corridor else None


def host_for_disruption(disruption):
    corridor = db.corridors.get(disruption["corridor_id"])
    return corridor["host_railroad_id"] if corridor else None


def host_for_statement(statement):
    agreement = db.operating_agreements.get(statement["operating_agreement_id"])
    return agreement["host_railroad_id"] if agreement else None


def host_for_segment(segment):
    corridor = db.corridors.get(segment["corridor_id"])
    return corridor["host_railroad_id"] if corridor else None


# ---------------------------------------------------------------------------
# Schedule feasibility & materialization (calc: schedule_feasibility)
# ---------------------------------------------------------------------------
def corridor_segments(corridor_id):
    """Track segments of a corridor in ascending sequence_no order."""
    segs = [s for s in db.track_segments.values() if s["corridor_id"] == corridor_id]
    segs.sort(key=lambda s: (s["sequence_no"], s["_seq"]))
    return segs


def schedule_walk(timetable, segments, agreement):
    """Yield (run_k, service_date, [(segment, planned_entry, planned_exit), ...]).

    For run k (0-based) on service_date D:
      scheduled_departure = D at departure_time_of_day + k * headway_minutes.
    Walk segments in ascending sequence_no:
      planned_entry(1) = scheduled_departure
      planned_exit(i)  = planned_entry(i) + ceil(pure_run_minutes(i) * (1 + pad)) minutes
      planned_entry(i+1) = planned_exit(i) + dwell_after_minutes(i)
    """
    pad = D(agreement["running_time_allowance_pct"])
    h, mi = timetable["departure_time_of_day"]
    service_dates = []
    d = timetable["service_date_start"]
    while d <= timetable["service_date_end"]:
        service_dates.append(d)
        d = d + timedelta(days=1)
    for service_date in service_dates:
        for k in range(timetable["trains_per_day"]):
            scheduled_departure = datetime(
                service_date.year,
                service_date.month,
                service_date.day,
                h,
                mi,
                tzinfo=UTC,
            ) + timedelta(minutes=k * timetable["headway_minutes"])
            walk = []
            cursor = scheduled_departure
            for seg in segments:
                entry = cursor
                padded = D(seg["pure_run_minutes"]) * (D(1) + pad)
                # ceil to whole minutes
                padded_minutes = int(padded.to_integral_value(rounding="ROUND_CEILING"))
                exit_ = entry + timedelta(minutes=padded_minutes)
                walk.append((seg, entry, exit_))
                cursor = exit_ + timedelta(minutes=seg.get("dwell_after_minutes") or 0)
            yield k, service_date, scheduled_departure, walk


def _half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap: conflict iff a.start < b.end AND b.start < a.end."""
    return a_start < b_end and b_start < a_end


def _locked_window_expanded(window):
    buffer = timedelta(minutes=window.get("clearance_buffer_minutes") or 0)
    return window["window_start_at"] - buffer, window["window_end_at"] + buffer


def _passage_conflicts_window(entry, exit_, window):
    """A passage conflicts with a LOCKED window w (buffer b) iff
    p.entry < w.end + b AND p.exit > w.start - b. Exact equality at either
    boundary is NOT a conflict (strict inequalities already encode that)."""
    w_start, w_end = _locked_window_expanded(window)
    return entry < w_end and exit_ > w_start


def check_schedule_feasibility(timetable, segments, agreement):
    """Run all feasibility rules for a proposed timetable; raise on first failure.

    Rules (per PRD §3.3 and scaffold `schedule_feasibility`):
      - capacity: per segment per service_date, runs crossing <= capacity_trains_per_day
      - overlap on SINGLE segments: no two planned passages on the same segment overlap
      - maintenance: no planned passage conflicts with a LOCKED window on same segment
    Per scaffold's validations table priority order:
      maintenance conflict (ERR_MAINTENANCE_CONFLICT, priority 9) precedes
      schedule infeasible (ERR_SCHEDULE_INFEASIBLE, priority 11), which precedes
      capacity (ERR_CAPACITY_EXCEEDED, priority 12).
    """
    # Build every planned passage for every run/date
    planned = []  # list of (segment_id, segment, entry, exit)
    per_segment_per_day = {}
    for _k, service_date, _dep, walk in schedule_walk(timetable, segments, agreement):
        for seg, entry, exit_ in walk:
            planned.append((seg, entry, exit_))
            key = (seg["id"], service_date)
            per_segment_per_day[key] = per_segment_per_day.get(key, 0) + 1

    # Maintenance conflicts against LOCKED windows on the same segment
    locked_windows = [w for w in db.maintenance_windows.values() if w["status"] == "LOCKED"]
    for seg, entry, exit_ in planned:
        for w in locked_windows:
            if w["track_segment_id"] != seg["id"]:
                continue
            if _passage_conflicts_window(entry, exit_, w):
                raise ApiError(
                    "ERR_MAINTENANCE_CONFLICT",
                    "Planned passage conflicts with a LOCKED maintenance window.",
                )

    # SINGLE-track self-overlap within the proposed timetable
    by_segment = {}
    for seg, entry, exit_ in planned:
        if seg["track_class"] != "SINGLE":
            continue
        by_segment.setdefault(seg["id"], []).append((entry, exit_))
    for seg_id, intervals in by_segment.items():
        intervals.sort()
        for i in range(len(intervals)):
            for j in range(i + 1, len(intervals)):
                a, b = intervals[i], intervals[j]
                if _half_open_overlap(a[0], a[1], b[0], b[1]):
                    raise ApiError(
                        "ERR_SCHEDULE_INFEASIBLE",
                        "Proposed timetable has planned SINGLE-track passage overlaps.",
                    )

    # Capacity
    for (seg_id, _date), count in per_segment_per_day.items():
        seg = db.track_segments[seg_id]
        if count > seg["capacity_trains_per_day"]:
            raise ApiError(
                "ERR_CAPACITY_EXCEEDED",
                "Per-day run count exceeds segment capacity.",
            )


def check_publish_guards(timetable, segments, agreement):
    """At publish, re-check maintenance clearance and overlap with other
    PUBLISHED timetables on the same SINGLE segments.

    Priority order per scaffold: maintenance conflict (9) precedes segment
    occupancy conflict (10).
    """
    planned = []
    for _k, _date, _dep, walk in schedule_walk(timetable, segments, agreement):
        for seg, entry, exit_ in walk:
            planned.append((seg, entry, exit_))

    # Maintenance conflicts
    locked_windows = [w for w in db.maintenance_windows.values() if w["status"] == "LOCKED"]
    for seg, entry, exit_ in planned:
        for w in locked_windows:
            if w["track_segment_id"] != seg["id"]:
                continue
            if _passage_conflicts_window(entry, exit_, w):
                raise ApiError(
                    "ERR_MAINTENANCE_CONFLICT",
                    "Planned passage conflicts with a LOCKED maintenance window.",
                )

    # Overlap against other PUBLISHED timetables' PLANNED/ACTUALIZED passages on
    # the same SINGLE segments.
    other_published_tt_ids = {
        t["id"]
        for t in db.timetables.values()
        if t["id"] != timetable["id"]
        and t["status"] == "PUBLISHED"
        and t["corridor_id"] == timetable["corridor_id"]
    }
    if other_published_tt_ids:
        other_runs = [
            r
            for r in db.train_runs.values()
            if r["timetable_id"] in other_published_tt_ids
        ]
        other_run_ids = {r["id"] for r in other_runs}
        # We only need to look at passages on segments that are SINGLE here.
        single_seg_ids = {s["id"] for s in segments if s["track_class"] == "SINGLE"}
        if single_seg_ids:
            existing = [
                p
                for p in db.segment_passages.values()
                if p["train_run_id"] in other_run_ids
                and p["track_segment_id"] in single_seg_ids
                and p["status"] in ("PLANNED", "ACTUALIZED")
            ]
            for seg, entry, exit_ in planned:
                if seg["track_class"] != "SINGLE":
                    continue
                for p in existing:
                    if p["track_segment_id"] != seg["id"]:
                        continue
                    # Use actual interval when actualized, planned otherwise.
                    p_start = p.get("actual_entry_at") or p["planned_entry_at"]
                    p_end = p.get("actual_exit_at") or p["planned_exit_at"]
                    if _half_open_overlap(entry, exit_, p_start, p_end):
                        raise ApiError(
                            "ERR_SEGMENT_OCCUPANCY_CONFLICT",
                            "Planned passage overlaps another published timetable's passage on a SINGLE segment.",
                        )


def materialize_runs(timetable, segments, agreement):
    """Create TrainRuns + SegmentPassages for the timetable."""
    runs_created = []
    for k, service_date, scheduled_departure, walk in schedule_walk(
        timetable, segments, agreement
    ):
        db.train_number_seq += 1
        train_number = str(db.train_number_seq)
        scheduled_arrival = walk[-1][2] if walk else scheduled_departure
        run = new_row(
            "train_run",
            timetable_id=timetable["id"],
            train_number=train_number,
            service_date=service_date.isoformat(),
            scheduled_departure_at=scheduled_departure,
            scheduled_arrival_at=scheduled_arrival,
            actual_departure_at=None,
            actual_arrival_at=None,
            origin_departure_delay_minutes=None,
            destination_arrival_delay_minutes=None,
            on_time_endpoint=None,
            on_time_all_stations=None,
            attributed_host_delay_minutes=0,
            cancellation_reason=None,
            status="SCHEDULED",
        )
        db.train_runs[run["id"]] = run
        for seg, entry, exit_ in walk:
            passage = new_row(
                "segment_passage",
                train_run_id=run["id"],
                track_segment_id=seg["id"],
                segment_sequence_no=seg["sequence_no"],
                planned_entry_at=entry,
                planned_exit_at=exit_,
                actual_entry_at=None,
                actual_exit_at=None,
                status="PLANNED",
            )
            db.segment_passages[passage["id"]] = passage
        runs_created.append(run)
    return runs_created


# ---------------------------------------------------------------------------
# Run / passage / incident helpers
# ---------------------------------------------------------------------------
def _delay_minutes(later, earlier):
    """max(0, floor((later - earlier) in whole minutes))."""
    delta_seconds = (later - earlier).total_seconds()
    if delta_seconds <= 0:
        return 0
    return int(delta_seconds // 60)


def recompute_run_attributed_minutes(run):
    total = 0
    for inc in db.delay_incidents.values():
        if (
            inc["train_run_id"] == run["id"]
            and inc["status"] == "CONFIRMED"
            and inc.get("host_attributable")
        ):
            total += inc["delay_minutes"]
    if run.get("attributed_host_delay_minutes") != total:
        run["attributed_host_delay_minutes"] = total
        touch(run)


def agreement_for_run(run):
    timetable = db.timetables.get(run["timetable_id"])
    if timetable is None:
        return None
    return db.operating_agreements.get(timetable["operating_agreement_id"])


def check_disrupted_run_incident(run, disruption_started_at=None):
    """When all PLANNED passages of a DISRUPTED run have flipped to SKIPPED,
    auto-create a DelayIncident (SYSTEM_DISRUPTION origin)."""
    if run["status"] != "DISRUPTED":
        return
    passages = [
        p for p in db.segment_passages.values() if p["train_run_id"] == run["id"]
    ]
    if not passages:
        return
    # Fire only when no PLANNED passages remain.
    if any(p["status"] == "PLANNED" for p in passages):
        return
    # Only create the auto-incident once per run.
    for inc in db.delay_incidents.values():
        if inc["train_run_id"] == run["id"] and inc.get("origin") == "SYSTEM_DISRUPTION":
            return
    started_at = disruption_started_at
    if started_at is None:
        # Find the most recent open/bridged disruption for this run's corridor.
        timetable = db.timetables.get(run["timetable_id"])
        if timetable:
            for d in db.service_disruptions.values():
                if d["corridor_id"] == timetable["corridor_id"] and d["status"] in (
                    "OPEN",
                    "BRIDGED",
                ):
                    started_at = d["started_at"]
                    break
    if started_at is None:
        started_at = now()
    delay = _delay_minutes(run["scheduled_arrival_at"], started_at)
    inc = new_row(
        "delay_incident",
        train_run_id=run["id"],
        segment_passage_id=None,
        cause_code="DISRUPTION",
        delay_minutes=delay,
        host_attributable=False,
        origin="SYSTEM_DISRUPTION",
        status="OPEN",
    )
    db.delay_incidents[inc["id"]] = inc


# ---------------------------------------------------------------------------
# Maintenance windows: equipment budget & cascades
# ---------------------------------------------------------------------------
def iso_week_key(dt):
    """(iso_year, iso_week) using Monday 00:00Z boundary."""
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def window_hours(start, end):
    """window_hours = round_half_up((end - start) / 3600 seconds, 2 decimals)."""
    seconds = D(str((end - start).total_seconds()))
    hours = seconds / D(3600)
    return rhu(hours, 2)


def consumed_hours(unit_id, week_key):
    total = D(0)
    for w in db.maintenance_windows.values():
        if w["status"] != "LOCKED":
            continue
        if w["equipment_unit_id"] != unit_id:
            continue
        if iso_week_key(w["window_start_at"]) != week_key:
            continue
        total += D(w["window_hours"])
    return total


def equipment_available(unit_id, week_of_dt):
    return WEEKLY_EQUIPMENT_ALLOWANCE_HOURS - consumed_hours(unit_id, iso_week_key(week_of_dt))


def refresh_window_availability(unit_id, week_key):
    """Recompute equipment_week_hours_available on every window of this unit/week."""
    for w in db.maintenance_windows.values():
        if w["equipment_unit_id"] != unit_id:
            continue
        if iso_week_key(w["window_start_at"]) != week_key:
            continue
        avail = WEEKLY_EQUIPMENT_ALLOWANCE_HOURS - consumed_hours(unit_id, week_key)
        if w.get("equipment_week_hours_available") != avail:
            w["equipment_week_hours_available"] = avail
            touch(w)


def cascade_skip_passages_for_window(window):
    """PLANNED SegmentPassages on this segment whose clearance-expanded planned
    interval intersects the window flip to SKIPPED."""
    for p in list(db.segment_passages.values()):
        if p["track_segment_id"] != window["track_segment_id"]:
            continue
        if p["status"] != "PLANNED":
            continue
        if _passage_conflicts_window(p["planned_entry_at"], p["planned_exit_at"], window):
            p["status"] = "SKIPPED"
            touch(p)
            run = db.train_runs.get(p["train_run_id"])
            if run is not None:
                check_disrupted_run_incident(run)


# ---------------------------------------------------------------------------
# Service disruption cascade
# ---------------------------------------------------------------------------
def disruption_bridge_cascade(disruption):
    """Move affected SCHEDULED/EN_ROUTE runs to DISRUPTED, skip their PLANNED
    passages, and auto-create incidents when passage sets complete."""
    corridor_id = disruption["corridor_id"]
    started_at = disruption["started_at"]
    affected_timetables = {
        t["id"]
        for t in db.timetables.values()
        if t["corridor_id"] == corridor_id
    }
    for run in list(db.train_runs.values()):
        if run["timetable_id"] not in affected_timetables:
            continue
        if run["status"] not in ("SCHEDULED", "EN_ROUTE"):
            continue
        # scheduled_departure_at >= started_at
        if run["scheduled_departure_at"] < started_at:
            continue
        run["status"] = "DISRUPTED"
        run["cancellation_reason"] = "DISRUPTION"
        touch(run)
        # Skip remaining PLANNED passages
        for p in list(db.segment_passages.values()):
            if p["train_run_id"] == run["id"] and p["status"] == "PLANNED":
                p["status"] = "SKIPPED"
                touch(p)
        check_disrupted_run_incident(run, disruption_started_at=started_at)


# ---------------------------------------------------------------------------
# Funding cost allocation (calc: funding_cost_allocation)
# ---------------------------------------------------------------------------
def funding_allocated_cost(corridor, state_code, period_start, period_end):
    days = (period_end - period_start).days + 1  # inclusive
    period_cost = rhu_int(D(corridor["annual_cost_cents"]) * D(days) / D(365))
    segs = corridor_segments(corridor["id"])
    total_miles = D(0)
    state_miles = D(0)
    for s in segs:
        miles = D(s["milepost_end"]) - D(s["milepost_start"])
        total_miles += miles
        if s["state_code"] == state_code:
            state_miles += miles
    if total_miles == 0:
        return 0
    line = rhu_int(D(period_cost) * state_miles / total_miles)
    return line


# ---------------------------------------------------------------------------
# Settlement statement computation
# ---------------------------------------------------------------------------
def compute_statement_fields(statement, agreement, corridor, variant):
    """Compute completed_run_count, train_miles, otp_pct, host_delay_minutes,
    penalty_cents, incentive_cents, net_cents for the given variant."""
    period_start = statement["period_start"]
    period_end = statement["period_end"]
    period_start_iso = period_start.isoformat()
    period_end_iso = period_end.isoformat()
    runs = [
        r
        for r in db.train_runs.values()
        if r["status"] == "COMPLETED"
        and r["service_date"] >= period_start_iso
        and r["service_date"] <= period_end_iso
    ]
    # Only runs whose timetable is on this corridor
    corridor_tt_ids = {
        t["id"] for t in db.timetables.values() if t["corridor_id"] == corridor["id"]
    }
    runs = [r for r in runs if r["timetable_id"] in corridor_tt_ids]

    completed_run_count = len(runs)
    segs = corridor_segments(corridor["id"])
    total_miles = D(0)
    for s in segs:
        total_miles += D(s["milepost_end"]) - D(s["milepost_start"])
    train_miles = total_miles * D(completed_run_count)

    if completed_run_count == 0:
        otp_pct = None
    else:
        on_time_count = sum(1 for r in runs if r.get("on_time_endpoint"))
        otp_pct = rhu(
            D(100) * D(on_time_count) / D(completed_run_count), 4
        )

    # Host delay attribution per variant
    run_ids = {r["id"] for r in runs}
    host_sum = 0
    non_host_sum = 0
    for inc in db.delay_incidents.values():
        if inc["train_run_id"] not in run_ids:
            continue
        if inc["status"] != "CONFIRMED":
            continue
        if inc.get("host_attributable"):
            host_sum += inc["delay_minutes"]
        else:
            non_host_sum += inc["delay_minutes"]
    if variant == "GROSS":
        host_delay_minutes = host_sum
    else:  # NET
        host_delay_minutes = max(0, host_sum - non_host_sum)

    # Penalty / incentive
    if otp_pct is None:
        penalty_cents = 0
        incentive_cents = 0
    else:
        otp = D(otp_pct) / D(100)
        target = D(agreement["otp_target_pct"])
        if otp >= target:
            incentive_cents = rhu_int(
                D(agreement["incentive_rate_cents_per_train_mile"])
                * train_miles
                * (otp - target)
            )
            penalty_cents = 0
        else:
            if otp >= target - D("0.05"):
                tier = 1
            elif otp >= target - D("0.15"):
                tier = 2
            else:
                tier = 3
            penalty_cents = rhu_int(
                D(agreement["penalty_rate_cents_per_minute"])
                * D(host_delay_minutes)
                * D(tier)
            )
            incentive_cents = 0
    net_cents = incentive_cents - penalty_cents

    return {
        "completed_run_count": completed_run_count,
        "train_miles": train_miles,
        "otp_pct": otp_pct,
        "host_delay_minutes": host_delay_minutes,
        "penalty_cents": penalty_cents,
        "incentive_cents": incentive_cents,
        "net_cents": net_cents,
    }


def agreement_expiry_sweep():
    """When the logical clock advances past effective_to, ACTIVE -> EXPIRED."""
    for ag in db.operating_agreements.values():
        if ag["status"] == "ACTIVE" and db.clock >= ag["effective_to"]:
            ag["status"] = "EXPIRED"
            touch(ag)
