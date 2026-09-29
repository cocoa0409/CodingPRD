"""Cross-entity derivations, ledgers, calculations and cascades.

Every function here traces to a numbered PRD section, cited in its docstring.
"""

import math
from decimal import Decimal

import store
from store import (
    APPURTENANCES, COATING_APPLICATIONS, COMMISSIONING_PACKAGES,
    FOUNDATION_PACKAGES, HYDROTEST_PLANS, NDE_REPORTS, PLATE_LOTS,
    SETTLEMENT_SURVEYS, SHELL_COURSES, TANKS, WATER_SOURCES,
    WATER_WITHDRAWALS, WELD_SEAMS, WELDERS,
)
from store import touch, touch_time
from util import D, add_years, now_logical, q, qd

PI = Decimal("3.141592653589793")
INCHES_PER_FOOT = Decimal(12)
ONE_FOOT_METHOD_COEFFICIENT = Decimal("2.6")
GALLONS_PER_KGAL = Decimal(1000)
RT_BUFFER_MINUTES = 60
BASE_EXAMINATION_PCT = 10.0
MAX_REPAIR_CYCLES = 2
GAUGE_READINGS_PER_SPOT = 3
SPOT_LOWER_FACTOR = Decimal("0.80")
SPOT_UPPER_FACTOR = Decimal("1.20")
MIN_DEW_POINT_SPREAD_F = 5.0
HOLIDAY_VOLTAGE_FACTOR = Decimal("67.5")
MAX_INTERNAL_INTERVAL_YEARS = 20
EXTERNAL_INTERVAL_COATED_YEARS = 5
EXTERNAL_INTERVAL_UNCOATED_YEARS = 2

REQUIRED_DOCUMENT_TYPES = [
    "MILL_TEST_REPORTS", "RT_FILM_LOG", "HYDROTEST_RECORD", "AS_BUILT_DRAWING",
]
OPTIONAL_DOCUMENT_TYPES = ["COATING_REPORT", "SETTLEMENT_LOG"]
DOCUMENT_TYPES = REQUIRED_DOCUMENT_TYPES + OPTIONAL_DOCUMENT_TYPES

# PRD 3.8: the cleanliness ranking, not a numeric one.
PREP_ORDER = ["SSPC_SP3", "SSPC_SP6", "SSPC_SP10", "SSPC_SP5"]


# ---------------------------------------------------------------- navigation
def by_created(collection_rows):
    return sorted(collection_rows, key=lambda r: (r["created_at"], r["id"]))


def package_of_tank(tank_id):
    for row in FOUNDATION_PACKAGES.values():
        if row["tank_id"] == tank_id:
            return row
    return None


def package_of_tank_all(tank_id):
    return [r for r in FOUNDATION_PACKAGES.values() if r["tank_id"] == tank_id]


def courses_of_tank(tank_id):
    return [c for c in SHELL_COURSES.values() if c["tank_id"] == tank_id]


def seams_of_course(course_id):
    return [s for s in WELD_SEAMS.values() if s["shell_course_id"] == course_id]


def seams_of_tank(tank_id):
    ids = {c["id"] for c in courses_of_tank(tank_id)}
    return [s for s in WELD_SEAMS.values() if s["shell_course_id"] in ids]


def course_of_seam(seam):
    return SHELL_COURSES.get(seam["shell_course_id"])


def tank_id_of_seam(seam):
    course = course_of_seam(seam)
    return course["tank_id"] if course else None


def tank_id_of_report(report):
    seam = WELD_SEAMS.get(report["weld_seam_id"])
    return tank_id_of_seam(seam) if seam else None


def reports_of_seam(seam_id):
    return [r for r in NDE_REPORTS.values() if r["weld_seam_id"] == seam_id]


def reports_of_tank(tank_id):
    ids = {s["id"] for s in seams_of_tank(tank_id)}
    return [r for r in NDE_REPORTS.values() if r["weld_seam_id"] in ids]


def surveys_of_package(package_id):
    return [s for s in SETTLEMENT_SURVEYS.values()
            if s["foundation_package_id"] == package_id]


def tank_id_of_survey(survey):
    package = FOUNDATION_PACKAGES.get(survey["foundation_package_id"])
    return package["tank_id"] if package else None


def lots_of_tank(tank_id):
    return [l for l in PLATE_LOTS.values() if l["tank_id"] == tank_id]


def plans_of_tank(tank_id):
    return [p for p in HYDROTEST_PLANS.values() if p["tank_id"] == tank_id]


def withdrawals_of_plan(plan_id):
    return [w for w in WATER_WITHDRAWALS.values()
            if w["hydrotest_plan_id"] == plan_id]


def withdrawals_of_source(source_id):
    return [w for w in WATER_WITHDRAWALS.values()
            if w["water_source_id"] == source_id]


def applications_of_tank(tank_id):
    return [a for a in COATING_APPLICATIONS.values() if a["tank_id"] == tank_id]


def appurtenances_of_tank(tank_id):
    return [a for a in APPURTENANCES.values() if a["tank_id"] == tank_id]


def package_of_tank_commissioning(tank_id):
    for row in COMMISSIONING_PACKAGES.values():
        if row["tank_id"] == tank_id:
            return row
    return None


def set_fields(row, values, bump=True):
    """Apply values; return True when at least one field actually changed."""
    changed = False
    for key, value in values.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed and bump:
        touch(row)
    return changed


# ------------------------------------------------- PRD 3.1 / 3.4 : thickness
def min_nominal_thickness(diameter_ft):
    """PRD 3.1: the four diameter bands of the minimum nominal thickness."""
    diameter = D(diameter_ft)
    if diameter < 50:
        return 0.188
    if diameter < 120:
        return 0.250
    if diameter < 200:
        return 0.313
    return 0.375


def compute_course_thickness(course, tank):
    """PRD 3.4: the one-foot method against design, test and the flat floor."""
    lower = [c for c in courses_of_tank(tank["id"])
             if c["id"] != course["id"]
             and int(c["course_number"]) < int(course["course_number"])]
    lower.sort(key=lambda c: int(c["course_number"]))
    bottom = Decimal(0)
    for other in lower:
        bottom += D(other["course_width_ft"])
    height = D(tank["design_liquid_level_ft"]) - bottom

    head = height - Decimal(1)
    diameter = D(tank["diameter_ft"])
    efficiency = D(tank["joint_efficiency"])
    design = (ONE_FOOT_METHOD_COEFFICIENT * head * diameter
              * D(tank["product_specific_gravity"])
              / (D(course["allowable_stress_design_psi"]) * efficiency)
              + D(tank["corrosion_allowance_in"]))
    test = (ONE_FOOT_METHOD_COEFFICIENT * head * diameter
            / (D(course["allowable_stress_test_psi"]) * efficiency))

    # PRD 2.5 / 3.4: each variant is rounded to 3 dp *before* anything is
    # compared, and the rounded values feed the maximum.
    design_r = qd(design, 3)
    test_r = qd(test, 3)
    floor_r = qd(tank["min_nominal_thickness_in"], 3)

    candidates = [("DESIGN", design_r), ("TEST", test_r),
                  ("MIN_NOMINAL", floor_r)]
    required = max(value for _name, value in candidates)
    governing = next(name for name, value in candidates if value == required)
    verdict = ("ADEQUATE" if D(course["plate_thickness_in"]) >= required
               else "DEFICIENT")

    return set_fields(course, {
        "course_bottom_elevation_ft": float(bottom),
        "design_liquid_height_ft": float(height),
        "required_thickness_design_in": float(design_r),
        "required_thickness_test_in": float(test_r),
        "required_thickness_in": float(required),
        "governing_case": governing,
        "thickness_verdict": verdict,
    })


def recompute_tank_courses(tank):
    """PRD 3.4: adding a lower course re-evaluates the courses above it."""
    for course in sorted(courses_of_tank(tank["id"]),
                         key=lambda c: int(c["course_number"])):
        compute_course_thickness(course, tank)


# ------------------------------------------------ PRD 3.4 : course re-derive
def rederive_course_status(course):
    """After fit-up a course status is a pure function of its weld seams."""
    if course["status"] == "SPECIFIED":
        return
    seams = seams_of_course(course["id"])
    statuses = [s["status"] for s in seams]
    if seams and all(s == "RT_ACCEPTED" for s in statuses):
        new_status = "RT_ACCEPTED"
    elif seams and all(s in ("WELDED", "EXAM_SCHEDULED", "RT_ACCEPTED")
                       for s in statuses):
        new_status = "WELDED"
    else:
        new_status = "FITTED"
    previous = course["status"]
    if new_status == previous:
        return
    course["status"] = new_status
    touch(course)
    # PRD 3.4: a course leaving radiographic acceptance reverts the tank.
    if previous == "RT_ACCEPTED":
        tank = TANKS.get(course["tank_id"])
        if tank is not None and tank["construction_phase"] == "SHELL_COMPLETE":
            tank["construction_phase"] = "ERECTION_IN_PROGRESS"
            touch(tank)


# ------------------------------------------- PRD 2.8 : posture and cascade
def count_open_nonconformances(tank_id):
    """Full recount over the four independent carriers."""
    total = 0
    for report in NDE_REPORTS.values():
        if report["nonconformance_open"] and tank_id_of_report(report) == tank_id:
            total += 1
    for survey in SETTLEMENT_SURVEYS.values():
        if (survey["nonconformance_state"] == "OPEN"
                and tank_id_of_survey(survey) == tank_id):
            total += 1
    for application in COATING_APPLICATIONS.values():
        if (application["tank_id"] == tank_id
                and application["status"] == "REWORK_REQUIRED"):
            total += 1
    for plan in HYDROTEST_PLANS.values():
        if plan["tank_id"] == tank_id and plan["status"] == "FAILED":
            total += 1
    return total


def posture_for(count):
    if count == 0:
        return "OPEN"
    if count <= 2:
        return "RESTRICTED"
    return "FROZEN"


def recompute_posture(tank):
    """PRD 2.8: recount, re-derive the posture, then propagate in one pass."""
    count = count_open_nonconformances(tank["id"])
    posture = posture_for(count)
    posture_changed = tank["quality_posture"] != posture
    count_changed = tank["open_nonconformance_count"] != count
    tank["open_nonconformance_count"] = count
    tank["quality_posture"] = posture
    if posture_changed:
        touch(tank)
    elif count_changed:
        touch_time(tank)
    if posture == "OPEN":
        restore_suspended_plans(tank)
    else:
        suspend_live_plans(tank)


def suspend_live_plans(tank):
    plans = [p for p in plans_of_tank(tank["id"])
             if p["status"] in ("APPROVED", "FILLING", "FILL_HOLD")]
    for plan in by_created(plans):
        plan["state_before_suspension"] = plan["status"]
        plan["suspension_reason"] = "TANK_POSTURE_" + tank["quality_posture"]
        plan["status"] = "SUSPENDED"
        touch(plan)
        cancel_plan_withdrawals(plan, "PLAN_SUSPENDED")


def restore_suspended_plans(tank):
    for plan in by_created(plans_of_tank(tank["id"])):
        if plan["status"] != "SUSPENDED":
            continue
        restored = plan["state_before_suspension"] or "APPROVED"
        plan["status"] = restored
        plan["state_before_suspension"] = None
        plan["suspension_reason"] = None
        touch(plan)


def cancel_plan_withdrawals(plan, reason):
    """Cancel the plan's RESERVED windows and hand the volume back."""
    sources = []
    for withdrawal in by_created(withdrawals_of_plan(plan["id"])):
        if withdrawal["status"] != "RESERVED":
            continue
        withdrawal["status"] = "CANCELLED"
        withdrawal["cancellation_reason"] = reason
        touch(withdrawal)
        source = WATER_SOURCES.get(withdrawal["water_source_id"])
        if source is not None and source not in sources:
            sources.append(source)
    for source in sources:
        rederive_water_ledger(source)
    recompute_plan_costs(plan)


# ------------------------------------------------- PRD 3.3 : the steel ledger
def rederive_steel_ledger(tank):
    """Full re-derivation of lot and tank weights (never incremental)."""
    lots = lots_of_tank(tank["id"])
    received_total = Decimal(0)
    allocated_total = Decimal(0)
    for lot in lots:
        allocated = Decimal(0)
        for course in SHELL_COURSES.values():
            if (course["allocated_plate_lot_id"] == lot["id"]
                    and course["allocation_status"] == "ALLOCATED"):
                allocated += D(course["allocated_weight_lb"])
        allocated = qd(allocated, 2)
        remaining = qd(D(lot["received_weight_lb"]), 2) - allocated
        if remaining < 0:
            remaining = Decimal("0.00")
        set_fields(lot, {
            "allocated_weight_lb": float(allocated),
            "remaining_weight_lb": float(remaining),
        })
        if lot["status"] in ("RECEIVED", "RELEASED", "QUARANTINED"):
            received_total += D(lot["received_weight_lb"])
        allocated_total += D(lot["allocated_weight_lb"])
    changed = set_fields(tank, {
        "steel_received_lb": q(received_total, 2),
        "steel_allocated_lb": q(allocated_total, 2),
    }, bump=False)
    if changed:
        touch_time(tank)


# ------------------------------------------------- PRD 3.7 : the water ledger
def rederive_water_ledger(source):
    reserved = Decimal(0)
    consumed = Decimal(0)
    for withdrawal in withdrawals_of_source(source["id"]):
        if withdrawal["status"] == "RESERVED":
            reserved += D(withdrawal["reserved_volume_gal"])
        elif withdrawal["status"] == "CONSUMED":
            consumed += D(withdrawal["reserved_volume_gal"])
    reserved = qd(reserved, 2)
    consumed = qd(consumed, 2)
    available = qd(D(source["permitted_volume_gal"]), 2) - reserved - consumed
    changed = set_fields(source, {
        "reserved_volume_gal": float(reserved),
        "consumed_volume_gal": float(consumed),
        "available_volume_gal": float(available),
    }, bump=False)
    if changed:
        # PRD 2.6: only an accepted reservation advances the source's version.
        touch_time(source)


def disposal_multiplier(total_kgal):
    if total_kgal <= 500:
        return Decimal("1.00")
    if total_kgal <= 2000:
        return Decimal("0.85")
    return Decimal("0.70")


def surcharge_pct(subtotal):
    if subtotal < 1000:
        return Decimal("0.00")
    if subtotal < 2000:
        return Decimal("0.03")
    return Decimal("0.05")


def recompute_plan_costs(plan):
    """PRD 3.7: round each withdrawal, then sum the rounded amounts."""
    source = WATER_SOURCES.get(plan["water_source_id"])
    inputs = [w for w in by_created(withdrawals_of_plan(plan["id"]))
              if w["status"] in ("RESERVED", "CONSUMED")]
    water_cost = Decimal("0.00")
    volume = Decimal(0)
    for withdrawal in inputs:
        per_unit = D(source["water_cost_usd_per_kgal"]) if source else Decimal(0)
        cost = qd(D(withdrawal["reserved_volume_gal"]) / GALLONS_PER_KGAL
                  * per_unit, 2)
        set_fields(withdrawal, {"withdrawal_cost_usd": float(cost)})
        water_cost += cost
        volume += D(withdrawal["reserved_volume_gal"])
    total_kgal = volume / GALLONS_PER_KGAL
    disposal_rate = D(source["disposal_cost_usd_per_kgal"]) if source else Decimal(0)
    disposal = qd(total_kgal * disposal_rate * disposal_multiplier(total_kgal), 2)
    subtotal = water_cost + disposal
    pct = surcharge_pct(subtotal)
    surcharge = qd(subtotal * pct, 2)
    total = subtotal + surcharge
    set_fields(plan, {
        "water_cost_usd": float(water_cost),
        "disposal_cost_usd": float(disposal),
        "subtotal_usd": float(subtotal),
        "permit_surcharge_pct": float(pct),
        "surcharge_usd": float(surcharge),
        "total_cost_usd": float(total),
    })


def withdrawal_cost_for(source, reserved_volume_gal):
    return q(D(reserved_volume_gal) / GALLONS_PER_KGAL
             * D(source["water_cost_usd_per_kgal"]), 2)


# -------------------------------------------- PRD 3.6 : reject rate ladder
def recompute_reject_rate(tank):
    population = [r for r in reports_of_tank(tank["id"])
                  if r["method"] == "RT"
                  and r["status"] in ("REPORTED_ACCEPT", "REPORTED_REJECT")]
    examined = len(population)
    rejected = len([r for r in population if r["status"] == "REPORTED_REJECT"])
    if examined == 0:
        rate = 0.0
    else:
        rate = q(D(rejected) / D(examined), 4)
    if rate >= 0.50:
        pct = 100.0
    elif rate >= 0.25:
        pct = 50.0
    else:
        pct = BASE_EXAMINATION_PCT
    changed = set_fields(tank, {
        "weld_reject_rate": rate,
        "required_examination_pct": pct,
    }, bump=False)
    if changed:
        touch_time(tank)


# ------------------------------------------------ PRD 3.5 : welder continuity
def refresh_welder(welder):
    """Lazy continuity re-evaluation against the logical clock."""
    if welder["qualification_status"] == "REVOKED":
        return welder
    expiry = welder["continuity_expires_at_utc"]
    if expiry is not None and expiry < now_logical():
        welder["qualification_status"] = "LAPSED"
    else:
        welder["qualification_status"] = "QUALIFIED"
    return welder


def refresh_all_welders():
    for welder in WELDERS.values():
        refresh_welder(welder)


# ------------------------------------------ PRD 3.2 : settlement evaluation
def settlement_envelope(package, tank):
    """PRD 3.2: freeze the tolerance envelope from the package and the tank."""
    spacing = (PI * D(tank["diameter_ft"]) * INCHES_PER_FOOT
               / D(package["monitoring_point_count"]))
    spacing_r = qd(spacing, 4)
    allowable = qd(D(package["permitted_differential_ratio"]) * spacing_r, 3)
    package["point_spacing_in"] = float(spacing_r)
    package["allowable_differential_in"] = float(allowable)


def readings_by_index(readings):
    return {int(r["point_index"]): D(r["elevation_in"]) for r in readings}


def evaluate_survey(survey, package, baseline):
    """PRD 3.2: both differential metrics are stored on every survey row."""
    count = int(package["monitoring_point_count"])
    this_readings = readings_by_index(survey["point_readings"])
    base_readings = readings_by_index(baseline["point_readings"])
    indexes = sorted(this_readings.keys())
    settlements = [base_readings[i] - this_readings[i] for i in indexes]
    n = len(settlements)

    mean = sum(settlements, Decimal(0)) / D(n)

    # Cosine best fit (one-term discrete Fourier).
    angles = [2.0 * math.pi * float(i) / float(count) for i in indexes]
    b = 0.0
    c = 0.0
    for value, angle in zip(settlements, angles):
        b += float(value) * math.cos(angle)
        c += float(value) * math.sin(angle)
    b = (2.0 / float(count)) * b
    c = (2.0 / float(count)) * c
    max_out = 0.0
    for value, angle in zip(settlements, angles):
        predicted = float(mean) + b * math.cos(angle) + c * math.sin(angle)
        deviation = abs(float(value) - predicted)
        if deviation > max_out:
            max_out = deviation

    # Adjacent pair, walked circularly.
    max_adjacent = Decimal(0)
    for position in range(n):
        step = abs(settlements[position] - settlements[(position + 1) % n])
        if step > max_adjacent:
            max_adjacent = step

    uniform_r = qd(mean, 3)
    out_r = qd(max_out, 3)
    adjacent_r = qd(max_adjacent, 3)
    if package["settlement_evaluation_method"] == "COSINE_BEST_FIT":
        governing = out_r
    else:
        governing = adjacent_r

    within = (governing <= D(package["allowable_differential_in"])
              and uniform_r <= D(package["permitted_uniform_settlement_in"]))
    survey["uniform_settlement_in"] = float(uniform_r)
    survey["max_out_of_plane_in"] = float(out_r)
    survey["max_adjacent_differential_in"] = float(adjacent_r)
    survey["governing_metric_in"] = float(governing)
    survey["verdict"] = "WITHIN_TOLERANCE" if within else "OUT_OF_TOLERANCE"


def close_superseded_surveys(new_survey, package):
    """PRD 3.2: a later WITHIN_TOLERANCE round at an equal or higher fill
    level closes an earlier open nonconformance."""
    if new_survey["verdict"] != "WITHIN_TOLERANCE":
        return
    for survey in by_created(surveys_of_package(package["id"])):
        if survey["id"] == new_survey["id"]:
            continue
        if survey["nonconformance_state"] != "OPEN":
            continue
        if D(new_survey["fill_percent"]) >= D(survey["fill_percent"]):
            survey["nonconformance_state"] = "CLOSED_BY_SUPERSEDING_SURVEY"
            survey["superseded_by_survey_id"] = new_survey["id"]
            touch(survey)


# -------------------------------------------------- PRD 3.8 : coating / DFT
def prep_rank(grade):
    return PREP_ORDER.index(grade) if grade in PREP_ORDER else -1


def evaluate_dft(application, spot_readings):
    """PRD 3.8: recompute every aggregate from the submitted payload alone."""
    spot_averages = []
    all_readings = []
    for spot in spot_readings:
        values = [D(v) for v in spot]
        all_readings.extend(values)
        spot_averages.append(qd(sum(values, Decimal(0)) / D(len(values)), 2))
    overall = qd(sum(all_readings, Decimal(0)) / D(len(all_readings)), 2)
    minimum = min(all_readings)
    specified = D(application["specified_min_dft_mils"])

    if application["dft_acceptance_method"] == "SPOT_AVERAGE_80_120":
        verdict = "PASS" if (
            all(avg >= SPOT_LOWER_FACTOR * specified for avg in spot_averages)
            and all(avg <= SPOT_UPPER_FACTOR * specified for avg in spot_averages)
            and overall >= specified
        ) else "FAIL"
    else:
        verdict = "PASS" if (minimum >= specified and overall >= specified) \
            else "FAIL"

    application["spot_count"] = len(spot_readings)
    application["computed_spot_average_min_mils"] = float(min(spot_averages))
    application["computed_spot_average_max_mils"] = float(max(spot_averages))
    application["computed_overall_average_mils"] = float(overall)
    application["computed_min_gauge_reading_mils"] = float(minimum)
    application["dft_verdict"] = verdict


def reset_dft_measurements(application):
    """PRD 3.8: re-preparation discards the previous cycle's evidence."""
    application["spot_count"] = 0
    application["computed_spot_average_min_mils"] = 0.0
    application["computed_spot_average_max_mils"] = 0.0
    application["computed_overall_average_mils"] = 0.0
    application["computed_min_gauge_reading_mils"] = 0.0
    application["dft_verdict"] = "NOT_EVALUATED"
    application["holidays_found"] = None
    application["holiday_test_voltage_v"] = None


def maybe_advance_coated(tank):
    """PRD 3.8: the last application reaching acceptance closes coating out."""
    applications = applications_of_tank(tank["id"])
    if not applications:
        return
    if any(a["status"] != "ACCEPTED" for a in applications):
        return
    if tank["quality_posture"] != "OPEN":
        return
    if tank["construction_phase"] != "HYDROTEST_PASSED":
        return
    tank["construction_phase"] = "COATED"
    touch(tank)


def coating_rework_cascade(tank):
    """PRD 3.8: posture, then the phase revert, then the package return."""
    recompute_posture(tank)
    if tank["construction_phase"] == "COATED":
        tank["construction_phase"] = "HYDROTEST_PASSED"
        touch(tank)
    package = package_of_tank_commissioning(tank["id"])
    if package is not None and package["status"] == "SUBMITTED":
        package["status"] = "RETURNED_FOR_CORRECTION"
        package["deficiency_count"] = int(package["deficiency_count"]) + 1
        package["next_internal_due_utc"] = None
        package["next_external_due_utc"] = None
        touch(package)


# ------------------------------------------------ PRD 3.9 : appurtenances
def required_clearance(appurtenance_type, nominal_size_in):
    """PRD 3.9: the clearance tier, rounded half up to 1 decimal place."""
    if appurtenance_type in ("NOZZLE", "MANWAY"):
        value = max(Decimal("8.0"), D(nominal_size_in) * Decimal("1.5"))
    elif appurtenance_type == "STAIRWAY":
        value = Decimal("30.0")
    elif appurtenance_type == "MIXER":
        value = Decimal("20.0")
    else:
        value = Decimal("5.0")
    return q(value, 1)


def clearance_conflict(appurtenance):
    """PRD 3.9: clash only against already INSTALLED neighbours of the course."""
    for other in APPURTENANCES.values():
        if other["id"] == appurtenance["id"]:
            continue
        if other["tank_id"] != appurtenance["tank_id"]:
            continue
        if other["host_shell_course_id"] != appurtenance["host_shell_course_id"]:
            continue
        if other["status"] != "INSTALLED":
            continue
        raw_gap = abs(D(appurtenance["azimuth_deg"]) - D(other["azimuth_deg"]))
        separation = min(raw_gap, Decimal(360) - raw_gap)
        separation = qd(separation, 1)
        requirement = max(D(appurtenance["required_clearance_deg"]),
                          D(other["required_clearance_deg"]))
        if separation < requirement:
            return True
    return False


# ------------------------------------------------ PRD 3.6 : RT window rules
def rt_window_conflict(new_report_seam_tank_id, method, start, end,
                       skip_report_id=None):
    """PRD 3.6: RT windows on one tank are exclusive, +/- 60 minutes, closed."""
    if method != "RT":
        return False
    from datetime import timedelta
    buffered_start = start - timedelta(minutes=RT_BUFFER_MINUTES)
    buffered_end = end + timedelta(minutes=RT_BUFFER_MINUTES)
    for report in NDE_REPORTS.values():
        if skip_report_id is not None and report["id"] == skip_report_id:
            continue
        if report["method"] != "RT":
            continue
        if report["status"] not in ("SCHEDULED", "REPORTED_ACCEPT",
                                    "REPORTED_REJECT"):
            continue
        if tank_id_of_report(report) != new_report_seam_tank_id:
            continue
        if (buffered_start <= report["window_end_utc"]
                and report["window_start_utc"] <= buffered_end):
            return True
    return False


# ------------------------------------------- PRD 3.7 : withdrawal capacity
def peak_rate_with(source, start, end, rate_gpm):
    """PRD 3.7: half-open overlap, summed rate rounded half up to 1 dp."""
    total = D(rate_gpm)
    for withdrawal in withdrawals_of_source(source["id"]):
        if withdrawal["status"] != "RESERVED":
            continue
        if (withdrawal["window_start_utc"] < end
                and start < withdrawal["window_end_utc"]):
            total += D(withdrawal["rate_gpm"])
    return qd(total, 1)


# ------------------------------ PRD 3.9 : commissioning document completeness
def refresh_documents(package):
    """Distinct types in required order, then extras in first-recorded order."""
    recorded = package.get("_documents", [])
    seen = []
    for entry in recorded:
        if entry["document_type"] not in seen:
            seen.append(entry["document_type"])
    submitted = [t for t in REQUIRED_DOCUMENT_TYPES if t in seen]
    submitted += [t for t in seen if t not in REQUIRED_DOCUMENT_TYPES]
    missing = [t for t in REQUIRED_DOCUMENT_TYPES if t not in seen]
    package["submitted_document_types"] = submitted
    package["missing_document_types"] = missing
    package["document_count"] = len(recorded)


# ------------------------------------ PRD 3.9 : in-service inspection schedule
def compute_in_service_schedule(package, tank, accepted_at):
    life = qd((D(tank["bottom_thickness_in"])
               - D(tank["bottom_minimum_thickness_in"]))
              / D(tank["assumed_corrosion_rate_ipy"]), 2)
    internal = min(MAX_INTERNAL_INTERVAL_YEARS,
                   int(math.floor(float(life) / 2.0)))
    externally_coated = any(
        a["scope"] == "EXTERNAL_COATING" and a["status"] == "ACCEPTED"
        for a in applications_of_tank(tank["id"]))
    external = (EXTERNAL_INTERVAL_COATED_YEARS if externally_coated
                else EXTERNAL_INTERVAL_UNCOATED_YEARS)
    package["bottom_remaining_life_years"] = float(life)
    package["internal_inspection_interval_years"] = internal
    package["external_inspection_interval_years"] = external
    package["accepted_at_utc"] = accepted_at
    package["next_internal_due_utc"] = add_years(accepted_at, internal)
    package["next_external_due_utc"] = add_years(accepted_at, external)


# ------------------------------------------------- PRD 3.1 : the tank summary
def tank_summary(tank):
    courses = courses_of_tank(tank["id"])
    seams = seams_of_tank(tank["id"])
    appurtenances = appurtenances_of_tank(tank["id"])
    total_cost = Decimal(0)
    for plan in plans_of_tank(tank["id"]):
        total_cost += D(plan["total_cost_usd"])
    remaining = (qd(D(tank["steel_received_lb"]), 2)
                 - qd(D(tank["steel_allocated_lb"]), 2))
    return {
        "tank_id": tank["id"],
        "construction_phase": tank["construction_phase"],
        "quality_posture": tank["quality_posture"],
        "open_nonconformance_count": tank["open_nonconformance_count"],
        "course_count": len(courses),
        "rt_accepted_course_count": len([c for c in courses
                                         if c["status"] == "RT_ACCEPTED"]),
        "seam_count": len(seams),
        "welded_seam_count": len([s for s in seams if s["status"] == "WELDED"]),
        "rt_accepted_seam_count": len([s for s in seams
                                       if s["status"] == "RT_ACCEPTED"]),
        "weld_reject_rate": tank["weld_reject_rate"],
        "required_examination_pct": tank["required_examination_pct"],
        "steel_received_lb": tank["steel_received_lb"],
        "steel_allocated_lb": tank["steel_allocated_lb"],
        "steel_remaining_lb": float(remaining),
        "active_hydrotest_plan_id": tank["active_hydrotest_plan_id"],
        "total_hydrotest_cost_usd": q(total_cost, 2),
        "installed_appurtenance_count": len([a for a in appurtenances
                                             if a["status"] == "INSTALLED"]),
        "designed_appurtenance_count": len(appurtenances),
    }
