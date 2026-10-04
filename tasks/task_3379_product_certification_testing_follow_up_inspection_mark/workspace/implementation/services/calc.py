"""Calculation rules (SCAFFOLD table 3 / PRD 3.x). All rounding is
ROUND_HALF_UP via Decimal; money is integer cents; scores/margins are 2dp."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from constants import (
    CONDITIONAL_BAND_PCT, DAMAGED_FEE_MULTIPLIER,
    INTERVAL_HIGH_MONTHS, INTERVAL_MID_MONTHS, INTERVAL_PROBATION_MONTHS,
    MIN_LOT, PENALTY_BY_SEVERITY, PROBATION_HARD_CAP, PROBATION_QUOTA_MULT,
    PROBATION_THRESHOLD, RETEST_SURCHARGE_PCT, SCORE_MID_THRESHOLD,
    SMALL_CLIENT_DISCOUNT, STANDARD_HARD_CAP, STANDARD_QUOTA_MULT,
    WINDOW_MONTHS,
)


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def add_months(dt, months):
    """Calendar-month addition onto a date, clamping the day of month."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# test_outcome_determination
# ---------------------------------------------------------------------------

def determine_outcome(protocol, measured_value, sample_condition):
    threshold = Decimal(str(protocol["pass_threshold"]))
    measured = Decimal(str(measured_value))
    band_floor = round_half_up(threshold * CONDITIONAL_BAND_PCT, 2)

    best_possible = "CONDITIONAL" if sample_condition == "DAMAGED" else "PASS"
    if measured >= threshold:
        raw = "PASS"
    elif measured >= band_floor:
        raw = "CONDITIONAL"
    else:
        raw = "FAIL"

    if raw == "PASS" and best_possible == "CONDITIONAL":
        outcome = "CONDITIONAL"
    elif raw == "CONDITIONAL" and protocol["mandatory"] and protocol["safety_critical"]:
        outcome = "FAIL"
    else:
        outcome = raw

    margin = round_half_up(measured - threshold, 2)
    return outcome, float(margin)


# ---------------------------------------------------------------------------
# evaluation_readiness / latest outcomes
# ---------------------------------------------------------------------------

def eligible_samples(project_id):
    return [s for s in db.samples.values()
            if s["project_id"] == project_id and s["status"] in ("ACCEPTED", "TESTED")]


def latest_results(project_id):
    """protocol_code -> (result, carrying_sample). Latest by recorded_at ASC;
    ties broken by measured_value DESC; final tiebreak: later insertion."""
    best = {}
    for sample in db.sorted_items(db.samples):
        if sample["project_id"] != project_id or sample["status"] not in ("ACCEPTED", "TESTED"):
            continue
        for result in sample["results"]:
            key = (
                result["recorded_at"],
                Decimal(str(result["measured_value"])),
                result["_seq"],
            )
            code = result["protocol_code"]
            if code not in best or key > best[code][0]:
                best[code] = (key, result, sample)
    return {code: (result, sample) for code, (key, result, sample) in best.items()}


def frozen_record(project_id):
    frozen = [cr for cr in db.construction_records.values()
              if cr["project_id"] == project_id and cr["status"] == "FROZEN"]
    return frozen[0] if len(frozen) == 1 else None


def evaluation_ready(project):
    standard = db.standards.get(project["standard_id"])
    if standard is None:
        return False
    latest = latest_results(project["id"])
    for protocol in standard["test_protocols"]:
        if protocol["mandatory"] and protocol["protocol_code"] not in latest:
            return False
    return frozen_record(project["id"]) is not None


# ---------------------------------------------------------------------------
# project_fee_calculation (per-line rounding BEFORE summation)
# ---------------------------------------------------------------------------

def compute_fee_snapshot(project, standard):
    latest = latest_results(project["id"])
    subtotal = Decimal(0)
    for protocol in standard["test_protocols"]:
        entry = latest.get(protocol["protocol_code"])
        if entry is None:
            continue
        _result, sample = entry
        mult = DAMAGED_FEE_MULTIPLIER if sample["condition"] == "DAMAGED" else Decimal("1")
        line = round_half_up(Decimal(str(protocol["base_fee_cents"])) * mult, 0)
        subtotal += line
    manufacturer = db.manufacturers[project["manufacturer_id"]]
    discount = SMALL_CLIENT_DISCOUNT if manufacturer["annual_revenue_tier"] == "SMALL" else Decimal(0)
    after_discount = round_half_up(subtotal * (Decimal(1) - discount), 0)
    surcharge = round_half_up(after_discount * RETEST_SURCHARGE_PCT * project["retest_count"], 0)
    return int(after_discount + surcharge)


# ---------------------------------------------------------------------------
# standard status derivation (PRD 2.6)
# ---------------------------------------------------------------------------

def standard_status(standard, at=None):
    return standard_status_window(standard["effective_from"], standard["effective_to"], at)


def standard_status_window(effective_from, effective_to, at=None):
    at = at or clock.now()
    if at < effective_from:
        return "UPCOMING"
    if effective_to is not None and at >= effective_to:
        return "RETIRED"
    return "ACTIVE"


def windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; open-ended = +inf; adjacency is legal."""
    a_end = a_to if a_to is not None else None
    b_end = b_to if b_to is not None else None
    left = True if b_end is None else a_from < b_end
    right = True if a_end is None else b_from < a_end
    return left and right


# ---------------------------------------------------------------------------
# factory_conformity_score + inspection_interval_derived
# ---------------------------------------------------------------------------

def completed_inspections(factory_id):
    return [i for i in db.inspections.values()
            if i["factory_id"] == factory_id and i["status"] == "COMPLETED"]


def _penalty_sum(inspections):
    total = 0
    for insp in inspections:
        for finding in insp["findings"]:
            total += PENALTY_BY_SEVERITY[finding["severity"]]
    return total


def windowed_score(factory_id, now):
    window_start = add_months(now, -WINDOW_MONTHS)
    included = [i for i in completed_inspections(factory_id)
                if i["completed_on"] >= window_start]
    return max(0, 100 - _penalty_sum(included))


def all_time_score(factory_id):
    return max(0, 100 - _penalty_sum(completed_inspections(factory_id)))


def open_critical_count(factory_id):
    count = 0
    for insp in completed_inspections(factory_id):
        count += sum(1 for f in insp["findings"] if f["severity"] == "CRITICAL")
    return count


def critical_findings_naming(factory_id, certification_id):
    count = 0
    for insp in completed_inspections(factory_id):
        for f in insp["findings"]:
            if f["severity"] == "CRITICAL" and f.get("certification_id") == certification_id:
                count += 1
    return count


def derive_interval_months(regime, score):
    if regime == "PROBATION" or score < 70:
        return INTERVAL_PROBATION_MONTHS
    if score < 90:
        return INTERVAL_MID_MONTHS
    return INTERVAL_HIGH_MONTHS


# ---------------------------------------------------------------------------
# label_quota_allocation
# ---------------------------------------------------------------------------

def quota_for(variant, declared_annual_volume):
    volume = Decimal(declared_annual_volume)
    if variant == "STANDARD_QUOTA":
        raw = min(int(volume * STANDARD_QUOTA_MULT), STANDARD_HARD_CAP)
    else:
        raw = min(int(volume * PROBATION_QUOTA_MULT), PROBATION_HARD_CAP)
    return max(MIN_LOT, (raw // 100) * 100)


# ---------------------------------------------------------------------------
# reciprocity_acceptance (one hop only)
# ---------------------------------------------------------------------------

def reciprocity_granted(site_jurisdiction, evaluating_jurisdiction):
    if site_jurisdiction["accepts_field_labels"]:
        return True
    if not site_jurisdiction["accepts_reciprocity"]:
        return False
    if evaluating_jurisdiction["jurisdiction_code"] not in site_jurisdiction["reciprocity_sources"]:
        return False
    if not evaluating_jurisdiction["accepts_field_labels"]:
        return False
    j_group = site_jurisdiction["reciprocity_group"]
    e_group = evaluating_jurisdiction["reciprocity_group"]
    return j_group == e_group or (j_group == "NONE" and e_group == "NONE")
