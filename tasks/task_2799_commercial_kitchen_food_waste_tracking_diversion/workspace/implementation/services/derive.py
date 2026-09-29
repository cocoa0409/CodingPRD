"""Derived-field recomputation and cascade helpers (PRD 2.6, 2.7, section 3).

Every aggregate is a full recomputation from the source rows - never an
incremental delta - so that compensating operations restore byte-exact values.
"""
from db import base_row, date_of, db, parse_ts, touch
from services import calc
from services.calc import D, num, rhu

COUNTED_STATUSES = ("RECORDED", "FLAGGED")
CAPTURE_PRESENT_STATUSES = ("RECORDED", "FLAGGED", "SUPERSEDED")


# ------------------------------------------------------------------- lookups
def entries_of_shift(shift_id):
    return [e for e in db.entries.values() if e["shift_id"] == shift_id]


def entries_of_site(site_id):
    return [e for e in db.entries.values() if e["site_id"] == site_id]


def lines_of_entry(entry_id):
    return [l for l in db.lines.values() if l["waste_entry_id"] == entry_id]


def lines_of_consignment(consignment_id):
    return [l for l in db.lines.values() if l["consignment_id"] == consignment_id]


def active_station_count(site_id):
    return len([s for s in db.stations.values()
                if s["site_id"] == site_id and s["status"] == "ACTIVE"])


def closed_shift_meals(site_id, start_date, end_date):
    total = 0
    for shift in db.shifts.values():
        if shift["site_id"] != site_id or shift["status"] != "CLOSED":
            continue
        if start_date <= shift["shift_date"] <= end_date:
            total += shift["meals_served"]
    return total


def counted_entries_in_window(site_id, start_date, end_date):
    rows = []
    for entry in entries_of_site(site_id):
        if entry["status"] not in COUNTED_STATUSES:
            continue
        if start_date <= date_of(entry["captured_at"]) <= end_date:
            rows.append(entry)
    return rows


# ------------------------------------------------------- shift_waste_intensity
def recompute_shift(shift, bump=False):
    entries = entries_of_shift(shift["id"])
    counted = [e for e in entries if e["status"] in COUNTED_STATUSES]
    waste = sum(e["weight_grams"] for e in counted)
    pre = sum(e["weight_grams"] for e in counted if e["stream"] == "PRE_CONSUMER")
    intensity = calc.intensity_per_1k_meals(waste, shift["meals_served"])
    share = calc.pre_consumer_share(pre, waste)
    with_capture = set(e["station_id"] for e in entries
                       if e["status"] in CAPTURE_PRESENT_STATUSES)
    compliance = calc.capture_compliance(len(with_capture),
                                         active_station_count(shift["site_id"]))
    shift["shift_waste_grams"] = waste
    shift["waste_intensity_kg_per_1k_meals"] = num(intensity)
    shift["pre_consumer_share_pct"] = num(share)
    shift["capture_compliance_pct"] = num(compliance)
    if shift["status"] == "CLOSED":
        site = db.sites[shift["site_id"]]
        shift["leaderboard_score"] = num(calc.leaderboard_score(
            intensity, site["target_intensity_kg_per_1k_meals"], compliance, share))
    else:
        shift["leaderboard_score"] = None
    if bump:
        touch(shift)
    return shift


# ------------------------------------------------------- site_waste_aggregates
def recompute_site(site, bump=False):
    counted = [e for e in entries_of_site(site["id"])
               if e["status"] in COUNTED_STATUSES]
    captured = sum(e["weight_grams"] for e in counted)
    valued = sum((e["effective_cost_cents"] or 0) for e in counted)
    diverted = 0
    for line in db.lines.values():
        cons = db.consignments.get(line["consignment_id"])
        if cons is None or cons["site_id"] != site["id"]:
            continue
        if cons["settlement_status"] == "SETTLED" and cons["logistics_status"] != "CANCELLED":
            diverted += line["allocated_weight_grams"]
    open_alerts = len([a for a in db.alerts.values()
                       if a["site_id"] == site["id"]
                       and a["status"] in ("OPEN", "ACKNOWLEDGED")])
    site["total_captured_weight_grams"] = captured
    site["valued_waste_cost_cents"] = valued
    site["diverted_weight_grams_settled"] = diverted
    site["diversion_rate_pct"] = num(calc.diversion_rate(diverted, captured))
    site["open_alert_count"] = open_alerts
    site["coaching_posture"] = calc.coaching_posture(open_alerts)
    if bump:
        touch(site)
    return site


# ------------------------------------------------------ routed_weight_allocation
def recompute_entry_routing(entry, bump=False):
    routed = 0
    for line in lines_of_entry(entry["id"]):
        cons = db.consignments.get(line["consignment_id"])
        if cons is not None and cons["logistics_status"] != "CANCELLED":
            routed += line["allocated_weight_grams"]
    entry["routed_weight_grams"] = routed
    entry["unrouted_weight_grams"] = entry["weight_grams"] - routed
    if bump:
        touch(entry)
    return entry


def recompute_consignment_totals(cons, bump=False):
    lines = lines_of_consignment(cons["id"])
    cons["staged_weight_grams"] = sum(l["allocated_weight_grams"] for l in lines)
    cons["line_count"] = len(lines)
    if bump:
        touch(cons)
    return cons


# ------------------------------------------------------ coaching_alert_trigger
def _has_open_alert(shift_id, alert_type):
    for alert in db.alerts.values():
        if (alert["shift_id"] == shift_id and alert["alert_type"] == alert_type
                and alert["status"] in ("OPEN", "ACKNOWLEDGED")):
            return True
    return False


def _new_alert(site_id, shift_id, entry_id, alert_type, severity, observed, message):
    alert = base_row(
        site_id=site_id,
        shift_id=shift_id,
        waste_entry_id=entry_id,
        alert_type=alert_type,
        severity=severity,
        status="OPEN",
        observed_intensity=observed,
        message=message,
        acknowledged_by_user_id=None,
        resolved_by_user_id=None,
        resolution_note=None,
        resolved_at=None,
    )
    db.alerts[alert["id"]] = alert
    return alert


def evaluate_coaching(shift, entry):
    """Rule A (intensity breach) is evaluated - and created - before rule B."""
    created = []
    intensity = shift["waste_intensity_kg_per_1k_meals"]
    if intensity is not None and D(intensity) >= calc.COACHING_INTENSITY_THRESHOLD:
        if not _has_open_alert(shift["id"], "INTENSITY_BREACH"):
            severity = ("HIGH" if D(intensity) >= calc.HIGH_SEVERITY_INTENSITY
                        else "MEDIUM")
            created.append(_new_alert(
                shift["site_id"], shift["id"], entry["id"], "INTENSITY_BREACH",
                severity, intensity,
                "Waste intensity %s kg per 1000 meals has reached the coaching "
                "threshold of 12.000 for this service period."
                % format(rhu(intensity, 3), "f")))
    if (entry["loss_reason"] == "OVERPRODUCTION"
            and entry["weight_grams"] >= calc.OVERPRODUCTION_SPIKE_GRAMS):
        if not _has_open_alert(shift["id"], "OVERPRODUCTION_SPIKE"):
            created.append(_new_alert(
                shift["site_id"], shift["id"], entry["id"], "OVERPRODUCTION_SPIKE",
                "MEDIUM", None,
                "Single overproduction capture of %d g has reached the spike "
                "threshold of 5000 g." % entry["weight_grams"]))
    return created


# ------------------------------------------------------- waste_entry_valuation
def apply_capture_valuation(entry, food_type, recipe):
    """Snapshots both bases at capture and writes the provisional valuation."""
    catalog_basis = food_type["default_cost_per_kg_cents"]
    recipe_basis = recipe["published_cost_per_kg_cents"] if recipe else None
    provisional = calc.valuation_cost(entry["weight_grams"], catalog_basis)
    entry["catalog_cost_basis_cents"] = catalog_basis
    entry["recipe_cost_basis_cents"] = recipe_basis
    entry["provisional_cost_cents"] = provisional
    entry["final_cost_cents"] = None
    entry["valuation_delta_cents"] = None
    entry["effective_cost_cents"] = provisional
    return entry


def final_valuation_pass(shift):
    """Runs at shift close over RECORDED and FLAGGED captures, oldest first."""
    rows = [e for e in entries_of_shift(shift["id"])
            if e["status"] in COUNTED_STATUSES]
    rows.sort(key=lambda e: (e["captured_at"], e["created_at"], e["_seq"]))
    for entry in rows:
        basis = entry["recipe_cost_basis_cents"]
        if basis is None:
            basis = entry["catalog_cost_basis_cents"]
        final = calc.valuation_cost(entry["weight_grams"], basis)
        entry["final_cost_cents"] = final
        entry["valuation_delta_cents"] = final - entry["provisional_cost_cents"]
        entry["effective_cost_cents"] = final
        touch(entry)
    return rows


# -------------------------------------------------------- reduction_attainment
def compute_attainment(target):
    site = db.sites[target["site_id"]]
    baseline = db.baselines.get(target["baseline_period_id"])
    window_start = target["window_start"]
    window_end = target["window_end"]
    counted = counted_entries_in_window(site["id"], window_start, window_end)
    perf_grams = sum(e["weight_grams"] for e in counted)
    perf_meals = closed_shift_meals(site["id"], window_start, window_end)
    perf_intensity = calc.intensity_per_1k_meals(perf_grams, perf_meals)

    baseline_grams = baseline["baseline_waste_grams"] if baseline else None
    baseline_intensity = (baseline["baseline_intensity_kg_per_1k_meals"]
                          if baseline else None)
    absolute_pct = calc.reduction_pct(baseline_grams, perf_grams)
    intensity_pct = calc.reduction_pct(baseline_intensity, perf_intensity)
    effective = absolute_pct if target["basis"] == "ABSOLUTE" else intensity_pct

    site_rate = site["diversion_rate_pct"]
    diversion_floor = D(site_rate) if site_rate is not None else D("0.00")
    state = "BEHIND"
    if (effective is not None
            and effective >= D(target["target_reduction_pct"])
            and diversion_floor >= D(target["min_diversion_rate_pct"])):
        state = "ACHIEVED_PENDING"
    return {
        "baseline_waste_grams": baseline_grams,
        "baseline_intensity_kg_per_1k_meals": baseline_intensity,
        "performance_waste_grams": perf_grams,
        "performance_meals_served": perf_meals,
        "performance_intensity_kg_per_1k_meals": num(perf_intensity),
        "absolute_reduction_pct": num(absolute_pct),
        "intensity_reduction_pct": num(intensity_pct),
        "effective_reduction_pct": num(effective),
        "site_diversion_rate_pct": site_rate,
        "attainment_state": state,
    }


def apply_attainment(target, bump=False):
    figures = compute_attainment(target)
    target["performance_waste_grams"] = figures["performance_waste_grams"]
    target["performance_meals_served"] = figures["performance_meals_served"]
    target["performance_intensity_kg_per_1k_meals"] = \
        figures["performance_intensity_kg_per_1k_meals"]
    target["absolute_reduction_pct"] = figures["absolute_reduction_pct"]
    target["intensity_reduction_pct"] = figures["intensity_reduction_pct"]
    target["effective_reduction_pct"] = figures["effective_reduction_pct"]
    target["attainment_state"] = figures["attainment_state"]
    if bump:
        touch(target)
    return target


def active_targets_of_site(site_id):
    rows = [t for t in db.targets.values()
            if t["site_id"] == site_id and t["status"] == "ACTIVE"]
    rows.sort(key=lambda t: (t["created_at"], t["_seq"]))
    return rows


# ----------------------------------------------------- corporate_rollup_metrics
def recompute_rollup(rollup, bump=False):
    site_ids = set(rollup["site_ids"])
    start = rollup["period_start"]
    end = rollup["period_end"]
    captured = 0
    valued = 0
    for entry in db.entries.values():
        if entry["site_id"] not in site_ids:
            continue
        if entry["status"] not in COUNTED_STATUSES:
            continue
        if not (start <= date_of(entry["captured_at"]) <= end):
            continue
        captured += entry["weight_grams"]
        valued += entry["effective_cost_cents"] or 0
    diverted = 0
    for line in db.lines.values():
        cons = db.consignments.get(line["consignment_id"])
        if cons is None or cons["site_id"] not in site_ids:
            continue
        if cons["settlement_status"] != "SETTLED":
            continue
        if cons["logistics_status"] == "CANCELLED":
            continue
        if not (start <= date_of(cons["pickup_window_start"]) <= end):
            continue
        diverted += line["allocated_weight_grams"]
    on_track = 0
    for site_id in site_ids:
        for target in db.targets.values():
            if (target["site_id"] == site_id and target["status"] == "ACTIVE"
                    and target["attainment_state"] == "ACHIEVED_PENDING"):
                on_track += 1
                break
    total_sites = len(site_ids)
    if on_track == total_sites and total_sites > 0:
        goal_state = "ALL_ON_TRACK"
    elif on_track == 0:
        goal_state = "NONE_ON_TRACK"
    else:
        goal_state = "PARTIAL"
    rollup["in_scope_site_count"] = total_sites
    rollup["total_captured_weight_grams"] = captured
    rollup["total_valued_cost_cents"] = valued
    rollup["total_diverted_weight_grams"] = diverted
    rollup["diversion_rate_pct"] = num(calc.diversion_rate(diverted, captured))
    rollup["sites_on_track_count"] = on_track
    rollup["goal_attainment_state"] = goal_state
    if bump:
        touch(rollup)
    return rollup


# ------------------------------------------------------- baseline_period_metrics
def freeze_baseline_metrics(period):
    counted = counted_entries_in_window(period["site_id"], period["start_date"],
                                        period["end_date"])
    grams = sum(e["weight_grams"] for e in counted)
    cost = sum((e["effective_cost_cents"] or 0) for e in counted)
    meals = closed_shift_meals(period["site_id"], period["start_date"],
                              period["end_date"])
    period["baseline_entry_count"] = len(counted)
    period["baseline_waste_grams"] = grams
    period["baseline_waste_kg"] = num(rhu(D(grams) / D(1000), 3))
    period["baseline_meals_served"] = meals
    period["baseline_intensity_kg_per_1k_meals"] = num(
        calc.intensity_per_1k_meals(grams, meals))
    period["baseline_cost_cents"] = cost
    return period


def clear_baseline_metrics(period):
    period["baseline_entry_count"] = 0
    period["baseline_waste_grams"] = 0
    period["baseline_waste_kg"] = 0.0
    period["baseline_meals_served"] = 0
    period["baseline_intensity_kg_per_1k_meals"] = None
    period["baseline_cost_cents"] = 0
    return period


# -------------------------------------------------------------- data_quality_scan
SHIFT_CODE_ORDER = {"AM": 0, "PM": 1, "NIGHT": 2}


def _finding_exists(finding_type, site_id, station_id, shift_id, entry_id):
    for finding in db.findings.values():
        if (finding["finding_type"] == finding_type
                and finding["site_id"] == site_id
                and finding["station_id"] == station_id
                and finding["shift_id"] == shift_id
                and finding["waste_entry_id"] == entry_id
                and finding["status"] == "OPEN"):
            return True
    return False


def _emit_finding(finding_type, site_id, station_id, shift_id, entry_id, detail):
    if _finding_exists(finding_type, site_id, station_id, shift_id, entry_id):
        return None
    finding = base_row(
        site_id=site_id,
        waste_entry_id=entry_id,
        station_id=station_id,
        shift_id=shift_id,
        finding_type=finding_type,
        status="OPEN",
        detail=detail,
        detected_at=db.now_iso(),
        resolved_by_user_id=None,
    )
    db.findings[finding["id"]] = finding
    return finding


def run_data_quality_scan(site, scan_date):
    created = []
    shifts = [s for s in db.shifts.values()
              if s["site_id"] == site["id"] and s["shift_date"] == scan_date]
    shifts.sort(key=lambda s: (SHIFT_CODE_ORDER.get(s["shift_code"], 99),
                               s["created_at"], s["_seq"]))
    stations = [s for s in db.stations.values()
                if s["site_id"] == site["id"] and s["status"] == "ACTIVE"]
    stations.sort(key=lambda s: (s["station_code"], s["created_at"], s["_seq"]))
    shift_ids = set(s["id"] for s in shifts)

    # 1. MISSED_CAPTURE, station_code ascending then AM, PM, NIGHT.
    for station in stations:
        for shift in shifts:
            present = False
            for entry in db.entries.values():
                if (entry["station_id"] == station["id"]
                        and entry["shift_id"] == shift["id"]
                        and entry["status"] in CAPTURE_PRESENT_STATUSES):
                    present = True
                    break
            if present:
                continue
            finding = _emit_finding(
                "MISSED_CAPTURE", site["id"], station["id"], shift["id"], None,
                "No capture was recorded at station %s during the %s service "
                "period on %s." % (station["station_code"], shift["shift_code"],
                                   scan_date))
            if finding:
                created.append(finding)

    scoped = [e for e in db.entries.values()
              if e["shift_id"] in shift_ids and e["status"] in COUNTED_STATUSES]
    scoped.sort(key=lambda e: (e["captured_at"], e["created_at"], e["_seq"]))

    # 2. DUPLICATE_ENTRY, reported on the later capture of the pair.
    for index, entry in enumerate(scoped):
        later_at = parse_ts(entry["captured_at"])
        for earlier in scoped[:index]:
            if (earlier["station_id"] != entry["station_id"]
                    or earlier["food_type_id"] != entry["food_type_id"]
                    or earlier["weight_grams"] != entry["weight_grams"]):
                continue
            elapsed = (later_at - parse_ts(earlier["captured_at"])).total_seconds()
            if elapsed <= calc.DUPLICATE_WINDOW_SECONDS:
                finding = _emit_finding(
                    "DUPLICATE_ENTRY", site["id"], entry["station_id"],
                    entry["shift_id"], entry["id"],
                    "Capture repeats the station, food type and weight of an "
                    "earlier capture within %d seconds."
                    % calc.DUPLICATE_WINDOW_SECONDS)
                if finding:
                    created.append(finding)
                break

    # 3. WEIGHT_OUTLIER.
    for entry in scoped:
        if entry["weight_grams"] < calc.OUTLIER_GRAMS_THRESHOLD:
            continue
        finding = _emit_finding(
            "WEIGHT_OUTLIER", site["id"], entry["station_id"], entry["shift_id"],
            entry["id"],
            "Capture weight of %d g is at or above the outlier threshold of "
            "%d g." % (entry["weight_grams"], calc.OUTLIER_GRAMS_THRESHOLD))
        if finding:
            created.append(finding)
    return created


def site_has_open_findings(site_ids):
    """Rollup publication guard: any OPEN finding at an in-scope site blocks
    publication - the finding's detected_at is irrelevant to this test."""
    for finding in db.findings.values():
        if finding["status"] == "OPEN" and finding["site_id"] in site_ids:
            return True
    return False
